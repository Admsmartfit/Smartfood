"""
E-07 — InventoryService: Gestão de Estoque com PVPS e Rastreabilidade de Lotes

Regras implementadas:
  - PVPS (Primeiro que Vence, Primeiro que Sai) — consumo pelo lote mais antigo
  - Estoque de Segurança Dinâmico: média_consumo × (lead_time + 2)
  - Ponto de Ressuprimento Automático
  - Rastreabilidade Lote de Insumo → Lote de Produção
  - Ajuste manual com trilha de auditoria
  - Divergência de recebimento NF-e vs. balança
"""
import logging
import statistics
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy.orm import Session

logger = logging.getLogger("inventory_service")

# Tolerância padrão para divergência NF-e vs balança (±%)
DEFAULT_DIVERGENCE_TOLERANCE_PCT = 0.5


# ─────────────────────────────────────────────────────────────────────────────
# PVPS — Primeiro que Vence, Primeiro que Sai
# ─────────────────────────────────────────────────────────────────────────────

def get_fifo_lots(
    db: Session,
    ingredient_id: uuid.UUID,
    qty_needed: float,
) -> list[dict]:
    """
    Retorna lista de lotes a consumir em ordem de vencimento (PVPS).
    Cada entrada: {lot_id, numero_lote, data_validade, qty_disponivel, qty_a_consumir}.
    Levanta ValueError se o estoque disponível for insuficiente.
    """
    from models import IngredientLot

    lots = (
        db.query(IngredientLot)
        .filter(
            IngredientLot.ingredient_id == ingredient_id,
            IngredientLot.status == "ativo",
            IngredientLot.quantidade_atual > 0,
        )
        .order_by(IngredientLot.data_validade.asc())
        .all()
    )

    result = []
    remaining = qty_needed

    for lot in lots:
        if remaining <= 0:
            break
        consumir = min(lot.quantidade_atual, remaining)
        result.append({
            "lot_id": str(lot.id),
            "numero_lote": lot.numero_lote,
            "data_validade": lot.data_validade.isoformat(),
            "qty_disponivel": lot.quantidade_atual,
            "qty_a_consumir": round(consumir, 4),
        })
        remaining -= consumir

    if remaining > 0.001:
        total_available = sum(r["qty_disponivel"] for r in result)
        raise ValueError(
            f"Estoque insuficiente: necessário {qty_needed:.3f}, "
            f"disponível {total_available:.3f}"
        )

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Estoque de Segurança Dinâmico
# ─────────────────────────────────────────────────────────────────────────────

def calculate_safety_stock(db: Session, ingredient_id: uuid.UUID) -> dict:
    """
    Estoque de Segurança = média_consumo_diário × (lead_time_dias + 2)

    Consumo diário estimado a partir de LotConsumption dos últimos 30 dias.
    Se não houver histórico, usa estoque_minimo como referência.
    """
    from models import Ingredient, LotConsumption, IngredientLot

    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        raise ValueError("Ingrediente não encontrado")

    since = datetime.now(timezone.utc) - timedelta(days=30)

    # Soma de consumo dos últimos 30 dias via LotConsumption
    consumptions = (
        db.query(LotConsumption)
        .join(IngredientLot, LotConsumption.ingredient_lot_id == IngredientLot.id)
        .filter(
            IngredientLot.ingredient_id == ingredient_id,
            LotConsumption.consumido_em >= since,
        )
        .all()
    )

    total_consumed_30d = sum(c.quantidade for c in consumptions)
    media_consumo_diario = total_consumed_30d / 30 if consumptions else (ing.estoque_minimo or 0) / 30

    lead_time = ing.lead_time_dias or 0
    safety_stock = media_consumo_diario * (lead_time + 2)
    ponto_ressuprimento = safety_stock + (media_consumo_diario * lead_time)
    precisa_comprar = (ing.estoque_atual or 0) <= ponto_ressuprimento

    return {
        "ingredient_id": str(ingredient_id),
        "ingrediente_nome": ing.nome,
        "estoque_atual": ing.estoque_atual or 0,
        "lead_time_dias": lead_time,
        "media_consumo_diario": round(media_consumo_diario, 4),
        "estoque_seguranca": round(safety_stock, 3),
        "ponto_ressuprimento": round(ponto_ressuprimento, 3),
        "precisa_comprar": precisa_comprar,
        "deficit": round(max(0, ponto_ressuprimento - (ing.estoque_atual or 0)), 3),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Recebimento de NF-e
# ─────────────────────────────────────────────────────────────────────────────

def _parse_nfe_xml(xml_content: str) -> dict:
    """
    Extrai campos básicos de NF-e XML.
    Tenta lxml primeiro; fallback para xml.etree.ElementTree.
    """
    try:
        from lxml import etree as ET
        root = ET.fromstring(xml_content.encode())
    except ImportError:
        import xml.etree.ElementTree as ET
        root = ET.fromstring(xml_content)

    ns = {
        "nfe": "http://www.portalfiscal.inf.br/nfe",
    }

    def _find(path: str) -> Optional[str]:
        # Tenta com namespace, depois sem
        el = root.find(f".//{{{ns['nfe']}}}{path}")
        if el is None:
            el = root.find(f".//{path}")
        return el.text if el is not None else None

    return {
        "chave": _find("chNFe") or _find("Id") or "",
        "numero": _find("nNF") or "",
        "fornecedor_nome": _find("xNome") or "",
        "peso_bruto": float(_find("pesoB") or 0),
        "peso_liquido": float(_find("pesoL") or 0),
        "valor_total": float(_find("vNF") or 0),
    }


def receive_ingredient(
    db: Session,
    ingredient_id: uuid.UUID,
    numero_lote: str,
    quantidade: float,
    data_validade: datetime,
    fornecedor_nome: Optional[str] = None,
    peso_balanca: Optional[float] = None,
    nfe_xml: Optional[str] = None,
    divergence_tolerance_pct: float = DEFAULT_DIVERGENCE_TOLERANCE_PCT,
) -> dict:
    """
    Registra recebimento de insumo: cria IngredientLot, atualiza estoque,
    verifica divergência NF-e vs. balança e gera alerta se necessário.
    """
    from models import Ingredient, IngredientLot, SystemAlert

    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        raise ValueError("Ingrediente não encontrado")

    nfe_data = {}
    if nfe_xml:
        try:
            nfe_data = _parse_nfe_xml(nfe_xml)
        except Exception as exc:
            logger.warning("Falha ao parsear NF-e XML: %s", exc)

    nfe_peso = nfe_data.get("peso_bruto") or nfe_data.get("peso_liquido") or None
    divergencia_pct = None
    alerts_created = []

    if peso_balanca and nfe_peso and nfe_peso > 0:
        divergencia_pct = abs(peso_balanca - nfe_peso) / nfe_peso * 100
        if divergencia_pct > divergence_tolerance_pct:
            msg = (
                f"Divergência de recebimento — '{ing.nome}' lote {numero_lote}: "
                f"NF-e={nfe_peso:.3f}kg, balança={peso_balanca:.3f}kg "
                f"(divergência {divergencia_pct:.2f}% > tolerância {divergence_tolerance_pct}%)"
            )
            alert = SystemAlert(
                tipo="DIVERGENCIA_RECEBIMENTO",
                categoria="estoque",
                mensagem=msg,
                severidade="atencao",
                status="ativo",
            )
            db.add(alert)
            alerts_created.append(msg)
            logger.warning(msg)

    lot = IngredientLot(
        ingredient_id=ingredient_id,
        numero_lote=numero_lote,
        fornecedor_nome=fornecedor_nome or nfe_data.get("fornecedor_nome"),
        quantidade_recebida=quantidade,
        quantidade_atual=quantidade,
        data_recebimento=datetime.now(timezone.utc),
        data_validade=data_validade,
        nfe_chave=nfe_data.get("chave"),
        nfe_peso_declarado=nfe_peso,
        peso_balanca=peso_balanca,
        divergencia_pct=round(divergencia_pct, 4) if divergencia_pct is not None else None,
        status="ativo",
    )
    db.add(lot)

    # Atualiza estoque do ingrediente
    ing.estoque_atual = (ing.estoque_atual or 0) + quantidade
    db.commit()
    db.refresh(lot)

    return {
        "lot_id": str(lot.id),
        "ingrediente_nome": ing.nome,
        "numero_lote": numero_lote,
        "quantidade_recebida": quantidade,
        "estoque_total_atualizado": ing.estoque_atual,
        "data_validade": data_validade.isoformat(),
        "divergencia_pct": round(divergencia_pct, 2) if divergencia_pct is not None else None,
        "alertas": alerts_created,
        "nfe_parsed": bool(nfe_data),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Consumo de Produção (PVPS)
# ─────────────────────────────────────────────────────────────────────────────

def consume_for_production(
    db: Session,
    production_batch_id: uuid.UUID,
) -> dict:
    """
    Deduz insumos do estoque usando PVPS para um lote de produção.
    Cria registros LotConsumption e atualiza IngredientLot + Ingredient.estoque_atual.
    """
    from models import ProductionBatch, BOMItem, Ingredient, IngredientLot, LotConsumption

    batch = db.query(ProductionBatch).filter(ProductionBatch.id == production_batch_id).first()
    if not batch:
        raise ValueError("Lote de produção não encontrado")

    qty_producao = batch.quantidade_planejada or 1.0
    bom_items = (
        db.query(BOMItem)
        .filter(BOMItem.product_id == batch.product_id, BOMItem.ingredient_id != None)
        .all()
    )

    consumed = []
    now = datetime.now(timezone.utc)

    for item in bom_items:
        qty_needed = item.quantidade * qty_producao
        try:
            lots_to_use = get_fifo_lots(db, item.ingredient_id, qty_needed)
        except ValueError as e:
            logger.warning("PVPS: %s", e)
            consumed.append({
                "ingrediente_id": str(item.ingredient_id),
                "erro": str(e),
                "qty_necessaria": qty_needed,
            })
            continue

        for lot_info in lots_to_use:
            lot = db.query(IngredientLot).filter(
                IngredientLot.id == uuid.UUID(lot_info["lot_id"])
            ).first()
            if not lot:
                continue

            lot.quantidade_atual -= lot_info["qty_a_consumir"]
            if lot.quantidade_atual <= 0.001:
                lot.status = "consumido"
                lot.quantidade_atual = 0.0

            consumption = LotConsumption(
                production_batch_id=production_batch_id,
                ingredient_lot_id=lot.id,
                quantidade=lot_info["qty_a_consumir"],
                consumido_em=now,
            )
            db.add(consumption)

            # Atualiza estoque do ingrediente
            ing = db.query(Ingredient).filter(Ingredient.id == item.ingredient_id).first()
            if ing:
                ing.estoque_atual = max(0, (ing.estoque_atual or 0) - lot_info["qty_a_consumir"])

        consumed.append({
            "ingrediente_id": str(item.ingredient_id),
            "qty_necessaria": qty_needed,
            "lotes_consumidos": lots_to_use,
        })

    batch.status = "EM_PRODUCAO"
    db.commit()

    return {
        "production_batch_id": str(production_batch_id),
        "produto_id": str(batch.product_id),
        "qty_producao": qty_producao,
        "insumos_consumidos": consumed,
        "total_ingredientes": len(bom_items),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Rastreabilidade
# ─────────────────────────────────────────────────────────────────────────────

def get_traceability(db: Session, production_batch_id: uuid.UUID) -> dict:
    """
    Retorna rastreabilidade completa de um lote de produção:
    todos os lotes de insumo usados com fornecedor, validade e quantidade.
    """
    from models import ProductionBatch, LotConsumption, IngredientLot, Ingredient

    batch = db.query(ProductionBatch).filter(ProductionBatch.id == production_batch_id).first()
    if not batch:
        raise ValueError("Lote de produção não encontrado")

    consumptions = (
        db.query(LotConsumption)
        .filter(LotConsumption.production_batch_id == production_batch_id)
        .all()
    )

    insumos = []
    for c in consumptions:
        lot = db.query(IngredientLot).filter(IngredientLot.id == c.ingredient_lot_id).first()
        if not lot:
            continue
        ing = db.query(Ingredient).filter(Ingredient.id == lot.ingredient_id).first()
        insumos.append({
            "ingrediente": ing.nome if ing else "?",
            "ingrediente_id": str(lot.ingredient_id),
            "numero_lote": lot.numero_lote,
            "fornecedor": lot.fornecedor_nome,
            "data_validade": lot.data_validade.isoformat(),
            "data_recebimento": lot.data_recebimento.isoformat(),
            "nfe_chave": lot.nfe_chave,
            "qty_consumida": c.quantidade,
            "consumido_em": c.consumido_em.isoformat(),
        })

    return {
        "production_batch_id": str(production_batch_id),
        "produto_id": str(batch.product_id),
        "status_lote": batch.status,
        "quantidade_planejada": batch.quantidade_planejada,
        "total_lotes_insumo": len(insumos),
        "insumos_rastreados": insumos,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Ajuste Manual de Estoque
# ─────────────────────────────────────────────────────────────────────────────

def adjust_inventory(
    db: Session,
    ingredient_id: uuid.UUID,
    qty_ajuste: float,
    motivo: str,
    ajustado_por: Optional[str] = None,
    foto_base64: Optional[str] = None,
) -> dict:
    """
    Registra ajuste manual de estoque com trilha de auditoria.
    qty_ajuste positivo = entrada, negativo = saída (quebra, validade, roubo).
    """
    from models import Ingredient, InventoryAdjustment

    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        raise ValueError("Ingrediente não encontrado")

    estoque_anterior = ing.estoque_atual or 0.0
    estoque_novo = max(0.0, estoque_anterior + qty_ajuste)

    if qty_ajuste < 0 and abs(qty_ajuste) > estoque_anterior:
        raise ValueError(
            f"Ajuste ({qty_ajuste}) resulta em estoque negativo. "
            f"Estoque atual: {estoque_anterior}"
        )

    now = datetime.now(timezone.utc)
    adj = InventoryAdjustment(
        ingredient_id=ingredient_id,
        qty_ajuste=qty_ajuste,
        motivo=motivo,
        foto_base64=foto_base64,
        ajustado_por=ajustado_por,
        ajustado_em=now,
    )
    db.add(adj)
    ing.estoque_atual = estoque_novo
    db.commit()
    db.refresh(adj)

    return {
        "adjustment_id": str(adj.id),
        "ingrediente_nome": ing.nome,
        "estoque_anterior": estoque_anterior,
        "qty_ajuste": qty_ajuste,
        "estoque_novo": estoque_novo,
        "motivo": motivo,
        "ajustado_por": ajustado_por,
        "ajustado_em": now.isoformat(),
    }

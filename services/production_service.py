"""
E-11 — ProductionService: Ordens de Produção e Consumo de Insumos

Ciclo de vida completo com máquina de estados:
  RASCUNHO → APROVADA → EM_PRODUCAO → CONCLUIDA
                                      ↘ CANCELADA (qualquer estado)

Funcionalidades:
  - Verificação de viabilidade (feasibility check) com listagem de déficits
  - Soft-lock de insumos na aprovação
  - Início com registro de operador e hora_inicio
  - Registro de consumo real por insumo/lote com cálculo de divergência
  - Conclusão com custo real (insumos + labor + energia) e atualização de estoque
"""
import logging
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy.orm import Session, joinedload

from cost_calculator import DEFAULT_LABOR_COST_PER_MIN

logger = logging.getLogger("production_service")

# Máquina de estados válidos
VALID_TRANSITIONS: dict[str, list[str]] = {
    "RASCUNHO":   ["APROVADA", "CANCELADA"],
    "APROVADA":   ["EM_PRODUCAO", "CANCELADA"],
    "EM_PRODUCAO":["CONCLUIDA", "CANCELADA"],
    "CONCLUIDA":  [],
    "CANCELADA":  [],
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _get_batch(db: Session, batch_id: uuid.UUID):
    from models import ProductionBatch
    batch = db.query(ProductionBatch).filter(ProductionBatch.id == batch_id).first()
    if not batch:
        raise ValueError("Ordem de produção não encontrada")
    return batch


def _assert_status(batch, expected: str):
    if batch.status != expected:
        raise ValueError(
            f"Operação inválida: OP está '{batch.status}', esperado '{expected}'"
        )


def _transition(batch, to_status: str):
    allowed = VALID_TRANSITIONS.get(batch.status, [])
    if to_status not in allowed:
        raise ValueError(
            f"Transição inválida: {batch.status} → {to_status}. "
            f"Permitidos: {allowed}"
        )
    batch.status = to_status


# ─────────────────────────────────────────────────────────────────────────────
# CRUD básico
# ─────────────────────────────────────────────────────────────────────────────

def create_production_order(
    db: Session,
    product_id: uuid.UUID,
    quantidade_planejada: float,
    data_inicio: Optional[datetime] = None,
    data_fim: Optional[datetime] = None,
) -> dict:
    from models import ProductionBatch, Product

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise ValueError("Produto não encontrado")

    batch = ProductionBatch(
        product_id=product_id,
        quantidade_planejada=quantidade_planejada,
        data_inicio=data_inicio,
        data_fim=data_fim,
        status="RASCUNHO",
    )
    db.add(batch)
    db.commit()
    db.refresh(batch)
    return _batch_to_dict(batch, product.nome)


def list_production_orders(db: Session, status: Optional[str] = None) -> list:
    from models import ProductionBatch, Product
    q = db.query(ProductionBatch)
    if status:
        q = q.filter(ProductionBatch.status == status)
    batches = q.order_by(ProductionBatch.created_at.desc()).all()
    result = []
    for b in batches:
        p = db.query(Product).filter(Product.id == b.product_id).first()
        result.append(_batch_to_dict(b, p.nome if p else "?"))
    return result


def _batch_to_dict(batch, produto_nome: str) -> dict:
    return {
        "id": str(batch.id),
        "produto_id": str(batch.product_id),
        "produto_nome": produto_nome,
        "quantidade_planejada": batch.quantidade_planejada,
        "quantidade_real": batch.quantidade_real,
        "status": batch.status,
        "operador_id": batch.operador_id,
        "data_inicio": batch.data_inicio.isoformat() if batch.data_inicio else None,
        "data_fim": batch.data_fim.isoformat() if batch.data_fim else None,
        "custo_total": batch.custo_total,
        "custo_labor": batch.custo_labor,
        "custo_energia_real": batch.custo_energia_real,
        "motivo_cancelamento": batch.motivo_cancelamento,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Verificação de Viabilidade (Feasibility Check)
# ─────────────────────────────────────────────────────────────────────────────

def feasibility_check(db: Session, batch_id: uuid.UUID) -> dict:
    """
    Verifica se todos os insumos da BOM têm estoque suficiente para
    a quantidade planejada. Lista déficits por ingrediente e supply.

    Inclui verificação de embalagens/etiquetas (integração E-08).
    """
    from models import ProductionBatch, BOMItem, Ingredient, Supply, Product
    from services.supply_service import check_packaging_for_plan

    batch = _get_batch(db, batch_id)
    qty = batch.quantidade_planejada or 1.0
    product = db.query(Product).filter(Product.id == batch.product_id).first()

    bom_items = (
        db.query(BOMItem)
        .options(joinedload(BOMItem.ingredient), joinedload(BOMItem.supply))
        .filter(BOMItem.product_id == batch.product_id)
        .all()
    )

    ingredientes_status = []
    tem_deficit = False

    for item in bom_items:
        if item.ingredient_id and item.ingredient:
            ing = item.ingredient
            qty_necessaria = item.quantidade * qty
            qty_disponivel = ing.estoque_atual or 0.0
            deficit = max(0.0, qty_necessaria - qty_disponivel)
            if deficit > 0:
                tem_deficit = True
            ingredientes_status.append({
                "tipo": "ingrediente",
                "id": str(ing.id),
                "nome": ing.nome,
                "unidade": item.unidade or ing.unidade,
                "qty_necessaria": round(qty_necessaria, 3),
                "qty_disponivel": round(qty_disponivel, 3),
                "deficit": round(deficit, 3),
                "lead_time_dias": ing.lead_time_dias or 0,
                "status": "ok" if deficit == 0 else "deficit",
            })

    # Verificação de embalagens (E-08)
    packaging = check_packaging_for_plan(db, batch.product_id, qty)
    for s in packaging.get("supplies", []):
        if s["status"] == "deficit":
            tem_deficit = True
        ingredientes_status.append({**s, "tipo": "supply"})

    return {
        "batch_id": str(batch_id),
        "produto_id": str(batch.product_id),
        "produto_nome": product.nome if product else "?",
        "quantidade_planejada": qty,
        "viavel": not tem_deficit,
        "total_insumos_verificados": len(ingredientes_status),
        "insumos_com_deficit": sum(1 for i in ingredientes_status if i.get("deficit", 0) > 0),
        "insumos": ingredientes_status,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Aprovação (soft-lock)
# ─────────────────────────────────────────────────────────────────────────────

def approve_order(db: Session, batch_id: uuid.UUID) -> dict:
    """
    Aprova OP: RASCUNHO → APROVADA.
    Executa feasibility_check — rejeita se houver déficits críticos.
    (Soft-lock: apenas reserva lógica, sem bloquear fisicamente o estoque.)
    """
    batch = _get_batch(db, batch_id)
    _assert_status(batch, "RASCUNHO")

    fcheck = feasibility_check(db, batch_id)
    if not fcheck["viavel"]:
        return {
            "aprovado": False,
            "mensagem": "OP não pode ser aprovada: há déficit de insumos.",
            "feasibility": fcheck,
        }

    _transition(batch, "APROVADA")
    db.commit()
    return {
        "aprovado": True,
        "batch_id": str(batch_id),
        "status": batch.status,
        "mensagem": "OP aprovada. Insumos verificados e reservados logicamente.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Início de Produção
# ─────────────────────────────────────────────────────────────────────────────

def start_production(
    db: Session,
    batch_id: uuid.UUID,
    operador_id: str,
) -> dict:
    """
    Inicia produção: APROVADA → EM_PRODUCAO.
    Registra hora_inicio e operador. Exibe lista PVPS de lotes a usar.
    """
    from models import BOMItem
    from services.inventory_service import get_fifo_lots

    batch = _get_batch(db, batch_id)
    _assert_status(batch, "APROVADA")

    now = datetime.now(timezone.utc)
    batch.data_inicio = now
    batch.operador_id = operador_id
    _transition(batch, "EM_PRODUCAO")
    db.commit()

    # Sugere lotes PVPS para o operador
    qty = batch.quantidade_planejada or 1.0
    bom_items = db.query(BOMItem).filter(
        BOMItem.product_id == batch.product_id,
        BOMItem.ingredient_id != None
    ).all()

    sugestao_pvps = []
    for item in bom_items:
        try:
            lotes = get_fifo_lots(db, item.ingredient_id, item.quantidade * qty)
            sugestao_pvps.append({
                "ingredient_id": str(item.ingredient_id),
                "qty_necessaria": round(item.quantidade * qty, 3),
                "lotes_sugeridos": lotes,
            })
        except ValueError as e:
            sugestao_pvps.append({
                "ingredient_id": str(item.ingredient_id),
                "erro": str(e),
            })

    return {
        "batch_id": str(batch_id),
        "status": batch.status,
        "hora_inicio": now.isoformat(),
        "operador_id": operador_id,
        "sugestao_pvps": sugestao_pvps,
        "mensagem": "Produção iniciada. Siga a lista PVPS acima para consumo correto dos insumos.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Registro de Consumo Real
# ─────────────────────────────────────────────────────────────────────────────

def record_ingredient_usage(
    db: Session,
    batch_id: uuid.UUID,
    usages: list[dict],  # [{ingredient_id, lot_id, qty_real}]
) -> dict:
    """
    Registra consumo real de insumos por lote (PVPS).
    Calcula divergência vs planejado e deduz estoque.

    usages: lista de {ingredient_id, lot_id (opcional), qty_real}
    """
    from models import BatchIngredientUsage, BOMItem, Ingredient, IngredientLot, LotConsumption

    batch = _get_batch(db, batch_id)
    _assert_status(batch, "EM_PRODUCAO")

    qty_planejada = batch.quantidade_planejada or 1.0
    now = datetime.now(timezone.utc)
    registros = []

    # Limpa usages anteriores (re-registro)
    db.query(BatchIngredientUsage).filter(BatchIngredientUsage.batch_id == batch_id).delete()

    for uso in usages:
        ing_id = uuid.UUID(str(uso["ingredient_id"]))
        qty_real = float(uso["qty_real"])

        ing = db.query(Ingredient).filter(Ingredient.id == ing_id).first()
        if not ing:
            continue

        # Qty planejada da BOM
        bom_item = db.query(BOMItem).filter(
            BOMItem.product_id == batch.product_id,
            BOMItem.ingredient_id == ing_id
        ).first()
        qty_plan = (bom_item.quantidade * qty_planejada) if bom_item else 0.0

        divergencia_pct = (
            (qty_real - qty_plan) / qty_plan * 100 if qty_plan > 0 else 0.0
        )

        # Deduz estoque do lote especificado ou via PVPS
        lot_id_str = uso.get("lot_id")
        if lot_id_str:
            lot = db.query(IngredientLot).filter(
                IngredientLot.id == uuid.UUID(str(lot_id_str))
            ).first()
            if lot:
                consumir = min(lot.quantidade_atual, qty_real)
                lot.quantidade_atual = max(0.0, lot.quantidade_atual - consumir)
                if lot.quantidade_atual <= 0.001:
                    lot.status = "consumido"
                    lot.quantidade_atual = 0.0
                db.add(LotConsumption(
                    production_batch_id=batch_id,
                    ingredient_lot_id=lot.id,
                    quantidade=consumir,
                    consumido_em=now,
                ))
        else:
            # PVPS automático
            from services.inventory_service import get_fifo_lots
            try:
                lots = get_fifo_lots(db, ing_id, qty_real)
                for li in lots:
                    lot = db.query(IngredientLot).filter(
                        IngredientLot.id == uuid.UUID(li["lot_id"])
                    ).first()
                    if lot:
                        lot.quantidade_atual -= li["qty_a_consumir"]
                        if lot.quantidade_atual <= 0.001:
                            lot.status = "consumido"
                            lot.quantidade_atual = 0.0
                        db.add(LotConsumption(
                            production_batch_id=batch_id,
                            ingredient_lot_id=lot.id,
                            quantidade=li["qty_a_consumir"],
                            consumido_em=now,
                        ))
            except ValueError:
                pass

        ing.estoque_atual = max(0.0, (ing.estoque_atual or 0.0) - qty_real)

        # Registra uso no batch
        biu = BatchIngredientUsage(
            batch_id=batch_id,
            ingredient_id=ing_id,
            qty_planejada=qty_plan,
            qty_real=qty_real,
            custo_unitario=ing.custo_atual or 0.0,
            divergencia_pct=round(divergencia_pct, 2),
        )
        db.add(biu)

        status_div = "ok"
        if abs(divergencia_pct) > 10:
            status_div = "alto"
        elif abs(divergencia_pct) > 5:
            status_div = "atencao"

        registros.append({
            "ingrediente": ing.nome,
            "qty_planejada": round(qty_plan, 3),
            "qty_real": round(qty_real, 3),
            "divergencia_pct": round(divergencia_pct, 2),
            "status_divergencia": status_div,
        })

    db.commit()
    return {
        "batch_id": str(batch_id),
        "registros": registros,
        "total_ingredientes": len(registros),
        "divergencias_altas": sum(1 for r in registros if r["status_divergencia"] == "alto"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Conclusão da OP
# ─────────────────────────────────────────────────────────────────────────────

def complete_production_order(
    db: Session,
    batch_id: uuid.UUID,
    quantidade_real: float,
    custo_energia_kwh: Optional[float] = None,
    labor_cost_per_min: float = DEFAULT_LABOR_COST_PER_MIN,
) -> dict:
    """
    Conclui OP: EM_PRODUCAO → CONCLUIDA.

    Calcula custo real:
      custo_total_real = Σ(qty_real × custo_unitario) + labor_cost + energia

    Labor cost = (hora_fim - hora_inicio).total_seconds() / 60 × labor_cost_per_min

    Adiciona quantidade_real ao estoque de produto acabado.
    """
    from models import BatchIngredientUsage, Product

    batch = _get_batch(db, batch_id)
    _assert_status(batch, "EM_PRODUCAO")

    now = datetime.now(timezone.utc)
    batch.data_fim = now
    batch.quantidade_real = quantidade_real

    # Custo de insumos
    usages = db.query(BatchIngredientUsage).filter(
        BatchIngredientUsage.batch_id == batch_id
    ).all()
    custo_insumos = sum(
        (u.qty_real or 0) * (u.custo_unitario or 0) for u in usages
    )

    # Labor cost
    custo_labor = 0.0
    if batch.data_inicio:
        minutos = (now - batch.data_inicio).total_seconds() / 60
        custo_labor = round(minutos * labor_cost_per_min, 2)
        batch.custo_labor = custo_labor
        logger.info("Labor cost: %.1f min × R$%.4f/min = R$%.2f", minutos, labor_cost_per_min, custo_labor)

    # Energia
    energia = custo_energia_kwh or 0.0
    batch.custo_energia_real = energia

    custo_total_real = round(custo_insumos + custo_labor + energia, 2)
    batch.custo_total = custo_total_real
    _transition(batch, "CONCLUIDA")

    # Atualiza estoque de produto acabado
    product = db.query(Product).filter(Product.id == batch.product_id).first()
    if product:
        product.estoque_atual = (product.estoque_atual or 0.0) + quantidade_real

    db.commit()

    return {
        "batch_id": str(batch_id),
        "status": batch.status,
        "quantidade_real_produzida": quantidade_real,
        "hora_inicio": batch.data_inicio.isoformat() if batch.data_inicio else None,
        "hora_fim": now.isoformat(),
        "custo_insumos": round(custo_insumos, 2),
        "custo_labor": custo_labor,
        "custo_energia": energia,
        "custo_total_real": custo_total_real,
        "estoque_produto_atualizado": product.estoque_atual if product else None,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Cancelamento
# ─────────────────────────────────────────────────────────────────────────────

def cancel_production_order(
    db: Session,
    batch_id: uuid.UUID,
    motivo: str,
) -> dict:
    batch = _get_batch(db, batch_id)
    if batch.status in ("CONCLUIDA", "CANCELADA"):
        raise ValueError(f"OP com status '{batch.status}' não pode ser cancelada")

    _transition(batch, "CANCELADA")
    batch.motivo_cancelamento = motivo
    db.commit()
    return {"batch_id": str(batch_id), "status": "CANCELADA", "motivo": motivo}

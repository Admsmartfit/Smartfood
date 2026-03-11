"""
E-08 — Gestão de Insumos Não-Alimentícios (Embalagens, Limpeza, EPI)

Lógica de consumo dual:
  - Embalagens / etiquetas → consumidas pela BOM de produção (consumo_por_lote)
  - Limpeza / EPI          → consumidas por job diário (consumo_diario_fixo × operadores)

Lead time crítico: supplies com lead_time_dias > 10 recebem alerta com antecedência dobrada.
"""
import logging
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy.orm import Session

logger = logging.getLogger("supply_service")

# Tipos que são consumidos pela BOM de produção
TIPOS_BOM = {"embalagem_primaria", "embalagem_secundaria", "etiqueta"}
# Tipos consumidos diariamente de forma fixa
TIPOS_DIARIO = {"limpeza", "epi"}
# Lead time crítico a partir do qual a antecedência de alerta é dobrada
LEAD_TIME_CRITICO = 10


# ─────────────────────────────────────────────────────────────────────────────
# Consumo diário de limpeza / EPI
# ─────────────────────────────────────────────────────────────────────────────

def consume_daily_supplies(db: Session, num_operadores: int = 2) -> list[dict]:
    """
    Job diário: deduz consumo de supplies de limpeza/EPI baseado em
    consumo_diario_fixo × num_operadores_ativos.
    Retorna lista de supplies atualizados.
    """
    from models import Supply, SystemAlert

    supplies = (
        db.query(Supply)
        .filter(Supply.tipo.in_(list(TIPOS_DIARIO)))
        .all()
    )

    updated = []
    for sup in supplies:
        consumo = (sup.consumo_diario_fixo or 0.0) * num_operadores
        if consumo <= 0:
            continue

        estoque_anterior = sup.estoque_atual or 0.0
        sup.estoque_atual = max(0.0, estoque_anterior - consumo)
        updated.append({
            "supply_id": str(sup.id),
            "nome": sup.nome,
            "tipo": sup.tipo,
            "consumo_deduzido": consumo,
            "estoque_anterior": estoque_anterior,
            "estoque_atual": sup.estoque_atual,
        })

        # Alerta se estoque ficou abaixo do mínimo
        if sup.estoque_atual <= (sup.estoque_minimo or 0.0):
            alert = SystemAlert(
                tipo="ESTOQUE_SUPPLY_CRITICO",
                categoria="estoque",
                mensagem=(
                    f"Supply '{sup.nome}' ({sup.tipo}): estoque {sup.estoque_atual:.2f} "
                    f"abaixo do mínimo ({sup.estoque_minimo:.2f}). Lead time: {sup.lead_time_dias}d."
                ),
                severidade="critico" if sup.lead_time_dias > LEAD_TIME_CRITICO else "atencao",
                status="ativo",
            )
            db.add(alert)

    db.commit()
    return updated


# ─────────────────────────────────────────────────────────────────────────────
# Consumo de embalagens por produção
# ─────────────────────────────────────────────────────────────────────────────

def consume_packaging_for_batch(
    db: Session,
    product_id: uuid.UUID,
    qty_producao: float,
) -> list[dict]:
    """
    Deduz embalagens/etiquetas do estoque para um lote de produção.
    Usa BOMItem.supply_id para supplies do tipo TIPOS_BOM.
    """
    from models import BOMItem, Supply

    bom_items = (
        db.query(BOMItem)
        .filter(BOMItem.product_id == product_id, BOMItem.supply_id != None)
        .all()
    )

    consumed = []
    for item in bom_items:
        sup = db.query(Supply).filter(Supply.id == item.supply_id).first()
        if not sup or sup.tipo not in TIPOS_BOM:
            continue

        qty_consumir = item.quantidade * qty_producao
        estoque_anterior = sup.estoque_atual or 0.0
        sup.estoque_atual = max(0.0, estoque_anterior - qty_consumir)

        consumed.append({
            "supply_id": str(sup.id),
            "nome": sup.nome,
            "tipo": sup.tipo,
            "qty_consumida": qty_consumir,
            "estoque_anterior": estoque_anterior,
            "estoque_atual": sup.estoque_atual,
        })

    db.commit()
    return consumed


# ─────────────────────────────────────────────────────────────────────────────
# Críticos — suprimentos em risco de ruptura
# ─────────────────────────────────────────────────────────────────────────────

def _consumo_diario_efetivo(sup, num_operadores: int = 2) -> float:
    """Retorna o consumo diário efetivo do supply, dependendo do tipo."""
    if sup.tipo in TIPOS_BOM:
        # Para embalagens: consumo_por_lote / frequência de produção (assume 1 lote/dia)
        return sup.consumo_por_lote or 0.0
    return (sup.consumo_diario_fixo or 0.0) * num_operadores


def get_critical_supplies(db: Session, num_operadores: int = 2) -> list[dict]:
    """
    Lista supplies críticos onde:
      (estoque_atual / consumo_diario) <= (lead_time_dias + 3)

    Para lead_time_dias > 10, antecedência de alerta é DOBRADA:
      (estoque_atual / consumo_diario) <= (lead_time_dias * 2 + 3)

    Retorna ordenado por urgência crescente (mais urgente primeiro).
    """
    from models import Supply

    supplies = db.query(Supply).all()
    critical = []

    for sup in supplies:
        consumo = _consumo_diario_efetivo(sup, num_operadores)
        if consumo <= 0:
            continue

        estoque = sup.estoque_atual or 0.0
        lead = sup.lead_time_dias or 0
        dias_cobertura = estoque / consumo

        # Antecedência dobrada para lead_time > 10 dias
        threshold = (lead * 2 + 3) if lead > LEAD_TIME_CRITICO else (lead + 3)

        if dias_cobertura <= threshold:
            urgencia_dias = max(0.0, dias_cobertura - lead)
            critical.append({
                "supply_id": str(sup.id),
                "nome": sup.nome,
                "tipo": sup.tipo,
                "unidade": sup.unidade,
                "estoque_atual": estoque,
                "consumo_diario_estimado": round(consumo, 4),
                "dias_cobertura": round(dias_cobertura, 1),
                "lead_time_dias": lead,
                "lead_time_critico": lead > LEAD_TIME_CRITICO,
                "threshold_alerta_dias": threshold,
                "urgencia_dias_restantes": round(urgencia_dias, 1),
                "custo_reposicao_estimado": round(
                    (consumo * (lead + 7)) * (sup.custo_atual or 0), 2
                ),
            })

    critical.sort(key=lambda x: x["urgencia_dias_restantes"])
    return critical


# ─────────────────────────────────────────────────────────────────────────────
# Verificação de embalagens no plano de produção (integração E-04)
# ─────────────────────────────────────────────────────────────────────────────

def check_packaging_for_plan(
    db: Session,
    product_id: uuid.UUID,
    qty_planejada: float,
    num_operadores: int = 2,
) -> dict:
    """
    Integração com Motor de Demanda (E-04): ao gerar plano de produção,
    verifica automaticamente embalagens e etiquetas necessárias.
    Retorna lista de supplies com status ok/deficit.
    """
    from models import BOMItem, Supply

    bom_items = (
        db.query(BOMItem)
        .filter(BOMItem.product_id == product_id, BOMItem.supply_id != None)
        .all()
    )

    supplies_status = []
    tem_deficit = False

    for item in bom_items:
        sup = db.query(Supply).filter(Supply.id == item.supply_id).first()
        if not sup:
            continue

        qty_necessaria = item.quantidade * qty_planejada
        qty_disponivel = sup.estoque_atual or 0.0
        qty_faltante = max(0.0, qty_necessaria - qty_disponivel)
        lead = sup.lead_time_dias or 0

        # Antecedência dobrada para supplies com lead crítico
        dias_para_comprar = lead * 2 if lead > LEAD_TIME_CRITICO else lead

        status_item = {
            "supply_id": str(sup.id),
            "nome": sup.nome,
            "tipo": sup.tipo,
            "unidade": sup.unidade or item.unidade,
            "qty_necessaria": round(qty_necessaria, 3),
            "qty_disponivel": round(qty_disponivel, 3),
            "qty_faltante": round(qty_faltante, 3),
            "lead_time_dias": lead,
            "lead_time_critico": lead > LEAD_TIME_CRITICO,
            "dias_antecedencia_compra": dias_para_comprar,
            "status": "ok" if qty_faltante == 0 else "deficit",
        }
        supplies_status.append(status_item)
        if qty_faltante > 0:
            tem_deficit = True

    return {
        "product_id": str(product_id),
        "qty_planejada": qty_planejada,
        "embalagens_verificadas": len(supplies_status),
        "tem_deficit_embalagem": tem_deficit,
        "supplies": supplies_status,
    }

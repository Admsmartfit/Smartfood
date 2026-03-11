"""
E-17 — SPIService: Índice de Performance de Fornecedores

US-017: Ranking de fornecedores por SPI (pontualidade + acuracidade de peso)
  Score 0-100, atualizado mensalmente.

Cálculo do SPI:
  score_pontualidade  = % pedidos entregues dentro do prazo × 100
  score_acuracidade   = % recebimentos sem divergência crítica de peso × 100
  score_rfq           = média dos scores de cotação (RFQ) × 100

  SPI = (score_pontualidade × 0.40)
      + (score_acuracidade  × 0.40)
      + (score_rfq          × 0.20)

Divergência crítica: > DEFAULT_DIVERGENCE_TOLERANCE_PCT (0.5%)
Pontualidade: IngredientLot criado até data_entrega_prevista do PO
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy.orm import Session

logger = logging.getLogger("spi_service")

DEFAULT_DIVERGENCE_TOLERANCE_PCT = 0.5  # mesmo valor de inventory_service
SPI_LOOKBACK_MONTHS = 6

# Thresholds de classificação
SPI_EXCELENTE = 80
SPI_BOM       = 60
SPI_REGULAR   = 40


# ─────────────────────────────────────────────────────────────────────────────
# Cálculo do SPI por fornecedor
# ─────────────────────────────────────────────────────────────────────────────

def calculate_spi(
    db: Session,
    supplier_id: uuid.UUID,
    months: int = SPI_LOOKBACK_MONTHS,
) -> dict:
    """
    Calcula SPI (0-100) de um fornecedor com base no histórico de recebimentos.

    Componentes:
      - Pontualidade (40%): % de lotes recebidos até a data prevista do PO
      - Acuracidade de peso (40%): % de lotes sem divergência > 0.5%
      - Score de cotação (20%): média do score RFQ das cotações aprovadas
    """
    from models import Supplier, PurchaseOrder, IngredientLot, RFQ, InventoryAdjustment

    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise ValueError("Fornecedor não encontrado")

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=months * 30)

    # Pedidos de compra do fornecedor no período
    pos = (
        db.query(PurchaseOrder)
        .filter(
            PurchaseOrder.supplier_id == supplier_id,
            PurchaseOrder.created_at >= cutoff,
        )
        .all()
    )

    # ── Pontualidade ──────────────────────────────────────────────────────────
    total_pos = len(pos)
    pontual = 0
    detalhe_pontualidade = []

    for po in pos:
        if not po.data_entrega_prevista:
            continue
        prazo = po.data_entrega_prevista
        if prazo.tzinfo is None:
            prazo = prazo.replace(tzinfo=timezone.utc)

        # Proxy: lotes do insumo criados após este PO e antes do prazo
        lotes_recebidos = (
            db.query(IngredientLot)
            .filter(
                IngredientLot.fornecedor == supplier.nome,
                IngredientLot.created_at >= (po.created_at or cutoff),
                IngredientLot.created_at <= prazo + timedelta(days=1),
            )
            .count()
        )
        no_prazo = lotes_recebidos > 0
        if no_prazo:
            pontual += 1
        detalhe_pontualidade.append({
            "po_id": str(po.id),
            "prazo": prazo.date().isoformat(),
            "no_prazo": no_prazo,
        })

    score_pontualidade = (pontual / len(detalhe_pontualidade) * 100) if detalhe_pontualidade else 0.0

    # ── Acuracidade de Peso ───────────────────────────────────────────────────
    lotes = (
        db.query(IngredientLot)
        .filter(
            IngredientLot.fornecedor == supplier.nome,
            IngredientLot.created_at >= cutoff,
        )
        .all()
    )

    total_lotes = len(lotes)
    lotes_ok = 0
    detalhe_acuracidade = []

    for lot in lotes:
        # Verifica ajustes de inventário negativos (divergência de peso) para este lote
        ajuste = (
            db.query(InventoryAdjustment)
            .filter(
                InventoryAdjustment.ingredient_id == lot.ingredient_id,
                InventoryAdjustment.tipo == "correcao_recebimento",
                InventoryAdjustment.created_at >= (lot.created_at or cutoff),
                InventoryAdjustment.created_at <= (lot.created_at or cutoff) + timedelta(hours=24),
            )
            .first()
        )

        if ajuste and lot.quantidade_original and lot.quantidade_original > 0:
            divergencia_pct = abs(ajuste.quantidade) / lot.quantidade_original * 100
            tem_divergencia = divergencia_pct > DEFAULT_DIVERGENCE_TOLERANCE_PCT
        else:
            divergencia_pct = 0.0
            tem_divergencia = False

        if not tem_divergencia:
            lotes_ok += 1
        detalhe_acuracidade.append({
            "lote": lot.codigo_lote,
            "divergencia_pct": round(divergencia_pct, 2),
            "ok": not tem_divergencia,
        })

    score_acuracidade = (lotes_ok / total_lotes * 100) if total_lotes > 0 else 100.0

    # ── Score de Cotação (RFQ) ────────────────────────────────────────────────
    rfqs = (
        db.query(RFQ)
        .filter(
            RFQ.supplier_id == supplier_id,
            RFQ.created_at >= cutoff,
            RFQ.score != None,
        )
        .all()
    )

    if rfqs:
        score_rfq = sum(r.score for r in rfqs) / len(rfqs) * 100
    else:
        score_rfq = 50.0  # neutro quando sem histórico de cotações

    # ── SPI Final ─────────────────────────────────────────────────────────────
    spi = (
        score_pontualidade * 0.40
        + score_acuracidade * 0.40
        + score_rfq         * 0.20
    )
    spi = round(spi, 1)

    return {
        "supplier_id": str(supplier_id),
        "fornecedor": supplier.nome,
        "periodo_meses": months,
        "spi": spi,
        "classificacao": _classify(spi),
        "componentes": {
            "pontualidade": {
                "score": round(score_pontualidade, 1),
                "peso": "40%",
                "total_pedidos": len(detalhe_pontualidade),
                "no_prazo": pontual,
                "detalhe": detalhe_pontualidade[:10],
            },
            "acuracidade_peso": {
                "score": round(score_acuracidade, 1),
                "peso": "40%",
                "total_lotes": total_lotes,
                "lotes_sem_divergencia": lotes_ok,
                "detalhe": detalhe_acuracidade[:10],
            },
            "score_cotacao": {
                "score": round(score_rfq, 1),
                "peso": "20%",
                "total_rfqs": len(rfqs),
            },
        },
        "calculado_em": datetime.now(timezone.utc).isoformat(),
    }


def _classify(spi: float) -> str:
    if spi >= SPI_EXCELENTE:
        return "excelente"
    elif spi >= SPI_BOM:
        return "bom"
    elif spi >= SPI_REGULAR:
        return "regular"
    return "ruim"


# ─────────────────────────────────────────────────────────────────────────────
# Ranking geral de fornecedores
# ─────────────────────────────────────────────────────────────────────────────

def spi_ranking(
    db: Session,
    months: int = SPI_LOOKBACK_MONTHS,
    limit: int = 50,
) -> dict:
    """
    US-017: Retorna ranking de todos os fornecedores por SPI.
    Inclui score 0-100, classificação e componentes principais.
    """
    from models import Supplier

    suppliers = db.query(Supplier).all()
    ranking = []

    for s in suppliers:
        try:
            result = calculate_spi(db, s.id, months)
            ranking.append({
                "posicao": 0,  # será preenchido após ordenação
                "supplier_id": result["supplier_id"],
                "fornecedor": result["fornecedor"],
                "spi": result["spi"],
                "classificacao": result["classificacao"],
                "pontualidade_score": result["componentes"]["pontualidade"]["score"],
                "acuracidade_score": result["componentes"]["acuracidade_peso"]["score"],
                "cotacao_score": result["componentes"]["score_cotacao"]["score"],
            })
        except Exception as e:
            logger.warning("Erro ao calcular SPI para %s: %s", s.nome, e)

    ranking.sort(key=lambda x: -x["spi"])
    for i, r in enumerate(ranking, 1):
        r["posicao"] = i

    return {
        "periodo_meses": months,
        "total_fornecedores": len(ranking),
        "calculado_em": datetime.now(timezone.utc).isoformat(),
        "resumo": {
            "excelentes": sum(1 for r in ranking if r["classificacao"] == "excelente"),
            "bons":       sum(1 for r in ranking if r["classificacao"] == "bom"),
            "regulares":  sum(1 for r in ranking if r["classificacao"] == "regular"),
            "ruins":      sum(1 for r in ranking if r["classificacao"] == "ruim"),
        },
        "ranking": ranking[:limit],
    }

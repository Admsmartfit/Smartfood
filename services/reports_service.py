"""
E-16 — ReportsService: DRE Automatizado e Relatórios de Lote

Funcionalidades:
  - DRE (Demonstração de Resultado do Exercício): P&L por período
  - Relatório de Lote: custo real, rendimento, divergências, custo/unidade
  - Evolução de margens por produto ao longo do tempo
  - Ranking de produtos por receita, margem e volume
  - Relatório de fornecedores (SPI — Supplier Performance Index)

DRE Automatizado:
  Receita       = Σ orders.total  (status=ENTREGUE, no período)
  CMV           = Σ production_batches.custo_total  (status=CONCLUIDA, no período)
  Lucro Bruto   = Receita - CMV
  Margem Bruta% = Lucro Bruto / Receita × 100

Relatório de Lote:
  Rendimento%   = quantidade_real / quantidade_planejada × 100
  Custo/Unid    = custo_total / quantidade_real
  Desvio médio  = média das divergencias_pct dos ingredientes
"""
import logging
from datetime import datetime, timezone
from typing import Optional
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger("reports_service")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de período
# ─────────────────────────────────────────────────────────────────────────────

def _ensure_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _parse_period(data_inicio: str, data_fim: str):
    """Converte strings ISO para datetime UTC."""
    inicio = _ensure_utc(datetime.fromisoformat(data_inicio))
    fim = _ensure_utc(datetime.fromisoformat(data_fim))
    return inicio, fim


# ─────────────────────────────────────────────────────────────────────────────
# DRE Automatizado (P&L)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_dre(
    db: Session,
    data_inicio: str,
    data_fim: str,
    agrupar_por: str = "mes",  # "dia" | "semana" | "mes" | "total"
) -> dict:
    """
    E-16: DRE por período com breakdown de receita, CMV, lucro bruto e margem.

    Receita     = total de pedidos entregues no período
    CMV         = custo total das OPs concluídas no período
    Lucro Bruto = Receita - CMV
    Margem%     = Lucro Bruto / Receita × 100
    """
    from models import Order, ProductionBatch

    inicio, fim = _parse_period(data_inicio, data_fim)

    # Receita: pedidos entregues
    orders = (
        db.query(Order)
        .filter(
            Order.status == "ENTREGUE",
            Order.data_pedido >= inicio,
            Order.data_pedido <= fim,
        )
        .all()
    )
    receita_total = sum(o.total or 0.0 for o in orders)

    # CMV: OPs concluídas
    batches = (
        db.query(ProductionBatch)
        .filter(
            ProductionBatch.status == "CONCLUIDA",
            ProductionBatch.data_fim >= inicio,
            ProductionBatch.data_fim <= fim,
        )
        .all()
    )
    cmv_total = sum(b.custo_total or 0.0 for b in batches)
    custo_labor_total = sum(b.custo_labor or 0.0 for b in batches)
    custo_energia_total = sum(b.custo_energia_real or 0.0 for b in batches)

    lucro_bruto = receita_total - cmv_total
    margem_bruta_pct = (lucro_bruto / receita_total * 100) if receita_total > 0 else 0.0

    # Agrupamento temporal
    grupos = _group_orders_by_period(orders, agrupar_por)

    return {
        "periodo": {"inicio": data_inicio, "fim": data_fim},
        "agrupamento": agrupar_por,
        "dre_consolidado": {
            "receita_bruta": round(receita_total, 2),
            "cmv": round(cmv_total, 2),
            "cmv_breakdown": {
                "insumos": round(cmv_total - custo_labor_total - custo_energia_total, 2),
                "labor": round(custo_labor_total, 2),
                "energia": round(custo_energia_total, 2),
            },
            "lucro_bruto": round(lucro_bruto, 2),
            "margem_bruta_pct": round(margem_bruta_pct, 1),
            "total_pedidos": len(orders),
            "total_lotes_produzidos": len(batches),
            "ticket_medio": round(receita_total / len(orders), 2) if orders else 0.0,
        },
        "evolucao_temporal": grupos,
    }


def _group_orders_by_period(orders, agrupar_por: str) -> list:
    """Agrupa pedidos por período para evolução temporal."""
    from collections import defaultdict

    grupos: dict[str, float] = defaultdict(float)
    for o in orders:
        if not o.data_pedido:
            continue
        dt = _ensure_utc(o.data_pedido)
        if agrupar_por == "dia":
            key = dt.strftime("%Y-%m-%d")
        elif agrupar_por == "semana":
            key = f"{dt.isocalendar().year}-W{dt.isocalendar().week:02d}"
        else:  # mes
            key = dt.strftime("%Y-%m")
        grupos[key] += o.total or 0.0

    return [
        {"periodo": k, "receita": round(v, 2)}
        for k, v in sorted(grupos.items())
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Relatório de Lote
# ─────────────────────────────────────────────────────────────────────────────

def batch_report(db: Session, batch_id: uuid.UUID) -> dict:
    """
    E-16: Relatório detalhado de um lote de produção.

    Inclui:
    - Rendimento% = quantidade_real / quantidade_planejada × 100
    - Custo por unidade = custo_total / quantidade_real
    - Breakdown de custos: insumos, labor, energia
    - Consumo real vs planejado por ingrediente (divergências)
    - Lotes de ingredientes consumidos (rastreabilidade)
    """
    from models import ProductionBatch, Product, BatchIngredientUsage, Ingredient, LotConsumption, IngredientLot

    batch = db.query(ProductionBatch).filter(ProductionBatch.id == batch_id).first()
    if not batch:
        raise ValueError("Lote não encontrado")

    product = db.query(Product).filter(Product.id == batch.product_id).first()

    qty_plan = batch.quantidade_planejada or 0.0
    qty_real = batch.quantidade_real or 0.0
    rendimento_pct = (qty_real / qty_plan * 100) if qty_plan > 0 else 0.0

    custo_total = batch.custo_total or 0.0
    custo_labor = batch.custo_labor or 0.0
    custo_energia = batch.custo_energia_real or 0.0
    custo_insumos = custo_total - custo_labor - custo_energia
    custo_por_unidade = (custo_total / qty_real) if qty_real > 0 else 0.0

    # Ingredientes usados
    usages = db.query(BatchIngredientUsage).filter(BatchIngredientUsage.batch_id == batch_id).all()
    ingredientes_usados = []
    divergencias_abs = []

    for u in usages:
        ing = db.query(Ingredient).filter(Ingredient.id == u.ingredient_id).first()
        div = abs(u.divergencia_pct or 0.0)
        divergencias_abs.append(div)

        status_div = "ok"
        if div > 10:
            status_div = "alto"
        elif div > 5:
            status_div = "atencao"

        ingredientes_usados.append({
            "ingrediente": ing.nome if ing else str(u.ingredient_id),
            "unidade": ing.unidade if ing else "?",
            "qty_planejada": round(u.qty_planejada or 0.0, 3),
            "qty_real": round(u.qty_real or 0.0, 3),
            "custo_unitario": u.custo_unitario,
            "custo_total_ingrediente": round((u.qty_real or 0) * (u.custo_unitario or 0), 2),
            "divergencia_pct": u.divergencia_pct,
            "status_divergencia": status_div,
        })

    desvio_medio = round(sum(divergencias_abs) / len(divergencias_abs), 1) if divergencias_abs else 0.0

    # Lotes de ingredientes rastreados
    consumos = db.query(LotConsumption).filter(LotConsumption.production_batch_id == batch_id).all()
    lotes_rastreados = []
    for c in consumos:
        lot = db.query(IngredientLot).filter(IngredientLot.id == c.ingredient_lot_id).first()
        if lot:
            ing = db.query(Ingredient).filter(Ingredient.id == lot.ingredient_id).first()
            lotes_rastreados.append({
                "lote_id": str(lot.id),
                "codigo_lote": lot.codigo_lote,
                "ingrediente": ing.nome if ing else "?",
                "quantidade_consumida": round(c.quantidade, 3),
                "fornecedor": lot.fornecedor,
                "data_validade": lot.data_validade.date().isoformat() if lot.data_validade else None,
            })

    duracao_min = None
    if batch.data_inicio and batch.data_fim:
        d1 = _ensure_utc(batch.data_inicio)
        d2 = _ensure_utc(batch.data_fim)
        duracao_min = round((d2 - d1).total_seconds() / 60, 1)

    return {
        "batch_id": str(batch_id),
        "produto": product.nome if product else "?",
        "sku": product.sku if product else None,
        "status": batch.status,
        "operador_id": batch.operador_id,
        "data_inicio": batch.data_inicio.isoformat() if batch.data_inicio else None,
        "data_fim": batch.data_fim.isoformat() if batch.data_fim else None,
        "duracao_min": duracao_min,
        "producao": {
            "quantidade_planejada": qty_plan,
            "quantidade_real": qty_real,
            "rendimento_pct": round(rendimento_pct, 1),
            "status_rendimento": (
                "ok" if rendimento_pct >= 95 else
                "atencao" if rendimento_pct >= 85 else
                "critico"
            ),
        },
        "custos": {
            "custo_insumos": round(custo_insumos, 2),
            "custo_labor": round(custo_labor, 2),
            "custo_energia": round(custo_energia, 2),
            "custo_total": round(custo_total, 2),
            "custo_por_unidade": round(custo_por_unidade, 4),
        },
        "qualidade": {
            "desvio_medio_ingredientes_pct": desvio_medio,
            "ingredientes_com_desvio_alto": sum(
                1 for i in ingredientes_usados if i["status_divergencia"] == "alto"
            ),
        },
        "ingredientes_utilizados": ingredientes_usados,
        "lotes_rastreados": lotes_rastreados,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Top Produtos por Receita e Margem
# ─────────────────────────────────────────────────────────────────────────────

def top_products_report(
    db: Session,
    data_inicio: str,
    data_fim: str,
    limit: int = 10,
) -> dict:
    """
    E-16: Ranking de produtos por receita, volume e margem no período.
    """
    from models import Order, OrderItem, Product

    inicio, fim = _parse_period(data_inicio, data_fim)

    orders = (
        db.query(Order)
        .filter(
            Order.status == "ENTREGUE",
            Order.data_pedido >= inicio,
            Order.data_pedido <= fim,
        )
        .all()
    )

    stats: dict[str, dict] = {}
    for order in orders:
        items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        for it in items:
            pid = str(it.product_id)
            if pid not in stats:
                stats[pid] = {"receita": 0.0, "volume": 0.0, "margem_total": 0.0, "count_pedidos": 0}
            receita_item = (it.quantidade or 0) * (it.preco_unitario or 0)
            stats[pid]["receita"] += receita_item
            stats[pid]["volume"] += it.quantidade or 0
            stats[pid]["margem_total"] += (it.margem_pct or 0)
            stats[pid]["count_pedidos"] += 1

    ranking = []
    for pid, s in stats.items():
        p = db.query(Product).filter(Product.id == uuid.UUID(pid)).first()
        margem_media = s["margem_total"] / s["count_pedidos"] if s["count_pedidos"] > 0 else 0.0
        ranking.append({
            "product_id": pid,
            "produto": p.nome if p else "?",
            "categoria": p.categoria if p else None,
            "receita_total": round(s["receita"], 2),
            "volume_vendido": round(s["volume"], 1),
            "margem_media_pct": round(margem_media, 1),
            "ticket_medio_por_pedido": round(s["receita"] / s["count_pedidos"], 2) if s["count_pedidos"] > 0 else 0.0,
        })

    ranking.sort(key=lambda x: -x["receita_total"])

    receita_total = sum(r["receita_total"] for r in ranking)
    for r in ranking:
        r["participacao_pct"] = round(r["receita_total"] / receita_total * 100, 1) if receita_total > 0 else 0.0

    return {
        "periodo": {"inicio": data_inicio, "fim": data_fim},
        "total_receita_periodo": round(receita_total, 2),
        "ranking": ranking[:limit],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Evolução de Margens por Produto
# ─────────────────────────────────────────────────────────────────────────────

def margin_evolution(
    db: Session,
    product_id: uuid.UUID,
    data_inicio: str,
    data_fim: str,
    agrupar_por: str = "mes",
) -> dict:
    """
    E-16: Evolução da margem de um produto ao longo do tempo.
    Compara margem de venda (pedidos) vs custo de produção (OPs).
    """
    from models import Order, OrderItem, ProductionBatch, Product

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise ValueError("Produto não encontrado")

    inicio, fim = _parse_period(data_inicio, data_fim)

    orders = (
        db.query(Order)
        .filter(Order.status == "ENTREGUE", Order.data_pedido >= inicio, Order.data_pedido <= fim)
        .all()
    )

    batches = (
        db.query(ProductionBatch)
        .filter(
            ProductionBatch.product_id == product_id,
            ProductionBatch.status == "CONCLUIDA",
            ProductionBatch.data_fim >= inicio,
            ProductionBatch.data_fim <= fim,
        )
        .all()
    )

    # Margem de venda por período
    from collections import defaultdict
    vendas: dict[str, dict] = defaultdict(lambda: {"receita": 0.0, "qty": 0.0})
    for order in orders:
        items = db.query(OrderItem).filter(
            OrderItem.order_id == order.id,
            OrderItem.product_id == product_id,
        ).all()
        for it in items:
            dt = _ensure_utc(order.data_pedido)
            key = dt.strftime("%Y-%m") if agrupar_por == "mes" else dt.strftime("%Y-%m-%d")
            vendas[key]["receita"] += (it.quantidade or 0) * (it.preco_unitario or 0)
            vendas[key]["qty"] += it.quantidade or 0

    # Custo de produção por período
    custos: dict[str, float] = defaultdict(float)
    qtys: dict[str, float] = defaultdict(float)
    for b in batches:
        dt = _ensure_utc(b.data_fim)
        key = dt.strftime("%Y-%m") if agrupar_por == "mes" else dt.strftime("%Y-%m-%d")
        custos[key] += b.custo_total or 0.0
        qtys[key] += b.quantidade_real or 0.0

    # Combina em série temporal
    all_keys = sorted(set(list(vendas.keys()) + list(custos.keys())))
    serie = []
    for k in all_keys:
        receita = vendas[k]["receita"]
        custo = custos[k]
        lucro = receita - custo
        margem = (lucro / receita * 100) if receita > 0 else 0.0
        serie.append({
            "periodo": k,
            "receita": round(receita, 2),
            "custo_producao": round(custo, 2),
            "lucro_bruto": round(lucro, 2),
            "margem_pct": round(margem, 1),
        })

    return {
        "product_id": str(product_id),
        "produto": product.nome,
        "periodo": {"inicio": data_inicio, "fim": data_fim},
        "serie_temporal": serie,
    }


# ─────────────────────────────────────────────────────────────────────────────
# SPI — Supplier Performance Index (visão geral por fornecedor)
# ─────────────────────────────────────────────────────────────────────────────

def supplier_performance(
    db: Session,
    data_inicio: str,
    data_fim: str,
) -> list:
    """
    E-16: Índice de desempenho de fornecedores (SPI) no período.

    Considera:
    - Número de cotações / pedidos de compra
    - Divergências de peso no recebimento (InventoryAdjustment)
    - Prazo médio de entrega (data_entrega_prevista vs criação do PO)
    - Score médio de cotações (RFQ score)
    """
    from models import PurchaseOrder, RFQ, Supplier, InventoryAdjustment

    inicio, fim = _parse_period(data_inicio, data_fim)

    suppliers = db.query(Supplier).all()
    result = []

    for supplier in suppliers:
        # Pedidos de compra
        pos = (
            db.query(PurchaseOrder)
            .filter(
                PurchaseOrder.supplier_id == supplier.id,
                PurchaseOrder.created_at >= inicio,
                PurchaseOrder.created_at <= fim,
            )
            .all()
        )

        # RFQs e score médio
        rfqs = (
            db.query(RFQ)
            .filter(
                RFQ.supplier_id == supplier.id,
                RFQ.created_at >= inicio,
                RFQ.created_at <= fim,
            )
            .all()
        )
        scores = [r.score for r in rfqs if r.score is not None]
        score_medio = round(sum(scores) / len(scores), 2) if scores else None

        # Prazo médio de entrega (dias entre criação PO e data_entrega_prevista)
        prazos = []
        for po in pos:
            if po.data_entrega_prevista and po.created_at:
                d1 = _ensure_utc(po.created_at)
                d2 = _ensure_utc(po.data_entrega_prevista)
                prazos.append((d2 - d1).days)
        prazo_medio = round(sum(prazos) / len(prazos), 1) if prazos else None

        result.append({
            "supplier_id": str(supplier.id),
            "fornecedor": supplier.nome,
            "total_pedidos": len(pos),
            "total_cotacoes": len(rfqs),
            "score_medio_cotacao": score_medio,
            "prazo_medio_entrega_dias": prazo_medio,
            "spi_classificacao": _classify_spi(score_medio),
        })

    result.sort(key=lambda x: -(x["score_medio_cotacao"] or 0))
    return result


def _classify_spi(score: Optional[float]) -> str:
    if score is None:
        return "sem_dados"
    if score >= 0.8:
        return "excelente"
    elif score >= 0.6:
        return "bom"
    elif score >= 0.4:
        return "regular"
    return "ruim"

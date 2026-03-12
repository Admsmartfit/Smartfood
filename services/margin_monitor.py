"""
E-03 — Motor de Precificação e Monitor de Margem em Tempo Real

Daemon assíncrono que roda a cada 15 minutos recalculando a margem de todos
os produtos ativos. Gerencia alertas na tabela system_alerts e oferece
funções de threshold e sugestão de preço.
"""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, List

from sqlalchemy.orm import Session, joinedload

from cost_calculator import calculate_product_cost, DEFAULT_LABOR_COST_PER_MIN

logger = logging.getLogger("margin_monitor")

# Intervalo do daemon em segundos (15 minutos)
MONITOR_INTERVAL_SECONDS: int = 15 * 60

# Zona de risco: margem entre (mínima - RISK_BUFFER_PP) e mínima
RISK_BUFFER_PP: float = 5.0

# Tipos de alerta usados em system_alerts
ALERT_TIPO_RISCO = "MARGEM_RISCO"
ALERT_TIPO_VIOLADA = "MARGEM_VIOLADA"


# ---------------------------------------------------------------------------
# Threshold
# ---------------------------------------------------------------------------

def get_margin_status(margem_pct: float, margem_minima: float) -> str:
    """
    Classifica a margem atual em:
      - 'verde'   : margem_pct >= margem_minima
      - 'amarelo' : margem_minima - RISK_BUFFER_PP <= margem_pct < margem_minima
      - 'vermelho': margem_pct < margem_minima - RISK_BUFFER_PP
    """
    if margem_pct >= margem_minima:
        return "verde"
    elif margem_pct >= (margem_minima - RISK_BUFFER_PP):
        return "amarelo"
    else:
        return "vermelho"


# ---------------------------------------------------------------------------
# Sugestão de novo preço
# ---------------------------------------------------------------------------

def suggest_new_price(
    product: Any,
    bom_items: List[Any],
    target_margin_pct: float,
    custo_labor_min: float = DEFAULT_LABOR_COST_PER_MIN,
    tempo_producao_min: float | None = None,
    custo_energia: float | None = None,
) -> dict:
    """
    Calcula o preço mínimo de venda e o markup necessário para que o produto
    atinja a margem-alvo informada.

    Fórmula: Preço = Custo_Total / (1 - target_margin / 100)
    """
    if not (0 < target_margin_pct < 100):
        raise ValueError("target_margin_pct deve estar entre 0 e 100 (exclusive)")

    cost = calculate_product_cost(
        product, bom_items, custo_labor_min, tempo_producao_min, custo_energia
    )
    custo_total: float = cost["custo_total"]

    preco_minimo: float = custo_total / (1 - target_margin_pct / 100)
    novo_markup: float = preco_minimo / custo_total if custo_total > 0 else 1.0
    margem_atual: float = cost["margem_pct"]

    return {
        "produto_id": product.id,
        "produto_nome": product.nome,
        "margem_atual_pct": margem_atual,
        "margem_alvo_pct": target_margin_pct,
        "custo_total": custo_total,
        "preco_atual_sugerido": cost["preco_sugerido"],
        "preco_minimo_sugerido": round(preco_minimo, 2),
        "novo_markup_sugerido": round(novo_markup, 4),
    }


# ---------------------------------------------------------------------------
# Gestão de alertas
# ---------------------------------------------------------------------------

def _resolve_alerts(db: Session, product_id, tipo: str):
    """Marca alertas ativos de um tipo como resolvidos."""
    from models import SystemAlert
    now = datetime.now(timezone.utc)
    db.query(SystemAlert).filter(
        SystemAlert.produto_id == product_id,
        SystemAlert.tipo == tipo,
        SystemAlert.status == "ativo",
    ).update({"status": "resolvido", "resolvido_em": now})


def _upsert_alert(db: Session, product_id, tipo: str, mensagem: str, severidade: str):
    """Cria alerta se não houver um ativo do mesmo tipo para o produto."""
    from models import SystemAlert
    exists = db.query(SystemAlert).filter(
        SystemAlert.produto_id == product_id,
        SystemAlert.tipo == tipo,
        SystemAlert.status == "ativo",
    ).first()
    if not exists:
        alert = SystemAlert(
            tipo=tipo,
            produto_id=product_id,
            mensagem=mensagem,
            severidade=severidade,
            status="ativo",
        )
        db.add(alert)


def _manage_alerts_for_product(
    db: Session, product: Any, status: str, margem_pct: float, preco_sugerido: float
):
    """Cria ou resolve alertas de margem conforme o status calculado."""
    pid = product.id

    if status == "verde":
        _resolve_alerts(db, pid, ALERT_TIPO_RISCO)
        _resolve_alerts(db, pid, ALERT_TIPO_VIOLADA)

    elif status == "amarelo":
        _resolve_alerts(db, pid, ALERT_TIPO_VIOLADA)
        _upsert_alert(
            db, pid, ALERT_TIPO_RISCO,
            mensagem=(
                f"Produto '{product.nome}': margem em risco ({margem_pct:.1f}%). "
                f"Margem mínima: {product.margem_minima:.1f}%. "
                "Monitore o custo dos insumos."
            ),
            severidade="atencao",
        )

    else:  # vermelho
        _resolve_alerts(db, pid, ALERT_TIPO_RISCO)
        _upsert_alert(
            db, pid, ALERT_TIPO_VIOLADA,
            mensagem=(
                f"Produto '{product.nome}': MARGEM VIOLADA ({margem_pct:.1f}%). "
                f"Margem mínima: {product.margem_minima:.1f}%. "
                f"Preço sugerido para recuperar: R$ {preco_sugerido:.2f}."
            ),
            severidade="critico",
        )


# ---------------------------------------------------------------------------
# Cálculo em cascata (chamado ao atualizar preço de insumo)
# ---------------------------------------------------------------------------

def recalculate_products_for_ingredient(
    db: Session, ingredient_id
) -> List[dict]:
    """
    Recalcula margem de todos os produtos que usam o ingrediente informado.
    Atualiza alertas e retorna lista com impacto.
    """
    from models import BOMItem, Product

    # Produtos afetados
    affected_product_ids = (
        db.query(BOMItem.product_id)
        .filter(BOMItem.ingredient_id == ingredient_id)
        .distinct()
        .all()
    )
    affected_product_ids = [row[0] for row in affected_product_ids]

    results = []
    for pid in affected_product_ids:
        product = db.query(Product).filter(Product.id == pid, Product.ativo == True).first()
        if not product:
            continue
        bom_items = (
            db.query(BOMItem)
            .options(joinedload(BOMItem.ingredient), joinedload(BOMItem.supply))
            .filter(BOMItem.product_id == pid)
            .all()
        )
        cost = calculate_product_cost(product, bom_items)
        status = get_margin_status(cost["margem_pct"], product.margem_minima or 0)
        _manage_alerts_for_product(db, product, status, cost["margem_pct"], cost["preco_sugerido"])
        results.append({
            "produto_id": str(product.id),
            "produto_nome": product.nome,
            "margem_pct": cost["margem_pct"],
            "preco_sugerido": cost["preco_sugerido"],
            "status_margem": status,
        })

    db.commit()
    return results


# ---------------------------------------------------------------------------
# Leitura rápida de margens (sem alterar alertas — para fragments HTMX)
# ---------------------------------------------------------------------------

def get_all_margins(db: Session) -> list:
    """
    Retorna a margem calculada de todos os produtos ativos.
    Leitura pura: não gera alertas, não faz commit.
    Usado pelo fragment /api/fragments/margin-table.
    """
    from models import BOMItem, Product

    products = db.query(Product).filter(Product.ativo == True).order_by(Product.nome).all()
    result = []
    for product in products:
        bom_items = (
            db.query(BOMItem)
            .options(joinedload(BOMItem.ingredient), joinedload(BOMItem.supply))
            .filter(BOMItem.product_id == product.id)
            .all()
        )
        cost = 0.0
        margin_pct = 0.0
        price = 0.0
        try:
            data = calculate_product_cost(product, bom_items)
            cost = data.get("custo_total", 0.0)
            margin_pct = data.get("margem_pct", 0.0)
            price = data.get("preco_sugerido", 0.0)
        except Exception:
            pass

        threshold = product.margem_minima or 20.0
        if margin_pct <= 0:
            status = "critical"
        elif margin_pct < threshold * 0.75:
            status = "critical"
        elif margin_pct < threshold:
            status = "warning"
        else:
            status = "ok"

        result.append({
            "product_id": str(product.id),
            "name": product.nome,
            "sku": product.sku,
            "cost_per_unit": round(cost, 2),
            "price": round(price, 2),
            "margin_pct": round(margin_pct, 1),
            "threshold": threshold,
            "status": status,
        })
    return result


# ---------------------------------------------------------------------------
# Monitor daemon (execução a cada 15 min)
# ---------------------------------------------------------------------------

def run_monitor_cycle(db: Session) -> int:
    """
    Executa um ciclo completo do monitor: recalcula margem de todos os produtos
    ativos e gerencia alertas. Retorna o número de produtos processados.
    """
    from models import BOMItem, Product

    products = db.query(Product).filter(Product.ativo == True).all()
    processed = 0

    for product in products:
        bom_items = (
            db.query(BOMItem)
            .options(joinedload(BOMItem.ingredient), joinedload(BOMItem.supply))
            .filter(BOMItem.product_id == product.id)
            .all()
        )
        if not bom_items:
            continue

        cost = calculate_product_cost(product, bom_items)
        status = get_margin_status(cost["margem_pct"], product.margem_minima or 0)
        _manage_alerts_for_product(db, product, status, cost["margem_pct"], cost["preco_sugerido"])
        processed += 1

    db.commit()
    logger.info("Ciclo do monitor concluído: %d produto(s) processado(s)", processed)
    return processed


async def margin_monitor_task(get_db_func):
    """
    Tarefa assíncrona do daemon. Chama run_monitor_cycle a cada MONITOR_INTERVAL_SECONDS.
    Deve ser iniciada via asyncio.create_task() no lifespan da aplicação.
    """
    logger.info(
        "MarginMonitor iniciado — ciclo a cada %d minutos",
        MONITOR_INTERVAL_SECONDS // 60,
    )
    while True:
        await asyncio.sleep(MONITOR_INTERVAL_SECONDS)
        db = next(get_db_func())
        try:
            run_monitor_cycle(db)
        except Exception as exc:
            logger.exception("Erro no ciclo do MarginMonitor: %s", exc)
        finally:
            db.close()

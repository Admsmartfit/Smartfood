"""
E-04 — Motor de Inteligência de Demanda (MRP Preditivo)

Arquitetura em 5 camadas:
  1. Coleta   → registra eventos de demanda com tag sazonal
  2. Análise  → médias, desvio, tendência, fatores por dia da semana
  3. Previsão → média móvel ponderada (7d×50% + 30d×30% + 90d×20%) × fator sazonal
  4. MRP      → explode BOM, calcula necessidade bruta de insumos
  5. Alertas  → days_to_order por insumo com semáforo critico/atencao/ok
"""
import asyncio
import logging
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
import uuid

from sqlalchemy.orm import Session, joinedload

logger = logging.getLogger("demand_engine")

# Nome do dia da semana em pt-BR (índice 0 = segunda)
DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

# ─────────────────────────────────────────────────────────────────────────────
# CAMADA 1 — Coleta
# ─────────────────────────────────────────────────────────────────────────────

def _sazonalidade_tag(dt: date) -> str:
    """Classifica a data como fim_de_semana, feriado ou dia_util."""
    # Lista de feriados nacionais fixos (MM-DD) — extensível
    FERIADOS_FIXOS = {
        "01-01", "04-21", "05-01", "09-07",
        "10-12", "11-02", "11-15", "12-25",
    }
    md = dt.strftime("%m-%d")
    if md in FERIADOS_FIXOS:
        return "feriado"
    if dt.weekday() >= 5:   # 5=Sáb, 6=Dom
        return "fim_de_semana"
    return "dia_util"


def record_demand_event(
    db: Session,
    product_id: uuid.UUID,
    qty: float,
    event_date: date,
    channel: str,
    customer_id: Optional[uuid.UUID] = None,
    delivery_date: Optional[date] = None,
) -> Any:
    """
    Camada 1 — Registra um evento de demanda com tag de sazonalidade automática.
    Retorna a instância DemandEvent criada.
    """
    from models import DemandEvent

    tag = _sazonalidade_tag(event_date)
    event = DemandEvent(
        produto_id=product_id,
        cliente_id=customer_id,
        quantidade=qty,
        data_pedido=datetime.combine(event_date, datetime.min.time()),
        data_entrega=datetime.combine(delivery_date, datetime.min.time()) if delivery_date else None,
        canal=channel,
        sazonalidade_tag=tag,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


# ─────────────────────────────────────────────────────────────────────────────
# CAMADA 2 — Análise
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate_daily(events: list) -> dict[date, float]:
    """Soma quantidades por dia."""
    agg: dict[date, float] = defaultdict(float)
    for ev in events:
        day = ev.data_pedido.date() if hasattr(ev.data_pedido, "date") else ev.data_pedido
        agg[day] += ev.quantidade
    return dict(agg)


def analyze_demand(db: Session, product_id: uuid.UUID, days: int = 90) -> dict:
    """
    Camada 2 — Analisa histórico de demanda.

    Retorna:
      media_diaria, desvio_padrao, tendencia_crescimento_pct,
      melhor_dia_semana, pior_dia_semana, fator_sazonal_por_dia_semana,
      total_eventos, periodo_dias
    """
    from models import DemandEvent

    since = datetime.now(timezone.utc) - timedelta(days=days)
    events = (
        db.query(DemandEvent)
        .filter(
            DemandEvent.produto_id == product_id,
            DemandEvent.data_pedido >= since,
        )
        .all()
    )

    if not events:
        return {
            "product_id": str(product_id),
            "total_eventos": 0,
            "periodo_dias": days,
            "media_diaria": 0.0,
            "desvio_padrao": 0.0,
            "tendencia_crescimento_pct": 0.0,
            "melhor_dia_semana": None,
            "pior_dia_semana": None,
            "fator_sazonal_por_dia_semana": {d: 1.0 for d in DIAS_SEMANA},
        }

    daily = _aggregate_daily(events)
    values = list(daily.values())
    media_diaria = statistics.mean(values)
    desvio = statistics.stdev(values) if len(values) > 1 else 0.0

    # Tendência: compara média da 1ª metade vs 2ª metade do período
    sorted_days = sorted(daily.keys())
    mid = len(sorted_days) // 2
    if mid > 0:
        first_half = [daily[d] for d in sorted_days[:mid]]
        second_half = [daily[d] for d in sorted_days[mid:]]
        media_primeira = statistics.mean(first_half)
        media_segunda = statistics.mean(second_half)
        tendencia = (
            (media_segunda - media_primeira) / media_primeira * 100
            if media_primeira > 0 else 0.0
        )
    else:
        tendencia = 0.0

    # Fator sazonal por dia da semana
    weekday_totals: dict[int, list[float]] = defaultdict(list)
    for d, qty in daily.items():
        weekday_totals[d.weekday()].append(qty)

    weekday_avgs: dict[int, float] = {
        wd: statistics.mean(vals) for wd, vals in weekday_totals.items()
    }

    # Fatores normalizados em relação à média geral
    fatores = {}
    for wd in range(7):
        avg = weekday_avgs.get(wd, media_diaria)
        fatores[DIAS_SEMANA[wd]] = round(avg / media_diaria, 3) if media_diaria > 0 else 1.0

    melhor_wd = max(weekday_avgs, key=weekday_avgs.get) if weekday_avgs else None
    pior_wd = min(weekday_avgs, key=weekday_avgs.get) if weekday_avgs else None

    return {
        "product_id": str(product_id),
        "total_eventos": len(events),
        "periodo_dias": days,
        "media_diaria": round(media_diaria, 2),
        "desvio_padrao": round(desvio, 2),
        "tendencia_crescimento_pct": round(tendencia, 2),
        "melhor_dia_semana": DIAS_SEMANA[melhor_wd] if melhor_wd is not None else None,
        "pior_dia_semana": DIAS_SEMANA[pior_wd] if pior_wd is not None else None,
        "fator_sazonal_por_dia_semana": fatores,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CAMADA 3 — Previsão
# ─────────────────────────────────────────────────────────────────────────────

def _window_avg(daily: dict[date, float], days: int) -> float:
    """Média diária dos últimos `days` dias."""
    cutoff = date.today() - timedelta(days=days)
    vals = [qty for d, qty in daily.items() if d >= cutoff]
    return statistics.mean(vals) if vals else 0.0


def _confidence(media: float, desvio: float) -> float:
    """Confiança baseada no coeficiente de variação (CV = desvio/media)."""
    if media == 0:
        return 0.0
    cv = desvio / media
    return round(max(40.0, 100.0 - cv * 80.0), 1)


def forecast_demand(db: Session, product_id: uuid.UUID, horizon_days: int = 14) -> dict:
    """
    Camada 3 — Previsão por média móvel ponderada.

    Pesos: últimos 7d = 50%, últimos 30d = 30%, últimos 90d = 20%.
    Cada dia do horizonte é multiplicado pelo fator sazonal do dia da semana.

    Retorna: previsao_diaria[], previsao_total_periodo, confianca_pct,
             intervalo_min, intervalo_max, modelo_usado
    """
    from models import DemandEvent

    since = datetime.now(timezone.utc) - timedelta(days=90)
    events = (
        db.query(DemandEvent)
        .filter(
            DemandEvent.produto_id == product_id,
            DemandEvent.data_pedido >= since,
        )
        .all()
    )

    daily = _aggregate_daily(events)
    values = list(daily.values())
    media_geral = statistics.mean(values) if values else 0.0
    desvio = statistics.stdev(values) if len(values) > 1 else 0.0

    avg_7d = _window_avg(daily, 7)
    avg_30d = _window_avg(daily, 30)
    avg_90d = _window_avg(daily, 90)

    # Média ponderada base
    base_avg = avg_7d * 0.50 + avg_30d * 0.30 + avg_90d * 0.20

    # Fatores sazonais por dia da semana
    weekday_totals: dict[int, list[float]] = defaultdict(list)
    for d, qty in daily.items():
        weekday_totals[d.weekday()].append(qty)

    weekday_avgs: dict[int, float] = {
        wd: statistics.mean(vals) for wd, vals in weekday_totals.items()
    }
    fatores_wd: dict[int, float] = {
        wd: avg / media_geral if media_geral > 0 else 1.0
        for wd, avg in weekday_avgs.items()
    }

    # Projeção diária
    previsao_diaria = []
    today = date.today()
    for i in range(1, horizon_days + 1):
        fut_date = today + timedelta(days=i)
        wd = fut_date.weekday()
        fator = fatores_wd.get(wd, 1.0)
        qty = round(base_avg * fator, 2)
        previsao_diaria.append({
            "data": fut_date.isoformat(),
            "dia_semana": DIAS_SEMANA[wd],
            "sazonalidade": _sazonalidade_tag(fut_date),
            "quantidade_prevista": qty,
        })

    total = sum(d["quantidade_prevista"] for d in previsao_diaria)
    confianca = _confidence(media_geral, desvio)
    margem = desvio * math.sqrt(horizon_days)

    return {
        "product_id": str(product_id),
        "horizon_days": horizon_days,
        "modelo_usado": "media_movel_ponderada_sazonal",
        "avg_7d": round(avg_7d, 2),
        "avg_30d": round(avg_30d, 2),
        "avg_90d": round(avg_90d, 2),
        "base_diaria_ponderada": round(base_avg, 2),
        "previsao_total_periodo": round(total, 1),
        "confianca_pct": confianca,
        "intervalo_min": round(max(0, total - margem), 1),
        "intervalo_max": round(total + margem, 1),
        "previsao_diaria": previsao_diaria,
    }


# ─────────────────────────────────────────────────────────────────────────────
# CAMADA 4 — MRP (Explosão de BOM)
# ─────────────────────────────────────────────────────────────────────────────

def calculate_production_plan(
    db: Session,
    product_id: uuid.UUID,
    forecast_qty: float,
) -> dict:
    """
    Camada 4 — Calcula necessidade bruta de insumos para produzir `forecast_qty`.

    Subtrai estoque atual do produto acabado, adiciona estoque de segurança
    (padrão 15%) e explode a BOM para cada insumo necessário.
    """
    from models import Product, BOMItem

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        return {"erro": "Produto não encontrado"}

    seguranca_pct = product.estoque_seguranca_pct or 15.0
    estoque_atual = product.estoque_atual or 0.0

    # Necessidade líquida com margem de segurança
    necessidade_bruta = forecast_qty * (1 + seguranca_pct / 100)
    necessidade_liquida = max(0.0, necessidade_bruta - estoque_atual)

    bom_items = (
        db.query(BOMItem)
        .options(joinedload(BOMItem.ingredient), joinedload(BOMItem.supply))
        .filter(BOMItem.product_id == product_id)
        .all()
    )

    insumos_necessarios = []
    for item in bom_items:
        if item.ingredient_id and item.ingredient:
            ing = item.ingredient
            qty_necessaria = item.quantidade * necessidade_liquida
            qty_disponivel = ing.estoque_atual or 0.0
            qty_comprar = max(0.0, qty_necessaria - qty_disponivel)
            insumos_necessarios.append({
                "tipo": "ingrediente",
                "id": str(ing.id),
                "nome": ing.nome,
                "unidade": item.unidade or ing.unidade,
                "qty_por_unidade_produto": item.quantidade,
                "qty_necessaria_total": round(qty_necessaria, 3),
                "qty_em_estoque": qty_disponivel,
                "qty_a_comprar": round(qty_comprar, 3),
                "lead_time_dias": ing.lead_time_dias or 0,
                "status": "ok" if qty_comprar == 0 else "deficit",
            })
        elif item.supply_id and item.supply:
            sup = item.supply
            qty_necessaria = item.quantidade * necessidade_liquida
            qty_disponivel = sup.estoque_atual or 0.0
            qty_comprar = max(0.0, qty_necessaria - qty_disponivel)
            insumos_necessarios.append({
                "tipo": "supply",
                "id": str(sup.id),
                "nome": sup.nome,
                "unidade": item.unidade or sup.unidade,
                "qty_por_unidade_produto": item.quantidade,
                "qty_necessaria_total": round(qty_necessaria, 3),
                "qty_em_estoque": qty_disponivel,
                "qty_a_comprar": round(qty_comprar, 3),
                "lead_time_dias": sup.lead_time_dias or 0,
                "status": "ok" if qty_comprar == 0 else "deficit",
            })

    tem_deficit = any(i["status"] == "deficit" for i in insumos_necessarios)

    return {
        "product_id": str(product_id),
        "produto_nome": product.nome,
        "forecast_qty": forecast_qty,
        "estoque_atual_produto": estoque_atual,
        "seguranca_pct": seguranca_pct,
        "necessidade_bruta": round(necessidade_bruta, 1),
        "necessidade_liquida": round(necessidade_liquida, 1),
        "insumos_necessarios": insumos_necessarios,
        "tem_deficit": tem_deficit,
        "total_insumos": len(insumos_necessarios),
        "insumos_com_deficit": sum(1 for i in insumos_necessarios if i["status"] == "deficit"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# CAMADA 5 — Alertas de Compra
# ─────────────────────────────────────────────────────────────────────────────

def calculate_purchase_alerts(
    db: Session,
    ingredient_id: uuid.UUID,
    qty_needed: float,
    production_date: Optional[date] = None,
) -> dict:
    """
    Camada 5 — Calcula urgência de compra para um ingrediente.

    Compara estoque atual com necessidade e subtrai lead_time do fornecedor
    da data prevista de produção.

    Retorna: days_to_order, urgencia (critico|atencao|ok), data_limite_pedido
    """
    from models import Ingredient

    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        return {"erro": "Ingrediente não encontrado"}

    estoque = ing.estoque_atual or 0.0
    lead_time = ing.lead_time_dias or 0
    qty_faltante = max(0.0, qty_needed - estoque)

    prod_date = production_date or (date.today() + timedelta(days=7))
    data_limite = prod_date - timedelta(days=lead_time)
    days_to_order = (data_limite - date.today()).days

    if qty_faltante == 0:
        urgencia = "ok"
    elif days_to_order <= 0:
        urgencia = "critico"
    elif days_to_order <= 3:
        urgencia = "atencao"
    else:
        urgencia = "ok"

    return {
        "ingredient_id": str(ingredient_id),
        "ingrediente_nome": ing.nome,
        "estoque_atual": estoque,
        "qty_necessaria": qty_needed,
        "qty_faltante": round(qty_faltante, 3),
        "lead_time_dias": lead_time,
        "data_producao_prevista": prod_date.isoformat(),
        "data_limite_pedido": data_limite.isoformat(),
        "days_to_order": days_to_order,
        "urgencia": urgencia,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Pipeline Completa — Job Diário
# ─────────────────────────────────────────────────────────────────────────────

def run_daily_pipeline(db: Session) -> dict:
    """
    Executa a pipeline completa para todos os produtos ativos:
      1. Analisa demanda histórica
      2. Gera forecast de 14 dias
      3. Persiste DemandForecast na tabela
      4. Calcula plano de produção + alertas de compra
      5. Gera SystemAlerts para déficits críticos

    Retorna resumo da execução.
    """
    from models import Product, DemandForecast, SystemAlert

    products = db.query(Product).filter(Product.ativo == True).all()
    resumo = {"produtos_processados": 0, "forecasts_gerados": 0, "alertas_criados": 0}

    for product in products:
        try:
            forecast = forecast_demand(db, product.id, horizon_days=14)
            total_previsto = forecast["previsao_total_periodo"]
            confianca = forecast["confianca_pct"]

            # Persiste DemandForecast
            df = DemandForecast(
                produto_id=product.id,
                periodo="14d",
                qty_prevista=total_previsto,
                confianca_pct=confianca,
                modelo_used=forecast["modelo_usado"],
            )
            db.add(df)
            resumo["forecasts_gerados"] += 1

            # MRP — alerta de compra para insumos em déficit
            plano = calculate_production_plan(db, product.id, total_previsto)
            for insumo in plano.get("insumos_necessarios", []):
                if insumo["status"] != "deficit" or insumo["tipo"] != "ingrediente":
                    continue

                alert_info = calculate_purchase_alerts(
                    db,
                    uuid.UUID(insumo["id"]),
                    insumo["qty_a_comprar"],
                )
                urgencia = alert_info.get("urgencia", "ok")
                if urgencia == "ok":
                    continue

                severidade = "critico" if urgencia == "critico" else "atencao"
                alert = SystemAlert(
                    tipo="COMPRA_URGENTE",
                    produto_id=product.id,
                    mensagem=(
                        f"[{urgencia.upper()}] Comprar {insumo['qty_a_comprar']:.1f} "
                        f"{insumo['unidade']} de '{insumo['nome']}' "
                        f"— prazo: {alert_info['data_limite_pedido']} "
                        f"(lead time {insumo['lead_time_dias']}d)"
                    ),
                    severidade=severidade,
                    status="ativo",
                )
                db.add(alert)
                resumo["alertas_criados"] += 1

            resumo["produtos_processados"] += 1

        except Exception as exc:
            logger.exception("Erro ao processar produto %s: %s", product.id, exc)

    db.commit()
    logger.info("Pipeline diária concluída: %s", resumo)
    return resumo


# ─────────────────────────────────────────────────────────────────────────────
# Scheduler assíncrono — roda às 23h59 todo dia
# ─────────────────────────────────────────────────────────────────────────────

async def _seconds_until(hour: int, minute: int) -> float:
    """Segundos até o próximo HH:MM (hoje ou amanhã)."""
    now = datetime.now()
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()


async def daily_demand_task(get_db_func):
    """
    Tarefa assíncrona do scheduler diário. Executa run_daily_pipeline às 23h59.
    Deve ser iniciada via asyncio.create_task() no lifespan da aplicação.
    """
    logger.info("DemandEngine scheduler iniciado — execução diária às 23h59")
    while True:
        secs = await _seconds_until(23, 59)
        logger.info("Próxima execução da pipeline de demanda em %.0f segundos", secs)
        await asyncio.sleep(secs)
        db = next(get_db_func())
        try:
            run_daily_pipeline(db)
        except Exception as exc:
            logger.exception("Erro na pipeline diária de demanda: %s", exc)
        finally:
            db.close()

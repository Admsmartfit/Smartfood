"""
E-04 — Rotas do Motor de Inteligência de Demanda (MRP Preditivo)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import date
import uuid

from database import get_db
from models import Product, Ingredient
from services.demand_engine import (
    record_demand_event,
    analyze_demand,
    forecast_demand,
    calculate_production_plan,
    calculate_purchase_alerts,
    run_daily_pipeline,
)

router = APIRouter(prefix="/demand", tags=["Demanda e MRP - E-04"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class DemandEventRequest(BaseModel):
    product_id: uuid.UUID
    qty: float
    event_date: date
    channel: str = "direto"
    customer_id: Optional[uuid.UUID] = None
    delivery_date: Optional[date] = None


class DemandEventResponse(BaseModel):
    id: uuid.UUID
    produto_id: uuid.UUID
    quantidade: float
    data_pedido: str
    canal: str
    sazonalidade_tag: str

    model_config = {"from_attributes": True}


class PipelineResponse(BaseModel):
    produtos_processados: int
    forecasts_gerados: int
    alertas_criados: int
    mensagem: str


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/events", response_model=DemandEventResponse, status_code=201)
def create_demand_event(payload: DemandEventRequest, db: Session = Depends(get_db)):
    """
    Camada 1 — Registra um evento de demanda com tag sazonal automática
    (fim_de_semana | feriado | dia_util).
    """
    product = db.query(Product).filter(Product.id == payload.product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    event = record_demand_event(
        db=db,
        product_id=payload.product_id,
        qty=payload.qty,
        event_date=payload.event_date,
        channel=payload.channel,
        customer_id=payload.customer_id,
        delivery_date=payload.delivery_date,
    )
    return DemandEventResponse(
        id=event.id,
        produto_id=event.produto_id,
        quantidade=event.quantidade,
        data_pedido=event.data_pedido.isoformat(),
        canal=event.canal,
        sazonalidade_tag=event.sazonalidade_tag,
    )


@router.get("/products/{product_id}/analysis")
def get_demand_analysis(
    product_id: uuid.UUID,
    days: int = Query(default=90, ge=7, le=365, description="Janela histórica em dias"),
    db: Session = Depends(get_db),
):
    """
    Camada 2 — Análise de demanda histórica: média diária, desvio padrão,
    tendência de crescimento e fatores sazonais por dia da semana.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    return analyze_demand(db, product_id, days=days)


@router.get("/products/{product_id}/forecast")
def get_demand_forecast(
    product_id: uuid.UUID,
    horizon_days: int = Query(default=14, ge=1, le=90, description="Horizonte de previsão em dias"),
    db: Session = Depends(get_db),
):
    """
    Camada 3 — Previsão de demanda por média móvel ponderada sazonal.
    Pesos: 7d × 50% + 30d × 30% + 90d × 20%, multiplicado pelo fator do dia da semana.
    Retorna previsão diária, total do período, confiança e intervalos min/max.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    return forecast_demand(db, product_id, horizon_days=horizon_days)


@router.get("/products/{product_id}/production-plan")
def get_production_plan(
    product_id: uuid.UUID,
    forecast_qty: float = Query(..., gt=0, description="Quantidade prevista a produzir"),
    db: Session = Depends(get_db),
):
    """
    Camada 4 — Plano de produção (MRP): explode a BOM, subtrai estoques
    atuais e retorna lista de insumos necessários com quantidade a comprar.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    plan = calculate_production_plan(db, product_id, forecast_qty)
    if "erro" in plan:
        raise HTTPException(status_code=422, detail=plan["erro"])
    return plan


@router.get("/purchase-alerts/{ingredient_id}")
def get_purchase_alert(
    ingredient_id: uuid.UUID,
    qty_needed: float = Query(..., gt=0, description="Quantidade necessária do ingrediente"),
    production_date: Optional[date] = Query(
        default=None,
        description="Data prevista de produção (padrão: hoje + 7 dias)"
    ),
    db: Session = Depends(get_db),
):
    """
    Camada 5 — Calcula urgência de compra: compara estoque atual com necessidade,
    desconta lead time e retorna days_to_order e urgencia (critico|atencao|ok).
    """
    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        raise HTTPException(status_code=404, detail="Ingrediente não encontrado")

    result = calculate_purchase_alerts(db, ingredient_id, qty_needed, production_date)
    if "erro" in result:
        raise HTTPException(status_code=422, detail=result["erro"])
    return result


@router.post("/run-pipeline", response_model=PipelineResponse)
def trigger_daily_pipeline(db: Session = Depends(get_db)):
    """
    Dispara manualmente a pipeline completa de demanda (equivalente ao job das 23h59).
    Processa todos os produtos ativos: gera forecasts, salva DemandForecast e
    cria SystemAlerts para insumos com compra urgente.
    """
    result = run_daily_pipeline(db)
    return PipelineResponse(
        **result,
        mensagem=(
            f"Pipeline executada: {result['produtos_processados']} produto(s), "
            f"{result['forecasts_gerados']} forecast(s), "
            f"{result['alertas_criados']} alerta(s) gerado(s)."
        ),
    )

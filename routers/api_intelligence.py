"""
FE-02 — API de Inteligência: Forecast Chart + Simulador "E se?"
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/intelligence", tags=["API — Inteligência FE-02"])
templates = Jinja2Templates(directory="templates")


class SimulateRequest(BaseModel):
    product_id: uuid.UUID
    qty_requested: float


# ─── Fragmento do Gráfico de Forecast ────────────────────────────────────────

@router.get("/fragments/forecast/{product_id}", response_class=HTMLResponse)
def fragment_forecast_chart(
    product_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Retorna SVG de barras (14 dias) + tabela de previsão diária.
    Gerado em Jinja2 puro, sem lib JavaScript.
    """
    from services.demand_engine import forecast_demand
    from models import Product

    produto = db.query(Product).filter(Product.id == product_id).first()
    if not produto:
        return HTMLResponse("<p class='text-red-500 p-4'>Produto não encontrado.</p>")

    try:
        forecast = forecast_demand(db, product_id, horizon_days=14)
    except Exception as e:
        forecast = {
            "previsao_diaria": [],
            "confianca_pct": 0,
            "modelo_usado": "sem histórico",
            "previsao_total_periodo": 0,
        }

    dias = forecast.get("previsao_diaria", [])
    # Normaliza para o template: lista de {data, qty_prevista, is_peak}
    max_qty = max((d.get("qty_prevista", 0) for d in dias), default=1) or 1

    return templates.TemplateResponse(
        "fragments/forecast_chart.html",
        {
            "request": request,
            "produto": produto,
            "dias": dias,
            "max_qty": max_qty,
            "confianca_pct": forecast.get("confianca_pct", 0),
            "modelo_usado": forecast.get("modelo_usado", ""),
            "previsao_total": forecast.get("previsao_total_periodo", 0),
        },
    )


# ─── Simulador "E se?" ────────────────────────────────────────────────────────

@router.post("/simulate", response_class=HTMLResponse)
def simulate_production(
    body: SimulateRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Simula se é possível produzir qty_requested unidades do produto.
    Retorna: can_produce, missing_ingredients, estimated_hours.
    """
    from services.demand_engine import calculate_production_plan
    from models import Product

    produto = db.query(Product).filter(Product.id == body.product_id).first()
    if not produto:
        return HTMLResponse("<p class='text-red-500 p-4'>Produto não encontrado.</p>")

    can_produce = True
    missing = []
    estimated_hours = 0.0

    try:
        plan = calculate_production_plan(db, body.product_id, body.qty_requested)
        can_produce = plan.get("viavel", False)
        missing = plan.get("deficit_ingredientes", [])
        # Tempo estimado em horas baseado em tempo_producao_min por unidade
        tempo_por_unidade = (produto.tempo_producao_min or 30.0)
        estimated_hours = round((tempo_por_unidade * body.qty_requested) / 60, 1)
    except Exception:
        # Fallback: verifica BOM manualmente
        from models import BOMItem, Ingredient
        bom_items = db.query(BOMItem).filter(BOMItem.product_id == body.product_id).all()
        for item in bom_items:
            if item.ingredient_id:
                ing = db.query(Ingredient).filter(Ingredient.id == item.ingredient_id).first()
                if ing:
                    qty_needed = (item.quantidade or 0) * body.qty_requested
                    if (ing.estoque_atual or 0) < qty_needed:
                        can_produce = False
                        missing.append({
                            "ingrediente": ing.nome,
                            "qty_needed": round(qty_needed, 2),
                            "qty_available": round(ing.estoque_atual or 0, 2),
                            "unidade": ing.unidade or "",
                        })
        tempo_por_unidade = produto.tempo_producao_min or 30.0
        estimated_hours = round((tempo_por_unidade * body.qty_requested) / 60, 1)

    import json
    trigger = json.dumps({"showToast": {"message": "Simulação concluída", "type": "info"}})
    response = templates.TemplateResponse(
        "fragments/simulate_result.html",
        {
            "request": request,
            "produto": produto,
            "qty_requested": body.qty_requested,
            "can_produce": can_produce,
            "missing": missing,
            "estimated_hours": estimated_hours,
        },
    )
    response.headers["HX-Trigger"] = trigger
    return response

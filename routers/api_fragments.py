"""
FE-02 — API de Fragmentos HTMX

Retornam HTML parcial (partials) consumidos pelo HTMX.
Todos os endpoints retornam HTMLResponse + header HX-Trigger para toast quando relevante.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/fragments", tags=["API — Fragmentos HTMX"])
templates = Jinja2Templates(directory="templates")


def _html(template: str, ctx: dict, trigger: Optional[dict] = None) -> HTMLResponse:
    """Helper: renderiza template e opcionalmente injeta HX-Trigger."""
    import json
    response = templates.TemplateResponse(template, ctx)
    if trigger:
        response.headers["HX-Trigger"] = json.dumps(trigger)
    return response


# ─── KPI Cards ───────────────────────────────────────────────────────────────

@router.get("/kpis", response_class=HTMLResponse)
def fragment_kpis(request: Request, db: Session = Depends(get_db)):
    """
    Retorna 4 KPI cards:
    - Previsão Semanal (demand forecast)
    - Compras Urgentes (insumos críticos)
    - Produção Pendente (OPs aprovadas)
    - Margem Média (produtos ativos)
    """
    from models import ProductionBatch, Ingredient, Product

    # OPs pendentes (APROVADA)
    ops_pendentes = (
        db.query(ProductionBatch)
        .filter(ProductionBatch.status.in_(["APROVADA", "EM_PRODUCAO"]))
        .count()
    )

    # Compras urgentes
    ings = db.query(Ingredient).filter(Ingredient.ativo == True).all()
    compras_urgentes = sum(
        1 for i in ings
        if (i.estoque_atual or 0) <= (i.estoque_minimo or 0)
    )

    # Margem média dos produtos
    produtos = db.query(Product).filter(Product.ativo == True).all()
    margens = []
    for p in produtos:
        try:
            from services.margin_monitor import calcular_margem_produto
            m = calcular_margem_produto(db, p)
            if m and m.get("margem_pct") is not None:
                margens.append(m["margem_pct"])
        except Exception:
            pass
    margem_media = round(sum(margens) / len(margens), 1) if margens else 0.0

    kpis = [
        {
            "label": "OPs Ativas",
            "value": ops_pendentes,
            "unit": "",
            "subtitle": "em produção / aprovadas",
            "icon": "factory",
            "delta_pct": None,
            "delta_direction": None,
            "is_critical": ops_pendentes == 0,
        },
        {
            "label": "Compras Urgentes",
            "value": compras_urgentes,
            "unit": "",
            "subtitle": "insumos abaixo do mínimo",
            "icon": "shopping-cart",
            "delta_pct": None,
            "delta_direction": None,
            "is_critical": compras_urgentes > 0,
        },
        {
            "label": "Produtos Ativos",
            "value": len(produtos),
            "unit": "",
            "subtitle": "no catálogo",
            "icon": "package",
            "delta_pct": None,
            "delta_direction": None,
            "is_critical": False,
        },
        {
            "label": "Margem Média",
            "value": f"{margem_media:.1f}",
            "unit": "%",
            "subtitle": "sobre produtos ativos",
            "icon": "chart-line-up",
            "delta_pct": None,
            "delta_direction": "up" if margem_media > 30 else "down",
            "is_critical": margem_media < 20,
        },
    ]

    return _html(
        "fragments/kpis.html",
        {"request": request, "kpis": kpis},
        trigger={"showToast": {"message": "KPIs atualizados", "type": "success"}},
    )


# ─── Monitor de Margem ────────────────────────────────────────────────────────

@router.get("/margin-table", response_class=HTMLResponse)
def fragment_margin_table(request: Request, db: Session = Depends(get_db)):
    """Tabela de produtos com custo, preço, margem% e status semáforo."""
    from services.margin_monitor import get_all_margins

    result = get_all_margins(db)
    return _html("fragments/margin_table.html", {"request": request, "products": result})


# ─── Alertas Dropdown ─────────────────────────────────────────────────────────

@router.get("/alerts", response_class=HTMLResponse)
def fragment_alerts(request: Request, db: Session = Depends(get_db)):
    """Lista de alertas ativos para o dropdown do topbar (máx 10)."""
    from models import SystemAlert

    alertas = (
        db.query(SystemAlert)
        .filter(SystemAlert.status == "ativo")
        .order_by(SystemAlert.created_at.desc())
        .limit(10)
        .all()
    )
    return _html("fragments/alerts_dropdown.html", {"request": request, "alerts": alertas})

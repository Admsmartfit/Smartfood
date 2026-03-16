"""
FE-01 / FE-02 — Rotas de página completa: Dashboard e Inteligência.

Padrão de renderização:
  - Requests normais (browser): retorna base.html + bloco de conteúdo
  - Requests HTMX (hx-get via sidebar): o cliente usa hx-select="#main-content",
    então o servidor sempre retorna a página completa; HTMX extrai somente #main-content.
"""
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from services.auth_service import AdminOrChef

router = APIRouter(tags=["UI — Dashboard e Inteligência"])
templates = Jinja2Templates(directory="templates")


def _ctx(request: Request, **kwargs) -> dict:
    """Contexto base injetado em todos os templates."""
    return {"request": request, "hoje": date.today().strftime("%d/%m/%Y"), **kwargs}


# ─── Raiz → redireciona para /dashboard ──────────────────────────────────────

@router.get("/", include_in_schema=False)
def root_redirect():
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/dashboard", status_code=302)


# ─── Dashboard ───────────────────────────────────────────────────────────────

@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request, _=AdminOrChef):
    """Página principal do dashboard com KPIs, monitor de margem e alertas."""
    return templates.TemplateResponse(
        "dashboard/index.html",
        _ctx(request),
    )


# ─── Inteligência ─────────────────────────────────────────────────────────────

@router.get("/intelligence/forecast", response_class=HTMLResponse)
def forecast_page(request: Request, _=AdminOrChef):
    """Previsão de Demanda — seletor de produto + gráfico + simulador."""
    return templates.TemplateResponse(
        "intelligence/forecast.html",
        _ctx(request),
    )


@router.get("/intelligence/alerts", response_class=HTMLResponse)
def alerts_page(request: Request, db: Session = Depends(get_db), _=AdminOrChef):
    """Central de Alertas — lista completa com filtros e snooze."""
    from models import SystemAlert
    alertas = (
        db.query(SystemAlert)
        .filter(SystemAlert.status == "ativo")
        .order_by(SystemAlert.created_at.desc())
        .limit(100)
        .all()
    )
    return templates.TemplateResponse(
        "intelligence/alerts.html",
        _ctx(request, alertas=alertas),
    )


@router.get("/intelligence/simulator", response_class=HTMLResponse)
def simulator_page(request: Request, _=AdminOrChef):
    """Simulador 'E se?' — simula produção de qualquer produto/quantidade."""
    return templates.TemplateResponse(
        "intelligence/forecast.html",
        _ctx(request, open_simulator=True),
    )

"""FE-04 / FE-05 / FE-07 — Rotas de páginas comerciais, portal B2B e relatórios."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db

router = APIRouter(tags=["UI — Comercial e Portal"])
templates = Jinja2Templates(directory="templates")

def _ctx(request: Request, **kw): return {"request": request, **kw}

@router.get("/commercial/purchasing", response_class=HTMLResponse)
def purchasing(request: Request):
    return templates.TemplateResponse("commercial/purchasing.html", _ctx(request))

@router.get("/commercial/orders", response_class=HTMLResponse)
def orders(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("commercial/orders.html", _ctx(request))

@router.get("/commercial/b2b-intelligence", response_class=HTMLResponse)
def b2b_intelligence(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("commercial/b2b_intel.html", _ctx(request))

@router.get("/commercial/suppliers", response_class=HTMLResponse)
def suppliers(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("commercial/suppliers.html", _ctx(request))

@router.get("/commercial/dre", response_class=HTMLResponse)
def dre(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("commercial/dre.html", _ctx(request))

@router.get("/portal/catalog", response_class=HTMLResponse)
def portal_catalog(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("portal/catalog.html", _ctx(request))

@router.get("/settings/users", response_class=HTMLResponse)
def settings_users(request: Request):
    return templates.TemplateResponse("settings/users.html", _ctx(request))

@router.get("/settings", response_class=HTMLResponse)
def settings(request: Request):
    import os
    _KEYS = [
        "margem_minima_pct", "alerta_estoque_dias", "mega_api_token", "mega_api_instance",
        "gmail_user", "empresa_nome", "empresa_cnpj", "empresa_endereco",
        "impressora_host", "impressora_porta", "notif_whatsapp", "notif_email", "notif_alertas_criticos",
    ]
    current = {k: os.environ.get(k.upper(), "") for k in _KEYS}
    return templates.TemplateResponse("settings/index.html", _ctx(request, settings=current))

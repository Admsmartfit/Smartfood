"""FE-03 / FE-06 — Rotas de páginas operacionais."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db

router = APIRouter(tags=["UI — Operações"])
templates = Jinja2Templates(directory="templates")

def _ctx(request: Request, **kw): return {"request": request, **kw}

@router.get("/operations/bom", response_class=HTMLResponse)
def bom_list(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("operations/bom_list.html", _ctx(request))

@router.get("/operations/bom/{product_id}", response_class=HTMLResponse)
def bom_detail(product_id: str, request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("operations/bom_detail.html", _ctx(request, product_id=product_id))

@router.get("/operations/inventory", response_class=HTMLResponse)
def inventory(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("operations/inventory.html", _ctx(request))

@router.get("/operations/receiving", response_class=HTMLResponse)
def receiving(request: Request):
    return templates.TemplateResponse("operations/receiving.html", _ctx(request))

@router.get("/operations/production", response_class=HTMLResponse)
def production_list(request: Request, db: Session = Depends(get_db)):
    return templates.TemplateResponse("operations/production_list.html", _ctx(request))

@router.get("/operations/labels", response_class=HTMLResponse)
def labels(request: Request):
    return templates.TemplateResponse("operations/labels.html", _ctx(request))

@router.get("/cadastro", response_class=HTMLResponse)
def cadastro(request: Request):
    return templates.TemplateResponse("cadastro/index.html", _ctx(request))

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
def bom_list(request: Request):
    return templates.TemplateResponse("operations/bom_list.html", _ctx(request))

@router.get("/operations/bom/new", response_class=HTMLResponse)
def bom_new(request: Request, db: Session = Depends(get_db)):
    from models import Ingredient, Supply
    ingredients = db.query(Ingredient).filter(Ingredient.ativo == True).order_by(Ingredient.nome).all()
    supplies = db.query(Supply).filter(Supply.ativo == True).order_by(Supply.nome).all()
    return templates.TemplateResponse(
        "operations/bom_form.html",
        _ctx(request, produto=None, bom_items=[], ingredients=ingredients, supplies=supplies),
    )

@router.get("/operations/bom/{product_id}/edit", response_class=HTMLResponse)
def bom_edit(product_id: str, request: Request, db: Session = Depends(get_db)):
    from models import Product, BOMItem, Ingredient, Supply
    produto = db.query(Product).filter(Product.id == product_id).first()
    if not produto:
        return templates.TemplateResponse("operations/bom_list.html", _ctx(request))
    bom_items = db.query(BOMItem).filter(BOMItem.product_id == product_id).all()
    ingredients = db.query(Ingredient).filter(Ingredient.ativo == True).order_by(Ingredient.nome).all()
    supplies = db.query(Supply).filter(Supply.ativo == True).order_by(Supply.nome).all()
    return templates.TemplateResponse(
        "operations/bom_form.html",
        _ctx(request, produto=produto, bom_items=bom_items, ingredients=ingredients, supplies=supplies),
    )

@router.get("/operations/bom/{product_id}", response_class=HTMLResponse)
def bom_detail(product_id: str, request: Request):
    return templates.TemplateResponse("operations/bom_detail.html", _ctx(request, product_id=product_id))

@router.get("/operations/inventory", response_class=HTMLResponse)
def inventory(request: Request):
    return templates.TemplateResponse("operations/inventory.html", _ctx(request))

@router.get("/operations/receiving", response_class=HTMLResponse)
def receiving(request: Request):
    return templates.TemplateResponse("operations/receiving.html", _ctx(request))

@router.get("/operations/receiving/{nfe_id}/conferencia", response_class=HTMLResponse)
def receiving_conferencia(nfe_id: str, request: Request):
    return templates.TemplateResponse(
        "operations/receiving_conferencia.html",
        _ctx(request, nfe_id=nfe_id, nfe=None),
    )

@router.get("/operations/production", response_class=HTMLResponse)
def production_list(request: Request):
    return templates.TemplateResponse("operations/production_list.html", _ctx(request))

@router.get("/operations/labels", response_class=HTMLResponse)
def labels(request: Request):
    return templates.TemplateResponse("operations/labels.html", _ctx(request))

@router.get("/cadastro", response_class=HTMLResponse)
def cadastro(request: Request):
    return templates.TemplateResponse("cadastro/index.html", _ctx(request))

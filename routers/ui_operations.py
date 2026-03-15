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
    import json
    from models import Ingredient, Supply, Equipment
    ingredients = db.query(Ingredient).filter(Ingredient.ativo == True).order_by(Ingredient.nome).all()
    supplies = db.query(Supply).filter(Supply.ativo == True).order_by(Supply.nome).all()
    equipments = db.query(Equipment).filter(Equipment.ativo == True).order_by(Equipment.nome).all()
    equipments_json = json.dumps([{"id": str(e.id), "nome": e.nome} for e in equipments])
    return templates.TemplateResponse(
        "operations/bom_form.html",
        _ctx(request, produto=None, bom_items=[], ingredients=ingredients, supplies=supplies,
             equipments=equipments, equipments_json=equipments_json, bom_eq_json="[]"),
    )

@router.get("/operations/bom/{product_id}/edit", response_class=HTMLResponse)
def bom_edit(product_id: str, request: Request, db: Session = Depends(get_db)):
    import json
    from models import Product, BOMItem, Ingredient, Supply, Equipment, BOMEquipment, EquipmentParameter
    produto = db.query(Product).filter(Product.id == product_id).first()
    if not produto:
        return templates.TemplateResponse("operations/bom_list.html", _ctx(request))
    bom_items = db.query(BOMItem).filter(BOMItem.product_id == product_id).all()
    ingredients = db.query(Ingredient).filter(Ingredient.ativo == True).order_by(Ingredient.nome).all()
    supplies = db.query(Supply).filter(Supply.ativo == True).order_by(Supply.nome).all()
    equipments = db.query(Equipment).filter(Equipment.ativo == True).order_by(Equipment.nome).all()
    equipments_json = json.dumps([{"id": str(e.id), "nome": e.nome} for e in equipments])

    bom_eqs = db.query(BOMEquipment).filter(BOMEquipment.product_id == product_id).all()
    bom_eq_list = []
    for beq in bom_eqs:
        param_templates = (
            db.query(EquipmentParameter)
            .filter(EquipmentParameter.equipment_id == beq.equipment_id)
            .order_by(EquipmentParameter.nome_parametro)
            .all()
        )
        saved = beq.parametros_json or {}
        params_dict = {}
        # 1. Carrega os do template primeiro
        for p in param_templates:
            nome_display = f"{p.nome_parametro} ({p.unidade_medida})" if p.unidade_medida else p.nome_parametro
            key_saved = p.nome_parametro + (f" ({p.unidade_medida})" if p.unidade_medida else "")
            # O front-end envia como chave o nome + unidade juntos agora (devido à nossa mudança no app.js)
            # Mas vamos procurar pelas chaves possíveis
            valor = saved.get(key_saved, saved.get(p.nome_parametro, p.valor_padrao or ""))
            params_dict[key_saved] = {"nome": key_saved, "valor": valor}
        
        # 2. Adiciona os customizados
        for k, v in saved.items():
            if k not in params_dict:
                params_dict[k] = {"nome": k, "valor": v}
        
        params = list(params_dict.values())
        bom_eq_list.append({
            "equipment_id": str(beq.equipment_id),
            "perda_processo_kg": beq.perda_processo_kg or 0.0,
            "params": params,
        })
    bom_eq_json = json.dumps(bom_eq_list)

    return templates.TemplateResponse(
        "operations/bom_form.html",
        _ctx(request, produto=produto, bom_items=bom_items, ingredients=ingredients, supplies=supplies,
             equipments=equipments, equipments_json=equipments_json, bom_eq_json=bom_eq_json),
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

@router.get("/operations/production/{batch_id}/apontamento", response_class=HTMLResponse)
def production_apontamento(batch_id: str, request: Request):
    return templates.TemplateResponse(
        "operations/production_portioning.html",
        _ctx(request, batch_id=batch_id),
    )

@router.get("/operations/labels", response_class=HTMLResponse)
def labels(request: Request):
    return templates.TemplateResponse("operations/labels.html", _ctx(request))

@router.get("/cadastro", response_class=HTMLResponse)
def cadastro(request: Request):
    return templates.TemplateResponse("cadastro/index.html", _ctx(request))

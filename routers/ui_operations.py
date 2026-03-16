"""FE-03 / FE-06 — Rotas de páginas operacionais."""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import get_db
from services.auth_service import AdminOnly, AdminOrChef

router = APIRouter(tags=["UI — Operações"])
templates = Jinja2Templates(directory="templates")

def _ctx(request: Request, **kw): return {"request": request, **kw}

@router.get("/operations/bom", response_class=HTMLResponse)
def bom_list(request: Request, _=AdminOrChef):
    return templates.TemplateResponse("operations/bom_list.html", _ctx(request))

@router.get("/operations/bom/new", response_class=HTMLResponse)
def bom_new(request: Request, db: Session = Depends(get_db), _=AdminOrChef):
    import json
    from models import Ingredient, Supply, Equipment
    ingredients = db.query(Ingredient).filter(Ingredient.ativo == True).order_by(Ingredient.nome).all()
    supplies = db.query(Supply).filter(Supply.ativo == True).order_by(Supply.nome).all()
    equipments = db.query(Equipment).filter(Equipment.ativo == True).order_by(Equipment.nome).all()
    equipments_json = json.dumps([{"id": str(e.id), "nome": e.nome} for e in equipments])
    ingredients_map_json = json.dumps({str(i.id): i.nome for i in ingredients})
    return templates.TemplateResponse(
        "operations/bom_form.html",
        _ctx(request, produto=None, bom_items=[], ingredients=ingredients, supplies=supplies,
             equipments=equipments, equipments_json=equipments_json, bom_eq_json="[]",
             ingredients_map_json=ingredients_map_json,
             sections_json="[]", bom_items_config_json="[]"),
    )

@router.get("/operations/bom/{product_id}/edit", response_class=HTMLResponse)
def bom_edit(product_id: str, request: Request, db: Session = Depends(get_db), _=AdminOrChef):
    import json
    from models import Product, BOMItem, Ingredient, Supply, Equipment, BOMEquipment, EquipmentParameter, RecipeSection
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
        for p in param_templates:
            key_saved = p.nome_parametro + (f" ({p.unidade_medida})" if p.unidade_medida else "")
            valor = saved.get(key_saved, saved.get(p.nome_parametro, p.valor_padrao or ""))
            params_dict[key_saved] = {"nome": key_saved, "valor": valor}
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
    ingredients_map_json = json.dumps({str(i.id): i.nome for i in ingredients})

    # Seções e mapa de chaves
    sections = db.query(RecipeSection).filter(
        RecipeSection.product_id == product_id
    ).order_by(RecipeSection.ordem).all()
    sec_key_map = {str(s.id): i + 1 for i, s in enumerate(sections)}
    sections_json = json.dumps([
        {"_key": i + 1, "nome": s.nome, "ordem": s.ordem,
         "peso_final_esperado_kg": s.peso_final_esperado_kg}
        for i, s in enumerate(sections)
    ])

    # Items com section_key pré-calculado
    bom_items_config = []
    for idx, item in enumerate(bom_items):
        bom_items_config.append({
            "_key": idx + 1,
            "tipo": "ingrediente" if item.ingredient_id else "embalagem",
            "ingredient_id": str(item.ingredient_id) if item.ingredient_id else "",
            "supply_id": str(item.supply_id) if item.supply_id else "",
            "quantidade": float(item.quantidade),
            "unidade": item.unidade or "kg",
            "perda_esperada_pct": float(item.perda_esperada_pct or 0),
            "peso_bruto_kg": float(item.peso_bruto_kg or 0),
            "peso_limpo_kg": float(item.peso_limpo_kg or 0),
            "peso_final_kg": float(item.peso_final_kg or 0),
            "section_key": sec_key_map.get(str(item.section_id)) if item.section_id else None,
        })
    bom_items_config_json = json.dumps(bom_items_config)

    return templates.TemplateResponse(
        "operations/bom_form.html",
        _ctx(request, produto=produto, bom_items=bom_items, ingredients=ingredients, supplies=supplies,
             equipments=equipments, equipments_json=equipments_json, bom_eq_json=bom_eq_json,
             ingredients_map_json=ingredients_map_json,
             sections_json=sections_json, bom_items_config_json=bom_items_config_json),
    )

@router.get("/operations/bom/{product_id}", response_class=HTMLResponse)
def bom_detail(product_id: str, request: Request, db: Session = Depends(get_db), _=AdminOrChef):
    from models import Product, BOMItem, RecipeSection
    produto = db.query(Product).filter(Product.id == product_id).first()
    sections = db.query(RecipeSection).filter(
        RecipeSection.product_id == product_id
    ).order_by(RecipeSection.ordem).all()
    all_items = db.query(BOMItem).filter(BOMItem.product_id == product_id).all()
    for item in all_items:
        item.ingredient
        item.supply

    seen = set()
    sections_with_items = []
    for sec in sections:
        sec_items = [i for i in all_items if str(i.section_id) == str(sec.id)]
        seen.update(i.id for i in sec_items)
        sections_with_items.append({"section": sec, "items": sec_items})

    sem_secao = [i for i in all_items if i.id not in seen]
    return templates.TemplateResponse(
        "operations/bom_detail.html",
        _ctx(request, product_id=product_id, produto=produto,
             sections_with_items=sections_with_items, sem_secao=sem_secao),
    )

@router.get("/operations/inventory", response_class=HTMLResponse)
def inventory(request: Request, _=AdminOrChef):
    return templates.TemplateResponse("operations/inventory.html", _ctx(request))

@router.get("/operations/receiving", response_class=HTMLResponse)
def receiving(request: Request, _=AdminOrChef):
    return templates.TemplateResponse("operations/receiving.html", _ctx(request))

@router.get("/operations/receiving/{nfe_id}/conferencia", response_class=HTMLResponse)
def receiving_conferencia(nfe_id: str, request: Request, _=AdminOrChef):
    return templates.TemplateResponse(
        "operations/receiving_conferencia.html",
        _ctx(request, nfe_id=nfe_id, nfe=None),
    )

@router.get("/operations/production", response_class=HTMLResponse)
def production_list(request: Request, db: Session = Depends(get_db), _=AdminOrChef):
    from models import Product
    
    # Vamos buscar os produtos ativos para popular o menu suspenso do Modal
    products = db.query(Product).filter(Product.ativo == True).order_by(Product.nome).all()
    
    return templates.TemplateResponse(
        "operations/production_list.html", 
        _ctx(request, products=products)
    )

@router.get("/operations/production/{batch_id}/apontamento", response_class=HTMLResponse)
def production_apontamento(batch_id: str, request: Request, _=AdminOrChef):
    return templates.TemplateResponse(
        "operations/production_portioning.html",
        _ctx(request, batch_id=batch_id),
    )

@router.get("/operations/labels", response_class=HTMLResponse)
def labels_page(request: Request, db: Session = Depends(get_db), _=AdminOrChef):
    """Página de impressão e gestão de Etiquetas"""
    from models import LabelTemplate, Product

    # 1. Busca todos os modelos de etiqueta ativos na base de dados
    templates_list = db.query(LabelTemplate).filter(LabelTemplate.ativo == True).order_by(LabelTemplate.nome).all()
    
    # 2. Busca os produtos para popular os selects e o mapa de nomes
    products = db.query(Product).filter(Product.ativo == True).order_by(Product.nome).all()
    prod_map = {str(p.id): p.nome for p in products}

    # 3. Envia os dados para o HTML, ativando assim a área de impressão!
    return templates.TemplateResponse(
        "operations/labels.html",
        {
            "request": request,
            "templates_list": templates_list,
            "products": products,
            "prod_map": prod_map,
        },
    )

@router.get("/cadastro", response_class=HTMLResponse)
def cadastro(request: Request, _=AdminOnly):
    return templates.TemplateResponse("cadastro/index.html", _ctx(request))

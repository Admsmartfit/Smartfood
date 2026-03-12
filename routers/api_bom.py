"""FE-03 — API BOM: busca live + calculadora de custo."""
import uuid

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/bom", tags=["API — BOM FE-03"])
templates = Jinja2Templates(directory="templates")


@router.get("/search", response_class=HTMLResponse)
def bom_search(
    request: Request,
    q: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Busca live de fichas técnicas (retorna apenas as <tr>)."""
    from models import Product, BOMItem
    from cost_calculator import calculate_product_cost

    query = db.query(Product).filter(Product.ativo == True)
    if q:
        query = query.filter(Product.nome.ilike(f"%{q}%") | Product.sku.ilike(f"%{q}%"))
    produtos = query.order_by(Product.nome).limit(50).all()

    items = []
    for p in produtos:
        bom_items = db.query(BOMItem).filter(BOMItem.product_id == p.id).all()
        for item in bom_items:
            item.ingredient
            item.supply
        cost_data = {}
        try:
            cost_data = calculate_product_cost(p, bom_items)
        except Exception:
            pass
        items.append({
            "id": str(p.id),
            "nome": p.nome,
            "sku": p.sku or "",
            "fc": p.fc,
            "fcoc": p.fcoc,
            "custo_total": cost_data.get("custo_total", 0.0),
            "preco_sugerido": cost_data.get("preco_sugerido", 0.0),
            "margem_pct": cost_data.get("margem_pct", 0.0),
            "num_ingredientes": sum(1 for i in bom_items if i.ingredient_id),
        })

    return templates.TemplateResponse(
        "fragments/bom_rows.html",
        {"request": request, "items": items, "query": q},
    )


@router.post("/{product_id}/calculate", response_class=HTMLResponse)
def bom_calculate(
    product_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """Recalcula custo completo de uma ficha e retorna o fragmento de resultado."""
    from models import Product, BOMItem
    from cost_calculator import calculate_product_cost

    produto = db.query(Product).filter(Product.id == product_id).first()
    if not produto:
        return HTMLResponse("<p class='text-red-500'>Produto não encontrado.</p>")

    bom_items = db.query(BOMItem).filter(BOMItem.product_id == product_id).all()
    for item in bom_items:
        item.ingredient
        item.supply

    try:
        result = calculate_product_cost(produto, bom_items)
    except Exception as e:
        return HTMLResponse(f"<p class='text-red-500'>Erro: {e}</p>")

    import json
    response = templates.TemplateResponse(
        "fragments/cost_result.html",
        {"request": request, "result": result, "produto": produto},
    )
    response.headers["HX-Trigger"] = json.dumps(
        {"showToast": {"message": "Custo recalculado!", "type": "success"}}
    )
    return response

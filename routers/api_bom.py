"""FE-03 — API BOM: busca live + calculadora de custo + save."""
import json
import uuid

from fastapi import APIRouter, Depends, Form, Query, Request
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

    response = templates.TemplateResponse(
        "fragments/cost_result.html",
        {"request": request, "result": result, "produto": produto},
    )
    response.headers["HX-Trigger"] = json.dumps(
        {"showToast": {"message": "Custo recalculado!", "type": "success"}}
    )
    return response


@router.post("/save", response_class=HTMLResponse)
def bom_save(
    _request: Request,
    product_id: str = Form(""),
    nome: str = Form(...),
    sku: str = Form(""),
    categoria: str = Form(""),
    rendimento_por_lote: float = Form(1.0),
    tempo_producao_min: float = Form(30.0),
    markup: float = Form(2.0),
    margem_minima: float = Form(30.0),
    modo_preparo_interno: str = Form(""),
    items_json: str = Form("[]"),
    db: Session = Depends(get_db),
):
    """Cria ou atualiza um Produto e os seus BOMItems."""
    from models import Product, BOMItem

    try:
        items_data = json.loads(items_json)
    except Exception:
        items_data = []

    try:
        # ── Produto ──────────────────────────────────────────────────
        pid = uuid.UUID(product_id) if product_id.strip() else None
        if pid:
            produto = db.query(Product).filter(Product.id == pid).first()
            if not produto:
                r = HTMLResponse('<p class="text-red-600">Produto não encontrado.</p>')
                r.headers["HX-Trigger"] = json.dumps(
                    {"showToast": {"message": "Produto não encontrado.", "type": "error"}}
                )
                return r
        else:
            produto = Product(id=uuid.uuid4())
            db.add(produto)

        produto.nome = nome.strip()
        produto.sku = sku.strip() or None
        produto.categoria = categoria.strip() or None
        produto.rendimento_por_lote = rendimento_por_lote
        produto.tempo_producao_min = tempo_producao_min
        produto.markup = markup
        produto.margem_minima = margem_minima
        produto.modo_preparo_interno = modo_preparo_interno.strip() or None
        produto.ativo = True
        db.flush()

        # ── BOM Items — substitui tudo ────────────────────────────────
        db.query(BOMItem).filter(BOMItem.product_id == produto.id).delete()
        for item in items_data:
            ing_id = item.get("ingredient_id") or None
            sup_id = item.get("supply_id") or None
            qty = float(item.get("quantidade", 0) or 0)
            if not (ing_id or sup_id) or qty <= 0:
                continue
            bom = BOMItem(
                id=uuid.uuid4(),
                product_id=produto.id,
                ingredient_id=uuid.UUID(ing_id) if ing_id else None,
                supply_id=uuid.UUID(sup_id) if sup_id else None,
                quantidade=qty,
                unidade=item.get("unidade", "kg"),
                perda_esperada_pct=float(item.get("perda_esperada_pct", 0) or 0),
            )
            db.add(bom)

        db.commit()
    except Exception as e:
        db.rollback()
        r = HTMLResponse(f'<p class="text-red-600">Erro ao salvar: {e}</p>')
        r.headers["HX-Trigger"] = json.dumps(
            {"showToast": {"message": f"Erro ao salvar: {e}", "type": "error"}}
        )
        return r

    action = "atualizada" if product_id.strip() else "criada"
    r = HTMLResponse(
        f'<div class="text-green-700 font-medium">Ficha técnica de '
        f'<strong>{produto.nome}</strong> {action} com sucesso! '
        f'<a href="/operations/bom" class="underline text-blue-600">Ver lista</a></div>'
    )
    r.headers["HX-Trigger"] = json.dumps(
        {"showToast": {"message": f'Ficha "{produto.nome}" {action}!', "type": "success"}}
    )
    return r

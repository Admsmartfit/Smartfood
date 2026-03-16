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
    from models import Product, BOMItem, BOMEquipment
    from cost_calculator import calculate_product_cost

    produto = db.query(Product).filter(Product.id == product_id).first()
    if not produto:
        return HTMLResponse("<p class='text-red-500'>Produto não encontrado.</p>")

    bom_items = db.query(BOMItem).filter(BOMItem.product_id == product_id).all()
    for item in bom_items:
        item.ingredient
        item.supply

    bom_equipments = db.query(BOMEquipment).filter(BOMEquipment.product_id == product_id).all()

    try:
        result = calculate_product_cost(produto, bom_items, bom_equipments=bom_equipments)
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


@router.post("/calculate-portions")
def calculate_portions(
    rendimento_por_lote: float = Form(1.0),
    peso_porcao_gramas: float = Form(350.0),
    custo_ingredientes: float = Form(0.0),
    custo_embalagens: float = Form(0.0),
    markup: float = Form(2.0),
    peso_bruto_kg: float = Form(0.0),
    peso_limpo_kg: float = Form(0.0),
    peso_final_kg: float = Form(0.0),
):
    """
    Calculadora de porcionamento — chamada via fetch() do Alpine.js.
    Retorna JSON com: num_porcoes, sobra_gramas, custo_por_porcao,
    preco_sugerido_porcao, margem_pct, fc, fcoc, sugestao_lote.
    """
    import math

    porcao_kg = peso_porcao_gramas / 1000.0
    rendimento_g = rendimento_por_lote * 1000.0

    num_porcoes = math.floor(rendimento_g / peso_porcao_gramas) if peso_porcao_gramas > 0 else 0
    sobra_gramas = rendimento_g % peso_porcao_gramas if peso_porcao_gramas > 0 else 0

    # Custo por porção
    custo_total = custo_ingredientes + custo_embalagens
    custo_por_porcao = custo_total / num_porcoes if num_porcoes > 0 else 0.0
    preco_sugerido = custo_por_porcao * markup
    margem_pct = ((preco_sugerido - custo_por_porcao) / preco_sugerido * 100) if preco_sugerido > 0 else 0.0

    # FC / FCoc
    fc = round(peso_bruto_kg / peso_limpo_kg, 4) if peso_limpo_kg > 0 else 0.0
    fcoc = round(peso_limpo_kg / peso_final_kg, 4) if peso_final_kg > 0 else 0.0

    # Sugestão: quantos gramas de ingrediente adicionar para render 1 porção a mais
    sugestao_gramas = round(peso_porcao_gramas - sobra_gramas, 1) if sobra_gramas > 0 else 0.0

    return {
        "num_porcoes": num_porcoes,
        "sobra_gramas": round(sobra_gramas, 1),
        "custo_por_porcao": round(custo_por_porcao, 4),
        "preco_sugerido_porcao": round(preco_sugerido, 2),
        "margem_pct": round(margem_pct, 1),
        "fc": fc,
        "fcoc": fcoc,
        "sugestao_gramas": sugestao_gramas,
        "porcao_kg": porcao_kg,
    }


@router.get("/{product_id}/scale", response_class=HTMLResponse)
def bom_scale(
    product_id: uuid.UUID,
    request: Request,
    porcoes: int = Query(default=1, ge=1),
    db: Session = Depends(get_db),
):
    """Escalonamento de ingredientes para N porções. Retorna fragmento HTML para o Chef."""
    from models import Product, BOMItem, RecipeSection

    produto = db.query(Product).filter(Product.id == product_id).first()
    if not produto:
        return HTMLResponse("<p class='text-red-500'>Produto não encontrado.</p>")

    peso_porcao_kg = (produto.peso_porcao_gramas or 350) / 1000.0
    rendimento_base = produto.rendimento_por_lote or 1.0
    peso_desejado_kg = porcoes * peso_porcao_kg
    fator = peso_desejado_kg / rendimento_base if rendimento_base > 0 else 1.0

    sections = (
        db.query(RecipeSection)
        .filter(RecipeSection.product_id == product_id)
        .order_by(RecipeSection.ordem)
        .all()
    )
    all_items = db.query(BOMItem).filter(BOMItem.product_id == product_id).all()
    for item in all_items:
        item.ingredient
        item.supply

    def _item_dict(i, fator):
        return {
            "nome": i.ingredient.nome if i.ingredient else (i.supply.nome if i.supply else "—"),
            "quantidade_original": i.quantidade,
            "quantidade_escalada": round(i.quantidade * fator, 3),
            "unidade": i.unidade,
            "tipo": "ingrediente" if i.ingredient_id else "embalagem",
        }

    seen_ids = set()
    sections_data = []
    for sec in sections:
        sec_items = [i for i in all_items if str(i.section_id) == str(sec.id)]
        seen_ids.update(i.id for i in sec_items)
        sections_data.append({
            "nome": sec.nome,
            "peso_final_esperado_kg": round(sec.peso_final_esperado_kg * fator, 3) if sec.peso_final_esperado_kg else None,
            "items": [_item_dict(i, fator) for i in sec_items],
        })

    sem_secao = [_item_dict(i, fator) for i in all_items if i.id not in seen_ids]

    return templates.TemplateResponse(
        "fragments/bom_scale_result.html",
        {
            "request": request,
            "produto": produto,
            "porcoes": porcoes,
            "fator": round(fator, 4),
            "peso_desejado_kg": round(peso_desejado_kg, 3),
            "peso_porcao_g": produto.peso_porcao_gramas or 350,
            "lotes_necessarios": round(fator, 2),
            "sections": sections_data,
            "sem_secao": sem_secao,
        },
    )


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
    peso_porcao_gramas: float = Form(0.0),
    unidade_estoque: str = Form("unid"),
    fc: float = Form(1.0),
    fcoc: float = Form(1.0),
    items_json: str = Form("[]"),
    sections_json: str = Form("[]"),
    bom_equipments_json: str = Form("[]"),
    db: Session = Depends(get_db),
):
    """Cria ou atualiza um Produto, suas RecipeSections, BOMItems e BOMEquipments."""
    from models import Product, BOMItem, BOMEquipment, RecipeSection

    try:
        items_data = json.loads(items_json)
    except Exception:
        items_data = []

    try:
        sections_data = json.loads(sections_json)
    except Exception:
        sections_data = []

    try:
        eq_data = json.loads(bom_equipments_json)
    except Exception:
        eq_data = []

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
        produto.fc = fc
        produto.fcoc = fcoc
        produto.peso_porcao_gramas = peso_porcao_gramas if peso_porcao_gramas > 0 else None
        produto.unidade_estoque = unidade_estoque or "unid"
        db.flush()

        # ── Seções — substitui tudo, constrói mapa _key → UUID ───────
        db.query(BOMItem).filter(BOMItem.product_id == produto.id).delete()
        db.query(RecipeSection).filter(RecipeSection.product_id == produto.id).delete()
        db.flush()

        section_key_map: dict = {}  # _key (int|str) → new UUID
        for idx, sec in enumerate(sections_data):
            sec_nome = (sec.get("nome") or "").strip()
            if not sec_nome:
                continue
            new_sec = RecipeSection(
                id=uuid.uuid4(),
                product_id=produto.id,
                nome=sec_nome,
                ordem=int(sec.get("ordem") or idx + 1),
                peso_final_esperado_kg=sec.get("peso_final_esperado_kg") or None,
            )
            db.add(new_sec)
            db.flush()
            section_key_map[sec.get("_key")] = new_sec.id

        # ── BOM Items — substitui tudo ────────────────────────────────
        for item in items_data:
            ing_id = item.get("ingredient_id") or None
            sup_id = item.get("supply_id") or None
            qty = float(item.get("quantidade", 0) or 0)
            if not (ing_id or sup_id) or qty <= 0:
                continue
            sec_key = item.get("section_key")
            sec_id = section_key_map.get(sec_key) if sec_key is not None else None
            bom = BOMItem(
                id=uuid.uuid4(),
                product_id=produto.id,
                ingredient_id=uuid.UUID(ing_id) if ing_id else None,
                supply_id=uuid.UUID(sup_id) if sup_id else None,
                section_id=sec_id,
                quantidade=qty,
                unidade=item.get("unidade", "kg"),
                perda_esperada_pct=float(item.get("perda_esperada_pct", 0) or 0),
                peso_bruto_kg=float(item.get("peso_bruto_kg", 0) or 0),
                peso_limpo_kg=float(item.get("peso_limpo_kg", 0) or 0),
                peso_final_kg=float(item.get("peso_final_kg", 0) or 0),
            )
            db.add(bom)

        # ── BOM Equipments — substitui tudo ──────────────────────────
        db.query(BOMEquipment).filter(BOMEquipment.product_id == produto.id).delete()
        for eq in eq_data:
            eq_id = eq.get("equipment_id") or None
            if not eq_id:
                continue
            bom_eq = BOMEquipment(
                id=uuid.uuid4(),
                product_id=produto.id,
                equipment_id=uuid.UUID(eq_id),
                perda_processo_kg=float(eq.get("perda_processo_kg", 0) or 0),
                parametros_json=eq.get("parametros_json") or {},
            )
            db.add(bom_eq)

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


@router.delete("/{product_id}", response_class=HTMLResponse)
def bom_delete(product_id: uuid.UUID, db: Session = Depends(get_db)):
    """Inativa uma ficha técnica (soft-delete)."""
    from models import Product
    produto = db.query(Product).filter(Product.id == product_id).first()
    if not produto:
        return HTMLResponse("", status_code=404)

    nome = produto.nome
    produto.ativo = False
    db.commit()

    response = HTMLResponse("")  # Remove a linha da tabela
    response.headers["HX-Trigger"] = json.dumps(
        {"showToast": {"message": f'Ficha "{nome}" excluída.', "type": "warning"}}
    )
    return response

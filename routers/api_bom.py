"""FE-03 — API BOM: busca live + calculadora de custo + save."""
import json
import uuid
import logging

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from services.auth_service import AdminOrChef

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/bom", tags=["API — BOM FE-03"])
templates = Jinja2Templates(directory="templates")

# =====================================================================
# FUNÇÕES UTILITÁRIAS
# =====================================================================
def _to_float(value: str, default: float = 0.0) -> float:
    """Converte strings com vírgula ou ponto para float, evitando Erro 422."""
    if not value:
        return default
    try:
        return float(str(value).replace(',', '.'))
    except ValueError:
        return default

# =====================================================================
# ROTAS DE CONSULTA E CÁLCULO (MANTIDAS INTACTAS)
# =====================================================================

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

    # Sugestão
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

# =====================================================================
# ROTA DE GRAVAÇÃO CORRIGIDA (SUPER TOLERANTE - ANTI ERRO 422)
# =====================================================================

@router.post("/save", response_class=HTMLResponse)
def bom_save(
    request: Request,
    product_id: str = Form(""),
    nome: str = Form(""),
    sku: str = Form(""),
    categoria: str = Form(""),
    markup: str = Form("2.0"),
    tempo_producao_min: str = Form("30"),
    margem_minima: str = Form("30.0"),
    modo_preparo_interno: str = Form(""),
    fc: str = Form("1.0"),
    fcoc: str = Form("1.0"),
    peso_porcao_gramas: str = Form("0"),
    unidade_estoque: str = Form("unid"),
    rendimento_por_lote: str = Form("0"),
    sections_json: str = Form("[]"),
    embalagens_json: str = Form("[]"),
    bom_equipments_json: str = Form("[]"),
    db: Session = Depends(get_db),
    _=AdminOrChef,
):
    from models import Product, BOMItem, BOMEquipment, RecipeSection

    if not nome.strip():
        return HTMLResponse(
            '<div class="p-3 bg-red-50 text-red-800 rounded-lg border border-red-200">'
            '<i class="ph-fill ph-x-circle"></i> O Nome do Produto é obrigatório.</div>'
        )

    try:
        _markup      = _to_float(markup, 2.0)
        _tempo       = _to_float(tempo_producao_min, 30.0)
        _margem      = _to_float(margem_minima, 30.0)
        _fc          = _to_float(fc, 1.0)
        _fcoc        = _to_float(fcoc, 1.0)
        _peso_porcao = _to_float(peso_porcao_gramas, 0.0)
        _rendimento  = _to_float(rendimento_por_lote, 0.0)

        sections   = json.loads(sections_json)
        embalagens = json.loads(embalagens_json)
        equipments = json.loads(bom_equipments_json)

        # Identificar ou criar produto
        pid = uuid.UUID(product_id) if product_id.strip() else None
        if pid:
            produto = db.query(Product).filter(Product.id == pid).first()
            if not produto:
                return HTMLResponse('<div class="text-red-600">Produto não encontrado.</div>')
        else:
            produto = Product(id=uuid.uuid4(), ativo=True)
            db.add(produto)

        produto.nome                 = nome.strip()
        produto.sku                  = sku.strip() or None
        produto.categoria            = categoria.strip() or None
        produto.markup               = _markup
        produto.tempo_producao_min   = int(_tempo)
        produto.margem_minima        = _margem
        produto.modo_preparo_interno = modo_preparo_interno.strip()
        produto.fc                   = _fc
        produto.fcoc                 = _fcoc
        produto.peso_porcao_gramas   = _peso_porcao if _peso_porcao > 0 else None
        produto.unidade_estoque      = unidade_estoque
        produto.rendimento_por_lote  = _rendimento
        db.flush()

        # Limpar ficha antiga (BOMItem antes de RecipeSection por FK)
        db.query(BOMItem).filter(BOMItem.product_id == produto.id).delete()
        db.query(BOMEquipment).filter(BOMEquipment.product_id == produto.id).delete()
        db.query(RecipeSection).filter(RecipeSection.product_id == produto.id).delete()
        db.flush()

        # Salvar seções e insumos
        for s_idx, sec_data in enumerate(sections):
            peso_sec = _to_float(sec_data.get("peso_final_esperado_kg"), 0.0)
            section = RecipeSection(
                id=uuid.uuid4(),
                product_id=produto.id,
                nome=sec_data.get("nome", f"Seção {s_idx + 1}"),
                ordem=s_idx + 1,
                peso_final_esperado_kg=peso_sec if peso_sec > 0 else None,
            )
            db.add(section)
            db.flush()
            for item in sec_data.get("items", []):
                if item.get("ingredient_id"):
                    qty = _to_float(item.get("quantidade"), 0.0)
                    if qty > 0:
                        db.add(BOMItem(
                            id=uuid.uuid4(),
                            product_id=produto.id,
                            section_id=section.id,
                            ingredient_id=item["ingredient_id"],
                            quantidade=qty,
                            unidade=item.get("unidade", "kg"),
                        ))

        # Salvar embalagens
        for emb in embalagens:
            if emb.get("supply_id"):
                qty = _to_float(emb.get("quantidade"), 1.0)
                if qty > 0:
                    db.add(BOMItem(
                        id=uuid.uuid4(),
                        product_id=produto.id,
                        section_id=None,
                        supply_id=emb["supply_id"],
                        quantidade=qty,
                        unidade=emb.get("unidade", "un"),
                    ))

        # Salvar equipamentos
        for eq in equipments:
            if eq.get("equipment_id"):
                params_dict = {p["nome"]: p["valor"] for p in eq.get("params", [])}
                db.add(BOMEquipment(
                    id=uuid.uuid4(),
                    product_id=produto.id,
                    equipment_id=eq["equipment_id"],
                    perda_processo_kg=_to_float(eq.get("perda_processo_kg"), 0.0),
                    parametros_json=params_dict,
                ))

        db.commit()

        acao = "atualizada" if pid else "criada"
        html = f"""
        <div class="p-3 bg-green-50 text-green-800 rounded-lg border border-green-200 flex items-center gap-2 font-medium">
            <i class="ph-fill ph-check-circle text-xl"></i> Ficha Técnica {acao} com sucesso! Redirecionando...
        </div>
        <script>setTimeout(() => window.location.href = '/operations/bom', 1500);</script>
        """
        r = HTMLResponse(content=html)
        r.headers["HX-Trigger"] = json.dumps({"showToast": {"message": "Receita salva!", "type": "success"}})
        return r

    except Exception as e:
        db.rollback()
        logger.error(f"Erro ao salvar Ficha Técnica: {e}", exc_info=True)
        return HTMLResponse(f"""
        <div class="p-3 bg-red-50 text-red-800 rounded-lg border border-red-200 flex items-center gap-2">
            <i class="ph-fill ph-warning-circle text-xl"></i> Erro interno ao salvar: {str(e)}
        </div>
        """)

@router.delete("/{product_id}", response_class=HTMLResponse)
def bom_delete(product_id: uuid.UUID, db: Session = Depends(get_db), _=AdminOrChef):
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
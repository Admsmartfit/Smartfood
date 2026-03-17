"""FE-09 — Cadastros via UI (Ingredientes, Produtos, Fornecedores, Clientes, Categorias, Equipamentos)."""
import json
import uuid as _uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/cadastro", tags=["API — Cadastros UI"])
templates = Jinja2Templates(directory="templates")


def _toast(msg: str, tipo: str = "success") -> str:
    return json.dumps({"showToast": {"message": msg, "type": tipo}})


def _ok(html: str, msg: str, tipo: str = "success") -> HTMLResponse:
    r = HTMLResponse(content=html)
    r.headers["HX-Trigger"] = _toast(msg, tipo)
    return r


def _err(msg: str) -> HTMLResponse:
    html = (
        f'<div class="flex items-center gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-800">'
        f'<i class="ph-fill ph-x-circle text-lg"></i><span>{msg}</span></div>'
    )
    r = HTMLResponse(content=html)
    r.headers["HX-Trigger"] = _toast(msg, "error")
    return r


# ─── Ingredientes ──────────────────────────────────────────────────────────────

def _ing_view_row(ing) -> str:
    low = (ing.estoque_atual or 0) <= (ing.estoque_minimo or 0)
    stk_cls = "text-red-600 font-semibold" if low else "text-gray-700"
    return (
        f'<tr id="ing-{ing.id}" class="odd:bg-white even:bg-slate-50 text-sm hover:bg-blue-50 cursor-pointer">'
        f'<td class="px-4 py-2 font-medium text-gray-900">{ing.nome}</td>'
        f'<td class="px-4 py-2 text-gray-500">{ing.unidade}</td>'
        f'<td class="px-4 py-2 text-right text-gray-700">R$ {ing.custo_atual:.2f}</td>'
        f'<td class="px-4 py-2 text-right {stk_cls}">{ing.estoque_atual:.1f}</td>'
        f'<td class="px-4 py-2 text-right text-gray-500">{ing.estoque_minimo:.1f}</td>'
        f'<td class="px-4 py-2 text-center text-gray-500">{ing.lead_time_dias}d</td>'
        f'<td class="px-4 py-2 text-center">'
        f'<button hx-get="/api/cadastro/ingredient/{ing.id}/edit-row" '
        f'hx-target="#ing-{ing.id}" hx-swap="outerHTML" '
        f'class="text-blue-500 hover:text-blue-700 p-1" title="Editar">'
        f'<i class="ph ph-pencil-simple"></i></button>'
        f'</td>'
        f'</tr>'
    )


@router.get("/ingredients", response_class=HTMLResponse)
def list_ingredients(request: Request, db: Session = Depends(get_db)):
    from models import Ingredient
    items = db.query(Ingredient).order_by(Ingredient.nome).all()
    return templates.TemplateResponse(
        "cadastro/fragments/ingredients_rows.html",
        {"request": request, "items": items},
    )


@router.get("/ingredient-options", response_class=HTMLResponse)
def ingredient_options(db: Session = Depends(get_db)):
    from models import Ingredient
    items = db.query(Ingredient).filter(Ingredient.ativo == True).order_by(Ingredient.nome).all()
    html = "".join(f'<option value="{i.id}">{i.nome}</option>' for i in items)
    return HTMLResponse(html or "")


@router.get("/ingredient/{ing_id}/view-row", response_class=HTMLResponse)
def ingredient_view_row(ing_id: str, db: Session = Depends(get_db)):
    from models import Ingredient
    ing = db.query(Ingredient).filter(Ingredient.id == ing_id).first()
    if not ing:
        return _err("Ingrediente não encontrado.")
    return HTMLResponse(_ing_view_row(ing))


@router.get("/ingredient/{ing_id}/edit-row", response_class=HTMLResponse)
def ingredient_edit_row(ing_id: str, db: Session = Depends(get_db)):
    from models import Ingredient
    ing = db.query(Ingredient).filter(Ingredient.id == ing_id).first()
    if not ing:
        return _err("Ingrediente não encontrado.")
    un_opts = ""
    for u in ["kg", "g", "L", "mL", "un", "cx"]:
        sel = " selected" if ing.unidade == u else ""
        un_opts += f'<option value="{u}"{sel}>{u}</option>'
    bruto_val = f"{ing.peso_bruto_padrao:.3f}" if ing.peso_bruto_padrao else ""
    limpo_val = f"{ing.peso_limpo_padrao:.3f}" if ing.peso_limpo_padrao else ""
    html = (
        f'<tr id="ing-{ing.id}" class="bg-blue-50 border-y-2 border-blue-300">'
        f'<td colspan="7" class="px-4 py-3">'
        f'<form hx-post="/api/cadastro/ingredient/{ing.id}/update" '
        f'hx-target="#ing-{ing.id}" hx-swap="outerHTML" '
        f'class="flex flex-wrap items-end gap-2">'
        f'<div class="flex-1 min-w-[140px]"><label class="text-xs text-gray-500">Nome</label>'
        f'<input name="nome" value="{ing.nome}" required '
        f'class="w-full px-2 py-1.5 border border-slate-300 rounded text-sm"></div>'
        f'<div class="w-20"><label class="text-xs text-gray-500">Unidade</label>'
        f'<select name="unidade" class="w-full px-2 py-1.5 border border-slate-300 rounded text-sm">{un_opts}</select></div>'
        f'<div class="w-28"><label class="text-xs text-gray-500">Peso Bruto (kg)</label>'
        f'<input name="peso_bruto_padrao" type="number" step="0.001" min="0" value="{bruto_val}" placeholder="0.000" '
        f'class="w-full px-2 py-1.5 border border-slate-300 rounded text-sm"></div>'
        f'<div class="w-28"><label class="text-xs text-gray-500">Peso Limpo (kg)</label>'
        f'<input name="peso_limpo_padrao" type="number" step="0.001" min="0" value="{limpo_val}" placeholder="0.000" '
        f'class="w-full px-2 py-1.5 border border-slate-300 rounded text-sm"></div>'
        f'<div class="w-28"><label class="text-xs text-gray-500">Custo R$/un</label>'
        f'<input name="custo_atual" type="number" step="0.01" min="0" value="{ing.custo_atual:.2f}" '
        f'class="w-full px-2 py-1.5 border border-slate-300 rounded text-sm"></div>'
        f'<div class="w-24"><label class="text-xs text-gray-500">Estoque</label>'
        f'<input name="estoque_atual" type="number" step="0.1" min="0" value="{ing.estoque_atual:.1f}" '
        f'class="w-full px-2 py-1.5 border border-slate-300 rounded text-sm"></div>'
        f'<div class="w-24"><label class="text-xs text-gray-500">Mínimo</label>'
        f'<input name="estoque_minimo" type="number" step="0.1" min="0" value="{ing.estoque_minimo:.1f}" '
        f'class="w-full px-2 py-1.5 border border-slate-300 rounded text-sm"></div>'
        f'<div class="w-20"><label class="text-xs text-gray-500">Lead (dias)</label>'
        f'<input name="lead_time_dias" type="number" step="1" min="1" value="{ing.lead_time_dias}" '
        f'class="w-full px-2 py-1.5 border border-slate-300 rounded text-sm"></div>'
        f'<div class="flex gap-2 items-end">'
        f'<button type="submit" class="px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold rounded transition-colors">'
        f'<i class="ph ph-check"></i> Salvar</button>'
        f'<button type="button" hx-get="/api/cadastro/ingredient/{ing.id}/view-row" '
        f'hx-target="#ing-{ing.id}" hx-swap="outerHTML" '
        f'class="px-3 py-1.5 bg-slate-200 hover:bg-slate-300 text-gray-700 text-xs font-semibold rounded transition-colors">'
        f'Cancelar</button></div>'
        f'</form></td></tr>'
    )
    return HTMLResponse(html)


@router.post("/ingredient/{ing_id}/update", response_class=HTMLResponse)
def update_ingredient(
    ing_id: str,
    nome: str = Form(...),
    unidade: str = Form("kg"),
    peso_bruto_padrao: float = Form(0.0),
    peso_limpo_padrao: float = Form(0.0),
    custo_atual: float = Form(0.0),
    estoque_atual: float = Form(0.0),
    estoque_minimo: float = Form(0.0),
    lead_time_dias: int = Form(3),
    db: Session = Depends(get_db),
):
    from models import Ingredient
    ing = db.query(Ingredient).filter(Ingredient.id == ing_id).first()
    if not ing:
        return _err("Ingrediente não encontrado.")
    bruto = peso_bruto_padrao if peso_bruto_padrao > 0 else None
    limpo = peso_limpo_padrao if peso_limpo_padrao > 0 else None
    try:
        ing.nome = nome.strip()
        ing.unidade = unidade.strip()
        ing.peso_bruto_padrao = bruto
        ing.peso_limpo_padrao = limpo
        ing.fc_medio = round(bruto / limpo, 4) if bruto and limpo else ing.fc_medio
        ing.custo_atual = custo_atual
        ing.estoque_atual = estoque_atual
        ing.estoque_minimo = estoque_minimo
        ing.lead_time_dias = lead_time_dias
        db.commit()
        db.refresh(ing)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao atualizar: {e}")
    r = HTMLResponse(_ing_view_row(ing))
    r.headers["HX-Trigger"] = _toast(f'Ingrediente "{ing.nome}" atualizado!', "success")
    return r


@router.post("/ingredient", response_class=HTMLResponse)
def create_ingredient(
    request: Request,
    nome: str = Form(...),
    unidade: str = Form("kg"),
    peso_bruto_padrao: float = Form(0.0),
    peso_limpo_padrao: float = Form(0.0),
    custo_atual: float = Form(0.0),
    estoque_atual: float = Form(0.0),
    estoque_minimo: float = Form(0.0),
    lead_time_dias: int = Form(3),
    db: Session = Depends(get_db),
):
    from models import Ingredient
    bruto = peso_bruto_padrao if peso_bruto_padrao > 0 else None
    limpo = peso_limpo_padrao if peso_limpo_padrao > 0 else None
    fc_calc = round(bruto / limpo, 4) if bruto and limpo else 1.0
    try:
        ing = Ingredient(
            id=_uuid.uuid4(),
            nome=nome.strip(),
            unidade=unidade.strip(),
            peso_bruto_padrao=bruto,
            peso_limpo_padrao=limpo,
            fc_medio=fc_calc,
            custo_atual=custo_atual,
            estoque_atual=estoque_atual,
            estoque_minimo=estoque_minimo,
            lead_time_dias=lead_time_dias,
            ativo=True,
        )
        db.add(ing)
        db.commit()
        db.refresh(ing)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao cadastrar: {e}")

    # Also refresh ingredient-options select via OOB
    return _ok(_ing_view_row(ing), f'Ingrediente "{ing.nome}" cadastrado!')


# ─── Produtos ──────────────────────────────────────────────────────────────────

@router.get("/products", response_class=HTMLResponse)
def list_products(request: Request, db: Session = Depends(get_db)):
    from models import Product
    items = db.query(Product).order_by(Product.nome).all()
    return templates.TemplateResponse(
        "cadastro/fragments/products_rows.html",
        {"request": request, "items": items},
    )


@router.post("/product", response_class=HTMLResponse)
def create_product(
    request: Request,
    nome: str = Form(...),
    sku: str = Form(""),
    categoria: str = Form(""),
    markup: float = Form(2.0),
    margem_minima: float = Form(30.0),
    tempo_producao_min: float = Form(30.0),
    db: Session = Depends(get_db),
):
    from models import Product
    try:
        p = Product(
            id=_uuid.uuid4(),
            nome=nome.strip(),
            sku=sku.strip() or None,
            categoria=categoria.strip() or None,
            markup=markup,
            margem_minima=margem_minima,
            tempo_producao_min=tempo_producao_min,
            ativo=True,
        )
        db.add(p)
        db.commit()
        db.refresh(p)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao cadastrar: {e}")

    row = (
        f'<tr id="prd-{p.id}" class="odd:bg-white even:bg-slate-50 text-sm">'
        f'<td class="px-4 py-2 font-medium text-gray-900">{p.nome}</td>'
        f'<td class="px-4 py-2 text-gray-500">{p.sku or "—"}</td>'
        f'<td class="px-4 py-2 text-gray-500">{p.categoria or "—"}</td>'
        f'<td class="px-4 py-2 text-right text-gray-700">{p.markup:.1f}×</td>'
        f'<td class="px-4 py-2 text-right text-gray-700">{p.margem_minima:.0f}%</td>'
        f'</tr>'
    )
    return _ok(row, f'Produto "{p.nome}" cadastrado!')


# ─── Fornecedores ──────────────────────────────────────────────────────────────

@router.get("/suppliers", response_class=HTMLResponse)
def list_suppliers(request: Request, db: Session = Depends(get_db)):
    from models import Supplier
    items = db.query(Supplier).order_by(Supplier.nome).all()
    return templates.TemplateResponse(
        "cadastro/fragments/suppliers_rows.html",
        {"request": request, "items": items},
    )


@router.post("/supplier", response_class=HTMLResponse)
def create_supplier(
    request: Request,
    nome: str = Form(...),
    tipo: str = Form("ingrediente"),
    whatsapp: str = Form(""),
    email: str = Form(""),
    cnpj: str = Form(""),
    razao_social: str = Form(""),
    nome_representante: str = Form(""),
    telefone_representante: str = Form(""),
    telefone_vendedor: str = Form(""),
    endereco_completo: str = Form(""),
    db: Session = Depends(get_db),
):
    from models import Supplier
    try:
        s = Supplier(
            id=_uuid.uuid4(),
            nome=nome.strip(),
            tipo=tipo.strip(),
            whatsapp=whatsapp.strip() or None,
            email=email.strip() or None,
            cnpj=cnpj.strip() or None,
            razao_social=razao_social.strip() or None,
            nome_representante=nome_representante.strip() or None,
            telefone_representante=telefone_representante.strip() or None,
            telefone_vendedor=telefone_vendedor.strip() or None,
            endereco_completo=endereco_completo.strip() or None,
        )
        db.add(s)
        db.commit()
        db.refresh(s)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao cadastrar: {e}")

    row = (
        f'<tr id="sup-{s.id}" class="odd:bg-white even:bg-slate-50 text-sm">'
        f'<td class="px-4 py-2 font-medium text-gray-900">{s.nome}</td>'
        f'<td class="px-4 py-2 text-gray-500">{s.tipo}</td>'
        f'<td class="px-4 py-2 text-gray-500">{s.whatsapp or "—"}</td>'
        f'<td class="px-4 py-2 text-gray-500">{s.email or "—"}</td>'
        f'<td class="px-4 py-2 text-gray-500">{s.cnpj or "—"}</td>'
        f'</tr>'
    )
    return _ok(row, f'Fornecedor "{s.nome}" cadastrado!')


# ─── Clientes ──────────────────────────────────────────────────────────────────

@router.get("/customers", response_class=HTMLResponse)
def list_customers(request: Request, db: Session = Depends(get_db)):
    from models import Customer
    items = db.query(Customer).order_by(Customer.nome).all()
    return templates.TemplateResponse(
        "cadastro/fragments/customers_rows.html",
        {"request": request, "items": items},
    )


@router.post("/customer", response_class=HTMLResponse)
def create_customer(
    request: Request,
    nome: str = Form(...),
    whatsapp: str = Form(""),
    email: str = Form(""),
    cnpj: str = Form(""),
    razao_social: str = Form(""),
    nome_representante: str = Form(""),
    telefone_representante: str = Form(""),
    telefone_vendedor: str = Form(""),
    endereco_completo: str = Form(""),
    db: Session = Depends(get_db),
):
    from models import Customer
    try:
        c = Customer(
            id=_uuid.uuid4(),
            nome=nome.strip(),
            whatsapp=whatsapp.strip() or None,
            email=email.strip() or None,
            cnpj=cnpj.strip() or None,
            razao_social=razao_social.strip() or None,
            nome_representante=nome_representante.strip() or None,
            telefone_representante=telefone_representante.strip() or None,
            telefone_vendedor=telefone_vendedor.strip() or None,
            endereco_completo=endereco_completo.strip() or None,
        )
        db.add(c)
        db.commit()
        db.refresh(c)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao cadastrar: {e}")

    row = (
        f'<tr id="cus-{c.id}" class="odd:bg-white even:bg-slate-50 text-sm">'
        f'<td class="px-4 py-2 font-medium text-gray-900">{c.nome}</td>'
        f'<td class="px-4 py-2 text-gray-500">{c.whatsapp or "—"}</td>'
        f'<td class="px-4 py-2 text-gray-500">{c.email or "—"}</td>'
        f'<td class="px-4 py-2 text-gray-500">{c.cnpj or "—"}</td>'
        f'</tr>'
    )
    return _ok(row, f'Cliente "{c.nome}" cadastrado!')


# ─── Categorias ────────────────────────────────────────────────────────────────

@router.get("/category-options", response_class=HTMLResponse)
def category_options(db: Session = Depends(get_db)):
    from models import Category
    items = db.query(Category).order_by(Category.nome).all()
    html = "".join(f'<option value="{c.nome}">{c.nome} ({c.tipo})</option>' for c in items)
    return HTMLResponse(html or "")


@router.get("/categories", response_class=HTMLResponse)
def list_categories(request: Request, db: Session = Depends(get_db)):
    from models import Category
    items = db.query(Category).order_by(Category.nome).all()
    rows = "".join(
        f'<tr id="cat-{c.id}" class="odd:bg-white even:bg-slate-50 text-sm">'
        f'<td class="px-4 py-2 font-medium text-gray-900">{c.nome}</td>'
        f'<td class="px-4 py-2 text-gray-500">{c.tipo}</td>'
        f'<td class="px-4 py-2 text-center">'
        f'<button hx-delete="/api/cadastro/category/{c.id}" hx-target="#cat-{c.id}" hx-swap="outerHTML swap:300ms" '
        f'hx-confirm="Excluir categoria {c.nome}?" '
        f'class="text-red-500 hover:text-red-700 p-1"><i class="ph ph-trash"></i></button>'
        f'</td></tr>'
        for c in items
    )
    return HTMLResponse(rows or '<tr><td colspan="3" class="px-4 py-6 text-center text-gray-400 text-sm">Nenhuma categoria.</td></tr>')


@router.post("/category", response_class=HTMLResponse)
def create_category(
    request: Request,
    nome: str = Form(...),
    tipo: str = Form("Insumo"),
    db: Session = Depends(get_db),
):
    from models import Category
    try:
        cat = Category(id=_uuid.uuid4(), nome=nome.strip(), tipo=tipo.strip())
        db.add(cat)
        db.commit()
        db.refresh(cat)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao cadastrar: {e}")

    row = (
        f'<tr id="cat-{cat.id}" class="odd:bg-white even:bg-slate-50 text-sm">'
        f'<td class="px-4 py-2 font-medium text-gray-900">{cat.nome}</td>'
        f'<td class="px-4 py-2 text-gray-500">{cat.tipo}</td>'
        f'<td class="px-4 py-2 text-center">'
        f'<button hx-delete="/api/cadastro/category/{cat.id}" hx-target="#cat-{cat.id}" hx-swap="outerHTML swap:300ms" '
        f'hx-confirm="Excluir categoria {cat.nome}?" '
        f'class="text-red-500 hover:text-red-700 p-1"><i class="ph ph-trash"></i></button>'
        f'</td></tr>'
    )
    return _ok(row, f'Categoria "{cat.nome}" cadastrada!')


@router.delete("/category/{cat_id}", response_class=HTMLResponse)
def delete_category(cat_id: str, db: Session = Depends(get_db)):
    from models import Category
    cat = db.query(Category).filter(Category.id == cat_id).first()
    if not cat:
        return _err("Categoria não encontrada.")
    try:
        db.delete(cat)
        db.commit()
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao excluir: {e}")
    r = HTMLResponse("")
    r.headers["HX-Trigger"] = _toast(f'Categoria excluída.', "success")
    return r


# ─── Fabricantes de Ingredientes ───────────────────────────────────────────────

@router.get("/ingredient/{ing_id}/manufacturers", response_class=HTMLResponse)
def list_manufacturers(request: Request, ing_id: str, db: Session = Depends(get_db)):
    from models import IngredientManufacturer
    items = db.query(IngredientManufacturer).filter(
        IngredientManufacturer.ingredient_id == ing_id
    ).order_by(IngredientManufacturer.nome_fabricante).all()

    stars = lambda n: "".join(
        f'<i class="ph-fill ph-star text-amber-400"></i>' if i < n else
        f'<i class="ph ph-star text-gray-300"></i>'
        for i in range(5)
    )
    rows = "".join(
        f'<tr id="mfr-{m.id}" class="hover:bg-amber-50 transition-colors">'
        f'<td class="px-4 py-3 font-medium text-gray-900">{m.nome_fabricante}</td>'
        f'<td class="px-4 py-3 font-mono font-bold text-blue-700 bg-blue-50">FC {m.percentual_rendimento:.2f}</td>'
        f'<td class="px-4 py-3 text-center">{stars(m.pontuacao_qualidade)}</td>'
        f'<td class="px-4 py-3 text-right">'
        f'<button hx-delete="/api/cadastro/manufacturer/{m.id}" hx-target="#mfr-{m.id}" hx-swap="outerHTML swap:300ms" '
        f'hx-confirm="Excluir marca e o seu FC?" '
        f'class="text-red-500 hover:text-red-700 p-1 bg-red-50 hover:bg-red-100 rounded"><i class="ph ph-trash"></i></button>'
        f'</td></tr>'
        for m in items
    )
    return HTMLResponse(rows or '<tr><td colspan="4" class="px-4 py-4 text-center text-gray-400 text-sm">Nenhuma marca vinculada. Adicione acima.</td></tr>')


@router.post("/ingredient/{ing_id}/manufacturer", response_class=HTMLResponse)
def create_manufacturer(
    ing_id: str,
    nome_fabricante: str = Form(...),
    fc_fabricante: float = Form(1.0),
    pontuacao_qualidade: int = Form(3),
    db: Session = Depends(get_db),
):
    from models import IngredientManufacturer
    try:
        m = IngredientManufacturer(
            id=_uuid.uuid4(),
            ingredient_id=ing_id,
            nome_fabricante=nome_fabricante.strip(),
            percentual_rendimento=fc_fabricante,
            pontuacao_qualidade=max(1, min(5, pontuacao_qualidade)),
        )
        db.add(m)
        db.commit()
        db.refresh(m)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao cadastrar marca: {e}")

    stars = "".join(
        f'<i class="ph-fill ph-star text-amber-400"></i>' if i < m.pontuacao_qualidade else
        f'<i class="ph ph-star text-gray-300"></i>'
        for i in range(5)
    )
    row = (
        f'<tr id="mfr-{m.id}" class="hover:bg-amber-50 transition-colors">'
        f'<td class="px-4 py-3 font-medium text-gray-900">{m.nome_fabricante}</td>'
        f'<td class="px-4 py-3 font-mono font-bold text-blue-700 bg-blue-50">FC {m.percentual_rendimento:.2f}</td>'
        f'<td class="px-4 py-3 text-center">{stars}</td>'
        f'<td class="px-4 py-3 text-right">'
        f'<button hx-delete="/api/cadastro/manufacturer/{m.id}" hx-target="#mfr-{m.id}" hx-swap="outerHTML swap:300ms" '
        f'hx-confirm="Excluir marca e o seu FC?" '
        f'class="text-red-500 hover:text-red-700 p-1 bg-red-50 hover:bg-red-100 rounded"><i class="ph ph-trash"></i></button>'
        f'</td></tr>'
    )
    return _ok(row, f'Marca "{m.nome_fabricante}" guardada com FC {fc_fabricante:.2f}!')


@router.delete("/manufacturer/{man_id}", response_class=HTMLResponse)
def delete_manufacturer(man_id: str, db: Session = Depends(get_db)):
    from models import IngredientManufacturer
    m = db.query(IngredientManufacturer).filter(IngredientManufacturer.id == man_id).first()
    if not m:
        return _err("Fabricante não encontrado.")
    try:
        db.delete(m)
        db.commit()
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao excluir: {e}")
    r = HTMLResponse("")
    r.headers["HX-Trigger"] = _toast("Fabricante excluído.", "success")
    return r


# ─── Catálogo do Fornecedor ────────────────────────────────────────────────────

@router.get("/supplier/{sup_id}/catalog", response_class=HTMLResponse)
def get_supplier_catalog(request: Request, sup_id: str, db: Session = Depends(get_db)):
    from models import SupplierIngredient
    items = db.query(SupplierIngredient).filter(
        SupplierIngredient.supplier_id == sup_id
    ).all()

    rows = "".join(
        f'<tr id="si-{si.id}" class="odd:bg-white even:bg-slate-50 text-sm">'
        f'<td class="px-4 py-2 font-medium text-gray-900">'
        f'{si.ingredient.nome if si.ingredient else "—"}</td>'
        f'<td class="px-4 py-2 text-right text-gray-700">'
        f'{"R$ {:.2f}".format(si.preco_ultima_compra) if si.preco_ultima_compra else "—"}</td>'
        f'<td class="px-4 py-2 text-center">'
        f'<button hx-delete="/api/cadastro/supplier-ingredient/{si.id}" '
        f'hx-target="#si-{si.id}" hx-swap="outerHTML swap:300ms" '
        f'hx-confirm="Remover do catálogo?" '
        f'class="text-red-500 hover:text-red-700 p-1"><i class="ph ph-trash"></i></button>'
        f'</td></tr>'
        for si in items
    )
    return HTMLResponse(rows or '<tr><td colspan="3" class="px-4 py-4 text-center text-gray-400 text-sm">Catálogo vazio.</td></tr>')


@router.post("/supplier/{sup_id}/catalog", response_class=HTMLResponse)
def add_to_catalog(
    request: Request,
    sup_id: str,
    ingredient_id: str = Form(...),
    preco_ultima_compra: float = Form(0.0),
    db: Session = Depends(get_db),
):
    from models import SupplierIngredient, Ingredient
    from datetime import datetime as _dt
    try:
        si = SupplierIngredient(
            id=_uuid.uuid4(),
            supplier_id=sup_id,
            ingredient_id=ingredient_id,
            preco_ultima_compra=preco_ultima_compra or None,
            data_atualizacao=_dt.utcnow(),
        )
        db.add(si)
        db.commit()
        db.refresh(si)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao adicionar: {e}")

    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    row = (
        f'<tr id="si-{si.id}" class="odd:bg-white even:bg-slate-50 text-sm">'
        f'<td class="px-4 py-2 font-medium text-gray-900">{ing.nome if ing else "—"}</td>'
        f'<td class="px-4 py-2 text-right text-gray-700">'
        f'{"R$ {:.2f}".format(si.preco_ultima_compra) if si.preco_ultima_compra else "—"}</td>'
        f'<td class="px-4 py-2 text-center">'
        f'<button hx-delete="/api/cadastro/supplier-ingredient/{si.id}" '
        f'hx-target="#si-{si.id}" hx-swap="outerHTML swap:300ms" '
        f'hx-confirm="Remover do catálogo?" '
        f'class="text-red-500 hover:text-red-700 p-1"><i class="ph ph-trash"></i></button>'
        f'</td></tr>'
    )
    return _ok(row, "Item adicionado ao catálogo!")


@router.delete("/supplier-ingredient/{si_id}", response_class=HTMLResponse)
def remove_from_catalog(si_id: str, db: Session = Depends(get_db)):
    from models import SupplierIngredient
    si = db.query(SupplierIngredient).filter(SupplierIngredient.id == si_id).first()
    if not si:
        return _err("Item não encontrado.")
    try:
        db.delete(si)
        db.commit()
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao remover: {e}")
    r = HTMLResponse("")
    r.headers["HX-Trigger"] = _toast("Item removido do catálogo.", "success")
    return r


# ─── Equipamentos ──────────────────────────────────────────────────────────────

@router.get("/equipments", response_class=HTMLResponse)
def list_equipments(request: Request, db: Session = Depends(get_db)):
    from models import Equipment
    items = db.query(Equipment).filter(Equipment.ativo == True).order_by(Equipment.nome).all()
    rows = "".join(
        f'<tr id="eq-{e.id}" class="odd:bg-white even:bg-slate-50 text-sm">'
        f'<td class="px-4 py-2 font-medium text-gray-900">{e.nome}</td>'
        f'<td class="px-4 py-2 text-gray-500">{e.descricao or "—"}</td>'
        f'<td class="px-4 py-2 text-center">'
        f'<button hx-delete="/api/cadastro/equipment/{e.id}" hx-target="#eq-{e.id}" hx-swap="outerHTML swap:300ms" '
        f'hx-confirm="Excluir {e.nome}?" '
        f'class="text-red-500 hover:text-red-700 p-1"><i class="ph ph-trash"></i></button>'
        f'</td></tr>'
        for e in items
    )
    return HTMLResponse(rows or '<tr><td colspan="3" class="px-4 py-6 text-center text-gray-400 text-sm">Nenhum equipamento.</td></tr>')


@router.post("/equipment", response_class=HTMLResponse)
def create_equipment(
    request: Request,
    nome: str = Form(...),
    descricao: str = Form(""),
    db: Session = Depends(get_db),
):
    from models import Equipment
    try:
        eq = Equipment(
            id=_uuid.uuid4(),
            nome=nome.strip(),
            descricao=descricao.strip() or None,
            ativo=True,
        )
        db.add(eq)
        db.commit()
        db.refresh(eq)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao cadastrar: {e}")

    row = (
        f'<tr id="eq-{eq.id}" class="odd:bg-white even:bg-slate-50 text-sm">'
        f'<td class="px-4 py-2 font-medium text-gray-900">{eq.nome}</td>'
        f'<td class="px-4 py-2 text-gray-500">{eq.descricao or "—"}</td>'
        f'<td class="px-4 py-2 text-center">'
        f'<button hx-delete="/api/cadastro/equipment/{eq.id}" hx-target="#eq-{eq.id}" hx-swap="outerHTML swap:300ms" '
        f'hx-confirm="Excluir {eq.nome}?" '
        f'class="text-red-500 hover:text-red-700 p-1"><i class="ph ph-trash"></i></button>'
        f'</td></tr>'
    )
    return _ok(row, f'Equipamento "{eq.nome}" cadastrado!')


@router.post("/equipment/{eq_id}/parameter", response_class=HTMLResponse)
def create_equipment_parameter(
    request: Request,
    eq_id: str,
    nome_parametro: str = Form(...),
    valor_padrao: str = Form(""),
    unidade_medida: str = Form(""),
    db: Session = Depends(get_db),
):
    from models import EquipmentParameter
    try:
        p = EquipmentParameter(
            id=_uuid.uuid4(),
            equipment_id=eq_id,
            nome_parametro=nome_parametro.strip(),
            valor_padrao=valor_padrao.strip() or None,
            unidade_medida=unidade_medida.strip() or None,
        )
        db.add(p)
        db.commit()
        db.refresh(p)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao cadastrar parâmetro: {e}")

    row = (
        f'<li class="flex items-center gap-2 text-sm text-gray-700 py-1 border-b border-slate-100">'
        f'<i class="ph ph-sliders text-blue-400"></i>'
        f'<span class="font-medium">{p.nome_parametro}</span>'
        f'<span class="text-gray-400">= {p.valor_padrao or "—"} {p.unidade_medida or ""}</span>'
        f'</li>'
    )
    return _ok(row, f'Parâmetro "{p.nome_parametro}" adicionado!')


@router.delete("/equipment/{eq_id}", response_class=HTMLResponse)
def delete_equipment(eq_id: str, db: Session = Depends(get_db)):
    from models import Equipment
    eq = db.query(Equipment).filter(Equipment.id == eq_id).first()
    if not eq:
        return _err("Equipamento não encontrado.")
    try:
        eq.ativo = False
        db.commit()
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao excluir: {e}")
    r = HTMLResponse("")
    r.headers["HX-Trigger"] = _toast("Equipamento removido.", "success")
    return r


# ─── Endpoints de listagem de equipamentos ────────────────────────────────────

@router.get("/equipments-options", response_class=HTMLResponse)
def equipments_options(request: Request, db: Session = Depends(get_db)):
    from models import Equipment
    items = db.query(Equipment).filter(Equipment.ativo == True).order_by(Equipment.nome).all()
    opts = '<option value="">— Selecionar Equipamento —</option>' + "".join(
        f'<option value="{e.id}">{e.nome}</option>' for e in items
    )
    return HTMLResponse(opts)


@router.get("/ingredient/{ing_id}/manufacturer-options", response_class=HTMLResponse)
def ingredient_manufacturer_options(ing_id: str, db: Session = Depends(get_db)):
    return _manufacturer_options_html(ing_id, db)


@router.get("/ingredient-manufacturer-options", response_class=HTMLResponse)
def ingredient_manufacturer_options_qs(ingredient_id: str = "", db: Session = Depends(get_db)):
    """Query-param variant used by HTMX hx-get (hx-include passes name=ingredient_id)."""
    return _manufacturer_options_html(ingredient_id, db)


def _manufacturer_options_html(ing_id: str, db) -> HTMLResponse:
    from models import IngredientManufacturer
    if not ing_id:
        return HTMLResponse('<option value="">— Selecione um insumo primeiro —</option>')
    items = db.query(IngredientManufacturer).filter(
        IngredientManufacturer.ingredient_id == ing_id
    ).order_by(IngredientManufacturer.nome_fabricante).all()
    if not items:
        return HTMLResponse('<option value="">— Nenhuma marca cadastrada —</option>')
    options = '<option value="">— Selecione a marca —</option>'
    options += "".join(
        f'<option value="{m.nome_fabricante}" data-fc="{m.percentual_rendimento:.2f}">'
        f'{m.nome_fabricante} (FC {m.percentual_rendimento:.2f})</option>'
        for m in items
    )
    return HTMLResponse(options)


# ─── Catálogo do Fornecedor (SupplierCatalog — marca + FC) ────────────────────

@router.get("/suppliers/{supplier_id}/catalog/modal", response_class=HTMLResponse)
def get_supplier_catalog_modal(supplier_id: str, request: Request, db: Session = Depends(get_db)):
    from models import Supplier, Ingredient, SupplierCatalog
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    ingredients = db.query(Ingredient).filter(Ingredient.ativo == True).order_by(Ingredient.nome).all()
    catalog_items = db.query(SupplierCatalog).filter(
        SupplierCatalog.supplier_id == supplier_id,
        SupplierCatalog.ativo == True,
    ).all()
    return templates.TemplateResponse(
        "cadastro/fragments/supplier_catalog_modal.html",
        {"request": request, "supplier": supplier, "ingredients": ingredients, "catalog_items": catalog_items},
    )


@router.post("/suppliers/{supplier_id}/catalog", response_class=HTMLResponse)
def add_supplier_catalog_item(
    supplier_id: str,
    ingredient_id: str = Form(...),
    marca_fabricante: str = Form(...),
    fc_marca: float = Form(1.0),
    preco_compra: float = Form(0.0),
    db: Session = Depends(get_db),
):
    from models import SupplierCatalog, Ingredient
    try:
        novo = SupplierCatalog(
            id=_uuid.uuid4(),
            supplier_id=supplier_id,
            ingredient_id=ingredient_id,
            marca_fabricante=marca_fabricante.strip(),
            fc_marca=fc_marca,
            preco_compra=preco_compra or None,
        )
        db.add(novo)
        db.commit()
        db.refresh(novo)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao adicionar: {e}")

    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    preco_str = f'R$ {novo.preco_compra:.2f}' if novo.preco_compra else '—'
    html = (
        f'<tr id="cat-item-{novo.id}" class="hover:bg-slate-50 transition-colors">'
        f'<td class="px-4 py-2.5 font-medium text-gray-900">{ing.nome if ing else "—"}</td>'
        f'<td class="px-4 py-2.5 text-gray-700">{novo.marca_fabricante}</td>'
        f'<td class="px-4 py-2.5 text-center">'
        f'<span class="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 font-mono text-xs font-bold">{novo.fc_marca:.2f}</span>'
        f'</td>'
        f'<td class="px-4 py-2.5 text-right text-gray-700 font-mono">{preco_str}</td>'
        f'<td class="px-4 py-2.5 text-right">'
        f'<button hx-delete="/api/cadastro/suppliers/catalog/{novo.id}" '
        f'hx-target="#cat-item-{novo.id}" hx-swap="outerHTML swap:300ms" '
        f'hx-confirm="Remover esta marca do catálogo?" '
        f'class="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded transition-colors">'
        f'<i class="ph ph-trash text-base"></i></button>'
        f'</td></tr>'
    )
    r = HTMLResponse(content=html)
    r.headers["HX-Trigger"] = _toast("Marca vinculada ao fornecedor!", "success")
    return r


@router.delete("/suppliers/catalog/{item_id}", response_class=HTMLResponse)
def delete_catalog_item(item_id: str, db: Session = Depends(get_db)):
    from models import SupplierCatalog
    item = db.query(SupplierCatalog).filter(SupplierCatalog.id == item_id).first()
    if not item:
        return _err("Item não encontrado.")
    try:
        item.ativo = False
        db.commit()
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao remover: {e}")
    r = HTMLResponse("")
    r.headers["HX-Trigger"] = _toast("Item removido do catálogo.", "warning")
    return r


@router.get("/equipment/{eq_id}/parameters-json")
def equipment_parameters_json(eq_id: str, db: Session = Depends(get_db)):
    """Retorna os parâmetros template de um equipamento como JSON (para o BOM form)."""
    import json as _json
    from models import EquipmentParameter
    from fastapi.responses import JSONResponse
    params = (
        db.query(EquipmentParameter)
        .filter(EquipmentParameter.equipment_id == eq_id)
        .order_by(EquipmentParameter.nome_parametro)
        .all()
    )
    return JSONResponse([
        {
            "nome": p.nome_parametro,
            "valor_padrao": p.valor_padrao or "",
            "unidade": p.unidade_medida or "",
        }
        for p in params
    ])

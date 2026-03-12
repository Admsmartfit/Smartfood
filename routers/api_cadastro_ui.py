"""FE-09 — Cadastros via UI (Ingredientes, Produtos, Fornecedores, Clientes)."""
import json
import uuid as _uuid

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

@router.get("/ingredients", response_class=HTMLResponse)
def list_ingredients(request: Request, db: Session = Depends(get_db)):
    from models import Ingredient
    items = db.query(Ingredient).order_by(Ingredient.nome).all()
    return templates.TemplateResponse(
        "cadastro/fragments/ingredients_rows.html",
        {"request": request, "items": items},
    )


@router.post("/ingredient", response_class=HTMLResponse)
def create_ingredient(
    request: Request,
    nome: str = Form(...),
    unidade: str = Form("kg"),
    custo_atual: float = Form(0.0),
    estoque_atual: float = Form(0.0),
    estoque_minimo: float = Form(0.0),
    lead_time_dias: int = Form(3),
    db: Session = Depends(get_db),
):
    from models import Ingredient
    try:
        ing = Ingredient(
            id=_uuid.uuid4(),
            nome=nome.strip(),
            unidade=unidade.strip(),
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

    row = (
        f'<tr id="ing-{ing.id}" class="odd:bg-white even:bg-slate-50 text-sm">'
        f'<td class="px-4 py-2 font-medium text-gray-900">{ing.nome}</td>'
        f'<td class="px-4 py-2 text-gray-500">{ing.unidade}</td>'
        f'<td class="px-4 py-2 text-right text-gray-700">R$ {ing.custo_atual:.2f}</td>'
        f'<td class="px-4 py-2 text-right">{ing.estoque_atual:.1f}</td>'
        f'<td class="px-4 py-2 text-right text-gray-500">{ing.estoque_minimo:.1f}</td>'
        f'<td class="px-4 py-2 text-center text-gray-500">{ing.lead_time_dias}d</td>'
        f'</tr>'
    )
    return _ok(row, f'Ingrediente "{ing.nome}" cadastrado!')


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
    db: Session = Depends(get_db),
):
    from models import Customer
    try:
        c = Customer(
            id=_uuid.uuid4(),
            nome=nome.strip(),
            whatsapp=whatsapp.strip() or None,
            email=email.strip() or None,
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
        f'</tr>'
    )
    return _ok(row, f'Cliente "{c.nome}" cadastrado!')

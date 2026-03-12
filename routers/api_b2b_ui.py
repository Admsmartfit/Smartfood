"""FE-05 — API B2B para UI: pedidos Kanban, reposição proativa, catálogo e carrinho."""
import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(tags=["API — B2B UI FE-05"])
templates = Jinja2Templates(directory="templates")


# ─── Kanban de Pedidos ────────────────────────────────────────────────────────

@router.get("/api/b2b/fragments/orders-board", response_class=HTMLResponse)
def fragment_orders_board(
    request: Request,
    customer_id: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Colunas Kanban com todos os pedidos agrupados por status."""
    from services.b2b_service import list_orders

    cid = uuid.UUID(customer_id) if customer_id else None
    all_orders = list_orders(db, customer_id=cid)

    STATUSES = [
        ("RASCUNHO",    "Rascunho",     "bg-gray-100",   "text-gray-700"),
        ("CONFIRMADO",  "Confirmado",   "bg-blue-100",   "text-blue-800"),
        ("EM_PRODUCAO", "Em Produção",  "bg-yellow-100", "text-yellow-800"),
        ("PRONTO",      "Pronto",       "bg-purple-100", "text-purple-800"),
        ("ENTREGUE",    "Entregue",     "bg-green-100",  "text-green-800"),
    ]

    columns = []
    for status, label, col_bg, col_txt in STATUSES:
        columns.append({
            "status": status,
            "label": label,
            "col_bg": col_bg,
            "col_txt": col_txt,
            "orders": [o for o in all_orders if o.get("status") == status],
        })

    return templates.TemplateResponse(
        "fragments/orders_board.html",
        {"request": request, "columns": columns},
    )


@router.post("/api/b2b/orders/{order_id}/status", response_class=HTMLResponse)
def update_order_status_ui(
    order_id: uuid.UUID,
    request: Request,
    new_status: str = Form(...),
    db: Session = Depends(get_db),
):
    """Atualiza status de um pedido e retorna o card atualizado."""
    from services.b2b_service import update_order_status

    error_msg = None
    order = {}
    try:
        order = update_order_status(db, order_id, new_status)
        msg = {"showToast": {"message": f"Pedido → {new_status}", "type": "success"}}
    except Exception as e:
        error_msg = str(e)
        msg = {"showToast": {"message": error_msg, "type": "error"}}

    response = templates.TemplateResponse(
        "fragments/order_card.html",
        {"request": request, "order": order, "error": error_msg},
    )
    response.headers["HX-Trigger"] = json.dumps(msg)
    return response


# ─── Reposição Proativa B2B ───────────────────────────────────────────────────

@router.get("/api/b2b/fragments/intel", response_class=HTMLResponse)
def fragment_b2b_intel(
    request: Request,
    db: Session = Depends(get_db),
):
    """Cards de clientes com risco de ruptura de estoque."""
    from models import Customer
    from services.b2b_service import check_inventory_depletion

    customers_db = db.query(Customer).filter(Customer.nome != None).order_by(Customer.nome).all()

    customers = []
    for c in customers_db:
        try:
            depletions = check_inventory_depletion(db, c.id)
        except Exception:
            depletions = []

        if not depletions:
            continue

        # Calcula urgência geral do cliente
        max_days = max((d.get("dias_apos_esgotamento", 0) for d in depletions), default=0)
        urgency = "critical" if max_days >= 3 else "warning"

        customers.append({
            "id": str(c.id),
            "nome": c.nome,
            "whatsapp": c.whatsapp or "",
            "urgency": urgency,
            "urgency_label": "Crítico" if urgency == "critical" else "Atenção",
            "running_low": [
                {
                    "nome": d["produto_nome"],
                    "days_remaining": -d["dias_apos_esgotamento"],  # negativo = já esgotou
                    "esgotado": d["dias_apos_esgotamento"] >= 0,
                }
                for d in depletions
            ],
        })

    # Críticos primeiro
    customers.sort(key=lambda x: 0 if x["urgency"] == "critical" else 1)

    return templates.TemplateResponse(
        "fragments/b2b_intel_cards.html",
        {"request": request, "customers": customers},
    )


@router.post("/commercial/b2b/send-replenishment/{customer_id}", response_class=HTMLResponse)
def send_replenishment(
    customer_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """Envia sugestão de reposição via WhatsApp e retorna card atualizado."""
    from models import Customer
    from services.b2b_service import check_inventory_depletion, get_suggested_order
    from services.purchase_automation import mega_client

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        return HTMLResponse("<p class='text-red-500 p-4'>Cliente não encontrado.</p>")

    error_msg = None
    sent_at = ""

    try:
        depletions = check_inventory_depletion(db, customer_id)
        suggested = get_suggested_order(db, customer_id)

        items_text = ""
        for d in depletions:
            items_text += f"\n• {d['produto_nome']}"

        msg = (
            f"Olá {customer.nome.split()[0]}! 📦 Seu estoque está baixo para:{items_text}\n\n"
            f"Posso incluir na sua próxima entrega? Responda SIM para confirmar. 🛒"
        )

        if customer.whatsapp:
            mega_client.send_message(customer.whatsapp, msg)

        sent_at = datetime.now(timezone.utc).strftime("%H:%M")
        trigger = json.dumps({"showToast": {"message": f"Mensagem enviada para {customer.nome}!", "type": "success"}})
    except Exception as e:
        error_msg = str(e)
        trigger = json.dumps({"showToast": {"message": f"Erro: {error_msg}", "type": "error"}})

    response = templates.TemplateResponse(
        "fragments/replenishment_sent.html",
        {
            "request": request,
            "customer": customer,
            "sent_at": sent_at,
            "error": error_msg,
        },
    )
    response.headers["HX-Trigger"] = trigger
    return response


# ─── Catálogo / Carrinho Portal B2B ──────────────────────────────────────────

@router.get("/api/b2b/catalog", response_class=HTMLResponse)
def catalog_fragment(
    request: Request,
    q: str = Query(default=""),
    categoria: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Grid de produtos do catálogo."""
    from services.b2b_service import get_catalog

    products = get_catalog(db)
    if q:
        products = [p for p in products if q.lower() in p["nome"].lower()]
    if categoria:
        products = [p for p in products if p.get("categoria") == categoria]

    return templates.TemplateResponse(
        "fragments/catalog_grid.html",
        {"request": request, "products": products, "query": q},
    )


@router.post("/portal/cart/add", response_class=HTMLResponse)
def cart_add(
    request: Request,
    product_id: str = Form(...),
    quantidade: float = Form(default=1.0),
    product_nome: str = Form(default=""),
    preco: float = Form(default=0.0),
    db: Session = Depends(get_db),
):
    """Adiciona item ao carrinho (sessão Alpine) e retorna o mini-carrinho atualizado."""
    trigger = json.dumps({"showToast": {"message": f"{product_nome} adicionado!", "type": "success"},
                          "cartAdd": {"product_id": product_id, "quantidade": quantidade, "preco": preco, "nome": product_nome}})
    response = HTMLResponse(content="")
    response.headers["HX-Trigger"] = trigger
    return response


@router.post("/portal/orders/repeat", response_class=HTMLResponse)
def repeat_order_ui(
    request: Request,
    order_id: str = Form(...),
    db: Session = Depends(get_db),
):
    """Repete último pedido e retorna confirmação."""
    from services.b2b_service import repeat_order

    error_msg = None
    new_order = {}
    try:
        new_order = repeat_order(db, uuid.UUID(order_id))
        trigger = json.dumps({"showToast": {"message": "Pedido repetido com sucesso!", "type": "success"}})
    except Exception as e:
        error_msg = str(e)
        trigger = json.dumps({"showToast": {"message": f"Erro: {error_msg}", "type": "error"}})

    response = templates.TemplateResponse(
        "fragments/order_repeated.html",
        {"request": request, "order": new_order, "error": error_msg},
    )
    response.headers["HX-Trigger"] = trigger
    return response

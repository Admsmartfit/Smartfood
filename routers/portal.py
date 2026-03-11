"""
E-12 — Rotas do Portal B2B: Catálogo, Pedidos, Recompra e NPS
"""
from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database import get_db
from services.b2b_service import (
    get_catalog,
    create_order,
    get_order,
    list_orders,
    update_order_status,
    repeat_order,
    get_suggested_order,
    send_nps_survey,
    register_nps_response,
    run_reorder_job,
    list_price_tables,
    ORDER_TRANSITIONS,
    # E-13
    check_inventory_depletion,
    notify_new_product,
    run_depletion_check_job,
)

router = APIRouter(tags=["Portal B2B - E-12"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class OrderItemInput(BaseModel):
    product_id: uuid.UUID
    quantidade: float

    @field_validator("quantidade")
    @classmethod
    def qty_positiva(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("Quantidade deve ser positiva")
        return v


class OrderCreate(BaseModel):
    customer_id: uuid.UUID
    items: List[OrderItemInput]
    canal: str = "b2b_portal"
    data_entrega_prevista: Optional[datetime] = None


class OrderStatusUpdate(BaseModel):
    novo_status: str


class NPSResponseInput(BaseModel):
    nota: int
    comentario: str = ""

    @field_validator("nota")
    @classmethod
    def nota_valida(cls, v: int) -> int:
        if not (0 <= v <= 10):
            raise ValueError("Nota NPS deve ser entre 0 e 10")
        return v


class PriceTableCreate(BaseModel):
    id: str
    nome: str
    desconto_pct: float = 0.0


# ─── Catálogo ───────────────────────────────────────────────────────────────

@router.get("/portal/catalog")
def catalog(
    customer_id: Optional[uuid.UUID] = Query(
        default=None,
        description="ID do cliente para aplicar tabela de preços correta"
    ),
    db: Session = Depends(get_db),
):
    """
    Retorna catálogo de produtos ativos com:
    - Foto, descrição de marketing, info nutricional, alérgenos
    - URL de instrução de preparo
    - Preço calculado com base na tabela de preços do cliente

    Se customer_id não informado, retorna preço com markup base.
    """
    return get_catalog(db, customer_id=customer_id)


# ─── Pedidos B2B ─────────────────────────────────────────────────────────────

@router.post("/orders", status_code=201)
def create_b2b_order(payload: OrderCreate, db: Session = Depends(get_db)):
    """
    Cria pedido B2B (status RASCUNHO) com:
    - Cálculo automático de margem por item
    - Preço segmentado pela tabela do cliente
    - Entrega prevista padrão: +2 dias úteis (customizável)
    """
    try:
        return create_order(
            db=db,
            customer_id=payload.customer_id,
            items=[{"product_id": str(it.product_id), "quantidade": it.quantidade} for it in payload.items],
            canal=payload.canal,
            data_entrega_prevista=payload.data_entrega_prevista,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/orders")
def list_b2b_orders(
    customer_id: Optional[uuid.UUID] = Query(default=None),
    status: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """Lista pedidos B2B com filtro opcional por cliente e status."""
    return list_orders(db, customer_id=customer_id, status=status)


@router.get("/orders/{order_id}")
def get_b2b_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """Retorna detalhes de um pedido com todos os itens."""
    try:
        return get_order(db, order_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/orders/{order_id}/status")
def change_order_status(
    order_id: uuid.UUID,
    payload: OrderStatusUpdate,
    db: Session = Depends(get_db),
):
    """
    Atualiza status do pedido segundo máquina de estados:

    `RASCUNHO → CONFIRMADO → EM_PRODUCAO → PRONTO → ENTREGUE`

    Ao atingir ENTREGUE, dispara pesquisa NPS automaticamente via WhatsApp.
    """
    valid = list(ORDER_TRANSITIONS.keys())
    if payload.novo_status not in valid and payload.novo_status != "CANCELADO":
        raise HTTPException(status_code=422, detail=f"Status inválido. Válidos: {valid}")
    try:
        return update_order_status(db, order_id, payload.novo_status)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/orders/{order_id}/repeat", status_code=201)
def repeat_b2b_order(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Repete pedido anterior em 1 clique (US-012).
    Cria novo pedido com mesmos itens e entrega +2 dias úteis.
    """
    try:
        return repeat_order(db, order_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ─── Sugestão de Pedido ──────────────────────────────────────────────────────

@router.get("/customers/{customer_id}/suggested-order")
def suggested_order(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Sugere próximo pedido baseado em histórico do cliente:
    - Dias desde último pedido
    - Intervalo médio entre pedidos
    - Produtos mais pedidos com quantidade média sugerida
    - Estimativa da data do próximo pedido
    """
    try:
        return get_suggested_order(db, customer_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── NPS ─────────────────────────────────────────────────────────────────────

@router.post("/orders/{order_id}/nps")
def trigger_nps(order_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Dispara pesquisa NPS manualmente via WhatsApp.
    Normalmente ativado automaticamente ao marcar pedido como ENTREGUE.
    """
    try:
        return send_nps_survey(db, order_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/nps/{survey_id}/response")
def nps_response(survey_id: uuid.UUID, payload: NPSResponseInput, db: Session = Depends(get_db)):
    """
    Registra resposta do cliente à pesquisa NPS (webhook ou input manual).
    Classifica como: promotor (9-10), neutro (7-8), detrator (0-6).
    """
    try:
        return register_nps_response(db, survey_id, payload.nota, payload.comentario)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ─── Recompra Proativa (E-12/E-13) ───────────────────────────────────────────

@router.post("/portal/run-reorder-job")
def trigger_reorder_job(db: Session = Depends(get_db)):
    """
    Dispara manualmente o job diário de recompra proativa.
    Para cada cliente ativo:
    1. Se dias_sem_pedido > intervalo_médio × 1.2 → alerta BAR_SEM_PEDIDO + WhatsApp
    2. Se feriado/fds prolongado nos próximos 5 dias → aviso de sazonalidade
    """
    return run_reorder_job(db)


# ─── E-13: Inteligência de Reposição Proativa ────────────────────────────────

@router.get("/customers/{customer_id}/inventory-depletion")
def inventory_depletion(customer_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    E-13: Projeta esgotamento de estoque do bar por produto.

    Fórmula: consumo_diario = last_order_qty / avg_interval_dias
    Se data_esgotamento <= hoje → retorna produto com status 'esgotado'.
    """
    try:
        return {"customer_id": str(customer_id), "depletions": check_inventory_depletion(db, customer_id)}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/products/{product_id}/notify-launch")
def notify_product_launch(product_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    E-13: Notifica clientes com perfil similar sobre novo produto no catálogo.
    Envia mensagem personalizada via WhatsApp com oferta de amostra grátis.
    """
    try:
        return notify_new_product(db, product_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/portal/run-depletion-job")
def trigger_depletion_job(db: Session = Depends(get_db)):
    """
    E-13: Job que verifica previsão de esgotamento de estoque de todos os clientes.
    Cria alertas ESGOTAMENTO_BAR e envia WhatsApp proativo quando detectado.
    """
    return run_depletion_check_job(db)


# ─── Tabelas de Preço ────────────────────────────────────────────────────────

@router.get("/price-tables")
def get_price_tables(db: Session = Depends(get_db)):
    """Lista tabelas de preços ativas (Grupo A, B, C)."""
    return list_price_tables(db)


@router.post("/price-tables", status_code=201)
def create_price_table(payload: PriceTableCreate, db: Session = Depends(get_db)):
    """
    Cria nova tabela de preços.

    Exemplos:
    - `{"id": "A", "nome": "Grandes Redes", "desconto_pct": 10.0}`
    - `{"id": "B", "nome": "Bares Parceiros", "desconto_pct": 5.0}`
    - `{"id": "C", "nome": "Spot", "desconto_pct": 0.0}`
    """
    from models import PriceTable
    existing = db.query(PriceTable).filter(PriceTable.id == payload.id).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Tabela '{payload.id}' já existe")
    pt = PriceTable(id=payload.id, nome=payload.nome, desconto_pct=payload.desconto_pct)
    db.add(pt)
    db.commit()
    return {"id": pt.id, "nome": pt.nome, "desconto_pct": pt.desconto_pct}

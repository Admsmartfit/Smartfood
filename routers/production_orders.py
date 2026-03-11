"""
E-11 — Rotas de Ordens de Produção (Estado de Máquina Completo)

Ciclo de vida: RASCUNHO → APROVADA → EM_PRODUCAO → CONCLUIDA | CANCELADA
"""
from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services.production_service import (
    create_production_order,
    list_production_orders,
    feasibility_check,
    approve_order,
    start_production,
    record_ingredient_usage,
    complete_production_order,
    cancel_production_order,
)
from cost_calculator import DEFAULT_LABOR_COST_PER_MIN

router = APIRouter(prefix="/production-orders", tags=["Ordens de Produção - E-11"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class ProductionOrderCreate(BaseModel):
    product_id: uuid.UUID
    quantidade_planejada: float
    data_inicio: Optional[datetime] = None
    data_fim: Optional[datetime] = None


class StartProductionRequest(BaseModel):
    operador_id: str


class IngredientUsageItem(BaseModel):
    ingredient_id: uuid.UUID
    lot_id: Optional[uuid.UUID] = None
    qty_real: float


class RecordUsageRequest(BaseModel):
    usages: List[IngredientUsageItem]


class CompleteProductionRequest(BaseModel):
    quantidade_real: float
    custo_energia_kwh: Optional[float] = None
    labor_cost_per_min: float = DEFAULT_LABOR_COST_PER_MIN


class CancelProductionRequest(BaseModel):
    motivo: str


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/", status_code=201)
def create_order(payload: ProductionOrderCreate, db: Session = Depends(get_db)):
    """
    Cria uma nova Ordem de Produção com status RASCUNHO.
    """
    try:
        return create_production_order(
            db=db,
            product_id=payload.product_id,
            quantidade_planejada=payload.quantidade_planejada,
            data_inicio=payload.data_inicio,
            data_fim=payload.data_fim,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/")
def list_orders(
    status: Optional[str] = Query(
        default=None,
        description="Filtrar por status: RASCUNHO|APROVADA|EM_PRODUCAO|CONCLUIDA|CANCELADA"
    ),
    db: Session = Depends(get_db),
):
    """Lista todas as Ordens de Produção, com filtro opcional por status."""
    return list_production_orders(db, status=status)


@router.get("/{batch_id}/feasibility")
def check_feasibility(batch_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Verifica viabilidade da OP: checa estoque de insumos (BOM) e embalagens (E-08).
    Retorna lista de déficits por ingrediente/supply.
    """
    try:
        return feasibility_check(db, batch_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/{batch_id}/approve")
def approve(batch_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Aprova OP: RASCUNHO → APROVADA.
    Executa feasibility check — rejeita se houver déficits.
    """
    try:
        result = approve_order(db, batch_id)
        if not result.get("aprovado"):
            raise HTTPException(status_code=422, detail=result)
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{batch_id}/start")
def start(
    batch_id: uuid.UUID,
    payload: StartProductionRequest,
    db: Session = Depends(get_db),
):
    """
    Inicia produção: APROVADA → EM_PRODUCAO.
    Registra hora_inicio, operador e retorna sugestão PVPS de lotes.
    """
    try:
        return start_production(db, batch_id, payload.operador_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{batch_id}/usage")
def record_usage(
    batch_id: uuid.UUID,
    payload: RecordUsageRequest,
    db: Session = Depends(get_db),
):
    """
    Registra consumo real de insumos por lote (PVPS).
    Calcula divergência vs planejado e deduz estoque dos lotes.
    Pode ser chamado múltiplas vezes — sobrescreve registros anteriores.

    Se `lot_id` não for informado, o sistema aplica PVPS automático.
    """
    try:
        usages = [
            {
                "ingredient_id": str(u.ingredient_id),
                "lot_id": str(u.lot_id) if u.lot_id else None,
                "qty_real": u.qty_real,
            }
            for u in payload.usages
        ]
        return record_ingredient_usage(db, batch_id, usages)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{batch_id}/complete")
def complete(
    batch_id: uuid.UUID,
    payload: CompleteProductionRequest,
    db: Session = Depends(get_db),
):
    """
    Conclui OP: EM_PRODUCAO → CONCLUIDA.

    Calcula custo real:
    - custo_insumos = Σ(qty_real × custo_unitário)
    - custo_labor   = (hora_fim - hora_inicio) em min × labor_cost_per_min
    - custo_energia = custo_energia_kwh informado
    - custo_total   = soma dos três

    Adiciona quantidade_real ao estoque do produto acabado.
    """
    try:
        return complete_production_order(
            db=db,
            batch_id=batch_id,
            quantidade_real=payload.quantidade_real,
            custo_energia_kwh=payload.custo_energia_kwh,
            labor_cost_per_min=payload.labor_cost_per_min,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/{batch_id}/cancel")
def cancel(
    batch_id: uuid.UUID,
    payload: CancelProductionRequest,
    db: Session = Depends(get_db),
):
    """
    Cancela OP (qualquer status exceto CONCLUIDA ou já CANCELADA).
    Registra motivo do cancelamento.
    """
    try:
        return cancel_production_order(db, batch_id, payload.motivo)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

"""
E-07 — Rotas de Gestão de Estoque com PVPS e Rastreabilidade de Lotes
"""
from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database import get_db
from models import Ingredient, IngredientLot, InventoryAdjustment
from services.inventory_service import (
    receive_ingredient,
    get_fifo_lots,
    consume_for_production,
    get_traceability,
    adjust_inventory,
    calculate_safety_stock,
    DEFAULT_DIVERGENCE_TOLERANCE_PCT,
)

router = APIRouter(prefix="/inventory", tags=["Estoque e Lotes - E-07"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class ReceiveRequest(BaseModel):
    ingredient_id: uuid.UUID
    numero_lote: str
    quantidade: float
    data_validade: datetime
    fornecedor_nome: Optional[str] = None
    peso_balanca: Optional[float] = None
    nfe_xml: Optional[str] = None
    divergence_tolerance_pct: float = DEFAULT_DIVERGENCE_TOLERANCE_PCT

    @field_validator("quantidade")
    @classmethod
    def qty_positiva(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("quantidade deve ser positiva")
        return v


class ReceiveResponse(BaseModel):
    lot_id: str
    ingrediente_nome: str
    numero_lote: str
    quantidade_recebida: float
    estoque_total_atualizado: float
    data_validade: str
    divergencia_pct: Optional[float]
    alertas: List[str]
    nfe_parsed: bool


class FifoLotItem(BaseModel):
    lot_id: str
    numero_lote: str
    data_validade: str
    qty_disponivel: float
    qty_a_consumir: float


class AdjustRequest(BaseModel):
    ingredient_id: uuid.UUID
    qty_ajuste: float
    motivo: str
    ajustado_por: Optional[str] = None
    foto_base64: Optional[str] = None

    @field_validator("motivo")
    @classmethod
    def motivo_nao_vazio(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("motivo é obrigatório para ajustes de estoque")
        return v


class LotItem(BaseModel):
    id: uuid.UUID
    numero_lote: str
    quantidade_recebida: float
    quantidade_atual: float
    data_validade: str
    data_recebimento: str
    fornecedor_nome: Optional[str]
    status: str
    divergencia_pct: Optional[float]

    model_config = {"from_attributes": True}


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/receive", response_model=ReceiveResponse, status_code=201)
def receive_nfe(payload: ReceiveRequest, db: Session = Depends(get_db)):
    """
    Entrada de insumo: cria lote, atualiza estoque e valida divergência
    NF-e vs. peso na balança. Gera alerta automático se divergência > tolerância.
    Aceita NF-e XML opcionalmente para extração automática de metadados.
    """
    ing = db.query(Ingredient).filter(Ingredient.id == payload.ingredient_id).first()
    if not ing:
        raise HTTPException(status_code=404, detail="Ingrediente não encontrado")

    try:
        result = receive_ingredient(
            db=db,
            ingredient_id=payload.ingredient_id,
            numero_lote=payload.numero_lote,
            quantidade=payload.quantidade,
            data_validade=payload.data_validade,
            fornecedor_nome=payload.fornecedor_nome,
            peso_balanca=payload.peso_balanca,
            nfe_xml=payload.nfe_xml,
            divergence_tolerance_pct=payload.divergence_tolerance_pct,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return ReceiveResponse(**result)


@router.get("/lots/{ingredient_id}", response_model=List[LotItem])
def list_lots(
    ingredient_id: uuid.UUID,
    apenas_ativos: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    """
    Lista lotes de um ingrediente ordenados por data de validade (PVPS).
    Ideal para o operador ver qual lote abrir primeiro.
    """
    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        raise HTTPException(status_code=404, detail="Ingrediente não encontrado")

    q = db.query(IngredientLot).filter(IngredientLot.ingredient_id == ingredient_id)
    if apenas_ativos:
        q = q.filter(IngredientLot.status == "ativo")

    lots = q.order_by(IngredientLot.data_validade.asc()).all()

    return [
        LotItem(
            id=lot.id,
            numero_lote=lot.numero_lote,
            quantidade_recebida=lot.quantidade_recebida,
            quantidade_atual=lot.quantidade_atual,
            data_validade=lot.data_validade.isoformat(),
            data_recebimento=lot.data_recebimento.isoformat(),
            fornecedor_nome=lot.fornecedor_nome,
            status=lot.status,
            divergencia_pct=lot.divergencia_pct,
        )
        for lot in lots
    ]


@router.get("/fifo/{ingredient_id}", response_model=List[FifoLotItem])
def get_fifo(
    ingredient_id: uuid.UUID,
    qty_needed: float = Query(..., gt=0, description="Quantidade necessária"),
    db: Session = Depends(get_db),
):
    """
    Simula o PVPS: retorna quais lotes seriam consumidos (em ordem de vencimento)
    para atender a quantidade solicitada, sem efetuar o consumo.
    """
    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        raise HTTPException(status_code=404, detail="Ingrediente não encontrado")

    try:
        lots = get_fifo_lots(db, ingredient_id, qty_needed)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    return [FifoLotItem(**lot) for lot in lots]


@router.get("/safety-stock/{ingredient_id}")
def safety_stock(ingredient_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Calcula Estoque de Segurança = média_consumo_diário × (lead_time + 2)
    e Ponto de Ressuprimento = estoque_segurança + consumo_no_lead_time.
    """
    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        raise HTTPException(status_code=404, detail="Ingrediente não encontrado")

    try:
        return calculate_safety_stock(db, ingredient_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/adjust", status_code=201)
def manual_adjust(payload: AdjustRequest, db: Session = Depends(get_db)):
    """
    Ajuste manual de estoque com trilha de auditoria obrigatória.
    qty_ajuste positivo = entrada | negativo = saída (quebra, vencimento, furto).
    Foto base64 opcional como evidência.
    """
    try:
        return adjust_inventory(
            db=db,
            ingredient_id=payload.ingredient_id,
            qty_ajuste=payload.qty_ajuste,
            motivo=payload.motivo,
            ajustado_por=payload.ajustado_por,
            foto_base64=payload.foto_base64,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/adjustments/{ingredient_id}")
def list_adjustments(
    ingredient_id: uuid.UUID,
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    """Histórico de ajustes manuais de estoque (trilha de auditoria)."""
    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        raise HTTPException(status_code=404, detail="Ingrediente não encontrado")

    adjs = (
        db.query(InventoryAdjustment)
        .filter(InventoryAdjustment.ingredient_id == ingredient_id)
        .order_by(InventoryAdjustment.ajustado_em.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(a.id),
            "qty_ajuste": a.qty_ajuste,
            "motivo": a.motivo,
            "ajustado_por": a.ajustado_por,
            "ajustado_em": a.ajustado_em.isoformat(),
            "tem_foto": bool(a.foto_base64),
        }
        for a in adjs
    ]


# ─── Produção ────────────────────────────────────────────────────────────────

production_router = APIRouter(prefix="/production", tags=["Produção - E-07"])


@production_router.post("/{batch_id}/consume")
def consume_production(batch_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Deduz insumos do estoque usando PVPS para um lote de produção.
    Registra LotConsumption para rastreabilidade completa.
    Atualiza status do lote para EM_PRODUCAO.
    """
    try:
        return consume_for_production(db, batch_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ─── Rastreabilidade ─────────────────────────────────────────────────────────

traceability_router = APIRouter(prefix="/traceability", tags=["Rastreabilidade - E-07"])


@traceability_router.get("/product-batch/{batch_id}")
def trace_batch(batch_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Rastreabilidade completa de um lote de produção: todos os lotes de insumo
    utilizados com fornecedor, NF-e, data de validade e quantidade consumida.
    Ideal para recalls e auditorias de qualidade.
    """
    try:
        return get_traceability(db, batch_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

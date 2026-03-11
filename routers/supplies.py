"""
E-08 — Rotas de Insumos Não-Alimentícios (Embalagens, Limpeza, EPI)
"""
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Supply
from services.supply_service import (
    get_critical_supplies,
    check_packaging_for_plan,
    consume_daily_supplies,
    TIPOS_BOM,
    TIPOS_DIARIO,
)

router = APIRouter(prefix="/supplies", tags=["Insumos Não-Alimentícios - E-08"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class SupplyCreate(BaseModel):
    nome: str
    tipo: str = "embalagem_primaria"
    unidade: str = "un"
    custo_atual: float = 0.0
    estoque_atual: float = 0.0
    estoque_minimo: float = 0.0
    lead_time_dias: int = 0
    consumo_por_lote: float = 0.0
    consumo_diario_fixo: float = 0.0


class SupplyResponse(BaseModel):
    id: uuid.UUID
    nome: str
    tipo: str
    unidade: Optional[str]
    custo_atual: float
    estoque_atual: float
    estoque_minimo: float
    lead_time_dias: int
    consumo_por_lote: float
    consumo_diario_fixo: float

    model_config = {"from_attributes": True}


class CriticalSupplyItem(BaseModel):
    supply_id: str
    nome: str
    tipo: str
    unidade: Optional[str]
    estoque_atual: float
    consumo_diario_estimado: float
    dias_cobertura: float
    lead_time_dias: int
    lead_time_critico: bool
    threshold_alerta_dias: int
    urgencia_dias_restantes: float
    custo_reposicao_estimado: float


class DailyConsumeResponse(BaseModel):
    operadores: int
    supplies_atualizados: int
    detalhe: list


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/", response_model=SupplyResponse, status_code=201)
def create_supply(payload: SupplyCreate, db: Session = Depends(get_db)):
    """Cadastra um novo supply não-alimentício."""
    valid_tipos = TIPOS_BOM | TIPOS_DIARIO | {"outros"}
    if payload.tipo not in valid_tipos:
        raise HTTPException(
            status_code=422,
            detail=f"tipo inválido. Use: {', '.join(sorted(valid_tipos))}"
        )
    sup = Supply(**payload.model_dump())
    db.add(sup)
    db.commit()
    db.refresh(sup)
    return sup


@router.get("/", response_model=List[SupplyResponse])
def list_supplies(
    tipo: Optional[str] = Query(default=None, description="Filtrar por tipo"),
    db: Session = Depends(get_db),
):
    """Lista todos os supplies, com filtro opcional por tipo."""
    q = db.query(Supply)
    if tipo:
        q = q.filter(Supply.tipo == tipo)
    return q.order_by(Supply.nome).all()


@router.get("/critical", response_model=List[CriticalSupplyItem])
def critical_supplies(
    num_operadores: int = Query(default=2, ge=1, description="Número de operadores ativos"),
    db: Session = Depends(get_db),
):
    """
    Lista supplies em situação crítica de estoque, onde:
      dias_cobertura ≤ (lead_time + 3)

    Para lead_time > 10 dias, a antecedência de alerta é DOBRADA.
    Ordenado por urgência (mais crítico primeiro).
    """
    return get_critical_supplies(db, num_operadores=num_operadores)


@router.get("/{supply_id}", response_model=SupplyResponse)
def get_supply(supply_id: uuid.UUID, db: Session = Depends(get_db)):
    sup = db.query(Supply).filter(Supply.id == supply_id).first()
    if not sup:
        raise HTTPException(status_code=404, detail="Supply não encontrado")
    return sup


@router.patch("/{supply_id}/stock")
def update_stock(
    supply_id: uuid.UUID,
    qty: float = Query(..., description="Quantidade a adicionar (positivo) ou remover (negativo)"),
    db: Session = Depends(get_db),
):
    """Atualiza estoque de um supply manualmente."""
    sup = db.query(Supply).filter(Supply.id == supply_id).first()
    if not sup:
        raise HTTPException(status_code=404, detail="Supply não encontrado")
    sup.estoque_atual = max(0.0, (sup.estoque_atual or 0.0) + qty)
    db.commit()
    return {"supply_id": str(supply_id), "estoque_atual": sup.estoque_atual}


@router.post("/daily-consume", response_model=DailyConsumeResponse)
def trigger_daily_consume(
    num_operadores: int = Query(default=2, ge=1),
    db: Session = Depends(get_db),
):
    """
    Dispara manualmente o job diário de consumo de limpeza/EPI.
    Normalmente é executado automaticamente pelo scheduler às 23h59.
    """
    updated = consume_daily_supplies(db, num_operadores=num_operadores)
    return DailyConsumeResponse(
        operadores=num_operadores,
        supplies_atualizados=len(updated),
        detalhe=updated,
    )


@router.get("/packaging-check/{product_id}")
def check_packaging(
    product_id: uuid.UUID,
    qty_planejada: float = Query(..., gt=0),
    num_operadores: int = Query(default=2, ge=1),
    db: Session = Depends(get_db),
):
    """
    Integração com E-04: verifica embalagens e etiquetas necessárias
    para produzir qty_planejada unidades do produto.
    Retorna status ok/deficit por supply com antecedência de compra.
    """
    from models import Product
    if not db.query(Product).filter(Product.id == product_id).first():
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return check_packaging_for_plan(db, product_id, qty_planejada, num_operadores)

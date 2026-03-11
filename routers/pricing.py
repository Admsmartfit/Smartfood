"""
E-03 — Rotas de Precificação e Monitor de Margem
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
import uuid

from database import get_db
from models import Ingredient, BOMItem, Product
from cost_calculator import DEFAULT_LABOR_COST_PER_MIN
from services.margin_monitor import (
    recalculate_products_for_ingredient,
    suggest_new_price,
    get_margin_status,
)

router = APIRouter(tags=["Precificação - E-03"])


# --- Schemas locais ---

class PriceUpdateRequest(BaseModel):
    novo_preco: float
    motivo: Optional[str] = None  # ex: "NF-e recebida", "cotação atualizada"


class PriceUpdateResponse(BaseModel):
    ingredient_id: uuid.UUID
    ingredient_nome: str
    preco_anterior: float
    novo_preco: float
    produtos_afetados: int
    impacto: List[dict]


class SuggestPriceResponse(BaseModel):
    produto_id: uuid.UUID
    produto_nome: str
    margem_atual_pct: float
    margem_alvo_pct: float
    custo_total: float
    preco_atual_sugerido: float
    preco_minimo_sugerido: float
    novo_markup_sugerido: float


# --- Endpoints ---

@router.patch("/ingredients/{ingredient_id}/price", response_model=PriceUpdateResponse)
def update_ingredient_price(
    ingredient_id: uuid.UUID,
    payload: PriceUpdateRequest,
    db: Session = Depends(get_db),
):
    """
    Atualiza o custo atual de um ingrediente e dispara recálculo em cascata
    de todos os produtos que o utilizam na BOM.
    Retorna lista de produtos afetados com nova margem e status.
    """
    ingredient = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ingredient:
        raise HTTPException(status_code=404, detail="Ingrediente não encontrado")

    if payload.novo_preco < 0:
        raise HTTPException(status_code=422, detail="novo_preco não pode ser negativo")

    preco_anterior = ingredient.custo_atual or 0.0
    ingredient.custo_atual = payload.novo_preco
    db.flush()

    impacto = recalculate_products_for_ingredient(db, ingredient_id)

    return PriceUpdateResponse(
        ingredient_id=ingredient.id,
        ingredient_nome=ingredient.nome,
        preco_anterior=preco_anterior,
        novo_preco=payload.novo_preco,
        produtos_afetados=len(impacto),
        impacto=impacto,
    )


@router.get("/products/{product_id}/suggest-price", response_model=SuggestPriceResponse)
def suggest_price(
    product_id: uuid.UUID,
    target_margin_pct: float = Query(
        ...,
        ge=0.1,
        lt=100,
        description="Margem-alvo desejada em % (ex: 35 para 35%)"
    ),
    custo_labor_min: Optional[float] = Query(
        default=None,
        description=f"Custo de mão-de-obra por minuto em R$ (padrão: {DEFAULT_LABOR_COST_PER_MIN})"
    ),
    db: Session = Depends(get_db),
):
    """
    Retorna o preço mínimo de venda e o markup necessário para que o produto
    atinja a margem-alvo informada.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    bom_items = (
        db.query(BOMItem)
        .options(joinedload(BOMItem.ingredient), joinedload(BOMItem.supply))
        .filter(BOMItem.product_id == product_id)
        .all()
    )
    if not bom_items:
        raise HTTPException(
            status_code=422,
            detail="Produto sem Ficha Técnica (BOM). Cadastre via POST /products/{id}/bom"
        )

    labor = custo_labor_min if custo_labor_min is not None else DEFAULT_LABOR_COST_PER_MIN
    result = suggest_new_price(product, bom_items, target_margin_pct, custo_labor_min=labor)

    return SuggestPriceResponse(**result)

"""
E-02 — Rotas de Fichas Técnicas (BOM) e Cálculo de Custo
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional
import uuid

from database import get_db
from models import Product, BOMItem, Ingredient, Supply
from schemas import BOMCreate, BOMItemResponse, BOMResponse, CostCalculationResponse
from cost_calculator import calculate_product_cost, DEFAULT_LABOR_COST_PER_MIN

router = APIRouter(prefix="/products", tags=["Fichas Técnicas - BOM"])


def _get_product_or_404(product_id: uuid.UUID, db: Session) -> Product:
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")
    return product


# --- BOM CRUD ---

@router.post("/{product_id}/bom", response_model=BOMResponse, status_code=201)
def create_or_replace_bom(
    product_id: uuid.UUID,
    payload: BOMCreate,
    db: Session = Depends(get_db),
):
    """
    Define (ou substitui) a Ficha Técnica (BOM) de um produto.
    Cada item deve ter **ingredient_id** (insumo alimentício) ou **supply_id** (embalagem/insumo não-alimentício).
    """
    product = _get_product_or_404(product_id, db)

    # Valida que cada item aponta para exatamente um dos dois
    for idx, item in enumerate(payload.items):
        if item.ingredient_id is None and item.supply_id is None:
            raise HTTPException(
                status_code=422,
                detail=f"Item #{idx + 1}: informe ingredient_id ou supply_id"
            )
        if item.ingredient_id and item.supply_id:
            raise HTTPException(
                status_code=422,
                detail=f"Item #{idx + 1}: informe apenas ingredient_id OU supply_id, não ambos"
            )
        # Verifica existência no banco
        if item.ingredient_id:
            if not db.query(Ingredient).filter(Ingredient.id == item.ingredient_id).first():
                raise HTTPException(status_code=404, detail=f"Ingrediente {item.ingredient_id} não encontrado")
        if item.supply_id:
            if not db.query(Supply).filter(Supply.id == item.supply_id).first():
                raise HTTPException(status_code=404, detail=f"Insumo/Supply {item.supply_id} não encontrado")

    # Remove BOM anterior
    db.query(BOMItem).filter(BOMItem.product_id == product_id).delete()

    # Insere novos itens
    new_items = []
    for item in payload.items:
        bom_item = BOMItem(
            product_id=product.id,
            ingredient_id=item.ingredient_id,
            supply_id=item.supply_id,
            quantidade=item.quantidade,
            unidade=item.unidade,
            perda_esperada_pct=item.perda_esperada_pct,
        )
        db.add(bom_item)
        new_items.append(bom_item)

    db.commit()
    for i in new_items:
        db.refresh(i)

    return BOMResponse(product_id=product.id, items=new_items)


@router.get("/{product_id}/bom", response_model=BOMResponse)
def get_bom(product_id: uuid.UUID, db: Session = Depends(get_db)):
    """Retorna a Ficha Técnica (BOM) de um produto."""
    _get_product_or_404(product_id, db)
    items = (
        db.query(BOMItem)
        .options(joinedload(BOMItem.ingredient), joinedload(BOMItem.supply))
        .filter(BOMItem.product_id == product_id)
        .all()
    )
    return BOMResponse(product_id=product_id, items=items)


@router.delete("/{product_id}/bom", status_code=204)
def delete_bom(product_id: uuid.UUID, db: Session = Depends(get_db)):
    """Remove toda a Ficha Técnica de um produto."""
    _get_product_or_404(product_id, db)
    db.query(BOMItem).filter(BOMItem.product_id == product_id).delete()
    db.commit()


# --- Cálculo de Custo ---

@router.get("/{product_id}/cost-calculation", response_model=CostCalculationResponse)
def cost_calculation(
    product_id: uuid.UUID,
    custo_labor_min: Optional[float] = Query(
        default=None,
        description=f"Custo de mão-de-obra por minuto em R$ (padrão: {DEFAULT_LABOR_COST_PER_MIN})"
    ),
    tempo_producao_min: Optional[float] = Query(
        default=None,
        description="Sobrescreve o tempo de produção do produto (minutos)"
    ),
    custo_energia: Optional[float] = Query(
        default=None,
        description="Sobrescreve o custo de energia por lote em R$"
    ),
    db: Session = Depends(get_db),
):
    """
    Calcula o custo detalhado do produto aplicando FC, FCoc, mão-de-obra e energia.

    Retorna: custo_insumos, custo_embalagem, custo_labor, custo_energia,
    custo_total, preco_sugerido, margem_pct e alertas de validação.
    """
    product = _get_product_or_404(product_id, db)

    bom_items = (
        db.query(BOMItem)
        .options(joinedload(BOMItem.ingredient), joinedload(BOMItem.supply))
        .filter(BOMItem.product_id == product_id)
        .all()
    )

    if not bom_items:
        raise HTTPException(
            status_code=422,
            detail="Produto não possui Ficha Técnica. Cadastre a BOM primeiro via POST /products/{id}/bom"
        )

    result = calculate_product_cost(
        product=product,
        bom_items=bom_items,
        custo_labor_min=custo_labor_min if custo_labor_min is not None else DEFAULT_LABOR_COST_PER_MIN,
        tempo_producao_min=tempo_producao_min,
        custo_energia=custo_energia,
    )

    return CostCalculationResponse(**result)

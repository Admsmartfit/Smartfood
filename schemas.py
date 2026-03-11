from pydantic import BaseModel, field_validator
from typing import Optional, List
import uuid


# --- BOM Schemas ---

class BOMItemCreate(BaseModel):
    ingredient_id: Optional[uuid.UUID] = None
    supply_id: Optional[uuid.UUID] = None
    quantidade: float
    unidade: str
    perda_esperada_pct: float = 0.0

    @field_validator("quantidade")
    @classmethod
    def quantidade_positiva(cls, v):
        if v <= 0:
            raise ValueError("quantidade deve ser maior que zero")
        return v


class BOMCreate(BaseModel):
    items: List[BOMItemCreate]


class BOMItemResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    ingredient_id: Optional[uuid.UUID] = None
    supply_id: Optional[uuid.UUID] = None
    quantidade: float
    unidade: str
    perda_esperada_pct: float

    model_config = {"from_attributes": True}


class BOMResponse(BaseModel):
    product_id: uuid.UUID
    items: List[BOMItemResponse]


# --- Cost Calculation Schemas ---

class CostCalculationResponse(BaseModel):
    produto_id: uuid.UUID
    produto_nome: str
    fc: float
    fcoc: float
    custo_insumos: float
    custo_embalagem: float
    custo_labor: float
    custo_energia: float
    custo_total: float
    markup: float
    preco_sugerido: float
    margem_pct: float
    margem_minima: float
    alertas: List[str]


# --- Product Schemas (criação básica para seed/testes) ---

class ProductCreate(BaseModel):
    nome: str
    sku: Optional[str] = None
    categoria: Optional[str] = None
    fc: float = 1.0
    fcoc: float = 1.0
    markup: float = 1.0
    margem_minima: float = 0.0
    tempo_producao_min: float = 30.0
    custo_energia: float = 0.50


class IngredientCreate(BaseModel):
    nome: str
    unidade: str = "kg"
    fc_medio: float = 1.0
    custo_atual: float = 0.0
    estoque_minimo: float = 0.0
    lead_time_dias: int = 0


class SupplyCreate(BaseModel):
    nome: str
    tipo: str = "embalagem"
    unidade: str = "un"
    custo_atual: float = 0.0
    estoque_minimo: float = 0.0
    lead_time_dias: int = 0
    consumo_por_lote: float = 0.0

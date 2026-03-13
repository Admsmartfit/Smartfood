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


# --- Ingredient Schemas ---

class IngredientCreate(BaseModel):
    nome: str
    unidade: str = "kg"
    fc_medio: float = 1.0
    custo_atual: float = 0.0
    estoque_atual: float = 0.0
    estoque_minimo: float = 0.0
    lead_time_dias: int = 0
    ativo: bool = True


class IngredientUpdate(BaseModel):
    nome: Optional[str] = None
    unidade: Optional[str] = None
    fc_medio: Optional[float] = None
    custo_atual: Optional[float] = None
    estoque_atual: Optional[float] = None
    estoque_minimo: Optional[float] = None
    lead_time_dias: Optional[int] = None
    ativo: Optional[bool] = None


class IngredientResponse(BaseModel):
    id: uuid.UUID
    nome: str
    unidade: str
    fc_medio: float
    custo_atual: float
    estoque_atual: float
    estoque_minimo: float
    lead_time_dias: int
    ativo: bool

    model_config = {"from_attributes": True}


# --- Product Schemas ---

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
    rendimento_por_lote: float = 1.0
    modo_preparo_interno: Optional[str] = None
    ativo: bool = True
    # E-21
    peso_porcao_gramas: Optional[float] = None
    unidade_estoque: str = "unid"


class ProductUpdate(BaseModel):
    nome: Optional[str] = None
    sku: Optional[str] = None
    categoria: Optional[str] = None
    fc: Optional[float] = None
    fcoc: Optional[float] = None
    markup: Optional[float] = None
    margem_minima: Optional[float] = None
    tempo_producao_min: Optional[float] = None
    custo_energia: Optional[float] = None
    rendimento_por_lote: Optional[float] = None
    modo_preparo_interno: Optional[str] = None
    ativo: Optional[bool] = None
    peso_porcao_gramas: Optional[float] = None
    unidade_estoque: Optional[str] = None


class ProductResponse(BaseModel):
    id: uuid.UUID
    nome: str
    sku: Optional[str] = None
    categoria: Optional[str] = None
    fc: float
    fcoc: float
    markup: float
    margem_minima: float
    tempo_producao_min: float
    custo_energia: float
    rendimento_por_lote: float
    modo_preparo_interno: Optional[str] = None
    ativo: bool
    peso_porcao_gramas: Optional[float] = None
    unidade_estoque: str = "unid"

    model_config = {"from_attributes": True}


# --- YieldHistory Schemas ---

class YieldHistoryCreate(BaseModel):
    batch_id: uuid.UUID
    product_id: uuid.UUID
    peso_bruto_kg: Optional[float] = None
    peso_limpo_kg: Optional[float] = None
    peso_final_kg: Optional[float] = None
    porcoes_esperadas: Optional[float] = None
    porcoes_reais: Optional[float] = None
    peso_porcao_gramas_configurado: Optional[float] = None
    sobra_gramas: Optional[float] = None
    custo_total_lote: Optional[float] = None
    custo_por_porcao_real: Optional[float] = None
    alerta_erosao_margem: bool = False
    operador_id: Optional[str] = None


class YieldHistoryResponse(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    product_id: uuid.UUID
    fc_real: Optional[float] = None
    fcoc_real: Optional[float] = None
    porcoes_esperadas: Optional[float] = None
    porcoes_reais: Optional[float] = None
    sobra_gramas: Optional[float] = None
    custo_por_porcao_real: Optional[float] = None
    alerta_erosao_margem: bool

    model_config = {"from_attributes": True}


# --- Supply Schemas ---

class SupplyCreate(BaseModel):
    nome: str
    tipo: str = "embalagem"
    unidade: str = "un"
    custo_atual: float = 0.0
    estoque_minimo: float = 0.0
    lead_time_dias: int = 0
    consumo_por_lote: float = 0.0
    ativo: bool = True


class SupplyUpdate(BaseModel):
    nome: Optional[str] = None
    tipo: Optional[str] = None
    unidade: Optional[str] = None
    custo_atual: Optional[float] = None
    estoque_minimo: Optional[float] = None
    lead_time_dias: Optional[int] = None
    consumo_por_lote: Optional[float] = None
    ativo: Optional[bool] = None


class SupplyResponse(BaseModel):
    id: uuid.UUID
    nome: str
    tipo: str
    unidade: str
    custo_atual: float
    estoque_minimo: float
    lead_time_dias: int
    consumo_por_lote: float
    ativo: bool

    model_config = {"from_attributes": True}


# --- User Schemas ---

class UserCreate(BaseModel):
    nome: str
    email: str
    perfil: str = "operador"
    pin_code: Optional[str] = None
    ativo: bool = True


class UserUpdate(BaseModel):
    nome: Optional[str] = None
    email: Optional[str] = None
    perfil: Optional[str] = None
    pin_code: Optional[str] = None
    ativo: Optional[bool] = None


class UserResponse(BaseModel):
    id: uuid.UUID
    nome: str
    email: str
    perfil: str
    pin_code: Optional[str] = None
    ativo: bool

    model_config = {"from_attributes": True}


# --- BatchIngredientUsage Schemas ---

class BatchIngredientUsageCreate(BaseModel):
    ingredient_id: Optional[uuid.UUID] = None
    supply_id: Optional[uuid.UUID] = None
    quantidade_real: float
    quantidade_planejada: float = 0.0
    motivo_desvio: Optional[str] = None

    @field_validator("ingredient_id", "supply_id", mode="before")
    @classmethod
    def pelo_menos_um_fk(cls, v):
        return v  # cross-field validation handled at API layer

    @field_validator("quantidade_real")
    @classmethod
    def quantidade_real_positiva(cls, v):
        if v < 0:
            raise ValueError("quantidade_real não pode ser negativa")
        return v


class BatchIngredientUsageResponse(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    ingredient_id: Optional[uuid.UUID] = None
    supply_id: Optional[uuid.UUID] = None
    quantidade_real: float
    quantidade_planejada: float
    motivo_desvio: Optional[str] = None

    model_config = {"from_attributes": True}

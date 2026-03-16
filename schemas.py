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
    perda_processo_kg: float = 0.0

    @field_validator("quantidade")
    @classmethod
    def quantidade_positiva(cls, v):
        if v <= 0:
            raise ValueError("quantidade deve ser maior que zero")
        return v


class BOMCreate(BaseModel):
    items: List[BOMItemCreate]


class RecipeSectionCreate(BaseModel):
    product_id: uuid.UUID
    nome: str
    ordem: int = 1
    peso_final_esperado_kg: Optional[float] = None


class RecipeSectionUpdate(BaseModel):
    nome: Optional[str] = None
    ordem: Optional[int] = None
    peso_final_esperado_kg: Optional[float] = None


class RecipeSectionResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    nome: str
    ordem: int
    peso_final_esperado_kg: Optional[float] = None

    model_config = {"from_attributes": True}


class BOMItemResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    ingredient_id: Optional[uuid.UUID] = None
    supply_id: Optional[uuid.UUID] = None
    section_id: Optional[uuid.UUID] = None
    quantidade: float
    unidade: str
    perda_esperada_pct: float
    perda_processo_kg: float = 0.0

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
    peso_bruto_padrao: Optional[float] = None
    peso_limpo_padrao: Optional[float] = None
    custo_atual: float = 0.0
    estoque_atual: float = 0.0
    estoque_minimo: float = 0.0
    lead_time_dias: int = 0
    ativo: bool = True


class IngredientUpdate(BaseModel):
    nome: Optional[str] = None
    unidade: Optional[str] = None
    fc_medio: Optional[float] = None
    peso_bruto_padrao: Optional[float] = None
    peso_limpo_padrao: Optional[float] = None
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
    peso_bruto_padrao: Optional[float] = None
    peso_limpo_padrao: Optional[float] = None
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


# ─── Category Schemas ──────────────────────────────────────────────────────────

class CategoryCreate(BaseModel):
    nome: str
    tipo: str = "Insumo"


class CategoryUpdate(BaseModel):
    nome: Optional[str] = None
    tipo: Optional[str] = None


class CategoryResponse(BaseModel):
    id: uuid.UUID
    nome: str
    tipo: str

    model_config = {"from_attributes": True}


# ─── IngredientManufacturer Schemas ───────────────────────────────────────────

class IngredientManufacturerCreate(BaseModel):
    ingredient_id: uuid.UUID
    nome_fabricante: str
    percentual_rendimento: float = 100.0
    pontuacao_qualidade: int = 3

    @field_validator("pontuacao_qualidade")
    @classmethod
    def qualidade_range(cls, v: int) -> int:
        if not (1 <= v <= 5):
            raise ValueError("pontuacao_qualidade deve estar entre 1 e 5")
        return v

    @field_validator("percentual_rendimento")
    @classmethod
    def rendimento_range(cls, v: float) -> float:
        if not (0.0 <= v <= 100.0):
            raise ValueError("percentual_rendimento deve estar entre 0 e 100")
        return v


class IngredientManufacturerUpdate(BaseModel):
    nome_fabricante: Optional[str] = None
    percentual_rendimento: Optional[float] = None
    pontuacao_qualidade: Optional[int] = None


class IngredientManufacturerResponse(BaseModel):
    id: uuid.UUID
    ingredient_id: uuid.UUID
    nome_fabricante: str
    percentual_rendimento: float
    pontuacao_qualidade: int

    model_config = {"from_attributes": True}


# ─── SupplierIngredient Schemas ───────────────────────────────────────────────

class SupplierIngredientCreate(BaseModel):
    supplier_id: uuid.UUID
    ingredient_id: uuid.UUID
    ingredient_manufacturer_id: Optional[uuid.UUID] = None
    preco_ultima_compra: Optional[float] = None


class SupplierIngredientUpdate(BaseModel):
    ingredient_manufacturer_id: Optional[uuid.UUID] = None
    preco_ultima_compra: Optional[float] = None


class SupplierIngredientResponse(BaseModel):
    id: uuid.UUID
    supplier_id: uuid.UUID
    ingredient_id: uuid.UUID
    ingredient_manufacturer_id: Optional[uuid.UUID] = None
    preco_ultima_compra: Optional[float] = None

    model_config = {"from_attributes": True}


# ─── Equipment Schemas ────────────────────────────────────────────────────────

class EquipmentCreate(BaseModel):
    nome: str
    descricao: Optional[str] = None
    ativo: bool = True


class EquipmentUpdate(BaseModel):
    nome: Optional[str] = None
    descricao: Optional[str] = None
    ativo: Optional[bool] = None


class EquipmentResponse(BaseModel):
    id: uuid.UUID
    nome: str
    descricao: Optional[str] = None
    ativo: bool

    model_config = {"from_attributes": True}


# ─── EquipmentParameter Schemas ───────────────────────────────────────────────

class EquipmentParameterCreate(BaseModel):
    equipment_id: uuid.UUID
    nome_parametro: str
    valor_padrao: Optional[str] = None
    unidade_medida: Optional[str] = None


class EquipmentParameterUpdate(BaseModel):
    nome_parametro: Optional[str] = None
    valor_padrao: Optional[str] = None
    unidade_medida: Optional[str] = None


class EquipmentParameterResponse(BaseModel):
    id: uuid.UUID
    equipment_id: uuid.UUID
    nome_parametro: str
    valor_padrao: Optional[str] = None
    unidade_medida: Optional[str] = None

    model_config = {"from_attributes": True}


# ─── BOMEquipment Schemas ─────────────────────────────────────────────────────

class BOMEquipmentCreate(BaseModel):
    product_id: uuid.UUID
    equipment_id: uuid.UUID
    parametros_json: Optional[dict] = None
    perda_processo_kg: float = 0.0


class BOMEquipmentUpdate(BaseModel):
    parametros_json: Optional[dict] = None
    perda_processo_kg: Optional[float] = None


class BOMEquipmentResponse(BaseModel):
    id: uuid.UUID
    product_id: uuid.UUID
    equipment_id: uuid.UUID
    parametros_json: Optional[dict] = None
    perda_processo_kg: float

    model_config = {"from_attributes": True}


# ─── FinancialExpense Schemas ──────────────────────────────────────────────────

from datetime import datetime as _dt

class FinancialExpenseCreate(BaseModel):
    descricao: str
    categoria_despesa: str = "Outros"
    valor: float
    data_competencia: _dt
    data_vencimento: Optional[_dt] = None
    status_pagamento: str = "pendente"

    @field_validator("valor")
    @classmethod
    def valor_positivo(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("valor deve ser maior que zero")
        return v

    @field_validator("status_pagamento")
    @classmethod
    def status_valido(cls, v: str) -> str:
        if v not in ("pendente", "pago", "vencido"):
            raise ValueError("status_pagamento deve ser: pendente, pago ou vencido")
        return v


class FinancialExpenseUpdate(BaseModel):
    descricao: Optional[str] = None
    categoria_despesa: Optional[str] = None
    valor: Optional[float] = None
    data_competencia: Optional[_dt] = None
    data_vencimento: Optional[_dt] = None
    status_pagamento: Optional[str] = None


class FinancialExpenseResponse(BaseModel):
    id: uuid.UUID
    descricao: str
    categoria_despesa: str
    valor: float
    data_competencia: _dt
    data_vencimento: Optional[_dt] = None
    status_pagamento: str

    model_config = {"from_attributes": True}

"""
E-10 — Rotas de Recebimento com Balança e Validação de NF-e XML
"""
from datetime import datetime
from typing import Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database import get_db
from services.nfe_service import (
    parse_nfe_xml,
    validate_weight_divergence,
    receive_nfe_full,
    DEFAULT_TOLERANCE_PCT,
)

router = APIRouter(prefix="/receiving", tags=["Recebimento NF-e - E-10"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class WeightValidationRequest(BaseModel):
    peso_balanca: float
    peso_nf: float
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT

    @field_validator("peso_balanca", "peso_nf")
    @classmethod
    def pesos_positivos(cls, v: float) -> float:
        if v < 0:
            raise ValueError("Pesos não podem ser negativos")
        return v


class NFeParseRequest(BaseModel):
    nfe_xml: str


class NFeReceiveRequest(BaseModel):
    nfe_xml: str
    peso_balanca_total: Optional[float] = None
    ingredient_map: Dict[str, str]          # {codigo_nfe: ingredient_id (str UUID)}
    data_validade_map: Optional[Dict[str, datetime]] = None  # {ingredient_id: datetime}
    numero_lote_prefix: str = "NF"
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT
    fornecedor_whatsapp: Optional[str] = None
    fornecedor_email: Optional[str] = None


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/validate-weight")
def validate_weight(payload: WeightValidationRequest):
    """
    Valida divergência entre peso da balança e peso declarado na NF-e.
    Tolerância padrão: ±0.5% (configurável).
    Retorna: divergencia_kg, divergencia_pct, dentro_tolerancia, acao_recomendada.
    """
    return validate_weight_divergence(
        payload.peso_balanca,
        payload.peso_nf,
        payload.tolerance_pct,
    )


@router.post("/parse-nfe")
def parse_nfe(payload: NFeParseRequest):
    """
    Parseia NF-e XML (padrão SEFAZ v4.0) e retorna estrutura extraída:
    cabeçalho, emitente, lista de itens com qtd/preço e totais de peso.
    Útil para preview antes de confirmar o recebimento.
    """
    result = parse_nfe_xml(payload.nfe_xml)
    if not result.get("raw_ok"):
        raise HTTPException(
            status_code=422,
            detail=f"Falha ao parsear NF-e XML: {result.get('erro', 'erro desconhecido')}"
        )
    return result


@router.post("/nfe-full")
def receive_full_nfe(payload: NFeReceiveRequest, db: Session = Depends(get_db)):
    """
    Recebimento completo de NF-e com múltiplos insumos.

    1. Parseia o XML e extrai todos os itens
    2. Valida divergência de peso total (balança vs NF-e)
    3. Para cada item do ingredient_map, cria lote e atualiza estoque
    4. Se divergência > tolerância: gera alerta e notifica fornecedor automaticamente

    **ingredient_map**: dicionário `{codigo_produto_nfe: ingredient_id}` para mapear
    itens da NF-e ao ingrediente correspondente no sistema.

    **Exemplo:**
    ```json
    {
      "nfe_xml": "<?xml...",
      "peso_balanca_total": 147.8,
      "ingredient_map": {"001": "uuid-do-frango", "002": "uuid-do-oleo"},
      "data_validade_map": {"uuid-do-frango": "2025-06-30T00:00:00"}
    }
    ```
    """
    # Converte ingredient_map de str→str para str→UUID
    try:
        ing_map = {k: uuid.UUID(v) for k, v in payload.ingredient_map.items()}
    except ValueError as e:
        raise HTTPException(status_code=422, detail=f"ingredient_map inválido: {e}")

    # Converte data_validade_map
    dv_map = {}
    if payload.data_validade_map:
        dv_map = {k: v for k, v in payload.data_validade_map.items()}

    result = receive_nfe_full(
        db=db,
        nfe_xml=payload.nfe_xml,
        peso_balanca_total=payload.peso_balanca_total,
        ingredient_map=ing_map,
        numero_lote_prefix=payload.numero_lote_prefix,
        data_validade_map=dv_map,
        tolerance_pct=payload.tolerance_pct,
        fornecedor_whatsapp=payload.fornecedor_whatsapp,
        fornecedor_email=payload.fornecedor_email,
    )

    if not result.get("sucesso"):
        raise HTTPException(
            status_code=422,
            detail=result.get("erro", "Falha no recebimento")
        )

    return result

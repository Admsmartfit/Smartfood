"""
E-05 — Rotas de Previsão de Demanda com Sazonalidade Avançada
"""
from datetime import datetime
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database import get_db
from models import Product, SeasonalEvent
from services.seasonal_forecaster import (
    seasonal_forecast,
    detect_holidays,
    auto_select_model,
    DemandAnalyzer,
    DEFAULT_SEASONALITY_FACTORS,
    DIAS_SEMANA,
)

router = APIRouter(prefix="/seasonality", tags=["Sazonalidade - E-05"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class ForecastDayItem(BaseModel):
    data: str
    dia_semana: str
    tipo_dia: str
    fator_aplicado: float
    quantidade_prevista: float


class PicoItem(BaseModel):
    data: str
    dia_semana: str
    quantidade: float
    fator: float


class SeasonalForecastResponse(BaseModel):
    product_id: str
    horizon_days: int
    historico_disponivel_dias: int
    modelo_usado: str
    total_previsto: float
    media_diaria_prevista: float
    confianca_pct: float
    proximos_picos_identificados: List[PicoItem]
    previsao_por_dia: List[ForecastDayItem]


class CustomEventRequest(BaseModel):
    nome: str
    data_inicio: datetime
    data_fim: datetime
    fator_multiplicador: float
    produto_id: Optional[uuid.UUID] = None

    @field_validator("fator_multiplicador")
    @classmethod
    def fator_valido(cls, v: float) -> float:
        if v <= 0:
            raise ValueError("fator_multiplicador deve ser maior que zero")
        return v

    @field_validator("data_fim")
    @classmethod
    def fim_apos_inicio(cls, v: datetime, info) -> datetime:
        if "data_inicio" in info.data and v < info.data["data_inicio"]:
            raise ValueError("data_fim deve ser posterior a data_inicio")
        return v


class CustomEventResponse(BaseModel):
    id: uuid.UUID
    nome: str
    data_inicio: str
    data_fim: str
    fator_multiplicador: float
    produto_id: Optional[uuid.UUID]
    ativo: bool

    model_config = {"from_attributes": True}


class SeasonalityFactorsResponse(BaseModel):
    product_id: str
    fonte: str
    fatores_por_dia: dict


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/products/{product_id}/forecast", response_model=SeasonalForecastResponse)
def get_seasonal_forecast(
    product_id: uuid.UUID,
    days: int = Query(default=14, ge=1, le=90, description="Horizonte de previsão em dias"),
    model: Optional[str] = Query(
        default=None,
        description="Força modelo: media_movel_ponderada | holt_winters | regressao_linear_sazonal"
    ),
    db: Session = Depends(get_db),
):
    """
    E-05 — Previsão de demanda com seleção automática de modelo.

    Seleciona automaticamente o melhor modelo baseado no tamanho do histórico:
    - < 90 dias  → Média Móvel Ponderada (7d×50% + 30d×30% + 90d×20%)
    - 90-179 dias → Holt-Winters (captura tendência + sazonalidade semanal)
    - ≥ 180 dias  → Regressão Linear com Dummies Sazonais

    Aplica fator sazonal por dia da semana (do histórico ou padrão PRD E-05.2)
    e sobrescreve com eventos especiais cadastrados.

    Retorna: modelo_usado, previsao_por_dia, total_previsto,
             confianca_pct, proximos_picos_identificados.
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    valid_models = {"media_movel_ponderada", "holt_winters", "regressao_linear_sazonal", None}
    if model not in valid_models:
        raise HTTPException(
            status_code=422,
            detail=f"Modelo inválido. Use: {', '.join(m for m in valid_models if m)}"
        )

    result = seasonal_forecast(db, product_id, days=days, model_override=model)
    return SeasonalForecastResponse(**result)


@router.get("/products/{product_id}/seasonality-factors", response_model=SeasonalityFactorsResponse)
def get_seasonality_factors(
    product_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    """
    Retorna os fatores de sazonalidade calculados do histórico.
    Se histórico insuficiente, retorna os fatores padrão do PRD (E-05.2).
    """
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=404, detail="Produto não encontrado")

    analyzer = DemandAnalyzer()
    fatores = analyzer.get_seasonality_factors(db, product_id)

    # Verifica se veio do histórico ou dos defaults
    default_vals = {DIAS_SEMANA[wd]: f for wd, f in DEFAULT_SEASONALITY_FACTORS.items()}
    fonte = "padrao_prd" if fatores == default_vals else "historico_calculado"

    return SeasonalityFactorsResponse(
        product_id=str(product_id),
        fonte=fonte,
        fatores_por_dia=fatores,
    )


@router.get("/model-selection")
def explain_model_selection(
    history_days: int = Query(..., ge=0, description="Dias de histórico disponível"),
):
    """
    Explica qual modelo seria selecionado para um dado tamanho de histórico.
    Útil para o gestor entender a lógica de seleção automática.
    """
    model = auto_select_model(history_days)
    descriptions = {
        "media_movel_ponderada": {
            "modelo": model,
            "precisao_esperada": "±15-25% de erro médio",
            "quando_usar": "Histórico < 90 dias ou demanda relativamente estável",
            "parametros": "Pesos: 7d=50%, 30d=30%, 90d=20%",
        },
        "holt_winters": {
            "modelo": model,
            "precisao_esperada": "±10-18% de erro médio",
            "quando_usar": "Histórico ≥ 90 dias com variação semanal visível",
            "parametros": "alpha=0.3 (nível), beta=0.1 (tendência), gamma=0.3 (sazonalidade)",
        },
        "regressao_linear_sazonal": {
            "modelo": model,
            "precisao_esperada": "±12-20% de erro médio",
            "quando_usar": "Histórico ≥ 180 dias, necessidade de explicabilidade",
            "parametros": "OLS com dummies por dia da semana + tendência linear",
        },
    }
    return {"history_days": history_days, **descriptions[model]}


@router.post("/custom-event", response_model=CustomEventResponse, status_code=201)
def create_custom_event(payload: CustomEventRequest, db: Session = Depends(get_db)):
    """
    Registra um evento especial com fator multiplicador manual.
    Exemplos: Copa do Mundo (×2.8), show local (×2.0), feriado regional (×1.8).
    O produto_id é opcional — se omitido, aplica-se a todos os produtos.
    """
    if payload.produto_id:
        product = db.query(Product).filter(Product.id == payload.produto_id).first()
        if not product:
            raise HTTPException(status_code=404, detail="Produto não encontrado")

    event = SeasonalEvent(
        nome=payload.nome,
        data_inicio=payload.data_inicio,
        data_fim=payload.data_fim,
        fator_multiplicador=payload.fator_multiplicador,
        produto_id=payload.produto_id,
        ativo=True,
    )
    db.add(event)
    db.commit()
    db.refresh(event)

    return CustomEventResponse(
        id=event.id,
        nome=event.nome,
        data_inicio=event.data_inicio.isoformat(),
        data_fim=event.data_fim.isoformat(),
        fator_multiplicador=event.fator_multiplicador,
        produto_id=event.produto_id,
        ativo=event.ativo,
    )


@router.get("/custom-events", response_model=List[CustomEventResponse])
def list_custom_events(
    apenas_ativos: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    """Lista eventos especiais cadastrados."""
    q = db.query(SeasonalEvent)
    if apenas_ativos:
        q = q.filter(SeasonalEvent.ativo == True)
    events = q.order_by(SeasonalEvent.data_inicio).all()
    return [
        CustomEventResponse(
            id=ev.id,
            nome=ev.nome,
            data_inicio=ev.data_inicio.isoformat(),
            data_fim=ev.data_fim.isoformat(),
            fator_multiplicador=ev.fator_multiplicador,
            produto_id=ev.produto_id,
            ativo=ev.ativo,
        )
        for ev in events
    ]


@router.delete("/custom-events/{event_id}", status_code=204)
def deactivate_custom_event(event_id: uuid.UUID, db: Session = Depends(get_db)):
    """Desativa (soft-delete) um evento especial."""
    event = db.query(SeasonalEvent).filter(SeasonalEvent.id == event_id).first()
    if not event:
        raise HTTPException(status_code=404, detail="Evento não encontrado")
    event.ativo = False
    db.commit()


@router.get("/holidays")
def check_holiday(
    check_date: str = Query(..., description="Data no formato YYYY-MM-DD"),
):
    """Verifica se uma data é feriado nacional brasileiro."""
    try:
        from datetime import date as date_type
        d = date_type.fromisoformat(check_date)
    except ValueError:
        raise HTTPException(status_code=422, detail="Formato de data inválido. Use YYYY-MM-DD")

    is_hol = detect_holidays(d)
    return {
        "data": check_date,
        "dia_semana": DIAS_SEMANA[d.weekday()],
        "feriado": is_hol,
        "fator_padrao_prd": 1.8 if is_hol else DEFAULT_SEASONALITY_FACTORS.get(d.weekday(), 1.0),
    }

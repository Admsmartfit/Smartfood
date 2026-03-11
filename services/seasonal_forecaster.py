"""
E-05 — Previsão de Demanda por Histórico e Sazonalidade

Implementa 3 modelos de previsão com seleção automática baseada no histórico:
  1. Média Móvel Ponderada   (< 90 dias de histórico)
  2. Holt-Winters            (>= 90 dias, variação semanal visível)
  3. Regressão Linear Sazonal(>= 180 dias, máxima explicabilidade)

Integra `python-holidays` para feriados brasileiros com fallback embutido.
"""
import logging
import math
import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy.orm import Session

logger = logging.getLogger("seasonal_forecaster")

# Fatores padrão do PRD quando não há histórico suficiente (E-05.2)
DEFAULT_SEASONALITY_FACTORS: dict[int, float] = {
    0: 1.0,   # Segunda
    1: 1.0,   # Terça
    2: 1.0,   # Quarta
    3: 1.0,   # Quinta
    4: 1.6,   # Sexta
    5: 2.1,   # Sábado
    6: 1.4,   # Domingo
}
DEFAULT_HOLIDAY_FACTOR = 1.8
DEFAULT_EVE_FACTOR = 2.0   # véspera de feriado

DIAS_SEMANA = ["segunda", "terça", "quarta", "quinta", "sexta", "sábado", "domingo"]

# ─────────────────────────────────────────────────────────────────────────────
# Detecção de Feriados
# ─────────────────────────────────────────────────────────────────────────────

try:
    import holidays as _holidays_lib
    _BR_HOLIDAYS = _holidays_lib.Brazil()
    def _is_holiday(d: date) -> bool:
        return d in _BR_HOLIDAYS
except ImportError:
    logger.warning("python-holidays não instalado. Usando lista de feriados embutida.")
    _FIXED_HOLIDAYS = {
        (1, 1), (4, 21), (5, 1), (9, 7),
        (10, 12), (11, 2), (11, 15), (12, 25),
    }
    def _is_holiday(d: date) -> bool:
        return (d.month, d.day) in _FIXED_HOLIDAYS


def detect_holidays(d: date) -> bool:
    """Retorna True se a data é feriado nacional brasileiro."""
    return _is_holiday(d)


def _day_type(d: date) -> str:
    """Classifica data: feriado | vespera_feriado | fim_de_semana | dia_util."""
    if _is_holiday(d):
        return "feriado"
    if _is_holiday(d + timedelta(days=1)):
        return "vespera_feriado"
    if d.weekday() >= 5:
        return "fim_de_semana"
    return "dia_util"


def _default_factor_for_date(d: date) -> float:
    """Fator sazonal padrão do PRD para uma data (sem histórico)."""
    if _is_holiday(d):
        return DEFAULT_HOLIDAY_FACTOR
    if _is_holiday(d + timedelta(days=1)):
        return DEFAULT_EVE_FACTOR
    return DEFAULT_SEASONALITY_FACTORS.get(d.weekday(), 1.0)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de agregação
# ─────────────────────────────────────────────────────────────────────────────

def _aggregate_daily(events) -> dict[date, float]:
    agg: dict[date, float] = defaultdict(float)
    for ev in events:
        day = ev.data_pedido.date() if hasattr(ev.data_pedido, "date") else ev.data_pedido
        agg[day] += ev.quantidade
    return dict(agg)


def _fetch_events(db: Session, product_id: uuid.UUID, days: int = 365):
    from models import DemandEvent
    since = datetime.now(timezone.utc) - timedelta(days=days)
    return (
        db.query(DemandEvent)
        .filter(DemandEvent.produto_id == product_id, DemandEvent.data_pedido >= since)
        .all()
    )


# ─────────────────────────────────────────────────────────────────────────────
# DemandAnalyzer
# ─────────────────────────────────────────────────────────────────────────────

class DemandAnalyzer:
    """Analisa histórico de demand_events e extrai fatores de sazonalidade."""

    def get_seasonality_factors(
        self, db: Session, product_id: uuid.UUID
    ) -> dict[str, float]:
        """
        Retorna fator multiplicador por dia da semana calculado do histórico.
        Fallback para os valores padrão do PRD (E-05.2) quando dados insuficientes.
        """
        events = _fetch_events(db, product_id, days=180)
        daily = _aggregate_daily(events)

        if len(daily) < 14:
            logger.info("Histórico insuficiente — usando fatores padrão do PRD")
            return {DIAS_SEMANA[wd]: f for wd, f in DEFAULT_SEASONALITY_FACTORS.items()}

        media_geral = statistics.mean(daily.values())
        if media_geral == 0:
            return {DIAS_SEMANA[wd]: 1.0 for wd in range(7)}

        weekday_vals: dict[int, list[float]] = defaultdict(list)
        for d, qty in daily.items():
            weekday_vals[d.weekday()].append(qty)

        fatores = {}
        for wd in range(7):
            if weekday_vals[wd]:
                avg = statistics.mean(weekday_vals[wd])
                fatores[DIAS_SEMANA[wd]] = round(avg / media_geral, 3)
            else:
                fatores[DIAS_SEMANA[wd]] = DEFAULT_SEASONALITY_FACTORS.get(wd, 1.0)

        return fatores

    def weighted_moving_average(
        self,
        series: list[float],
        weights: list[float] = None,
        window_sizes: list[int] = None,
    ) -> float:
        """
        Média móvel ponderada para janelas de 7, 30 e 90 dias.
        weights=[0.5, 0.3, 0.2] por padrão.
        """
        if weights is None:
            weights = [0.5, 0.3, 0.2]
        if window_sizes is None:
            window_sizes = [7, 30, 90]

        if not series:
            return 0.0

        avgs = []
        for w in window_sizes:
            window = series[-w:] if len(series) >= w else series
            avgs.append(statistics.mean(window) if window else 0.0)

        # Normaliza pesos para a quantidade de janelas disponíveis
        n = min(len(avgs), len(weights))
        total_w = sum(weights[:n])
        wma = sum(avgs[i] * weights[i] / total_w for i in range(n))
        return wma


# ─────────────────────────────────────────────────────────────────────────────
# Holt-Winters (Triple Exponential Smoothing)
# ─────────────────────────────────────────────────────────────────────────────

class HoltWinters:
    """
    Suavização Exponencial de Holt-Winters com tendência e sazonalidade multiplicativa.
    Adequado para séries com padrão semanal definido (period=7).
    """

    def __init__(self, alpha: float = 0.3, beta: float = 0.1, gamma: float = 0.3, period: int = 7):
        self.alpha = alpha
        self.beta = beta
        self.gamma = gamma
        self.period = period
        self.level: float = 0.0
        self.trend: float = 0.0
        self.seasonal: list[float] = []
        self._n_fitted: int = 0

    def fit(self, series: list[float]) -> "HoltWinters":
        m = self.period
        n = len(series)
        if n < 2 * m:
            raise ValueError(f"Série precisa de pelo menos {2 * m} pontos (period={m})")

        # Inicialização
        self.level = statistics.mean(series[:m])
        self.trend = (statistics.mean(series[m: 2 * m]) - statistics.mean(series[:m])) / m
        # Fator sazonal inicial: valor / média do primeiro ciclo
        first_avg = statistics.mean(series[:m])
        self.seasonal = [
            (series[i] / first_avg) if first_avg > 0 else 1.0
            for i in range(m)
        ]
        self._n_fitted = 0

        for i, y in enumerate(series):
            s_idx = i % m
            prev_level = self.level
            prev_trend = self.trend

            denom = self.seasonal[s_idx] if self.seasonal[s_idx] != 0 else 1.0
            self.level = (
                self.alpha * (y / denom)
                + (1 - self.alpha) * (prev_level + prev_trend)
            )
            self.trend = (
                self.beta * (self.level - prev_level)
                + (1 - self.beta) * prev_trend
            )
            self.seasonal[s_idx] = (
                self.gamma * (y / self.level if self.level > 0 else 1.0)
                + (1 - self.gamma) * self.seasonal[s_idx]
            )
            self._n_fitted += 1

        return self

    def forecast(self, steps: int) -> list[float]:
        result = []
        for h in range(1, steps + 1):
            s_idx = (self._n_fitted + h - 1) % self.period
            val = (self.level + h * self.trend) * self.seasonal[s_idx]
            result.append(max(0.0, val))
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Regressão Linear com Dummy Sazonal
# ─────────────────────────────────────────────────────────────────────────────

class LinearSeasonalForecaster:
    """
    Decompõe a série em tendência linear + efeitos sazonais por dia da semana.
    Equivalente a OLS com dummies — implementado sem numpy.
    """

    def __init__(self):
        self._slope: float = 0.0
        self._intercept: float = 0.0
        self._seasonal_effects: dict[int, float] = {wd: 0.0 for wd in range(7)}

    def fit(self, series: list[float], start_date: date) -> "LinearSeasonalForecaster":
        n = len(series)
        if n < 14:
            raise ValueError("LinearSeasonalForecaster precisa de pelo menos 14 pontos")

        xs = list(range(n))
        # Ajuste de tendência linear
        try:
            slope, intercept = statistics.linear_regression(xs, series)
        except AttributeError:
            # Python < 3.10 — fallback manual
            xm = statistics.mean(xs)
            ym = statistics.mean(series)
            num = sum((x - xm) * (y - ym) for x, y in zip(xs, series))
            den = sum((x - xm) ** 2 for x in xs)
            slope = num / den if den != 0 else 0.0
            intercept = ym - slope * xm

        self._slope = slope
        self._intercept = intercept

        # Resíduos por dia da semana → efeito sazonal
        residuals_by_wd: dict[int, list[float]] = defaultdict(list)
        for i, y in enumerate(series):
            trend_val = intercept + slope * i
            resid = y - trend_val
            wd = (start_date + timedelta(days=i)).weekday()
            residuals_by_wd[wd].append(resid)

        for wd in range(7):
            if residuals_by_wd[wd]:
                self._seasonal_effects[wd] = statistics.mean(residuals_by_wd[wd])

        return self

    def forecast(self, steps: int, last_idx: int, start_date: date) -> list[float]:
        result = []
        for h in range(1, steps + 1):
            t = last_idx + h
            trend_val = self._intercept + self._slope * t
            fut_date = start_date + timedelta(days=last_idx + h)
            wd = fut_date.weekday()
            val = trend_val + self._seasonal_effects.get(wd, 0.0)
            result.append(max(0.0, val))
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Seleção automática de modelo
# ─────────────────────────────────────────────────────────────────────────────

def auto_select_model(history_days: int) -> str:
    """
    Seleciona o modelo ideal baseado no tamanho do histórico disponível.
      < 90 dias  → media_movel_ponderada
      90-179 dias → holt_winters
      >= 180 dias → regressao_linear_sazonal
    """
    if history_days < 90:
        return "media_movel_ponderada"
    if history_days < 180:
        return "holt_winters"
    return "regressao_linear_sazonal"


# ─────────────────────────────────────────────────────────────────────────────
# Função principal: seasonal_forecast
# ─────────────────────────────────────────────────────────────────────────────

def _active_custom_factor(db: Session, product_id: uuid.UUID, d: date) -> Optional[float]:
    """Retorna fator de evento especial ativo para o produto na data, ou None."""
    from models import SeasonalEvent
    dt = datetime.combine(d, datetime.min.time())
    events = (
        db.query(SeasonalEvent)
        .filter(
            SeasonalEvent.ativo == True,
            SeasonalEvent.data_inicio <= dt,
            SeasonalEvent.data_fim >= dt,
        )
        .filter(
            (SeasonalEvent.produto_id == product_id)
            | (SeasonalEvent.produto_id == None)
        )
        .all()
    )
    if not events:
        return None
    # Usa o maior fator se houver sobreposição
    return max(ev.fator_multiplicador for ev in events)


def _confidence_from_cv(series: list[float]) -> float:
    if len(series) < 2:
        return 50.0
    mean_val = statistics.mean(series)
    if mean_val == 0:
        return 0.0
    cv = statistics.stdev(series) / mean_val
    return round(max(40.0, 100.0 - cv * 80.0), 1)


def seasonal_forecast(
    db: Session,
    product_id: uuid.UUID,
    days: int = 14,
    model_override: Optional[str] = None,
) -> dict:
    """
    Função principal de E-05: seleciona modelo, aplica sazonalidade e eventos
    especiais, e retorna previsão diária com picos identificados.

    Retorna: modelo_usado, previsao_por_dia, total_previsto,
             confianca_pct, proximos_picos_identificados
    """
    events = _fetch_events(db, product_id, days=365)
    daily = _aggregate_daily(events)

    sorted_days = sorted(daily.keys())
    series = [daily[d] for d in sorted_days]
    history_days = len(sorted_days)

    model = model_override or auto_select_model(history_days)

    today = date.today()
    analyzer = DemandAnalyzer()
    base_daily_forecast: list[float] = []

    if model == "media_movel_ponderada" or history_days < 14:
        wma = analyzer.weighted_moving_average(series)
        base_daily_forecast = [wma] * days

    elif model == "holt_winters":
        hw = HoltWinters(alpha=0.3, beta=0.1, gamma=0.3, period=7)
        try:
            hw.fit(series)
            base_daily_forecast = hw.forecast(days)
        except ValueError:
            # fallback WMA
            model = "media_movel_ponderada"
            wma = analyzer.weighted_moving_average(series)
            base_daily_forecast = [wma] * days

    else:  # regressao_linear_sazonal
        lsf = LinearSeasonalForecaster()
        start = sorted_days[0] if sorted_days else today
        try:
            lsf.fit(series, start)
            base_daily_forecast = lsf.forecast(days, len(series) - 1, start)
        except ValueError:
            model = "holt_winters"
            hw = HoltWinters(alpha=0.3, beta=0.1, gamma=0.3, period=7)
            try:
                hw.fit(series)
                base_daily_forecast = hw.forecast(days)
            except ValueError:
                model = "media_movel_ponderada"
                wma = analyzer.weighted_moving_average(series)
                base_daily_forecast = [wma] * days

    # Busca fatores sazonais do histórico
    factors = analyzer.get_seasonality_factors(db, product_id)
    wd_factor_map = {DIAS_SEMANA[i]: factors.get(DIAS_SEMANA[i], 1.0) for i in range(7)}

    # Aplica sazonalidade + eventos especiais a cada dia
    previsao_por_dia = []
    for i in range(days):
        fut_date = today + timedelta(days=i + 1)
        wd = fut_date.weekday()
        base = base_daily_forecast[i] if i < len(base_daily_forecast) else 0.0

        # Fator sazonal (histórico ou padrão PRD)
        if history_days >= 14:
            fator = wd_factor_map.get(DIAS_SEMANA[wd], 1.0)
        else:
            fator = _default_factor_for_date(fut_date)

        # Evento especial (maior prioridade)
        custom_factor = _active_custom_factor(db, product_id, fut_date)
        if custom_factor is not None:
            fator = custom_factor

        qty = round(base * fator, 2)
        previsao_por_dia.append({
            "data": fut_date.isoformat(),
            "dia_semana": DIAS_SEMANA[wd],
            "tipo_dia": _day_type(fut_date),
            "fator_aplicado": round(fator, 3),
            "quantidade_prevista": qty,
        })

    total = sum(d["quantidade_prevista"] for d in previsao_por_dia)
    confianca = _confidence_from_cv(series) if series else 50.0

    # Picos: dias com previsão > 1.5× a média diária prevista
    media_forecast = total / days if days > 0 else 0.0
    picos = [
        {"data": d["data"], "dia_semana": d["dia_semana"],
         "quantidade": d["quantidade_prevista"], "fator": d["fator_aplicado"]}
        for d in previsao_por_dia
        if d["quantidade_prevista"] >= media_forecast * 1.5
    ]

    return {
        "product_id": str(product_id),
        "horizon_days": days,
        "historico_disponivel_dias": history_days,
        "modelo_usado": model,
        "total_previsto": round(total, 1),
        "media_diaria_prevista": round(media_forecast, 2),
        "confianca_pct": confianca,
        "proximos_picos_identificados": picos,
        "previsao_por_dia": previsao_por_dia,
    }

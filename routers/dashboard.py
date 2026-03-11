"""
E-03 — Dashboard de Alertas de Margem
"""
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
from typing import List, Optional
import uuid

from database import get_db
from models import SystemAlert, Product, BOMItem
from cost_calculator import calculate_product_cost
from services.margin_monitor import (
    get_margin_status,
    ALERT_TIPO_RISCO,
    ALERT_TIPO_VIOLADA,
    RISK_BUFFER_PP,
    run_monitor_cycle,
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard - E-03"])


# --- Schemas ---

class MarginAlertItem(BaseModel):
    produto_id: uuid.UUID
    produto_nome: str
    margem_atual_pct: float
    margem_minima_pct: float
    status_margem: str          # verde | amarelo | vermelho
    preco_sugerido: float
    mensagem: str
    urgencia: int               # 1=vermelho, 2=amarelo (para ordenação)


class DashboardMarginResponse(BaseModel):
    total_produtos_ativos: int
    em_risco: int               # amarelo
    margem_violada: int         # vermelho
    ok: int                     # verde
    alertas: List[MarginAlertItem]


class MonitorCycleResponse(BaseModel):
    produtos_processados: int
    mensagem: str


# --- Endpoints ---

@router.get("/margin-alerts", response_model=DashboardMarginResponse)
def get_margin_alerts(
    status_filter: Optional[str] = Query(
        default=None,
        description="Filtrar por status: vermelho | amarelo | verde"
    ),
    db: Session = Depends(get_db),
):
    """
    Retorna lista de todos os produtos ativos com seu status de margem atual,
    ordenados por urgência (vermelho primeiro, depois amarelo, depois verde).
    """
    products = db.query(Product).filter(Product.ativo == True).all()

    alertas: List[MarginAlertItem] = []
    total = len(products)
    count_verde = count_amarelo = count_vermelho = 0

    for product in products:
        bom_items = (
            db.query(BOMItem)
            .options(joinedload(BOMItem.ingredient), joinedload(BOMItem.supply))
            .filter(BOMItem.product_id == product.id)
            .all()
        )

        if not bom_items:
            # Produto sem BOM não pode ter margem calculada
            total -= 1
            continue

        cost = calculate_product_cost(product, bom_items)
        margem_pct = cost["margem_pct"]
        margem_minima = product.margem_minima or 0.0
        status = get_margin_status(margem_pct, margem_minima)

        if status == "verde":
            count_verde += 1
            urgencia = 3
            mensagem = f"Margem OK ({margem_pct:.1f}% ≥ mínima {margem_minima:.1f}%)"
        elif status == "amarelo":
            count_amarelo += 1
            urgencia = 2
            mensagem = (
                f"Margem em risco ({margem_pct:.1f}%). "
                f"Zona de risco: {margem_minima - RISK_BUFFER_PP:.1f}% – {margem_minima:.1f}%"
            )
        else:
            count_vermelho += 1
            urgencia = 1
            mensagem = (
                f"MARGEM VIOLADA ({margem_pct:.1f}% < mínima {margem_minima:.1f}%). "
                f"Preço sugerido: R$ {cost['preco_sugerido']:.2f}"
            )

        if status_filter and status != status_filter:
            continue

        alertas.append(MarginAlertItem(
            produto_id=product.id,
            produto_nome=product.nome,
            margem_atual_pct=margem_pct,
            margem_minima_pct=margem_minima,
            status_margem=status,
            preco_sugerido=cost["preco_sugerido"],
            mensagem=mensagem,
            urgencia=urgencia,
        ))

    alertas.sort(key=lambda x: x.urgencia)

    return DashboardMarginResponse(
        total_produtos_ativos=total,
        em_risco=count_amarelo,
        margem_violada=count_vermelho,
        ok=count_verde,
        alertas=alertas,
    )


@router.post("/margin-alerts/run-monitor", response_model=MonitorCycleResponse)
def trigger_monitor_cycle(db: Session = Depends(get_db)):
    """
    Dispara manualmente um ciclo do monitor de margem (útil para testes e
    para forçar recálculo imediato sem aguardar o daemon dos 15 minutos).
    """
    processed = run_monitor_cycle(db)
    return MonitorCycleResponse(
        produtos_processados=processed,
        mensagem=f"Ciclo concluído: {processed} produto(s) processado(s) e alertas atualizados.",
    )

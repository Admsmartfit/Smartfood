"""
E-06 — Rotas do Orquestrador de Alertas Inteligentes
"""
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import SystemAlert, NotificationPreference
from services.alert_orchestrator import orchestrator

router = APIRouter(tags=["Alertas - E-06"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class AlertItem(BaseModel):
    id: uuid.UUID
    tipo: str
    categoria: str
    severidade: str
    status: str
    mensagem: str
    produto_id: Optional[uuid.UUID]
    snoozed_until: Optional[datetime]
    created_at: Optional[datetime]

    model_config = {"from_attributes": True}


class AlertsGrouped(BaseModel):
    total: int
    criticos: int
    atencao: int
    por_categoria: Dict[str, List[AlertItem]]


class NotificationPrefRequest(BaseModel):
    alert_tipo: str
    canal_push: bool = True
    canal_whatsapp: bool = False
    canal_email: bool = False


class NotificationPrefResponse(BaseModel):
    id: uuid.UUID
    user_id: str
    alert_tipo: str
    canal_push: bool
    canal_whatsapp: bool
    canal_email: bool
    ativo: bool

    model_config = {"from_attributes": True}


class OrchestratorRunResponse(BaseModel):
    criados: int
    resolvidos: int
    mensagem: str


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/alerts/active", response_model=AlertsGrouped)
def get_active_alerts(
    categoria: Optional[str] = Query(
        default=None,
        description="Filtrar: financeiro|estoque|producao|capacidade|demanda|comercial|qualidade"
    ),
    severidade: Optional[str] = Query(default=None, description="critico|atencao|info"),
    db: Session = Depends(get_db),
):
    """
    Retorna todos os alertas ativos, agrupados por categoria e ordenados por
    severidade (crítico primeiro). Alertas snoozed são incluídos mas marcados.
    """
    now = datetime.now(timezone.utc)
    q = db.query(SystemAlert).filter(SystemAlert.status.in_(["ativo", "snoozed"]))

    if categoria:
        q = q.filter(SystemAlert.categoria == categoria)
    if severidade:
        q = q.filter(SystemAlert.severidade == severidade)

    alerts = q.order_by(SystemAlert.severidade, SystemAlert.created_at.desc()).all()

    grouped: Dict[str, List[AlertItem]] = {}
    criticos = atencao = 0

    for a in alerts:
        cat = a.categoria or "outros"
        if cat not in grouped:
            grouped[cat] = []
        grouped[cat].append(AlertItem(
            id=a.id,
            tipo=a.tipo,
            categoria=cat,
            severidade=a.severidade or "info",
            status=a.status,
            mensagem=a.mensagem,
            produto_id=a.produto_id,
            snoozed_until=a.snoozed_until,
            created_at=a.created_at,
        ))
        if a.severidade == "critico":
            criticos += 1
        elif a.severidade == "atencao":
            atencao += 1

    return AlertsGrouped(
        total=len(alerts),
        criticos=criticos,
        atencao=atencao,
        por_categoria=grouped,
    )


@router.post("/alerts/{alert_id}/snooze", response_model=AlertItem)
def snooze_alert(
    alert_id: uuid.UUID,
    hours: int = Query(default=2, ge=1, le=72, description="Horas para silenciar"),
    db: Session = Depends(get_db),
):
    """
    Silencia temporariamente um alerta. Após o período, voltará a aparecer
    como ativo e será renotificado no próximo ciclo.
    """
    alert = db.query(SystemAlert).filter(SystemAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta não encontrado")
    if alert.status == "resolvido":
        raise HTTPException(status_code=422, detail="Alerta já está resolvido")

    alert.status = "snoozed"
    alert.snoozed_until = datetime.now(timezone.utc) + timedelta(hours=hours)
    db.commit()
    db.refresh(alert)

    return AlertItem(
        id=alert.id,
        tipo=alert.tipo,
        categoria=alert.categoria or "outros",
        severidade=alert.severidade or "info",
        status=alert.status,
        mensagem=alert.mensagem,
        produto_id=alert.produto_id,
        snoozed_until=alert.snoozed_until,
        created_at=alert.created_at,
    )


@router.post("/alerts/{alert_id}/resolve", status_code=204)
def resolve_alert(alert_id: uuid.UUID, db: Session = Depends(get_db)):
    """Marca manualmente um alerta como resolvido."""
    alert = db.query(SystemAlert).filter(SystemAlert.id == alert_id).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta não encontrado")

    alert.status = "resolvido"
    alert.resolvido_em = datetime.now(timezone.utc)
    db.commit()


@router.post("/alerts/run-orchestrator", response_model=OrchestratorRunResponse)
def trigger_orchestrator(db: Session = Depends(get_db)):
    """Dispara manualmente um ciclo do AlertOrchestrator (equivalente ao daemon de 15 min)."""
    counts = orchestrator.evaluate_all(db)
    return OrchestratorRunResponse(
        **counts,
        mensagem=(
            f"Ciclo concluído: {counts['criados']} alerta(s) novo(s), "
            f"{counts['resolvidos']} resolvido(s)."
        ),
    )


# ─── Preferências de notificação ────────────────────────────────────────────

@router.put("/notifications/preferences", response_model=NotificationPrefResponse)
def upsert_notification_preference(
    payload: NotificationPrefRequest,
    user_id: str = Query(..., description="ID do usuário (gestor, operador, etc.)"),
    db: Session = Depends(get_db),
):
    """
    Define ou atualiza preferência de canal de notificação para um tipo de alerta.
    Canais disponíveis: push, whatsapp, email.
    """
    pref = (
        db.query(NotificationPreference)
        .filter(
            NotificationPreference.user_id == user_id,
            NotificationPreference.alert_tipo == payload.alert_tipo,
        )
        .first()
    )

    if pref:
        pref.canal_push = payload.canal_push
        pref.canal_whatsapp = payload.canal_whatsapp
        pref.canal_email = payload.canal_email
        pref.ativo = True
    else:
        pref = NotificationPreference(
            user_id=user_id,
            alert_tipo=payload.alert_tipo,
            canal_push=payload.canal_push,
            canal_whatsapp=payload.canal_whatsapp,
            canal_email=payload.canal_email,
        )
        db.add(pref)

    db.commit()
    db.refresh(pref)
    return pref


@router.get("/notifications/preferences", response_model=List[NotificationPrefResponse])
def list_notification_preferences(
    user_id: str = Query(..., description="ID do usuário"),
    db: Session = Depends(get_db),
):
    """Lista todas as preferências de notificação de um usuário."""
    return (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user_id, NotificationPreference.ativo == True)
        .all()
    )

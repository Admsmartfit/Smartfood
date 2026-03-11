"""
E-18 — OfflineSyncService: Sincronização de Eventos Offline

US-019: Operador usa sistema sem internet (SQLite no device). Ao reconectar,
POST /sync envia batch de eventos ao servidor, que os processa de forma
idempotente (event_id garante que o mesmo evento não seja duplicado).

Tipos de evento suportados:
  ingredient_usage      — consumo de ingrediente em OP (BatchIngredientUsage)
  inventory_adjustment  — ajuste manual de estoque
  order_status_update   — mudança de status de pedido B2B
  production_start      — início de OP (registra operador e hora_inicio)
  production_complete   — conclusão de OP (quantidade_real, custos)

Protocolo de idempotência:
  1. Cliente gera event_id = UUID v4 no momento da ação (offline)
  2. Servidor verifica se event_id já existe em sync_events
  3. Se existir → status='ignorado' (sem reprocessamento)
  4. Se não existir → processa e persiste com status='processado'
"""
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

logger = logging.getLogger("offline_sync")


# ─────────────────────────────────────────────────────────────────────────────
# Processador central
# ─────────────────────────────────────────────────────────────────────────────

def process_sync_batch(db: Session, device_id: str, events: list[dict]) -> dict:
    """
    Processa um batch de eventos offline de forma idempotente.

    Retorna sumário: total, processados, ignorados (duplicatas), erros.
    """
    from models import SyncEvent

    total = len(events)
    processados = 0
    ignorados = 0
    erros = []

    for raw in events:
        event_id = str(raw.get("event_id", ""))
        event_type = raw.get("event_type", "")
        payload = raw.get("payload", {})
        synced_at_str = raw.get("synced_at")

        synced_at = None
        if synced_at_str:
            try:
                synced_at = datetime.fromisoformat(synced_at_str)
                if synced_at.tzinfo is None:
                    synced_at = synced_at.replace(tzinfo=timezone.utc)
            except ValueError:
                synced_at = datetime.now(timezone.utc)

        if not event_id:
            erros.append({"event_type": event_type, "erro": "event_id ausente"})
            continue

        # Idempotência: verifica duplicata
        existente = db.query(SyncEvent).filter(SyncEvent.event_id == event_id).first()
        if existente:
            ignorados += 1
            continue

        # Cria registro de sync
        sync_record = SyncEvent(
            event_id=event_id,
            device_id=device_id,
            event_type=event_type,
            payload=payload,
            status="pendente",
            synced_at=synced_at,
        )
        db.add(sync_record)
        db.flush()

        # Processa conforme tipo
        try:
            _dispatch(db, event_type, payload, synced_at)
            sync_record.status = "processado"
            processados += 1
        except Exception as e:
            sync_record.status = "erro"
            sync_record.erro_msg = str(e)
            erros.append({"event_id": event_id, "event_type": event_type, "erro": str(e)})
            logger.warning("Erro ao processar evento %s (%s): %s", event_id, event_type, e)

    db.commit()

    return {
        "device_id": device_id,
        "total_recebidos": total,
        "processados": processados,
        "ignorados_duplicata": ignorados,
        "erros": len(erros),
        "detalhe_erros": erros,
        "sincronizado_em": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher por tipo de evento
# ─────────────────────────────────────────────────────────────────────────────

def _dispatch(db: Session, event_type: str, payload: dict, synced_at: datetime | None):
    handlers = {
        "ingredient_usage":     _handle_ingredient_usage,
        "inventory_adjustment": _handle_inventory_adjustment,
        "order_status_update":  _handle_order_status,
        "production_start":     _handle_production_start,
        "production_complete":  _handle_production_complete,
    }
    handler = handlers.get(event_type)
    if not handler:
        raise ValueError(f"Tipo de evento desconhecido: '{event_type}'")
    handler(db, payload, synced_at)


def _handle_ingredient_usage(db: Session, payload: dict, ts: datetime | None):
    """
    Registra consumo de ingrediente em OP.
    payload: {batch_id, usages: [{ingredient_id, lot_id?, qty_real}]}
    """
    from services.production_service import record_ingredient_usage
    batch_id = uuid.UUID(str(payload["batch_id"]))
    usages = payload.get("usages", [])
    record_ingredient_usage(db, batch_id, usages)


def _handle_inventory_adjustment(db: Session, payload: dict, ts: datetime | None):
    """
    Aplica ajuste de estoque registrado offline.
    payload: {ingredient_id, tipo, quantidade, motivo}
    """
    from services.inventory_service import adjust_inventory
    adjust_inventory(
        db,
        ingredient_id=uuid.UUID(str(payload["ingredient_id"])),
        tipo=payload.get("tipo", "correcao_manual"),
        quantidade=float(payload["quantidade"]),
        motivo=payload.get("motivo", "ajuste offline"),
        operador=payload.get("operador"),
    )


def _handle_order_status(db: Session, payload: dict, ts: datetime | None):
    """
    Atualiza status de pedido B2B.
    payload: {order_id, novo_status}
    """
    from services.b2b_service import update_order_status
    update_order_status(
        db,
        order_id=uuid.UUID(str(payload["order_id"])),
        new_status=payload["novo_status"],
    )


def _handle_production_start(db: Session, payload: dict, ts: datetime | None):
    """
    Inicia OP registrada offline.
    payload: {batch_id, operador_id}
    """
    from services.production_service import start_production
    start_production(db, uuid.UUID(str(payload["batch_id"])), payload["operador_id"])


def _handle_production_complete(db: Session, payload: dict, ts: datetime | None):
    """
    Conclui OP registrada offline.
    payload: {batch_id, quantidade_real, custo_energia_kwh?, labor_cost_per_min?}
    """
    from services.production_service import complete_production_order
    from cost_calculator import DEFAULT_LABOR_COST_PER_MIN
    complete_production_order(
        db,
        batch_id=uuid.UUID(str(payload["batch_id"])),
        quantidade_real=float(payload["quantidade_real"]),
        custo_energia_kwh=payload.get("custo_energia_kwh"),
        labor_cost_per_min=payload.get("labor_cost_per_min", DEFAULT_LABOR_COST_PER_MIN),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Status de sincronização por device
# ─────────────────────────────────────────────────────────────────────────────

def get_sync_status(db: Session, device_id: str) -> dict:
    """Retorna resumo do histórico de sincronização de um device."""
    from models import SyncEvent
    from sqlalchemy import func

    events = db.query(SyncEvent).filter(SyncEvent.device_id == device_id).all()
    if not events:
        return {"device_id": device_id, "total_syncs": 0, "ultima_sync": None}

    ultimo = max((e.created_at for e in events if e.created_at), default=None)
    por_status: dict[str, int] = {}
    for e in events:
        por_status[e.status] = por_status.get(e.status, 0) + 1

    return {
        "device_id": device_id,
        "total_eventos": len(events),
        "ultima_sync": ultimo.isoformat() if ultimo else None,
        "por_status": por_status,
        "eventos_com_erro": [
            {"event_id": e.event_id, "tipo": e.event_type, "erro": e.erro_msg}
            for e in events if e.status == "erro"
        ],
    }

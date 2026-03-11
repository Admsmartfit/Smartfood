"""
E-18 — Rotas de Sincronização Offline e Briefing Diário

Endpoints:
  POST /sync                         — envia batch de eventos offline (idempotente)
  GET  /sync/status/{device_id}      — histórico de syncs de um device
  GET  /sync/events                  — lista eventos com filtro por status
  POST /briefing/send                — dispara briefing diário manualmente
  GET  /briefing/preview             — preview do briefing sem enviar
"""
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services.offline_sync_service import process_sync_batch, get_sync_status
from services.daily_briefing_service import generate_daily_briefing, send_daily_briefing

router = APIRouter(tags=["Offline Sync e Briefing Diário - E-18"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class SyncEventItem(BaseModel):
    event_id: str
    event_type: str
    payload: Dict[str, Any]
    synced_at: Optional[str] = None


class SyncBatchRequest(BaseModel):
    device_id: str
    events: List[SyncEventItem]


# ─── Sincronização Offline ───────────────────────────────────────────────────

@router.post("/sync")
def sync_offline_events(payload: SyncBatchRequest, db: Session = Depends(get_db)):
    """
    US-019 — Sincroniza eventos registrados offline no device (SQLite).

    O cliente envia um batch de eventos; o servidor processa de forma **idempotente**:
    - `event_id` duplicado → ignorado silenciosamente (status=`ignorado`)
    - Evento novo → processado e persistido (status=`processado`)
    - Evento com erro → registrado sem falhar o batch (status=`erro`)

    **Tipos de evento suportados:**

    | `event_type`            | Ação no servidor                              |
    |-------------------------|-----------------------------------------------|
    | `ingredient_usage`      | Registra consumo em OP (BatchIngredientUsage) |
    | `inventory_adjustment`  | Aplica ajuste de estoque                      |
    | `order_status_update`   | Muda status de pedido B2B                     |
    | `production_start`      | Inicia OP (registra operador e hora_inicio)   |
    | `production_complete`   | Conclui OP (quantidade_real, custos)          |

    **Exemplo de payload para `ingredient_usage`:**
    ```json
    {
      "event_id": "uuid-gerado-no-device",
      "event_type": "ingredient_usage",
      "synced_at": "2025-06-15T14:30:00Z",
      "payload": {
        "batch_id": "uuid-da-op",
        "usages": [
          {"ingredient_id": "uuid", "qty_real": 2.5},
          {"ingredient_id": "uuid", "lot_id": "uuid-lote", "qty_real": 1.0}
        ]
      }
    }
    ```
    """
    events = [e.model_dump() for e in payload.events]
    return process_sync_batch(db, device_id=payload.device_id, events=events)


@router.get("/sync/status/{device_id}")
def sync_status(device_id: str, db: Session = Depends(get_db)):
    """
    Retorna histórico de sincronizações de um device específico:
    - Total de eventos, última sync, distribuição por status
    - Lista de eventos com erro para reenvio
    """
    return get_sync_status(db, device_id)


@router.get("/sync/events")
def list_sync_events(
    status: Optional[str] = Query(default=None,
                                   description="pendente | processado | erro | ignorado"),
    device_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, le=200),
    db: Session = Depends(get_db),
):
    """Lista eventos de sync com filtro por status e/ou device."""
    from models import SyncEvent
    q = db.query(SyncEvent)
    if status:
        q = q.filter(SyncEvent.status == status)
    if device_id:
        q = q.filter(SyncEvent.device_id == device_id)
    events = q.order_by(SyncEvent.created_at.desc()).limit(limit).all()
    return [
        {
            "id": str(e.id),
            "event_id": e.event_id,
            "device_id": e.device_id,
            "event_type": e.event_type,
            "status": e.status,
            "erro_msg": e.erro_msg,
            "synced_at": e.synced_at.isoformat() if e.synced_at else None,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in events
    ]


# ─── Briefing Diário ─────────────────────────────────────────────────────────

@router.get("/briefing/preview")
def briefing_preview(db: Session = Depends(get_db)):
    """
    US-020 — Gera e retorna o briefing diário sem enviar via WhatsApp.

    Retorna as 3 seções (Produção / Compras / Entregas) e a mensagem
    formatada que seria enviada às 7h.
    """
    return generate_daily_briefing(db)


@router.post("/briefing/send")
def briefing_send(db: Session = Depends(get_db)):
    """
    US-020 — Dispara o briefing diário manualmente via WhatsApp.

    Normalmente executado automaticamente às 7h BRT pelo daemon `daily_briefing_task`.
    Exige variável de ambiente `MANAGER_PHONES` com números separados por vírgula.

    **Formato da mensagem:**
    ```
    SmartFood Ops 360 — Briefing Diário 15/06/2025

    📦 PRODUÇÃO
      • Coxinha 200g — 500un — EM_PRODUCAO
      Produzir hoje:
        ↪ Kibe 100g: 300 un (estoque: 50)

    🛒 COMPRAS URGENTES
      • Frango CMS — 2kg / min 25kg — CRITICO (LT: 3d)

    🚚 ENTREGAS HOJE
      • Bar do Zé — R$1.250,00 — PRONTO
      Total: R$1.250,00 (1 pedidos)
    ```
    """
    result = send_daily_briefing(db)
    return {
        "enviado": True,
        "destinatarios": result.get("enviado_para", 0),
        "total_alertas": result.get("total_alertas", 0),
        "data": result.get("data"),
    }

"""
E-06 — Orquestrador de Alertas Inteligentes

AlertOrchestrator: avalia todas as 12 categorias de alerta a cada 15 minutos.
NotificationDispatcher: despacha notificações (stub — integração WhatsApp/FCM em E-09).
Deduplicação: mesmo alerta não é reenviado em menos de 4 horas.
"""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy.orm import Session, joinedload

from cost_calculator import calculate_product_cost, DEFAULT_LABOR_COST_PER_MIN
from services.margin_monitor import get_margin_status

logger = logging.getLogger("alert_orchestrator")

ORCHESTRATOR_INTERVAL_SECONDS = 15 * 60  # 15 minutos
DEDUP_HOURS = 4  # Não reenviar o mesmo alerta nesse período

# Mapeamento tipo → categoria e severidade padrão
ALERT_META: dict[str, dict] = {
    "MARGEM_VIOLADA":        {"categoria": "financeiro",  "severidade": "critico"},
    "MARGEM_RISCO":          {"categoria": "financeiro",  "severidade": "atencao"},
    "COMPRA_URGENTE":        {"categoria": "estoque",     "severidade": "critico"},
    "COMPRA_3_DIAS":         {"categoria": "estoque",     "severidade": "atencao"},
    "CAPACIDADE_EXCEDIDA":   {"categoria": "capacidade",  "severidade": "atencao"},
    "SAZONALIDADE_ALTA":     {"categoria": "demanda",     "severidade": "atencao"},
    "PRODUCAO_ATRASADA":     {"categoria": "producao",    "severidade": "critico"},
    "ESTOQUE_ABAIXO_MINIMO": {"categoria": "estoque",     "severidade": "critico"},
    "DIVERGENCIA_RECEBIMENTO":{"categoria": "estoque",    "severidade": "atencao"},
    "COMPRA_URGENTE_HOJE":   {"categoria": "estoque",     "severidade": "critico"},
}


# ─────────────────────────────────────────────────────────────────────────────
# NotificationDispatcher (stub — substitua com Mega API / FCM em E-09)
# ─────────────────────────────────────────────────────────────────────────────

class NotificationDispatcher:
    def send_whatsapp(self, phone: str, message: str) -> None:
        logger.info("[WhatsApp→%s] %s", phone, message[:120])

    def send_push(self, user_id: str, title: str, body: str) -> None:
        logger.info("[Push→%s] %s | %s", user_id, title, body[:80])

    def send_email(self, email: str, subject: str, body: str) -> None:
        logger.info("[Email→%s] %s", email, subject)


dispatcher = NotificationDispatcher()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers de alerta
# ─────────────────────────────────────────────────────────────────────────────

def _resolve_alerts_of_tipo(db: Session, tipo: str, entity_id=None, field: str = "produto_id"):
    from models import SystemAlert
    now = datetime.now(timezone.utc)
    q = db.query(SystemAlert).filter(
        SystemAlert.tipo == tipo,
        SystemAlert.status == "ativo",
    )
    if entity_id is not None:
        q = q.filter(getattr(SystemAlert, field) == entity_id)
    q.update({"status": "resolvido", "resolvido_em": now}, synchronize_session=False)


def _upsert_alert(
    db: Session,
    tipo: str,
    mensagem: str,
    produto_id=None,
    supply_id=None,
) -> bool:
    """
    Cria alerta se não houver um ativo do mesmo tipo+entidade.
    Respeita deduplicação de 4h para notificação.
    Retorna True se alerta foi criado/atualizado.
    """
    from models import SystemAlert
    meta = ALERT_META.get(tipo, {"categoria": "outros", "severidade": "atencao"})
    now = datetime.now(timezone.utc)

    existing = (
        db.query(SystemAlert)
        .filter(
            SystemAlert.tipo == tipo,
            SystemAlert.status == "ativo",
            SystemAlert.produto_id == produto_id,
        )
        .first()
    )

    if existing:
        existing.mensagem = mensagem
        return False  # já existe, apenas atualiza mensagem

    alert = SystemAlert(
        tipo=tipo,
        categoria=meta["categoria"],
        produto_id=produto_id,
        supply_id=supply_id,
        mensagem=mensagem,
        severidade=meta["severidade"],
        status="ativo",
        last_notified_at=now,
    )
    db.add(alert)
    return True


def _should_notify(alert) -> bool:
    """Retorna True se já passaram DEDUP_HOURS desde a última notificação."""
    if alert.last_notified_at is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DEDUP_HOURS)
    return alert.last_notified_at < cutoff


# ─────────────────────────────────────────────────────────────────────────────
# AlertOrchestrator
# ─────────────────────────────────────────────────────────────────────────────

class AlertOrchestrator:
    """
    Avalia todas as regras de alerta do sistema e gerencia lifecycle na
    tabela system_alerts. Roda a cada 15 minutos via daemon assíncrono.
    """

    def evaluate_all(self, db: Session) -> dict:
        counts = {"criados": 0, "resolvidos": 0}

        counts["criados"] += self._check_margin_alerts(db)
        counts["criados"] += self._check_stock_alerts(db)
        counts["criados"] += self._check_seasonality_alerts(db)
        counts["criados"] += self._check_production_alerts(db)

        db.commit()
        return counts

    # ── Regra 1 & 2: Margem (reusa lógica E-03) ─────────────────────────────
    def _check_margin_alerts(self, db: Session) -> int:
        from models import Product, BOMItem

        created = 0
        products = db.query(Product).filter(Product.ativo == True).all()

        for product in products:
            bom_items = (
                db.query(BOMItem)
                .options(joinedload(BOMItem.ingredient), joinedload(BOMItem.supply))
                .filter(BOMItem.product_id == product.id)
                .all()
            )
            if not bom_items:
                continue

            cost = calculate_product_cost(product, bom_items, DEFAULT_LABOR_COST_PER_MIN)
            margem = cost["margem_pct"]
            status = get_margin_status(margem, product.margem_minima or 0)

            if status == "verde":
                _resolve_alerts_of_tipo(db, "MARGEM_VIOLADA", product.id)
                _resolve_alerts_of_tipo(db, "MARGEM_RISCO", product.id)

            elif status == "amarelo":
                _resolve_alerts_of_tipo(db, "MARGEM_VIOLADA", product.id)
                ok = _upsert_alert(
                    db, "MARGEM_RISCO",
                    f"Produto '{product.nome}': margem em risco ({margem:.1f}%). "
                    f"Mínima: {product.margem_minima:.1f}%. Insumos podem ter subido.",
                    produto_id=product.id,
                )
                created += int(ok)

            else:  # vermelho
                _resolve_alerts_of_tipo(db, "MARGEM_RISCO", product.id)
                ok = _upsert_alert(
                    db, "MARGEM_VIOLADA",
                    f"MARGEM VIOLADA — '{product.nome}': {margem:.1f}% "
                    f"(mín {product.margem_minima:.1f}%). "
                    f"Preço sugerido: R$ {cost['preco_sugerido']:.2f}",
                    produto_id=product.id,
                )
                created += int(ok)

        return created

    # ── Regra 3 & 6: Estoque crítico e compra em 3 dias ─────────────────────
    def _check_stock_alerts(self, db: Session) -> int:
        from models import Ingredient

        created = 0
        ingredients = db.query(Ingredient).all()

        for ing in ingredients:
            estoque = ing.estoque_atual or 0.0
            estoque_min = ing.estoque_minimo or 0.0
            lead = ing.lead_time_dias or 0

            # Consumo diário médio estimado a partir do estoque mínimo e lead time
            consumo_diario = (estoque_min / (lead + 2)) if (lead + 2) > 0 else 0.0
            dias_cobertura = (estoque / consumo_diario) if consumo_diario > 0 else 9999

            if estoque <= estoque_min:
                # Estoque abaixo do mínimo
                ok = _upsert_alert(
                    db, "ESTOQUE_ABAIXO_MINIMO",
                    f"Insumo '{ing.nome}': estoque {estoque:.2f} {ing.unidade} "
                    f"abaixo do mínimo ({estoque_min:.2f}). Lead time: {lead}d.",
                )
                created += int(ok)
                _resolve_alerts_of_tipo(db, "COMPRA_3_DIAS")

            elif dias_cobertura <= lead:
                # Comprar hoje — cobertura não alcança o lead time
                ok = _upsert_alert(
                    db, "COMPRA_URGENTE_HOJE",
                    f"COMPRAR HOJE — '{ing.nome}': cobertura estimada "
                    f"{dias_cobertura:.0f}d, lead time {lead}d. "
                    f"Estoque: {estoque:.2f} {ing.unidade}",
                )
                created += int(ok)

            elif dias_cobertura <= lead + 3:
                # Comprar em até 3 dias
                _resolve_alerts_of_tipo(db, "COMPRA_URGENTE_HOJE")
                ok = _upsert_alert(
                    db, "COMPRA_3_DIAS",
                    f"Comprar '{ing.nome}' em até 3 dias — cobertura "
                    f"{dias_cobertura:.0f}d, lead time {lead}d.",
                )
                created += int(ok)

            else:
                _resolve_alerts_of_tipo(db, "ESTOQUE_ABAIXO_MINIMO")
                _resolve_alerts_of_tipo(db, "COMPRA_URGENTE_HOJE")
                _resolve_alerts_of_tipo(db, "COMPRA_3_DIAS")

        return created

    # ── Regra 7: Sazonalidade alta nos próximos 7 dias ──────────────────────
    def _check_seasonality_alerts(self, db: Session) -> int:
        from datetime import date
        try:
            from services.seasonal_forecaster import detect_holidays, DEFAULT_SEASONALITY_FACTORS
        except Exception:
            return 0

        created = 0
        today = date.today()
        high_days = []
        for i in range(1, 8):
            d = today + timedelta(days=i)
            is_hol = detect_holidays(d)
            wd_factor = DEFAULT_SEASONALITY_FACTORS.get(d.weekday(), 1.0)
            if is_hol or wd_factor >= 1.6:
                label = "feriado" if is_hol else d.strftime("%A")
                high_days.append(f"{d.isoformat()} ({label})")

        if high_days:
            ok = _upsert_alert(
                db, "SAZONALIDADE_ALTA",
                f"Alta demanda prevista nos próximos 7 dias: {', '.join(high_days)}. "
                "Antecipar produção recomendado.",
            )
            created += int(ok)
        else:
            _resolve_alerts_of_tipo(db, "SAZONALIDADE_ALTA")

        return created

    # ── Regra 3: Produção atrasada ───────────────────────────────────────────
    def _check_production_alerts(self, db: Session) -> int:
        from models import ProductionBatch

        created = 0
        now = datetime.now(timezone.utc)
        tomorrow = now + timedelta(days=1)

        # Lotes planejados/aprovados com data de início já passou ou é hoje
        late_batches = (
            db.query(ProductionBatch)
            .filter(
                ProductionBatch.status.in_(["RASCUNHO", "APROVADA"]),
                ProductionBatch.data_inicio <= tomorrow,
            )
            .all()
        )

        for batch in late_batches:
            ok = _upsert_alert(
                db, "PRODUCAO_ATRASADA",
                f"Lote de produção #{str(batch.id)[:8]} não iniciado. "
                f"Data prevista: {batch.data_inicio}. Status: {batch.status}.",
                produto_id=batch.product_id,
            )
            created += int(ok)

        return created


# ─────────────────────────────────────────────────────────────────────────────
# Dispatcher de notificações após evaluate_all
# ─────────────────────────────────────────────────────────────────────────────

def dispatch_pending_notifications(db: Session) -> None:
    """
    Lê alertas ativos não snoozed e envia notificações respeitando deduplicação.
    Em produção, busca preferências do usuário gestor para escolher canal.
    """
    from models import SystemAlert, NotificationPreference

    now = datetime.now(timezone.utc)
    active_alerts = (
        db.query(SystemAlert)
        .filter(
            SystemAlert.status == "ativo",
            (SystemAlert.snoozed_until == None) | (SystemAlert.snoozed_until < now),
        )
        .all()
    )

    for alert in active_alerts:
        if not _should_notify(alert):
            continue

        # Busca preferências (fallback: push sempre, WhatsApp para críticos)
        prefs = (
            db.query(NotificationPreference)
            .filter(
                NotificationPreference.alert_tipo == alert.tipo,
                NotificationPreference.ativo == True,
            )
            .all()
        )

        if prefs:
            for pref in prefs:
                if pref.canal_push:
                    dispatcher.send_push(pref.user_id, f"[{alert.severidade.upper()}] {alert.tipo}", alert.mensagem)
                if pref.canal_whatsapp:
                    dispatcher.send_whatsapp("gestor", alert.mensagem)
        else:
            # Padrão: push para todos, WhatsApp só para críticos
            dispatcher.send_push("gestor", f"[{alert.severidade.upper()}] {alert.tipo}", alert.mensagem)
            if alert.severidade == "critico":
                dispatcher.send_whatsapp("gestor", alert.mensagem)

        alert.last_notified_at = now

    db.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Daemon assíncrono
# ─────────────────────────────────────────────────────────────────────────────

orchestrator = AlertOrchestrator()


async def alert_orchestrator_task(get_db_func):
    """
    Tarefa assíncrona: avalia alertas + despacha notificações a cada 15 min.
    Deve ser iniciada via asyncio.create_task() no lifespan.
    """
    logger.info("AlertOrchestrator iniciado — ciclo a cada 15 minutos")
    while True:
        await asyncio.sleep(ORCHESTRATOR_INTERVAL_SECONDS)
        db = next(get_db_func())
        try:
            counts = orchestrator.evaluate_all(db)
            dispatch_pending_notifications(db)
            logger.info("AlertOrchestrator: %s", counts)
        except Exception as exc:
            logger.exception("Erro no AlertOrchestrator: %s", exc)
        finally:
            db.close()

"""
E-18 — DailyBriefingService: Relatório Diário às 7h via WhatsApp

US-020: Gestor recebe às 7h um resumo com 3 seções:
  📦 PRODUÇÃO — o que produzir hoje
  🛒 COMPRAS  — o que comprar urgente
  🚚 ENTREGAS — pedidos a entregar hoje

Enviado via Mega API (WhatsApp) para todos os gestores cadastrados.
Disparado pelo async daemon daily_briefing_task().
"""
import asyncio
import logging
from datetime import datetime, date, timedelta, timezone

from sqlalchemy.orm import Session

logger = logging.getLogger("daily_briefing")

# Hora de envio (UTC — ajustar conforme fuso do servidor)
BRIEFING_HOUR_UTC = 10  # 10h UTC = 7h BRT (UTC-3)


# ─────────────────────────────────────────────────────────────────────────────
# Geração do briefing
# ─────────────────────────────────────────────────────────────────────────────

def generate_daily_briefing(db: Session) -> dict:
    """
    Compila o relatório diário com 3 seções:
      1. Produção: OPs em andamento + demanda prevista que precisa ser produzida hoje
      2. Compras: insumos com estoque < estoque de segurança (críticos)
      3. Entregas: pedidos B2B com data_entrega_prevista = hoje
    """
    hoje = date.today()
    now = datetime.now(timezone.utc)

    secao_producao = _secao_producao(db, hoje)
    secao_compras   = _secao_compras(db)
    secao_entregas  = _secao_entregas(db, hoje)

    total_alertas = (
        len(secao_producao["ops_em_andamento"])
        + len(secao_producao["producoes_necessarias"])
        + len(secao_compras["criticos"])
        + len(secao_entregas["entregas_hoje"])
    )

    mensagem_whatsapp = _formatar_whatsapp(secao_producao, secao_compras, secao_entregas, hoje)

    return {
        "data": hoje.isoformat(),
        "gerado_em": now.isoformat(),
        "total_alertas": total_alertas,
        "secoes": {
            "producao": secao_producao,
            "compras": secao_compras,
            "entregas": secao_entregas,
        },
        "mensagem_whatsapp": mensagem_whatsapp,
    }


def _secao_producao(db: Session, hoje: date) -> dict:
    """OPs ativas hoje + produtos que precisam ser produzidos com base na demanda."""
    from models import ProductionBatch, Product, DemandForecast

    # OPs em andamento
    ops_ativas = (
        db.query(ProductionBatch)
        .filter(ProductionBatch.status.in_(["APROVADA", "EM_PRODUCAO"]))
        .order_by(ProductionBatch.data_inicio)
        .all()
    )

    ops_em_andamento = []
    for op in ops_ativas:
        p = db.query(Product).filter(Product.id == op.product_id).first()
        ops_em_andamento.append({
            "op_id": str(op.id)[:8].upper(),
            "produto": p.nome if p else "?",
            "quantidade_planejada": op.quantidade_planejada,
            "status": op.status,
            "operador": op.operador_id or "não iniciada",
        })

    # Previsões de demanda para hoje (produtos que devem estar prontos)
    inicio_dia = datetime.combine(hoje, datetime.min.time()).replace(tzinfo=timezone.utc)
    fim_dia = inicio_dia + timedelta(days=1)
    forecasts = (
        db.query(DemandForecast)
        .filter(
            DemandForecast.data_previsao >= inicio_dia,
            DemandForecast.data_previsao < fim_dia,
        )
        .order_by(DemandForecast.quantidade_prevista.desc())
        .limit(5)
        .all()
    )

    producoes_necessarias = []
    for f in forecasts:
        p = db.query(Product).filter(Product.id == f.produto_id).first()
        estoque = p.estoque_atual or 0.0 if p else 0.0
        necessario = max(0.0, f.quantidade_prevista - estoque)
        if necessario > 0:
            producoes_necessarias.append({
                "produto": p.nome if p else "?",
                "previsao_demanda": round(f.quantidade_prevista, 1),
                "estoque_atual": round(estoque, 1),
                "a_produzir": round(necessario, 1),
            })

    return {
        "ops_em_andamento": ops_em_andamento,
        "producoes_necessarias": producoes_necessarias,
    }


def _secao_compras(db: Session) -> dict:
    """Insumos abaixo do estoque de segurança (críticos para compra urgente)."""
    from models import Ingredient

    ings = db.query(Ingredient).filter(Ingredient.ativo == True).all()
    criticos = []
    atencao = []

    for ing in ings:
        estoque = ing.estoque_atual or 0.0
        # Safety stock = consumo_diario_medio × (lead_time + 2 dias buffer)
        # Aqui usamos estoque_minimo se disponível, caso contrário estimativa simples
        estoque_min = getattr(ing, "estoque_minimo", None) or (
            (ing.consumo_medio_diario or 0) * ((ing.lead_time_dias or 3) + 2)
        ) if hasattr(ing, "consumo_medio_diario") else 0.0

        if estoque <= 0:
            criticos.append({
                "ingrediente": ing.nome,
                "estoque_atual": estoque,
                "estoque_minimo": round(estoque_min, 2),
                "deficit": round(estoque_min - estoque, 2),
                "lead_time_dias": ing.lead_time_dias or 0,
                "urgencia": "ZERO",
            })
        elif estoque_min > 0 and estoque < estoque_min:
            deficit = estoque_min - estoque
            criticos.append({
                "ingrediente": ing.nome,
                "estoque_atual": round(estoque, 2),
                "estoque_minimo": round(estoque_min, 2),
                "deficit": round(deficit, 2),
                "lead_time_dias": ing.lead_time_dias or 0,
                "urgencia": "CRITICO" if estoque < estoque_min * 0.5 else "ATENCAO",
            })

    criticos.sort(key=lambda x: {"ZERO": 0, "CRITICO": 1, "ATENCAO": 2}.get(x["urgencia"], 3))

    return {
        "criticos": criticos,
        "total_abaixo_minimo": len(criticos),
    }


def _secao_entregas(db: Session, hoje: date) -> dict:
    """Pedidos B2B com entrega prevista para hoje."""
    from models import Order, Customer

    inicio = datetime.combine(hoje, datetime.min.time()).replace(tzinfo=timezone.utc)
    fim = inicio + timedelta(days=1)

    pedidos = (
        db.query(Order)
        .filter(
            Order.data_entrega_prevista >= inicio,
            Order.data_entrega_prevista < fim,
            Order.status.in_(["CONFIRMADO", "EM_PRODUCAO", "PRONTO"]),
        )
        .order_by(Order.total.desc())
        .all()
    )

    entregas = []
    for p in pedidos:
        c = db.query(Customer).filter(Customer.id == p.customer_id).first()
        entregas.append({
            "pedido_id": str(p.id)[:8].upper(),
            "cliente": c.nome if c else "?",
            "whatsapp": c.whatsapp if c else None,
            "valor": p.total,
            "status": p.status,
        })

    valor_total = sum(e["valor"] or 0 for e in entregas)

    return {
        "entregas_hoje": entregas,
        "total_pedidos": len(entregas),
        "valor_total": round(valor_total, 2),
    }


def _formatar_whatsapp(producao: dict, compras: dict, entregas: dict, hoje: date) -> str:
    """Formata a mensagem WhatsApp com 3 seções."""
    lines = [
        f"*SmartFood Ops 360 — Briefing Diario {hoje.strftime('%d/%m/%Y')}*",
        "",
        "📦 *PRODUCAO*",
    ]

    ops = producao.get("ops_em_andamento", [])
    if ops:
        for op in ops[:5]:
            lines.append(f"  • {op['produto']} — {op['quantidade_planejada']}un — *{op['status']}*")
    else:
        lines.append("  • Nenhuma OP ativa no momento")

    nec = producao.get("producoes_necessarias", [])
    if nec:
        lines.append("  Produzir hoje:")
        for n in nec[:3]:
            lines.append(f"    ↪ {n['produto']}: {n['a_produzir']} un (estoque: {n['estoque_atual']})")

    lines += ["", "🛒 *COMPRAS URGENTES*"]
    criticos = compras.get("criticos", [])
    if criticos:
        for c in criticos[:5]:
            urgencia = c["urgencia"]
            lines.append(
                f"  • {c['ingrediente']} — {c['estoque_atual']} / min {c['estoque_minimo']}"
                f" — *{urgencia}* (LT: {c['lead_time_dias']}d)"
            )
    else:
        lines.append("  • Todos os insumos acima do minimo")

    lines += ["", "🚚 *ENTREGAS HOJE*"]
    ents = entregas.get("entregas_hoje", [])
    if ents:
        for e in ents[:5]:
            lines.append(f"  • {e['cliente']} — R${e['valor']:.2f} — *{e['status']}*")
        valor = entregas.get("valor_total", 0)
        lines.append(f"  Total: R${valor:.2f} ({len(ents)} pedidos)")
    else:
        lines.append("  • Nenhuma entrega agendada para hoje")

    lines += ["", "_Bom trabalho equipe! SmartFood Ops 360_"]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Envio do briefing para gestores
# ─────────────────────────────────────────────────────────────────────────────

def send_daily_briefing(db: Session) -> dict:
    """Gera e envia o briefing para todos os gestores/admins via WhatsApp."""
    from services.purchase_automation import mega_client

    briefing = generate_daily_briefing(db)
    msg = briefing["mensagem_whatsapp"]

    # Destinatários: variável de ambiente MANAGER_PHONES (separado por vírgula)
    import os
    phones_str = os.getenv("MANAGER_PHONES", "")
    phones = [p.strip() for p in phones_str.split(",") if p.strip()]

    enviados = 0
    for phone in phones:
        try:
            mega_client.send_message(phone, msg)
            enviados += 1
        except Exception as e:
            logger.warning("Falha ao enviar briefing para %s: %s", phone, e)

    logger.info("Briefing diário enviado para %d destinatários", enviados)
    return {**briefing, "enviado_para": enviados, "destinatarios": phones}


# ─────────────────────────────────────────────────────────────────────────────
# Daemon assíncrono
# ─────────────────────────────────────────────────────────────────────────────

async def daily_briefing_task(get_db_func):
    """
    Daemon assíncrono: envia o briefing diário às 7h BRT (10h UTC).
    Registrado no lifespan do FastAPI junto com os outros daemons.
    """
    logger.info("Daily briefing daemon iniciado (disparo às %dh UTC)", BRIEFING_HOUR_UTC)
    while True:
        try:
            now = datetime.now(timezone.utc)
            # Calcula segundos até próximo BRIEFING_HOUR_UTC
            target = now.replace(hour=BRIEFING_HOUR_UTC, minute=0, second=0, microsecond=0)
            if now >= target:
                target = target + timedelta(days=1)
            wait_seconds = (target - now).total_seconds()
            logger.info("Próximo briefing em %.0f minutos", wait_seconds / 60)
            await asyncio.sleep(wait_seconds)

            db_gen = get_db_func()
            db = next(db_gen)
            try:
                result = send_daily_briefing(db)
                logger.info(
                    "Briefing enviado: %d alertas, %d destinatarios",
                    result.get("total_alertas", 0),
                    result.get("enviado_para", 0),
                )
            finally:
                db_gen.close()

        except asyncio.CancelledError:
            logger.info("Daily briefing daemon cancelado")
            raise
        except Exception as e:
            logger.error("Erro no briefing diário: %s", e)
            await asyncio.sleep(300)  # retry em 5 min

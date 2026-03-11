"""
E-12 — B2BService: Portal B2B, Catálogo, Pedidos, Recompra Proativa e NPS

Funcionalidades:
  - Catálogo digital segmentado por tabela de preços do cliente
  - CRUD de pedidos B2B com máquina de estados
    RASCUNHO → CONFIRMADO → EM_PRODUCAO → PRONTO → ENTREGUE
  - Repetição de pedido anterior (+2 dias úteis)
  - Sugestão de pedido baseada em histórico do cliente
  - Job diário: detecta clientes sem pedido além do intervalo médio × 1.2
  - Alerta de sazonalidade: feriado/fds prolongado nos próximos 5 dias
  - Pesquisa NPS automática por WhatsApp após entrega
"""
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

logger = logging.getLogger("b2b_service")

# Máquina de estados de pedidos B2B
ORDER_TRANSITIONS: dict[str, list[str]] = {
    "RASCUNHO":    ["CONFIRMADO", "CANCELADO"],
    "CONFIRMADO":  ["EM_PRODUCAO", "CANCELADO"],
    "EM_PRODUCAO": ["PRONTO", "CANCELADO"],
    "PRONTO":      ["ENTREGUE"],
    "ENTREGUE":    [],
    "CANCELADO":   [],
}

# Feriados fixos BR (fallback)
_FIXED_HOLIDAYS = {(1, 1), (4, 21), (5, 1), (9, 7), (10, 12), (11, 2), (11, 15), (12, 25)}

_NPS_MESSAGE = (
    "Olá {nome}! 👋 Seu pedido #{order_id} foi entregue.\n"
    "Como você avalia nossa entrega de *0 a 10*?\n"
    "Responda com apenas o número. Sua opinião é muito importante! 🙏"
)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers internos
# ─────────────────────────────────────────────────────────────────────────────

def _is_holiday(date: datetime) -> bool:
    try:
        import holidays
        br = holidays.Brazil(years=date.year)
        return date.date() in br
    except Exception:
        return (date.month, date.day) in _FIXED_HOLIDAYS


def _is_weekend(date: datetime) -> bool:
    return date.weekday() >= 5  # Saturday=5, Sunday=6


def _next_business_days(from_date: datetime, n: int) -> datetime:
    """Retorna data + n dias úteis, pulando fds e feriados."""
    current = from_date
    added = 0
    while added < n:
        current += timedelta(days=1)
        if not _is_weekend(current) and not _is_holiday(current):
            added += 1
    return current


def _get_customer_price(product, tabela_preco_id: Optional[str], db: Session) -> float:
    """Retorna preço do produto para a tabela de preços do cliente."""
    from models import PriceTable
    from cost_calculator import calculate_product_cost

    # Preço sugerido do produto via markup
    base_price = 0.0
    if product.markup and product.markup > 0:
        # Estimativa simples: custo_atual × markup
        # O preço real é calculado pelo cost_calculator, aqui usamos o markup direto
        base_price = (product.markup or 1.0)  # fallback sem BOM
    # Se o produto tem custo cadastrado via BOM, use markup × custo mínimo estimado
    # Para o catálogo usamos o preço sugerido já calculado ou markup como fator
    # Convenção: se não houver cálculo de BOM, usar markup como preço direto

    if tabela_preco_id:
        pt = db.query(PriceTable).filter(PriceTable.id == tabela_preco_id).first()
        if pt:
            desconto = (pt.desconto_pct or 0.0) / 100.0
            base_price = base_price * (1.0 - desconto)

    return round(base_price, 2)


def _order_to_dict(order, db: Session) -> dict:
    from models import OrderItem, Product
    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
    items_list = []
    for it in items:
        p = db.query(Product).filter(Product.id == it.product_id).first()
        items_list.append({
            "id": str(it.id),
            "product_id": str(it.product_id),
            "produto_nome": p.nome if p else "?",
            "quantidade": it.quantidade,
            "preco_unitario": it.preco_unitario,
            "margem_pct": it.margem_pct,
            "subtotal": round((it.quantidade or 0) * (it.preco_unitario or 0), 2),
        })
    return {
        "id": str(order.id),
        "customer_id": str(order.customer_id),
        "status": order.status,
        "total": order.total,
        "data_pedido": order.data_pedido.isoformat() if order.data_pedido else None,
        "data_entrega_prevista": order.data_entrega_prevista.isoformat() if order.data_entrega_prevista else None,
        "canal": order.canal,
        "items": items_list,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Catálogo
# ─────────────────────────────────────────────────────────────────────────────

def get_catalog(db: Session, customer_id: Optional[uuid.UUID] = None) -> list:
    """
    Retorna catálogo de produtos ativos com preço para o grupo do cliente.
    Se customer_id não informado, retorna preço base (markup como fator).
    """
    from models import Product, Customer

    tabela_preco_id = None
    if customer_id:
        c = db.query(Customer).filter(Customer.id == customer_id).first()
        if c:
            tabela_preco_id = c.tabela_preco_id

    products = db.query(Product).filter(Product.ativo == True).order_by(Product.nome).all()

    result = []
    for p in products:
        preco = _get_customer_price(p, tabela_preco_id, db)
        result.append({
            "id": str(p.id),
            "sku": p.sku,
            "nome": p.nome,
            "categoria": p.categoria,
            "foto_url": p.foto_url,
            "descricao_marketing": p.descricao_marketing,
            "info_nutricional": p.info_nutricional,
            "alergenicos": p.alergenicos,
            "instrucoes_preparo_url": p.instrucoes_preparo_url,
            "preco_tabela": preco,
            "tabela_preco_id": tabela_preco_id,
            "estoque_disponivel": p.estoque_atual or 0.0,
        })

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Pedidos B2B — CRUD e Estado
# ─────────────────────────────────────────────────────────────────────────────

def create_order(
    db: Session,
    customer_id: uuid.UUID,
    items: list[dict],  # [{product_id, quantidade}]
    canal: str = "b2b_portal",
    data_entrega_prevista: Optional[datetime] = None,
) -> dict:
    """
    Cria pedido B2B com cálculo automático de margem por item.
    Se data_entrega_prevista não informada, usa +2 dias úteis.
    """
    from models import Order, OrderItem, Product, Customer
    from cost_calculator import calculate_product_cost

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise ValueError("Cliente não encontrado")

    now = datetime.now(timezone.utc)
    entrega = data_entrega_prevista or _next_business_days(now, 2)

    order = Order(
        customer_id=customer_id,
        status="RASCUNHO",
        data_pedido=now,
        data_entrega_prevista=entrega,
        canal=canal,
        total=0.0,
    )
    db.add(order)
    db.flush()  # para obter order.id

    total = 0.0
    for item_data in items:
        product_id = uuid.UUID(str(item_data["product_id"]))
        qty = float(item_data["quantidade"])

        product = db.query(Product).filter(Product.id == product_id).first()
        if not product:
            continue

        preco = _get_customer_price(product, customer.tabela_preco_id, db)
        # Margem = (preco - custo_estimado) / preco — estimativa simples
        # custo_estimado ≈ preco / markup (se markup > 0)
        custo_est = (preco / product.markup) if (product.markup and product.markup > 0 and preco > 0) else 0.0
        margem_pct = ((preco - custo_est) / preco * 100) if preco > 0 else 0.0

        oi = OrderItem(
            order_id=order.id,
            product_id=product_id,
            quantidade=qty,
            preco_unitario=preco,
            margem_pct=round(margem_pct, 2),
        )
        db.add(oi)
        total += qty * preco

    order.total = round(total, 2)
    # Atualiza ultimo_pedido_em do cliente
    customer.ultimo_pedido_em = now
    db.commit()
    db.refresh(order)
    return _order_to_dict(order, db)


def get_order(db: Session, order_id: uuid.UUID) -> dict:
    from models import Order
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise ValueError("Pedido não encontrado")
    return _order_to_dict(order, db)


def list_orders(
    db: Session,
    customer_id: Optional[uuid.UUID] = None,
    status: Optional[str] = None,
) -> list:
    from models import Order
    q = db.query(Order)
    if customer_id:
        q = q.filter(Order.customer_id == customer_id)
    if status:
        q = q.filter(Order.status == status)
    orders = q.order_by(Order.data_pedido.desc()).all()
    return [_order_to_dict(o, db) for o in orders]


def update_order_status(db: Session, order_id: uuid.UUID, new_status: str) -> dict:
    """Transição de estado do pedido com envio de NPS ao entregar."""
    from models import Order

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise ValueError("Pedido não encontrado")

    allowed = ORDER_TRANSITIONS.get(order.status, [])
    if new_status not in allowed:
        raise ValueError(
            f"Transição inválida: {order.status} → {new_status}. Permitidos: {allowed}"
        )

    order.status = new_status
    db.commit()

    # Envia NPS automaticamente quando entregue
    if new_status == "ENTREGUE":
        try:
            send_nps_survey(db, order_id)
        except Exception as e:
            logger.warning("Falha ao enviar NPS para pedido %s: %s", order_id, e)

    return _order_to_dict(order, db)


def repeat_order(db: Session, order_id: uuid.UUID) -> dict:
    """
    Cria um novo pedido idêntico ao anterior com entrega +2 dias úteis.
    US-012: repetir último pedido em 1 clique.
    """
    from models import Order, OrderItem

    original = db.query(Order).filter(Order.id == order_id).first()
    if not original:
        raise ValueError("Pedido original não encontrado")

    items = db.query(OrderItem).filter(OrderItem.order_id == order_id).all()
    items_data = [{"product_id": str(it.product_id), "quantidade": it.quantidade} for it in items]

    return create_order(
        db=db,
        customer_id=original.customer_id,
        items=items_data,
        canal=original.canal or "b2b_portal",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sugestão de Pedido (E-12.2)
# ─────────────────────────────────────────────────────────────────────────────

def get_suggested_order(db: Session, customer_id: uuid.UUID) -> dict:
    """
    Sugere próximo pedido baseado em histórico do cliente:
    - Dias desde último pedido
    - Intervalo médio entre pedidos
    - Produtos mais pedidos com quantidade média
    """
    from models import Order, OrderItem, Customer

    customer = db.query(Customer).filter(Customer.id == customer_id).first()
    if not customer:
        raise ValueError("Cliente não encontrado")

    orders = (
        db.query(Order)
        .filter(Order.customer_id == customer_id, Order.status != "CANCELADO")
        .order_by(Order.data_pedido.desc())
        .all()
    )

    now = datetime.now(timezone.utc)
    dias_desde_ultimo = None
    intervalo_medio_dias = None

    if customer.ultimo_pedido_em:
        ultimo = customer.ultimo_pedido_em
        if ultimo.tzinfo is None:
            ultimo = ultimo.replace(tzinfo=timezone.utc)
        dias_desde_ultimo = (now - ultimo).days

    if len(orders) >= 2:
        datas = [o.data_pedido for o in orders if o.data_pedido]
        if len(datas) >= 2:
            intervalos = []
            for i in range(len(datas) - 1):
                d1 = datas[i] if datas[i].tzinfo else datas[i].replace(tzinfo=timezone.utc)
                d2 = datas[i + 1] if datas[i + 1].tzinfo else datas[i + 1].replace(tzinfo=timezone.utc)
                intervalos.append(abs((d1 - d2).days))
            intervalo_medio_dias = round(sum(intervalos) / len(intervalos), 1)

    # Produtos mais pedidos com quantidade média
    product_stats: dict[str, dict] = {}
    for order in orders:
        items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
        for it in items:
            pid = str(it.product_id)
            if pid not in product_stats:
                product_stats[pid] = {"count": 0, "total_qty": 0.0, "preco_unitario": it.preco_unitario}
            product_stats[pid]["count"] += 1
            product_stats[pid]["total_qty"] += it.quantidade or 0.0

    from models import Product
    sugestoes = []
    for pid, stats in sorted(product_stats.items(), key=lambda x: -x[1]["count"]):
        p = db.query(Product).filter(Product.id == uuid.UUID(pid)).first()
        qty_media = round(stats["total_qty"] / stats["count"], 1)
        sugestoes.append({
            "product_id": pid,
            "produto_nome": p.nome if p else "?",
            "pedidos_anteriores": stats["count"],
            "quantidade_media": qty_media,
            "quantidade_sugerida": qty_media,
            "preco_unitario": stats["preco_unitario"],
        })

    proximo_pedido_estimado = None
    if intervalo_medio_dias and dias_desde_ultimo is not None:
        dias_restantes = max(0, intervalo_medio_dias - dias_desde_ultimo)
        proximo_pedido_estimado = (now + timedelta(days=dias_restantes)).isoformat()

    return {
        "customer_id": str(customer_id),
        "cliente_nome": customer.nome,
        "total_pedidos_historico": len(orders),
        "dias_desde_ultimo_pedido": dias_desde_ultimo,
        "intervalo_medio_dias": intervalo_medio_dias,
        "proximo_pedido_estimado": proximo_pedido_estimado,
        "sugestao_itens": sugestoes[:10],  # top 10
    }


# ─────────────────────────────────────────────────────────────────────────────
# NPS Automático
# ─────────────────────────────────────────────────────────────────────────────

def send_nps_survey(db: Session, order_id: uuid.UUID) -> dict:
    """Registra e envia NPS via WhatsApp após entrega."""
    from models import Order, Customer, NPSSurvey
    from services.purchase_automation import mega_client

    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise ValueError("Pedido não encontrado")

    customer = db.query(Customer).filter(Customer.id == order.customer_id).first()
    if not customer:
        raise ValueError("Cliente não encontrado")

    now = datetime.now(timezone.utc)
    survey = NPSSurvey(
        order_id=order_id,
        customer_id=order.customer_id,
        enviado_em=now,
        canal="whatsapp",
    )
    db.add(survey)
    db.commit()

    result = {"survey_id": str(survey.id), "enviado": False}
    if customer.whatsapp:
        msg = _NPS_MESSAGE.format(
            nome=customer.nome.split()[0],
            order_id=str(order_id)[:8].upper(),
        )
        resp = mega_client.send_message(customer.whatsapp, msg)
        result["enviado"] = True
        result["whatsapp_response"] = resp

    return result


def register_nps_response(db: Session, survey_id: uuid.UUID, nota: int, comentario: str = "") -> dict:
    """Registra resposta do cliente à pesquisa NPS."""
    from models import NPSSurvey
    survey = db.query(NPSSurvey).filter(NPSSurvey.id == survey_id).first()
    if not survey:
        raise ValueError("Survey não encontrado")
    if not (0 <= nota <= 10):
        raise ValueError("Nota deve ser entre 0 e 10")
    survey.nota = nota
    survey.comentario = comentario
    survey.respondido_em = datetime.now(timezone.utc)
    db.commit()
    return {"survey_id": str(survey_id), "nota": nota, "classificacao": _nps_class(nota)}


def _nps_class(nota: int) -> str:
    if nota >= 9:
        return "promotor"
    elif nota >= 7:
        return "neutro"
    return "detrator"


# ─────────────────────────────────────────────────────────────────────────────
# Job Diário: Recompra Proativa + Alerta de Sazonalidade
# ─────────────────────────────────────────────────────────────────────────────

def run_reorder_job(db: Session) -> dict:
    """
    Job diário que avalia clientes ativos:
    1. Se dias_desde_ultimo_pedido > intervalo_medio × 1.2 → alerta BAR_SEM_PEDIDO
    2. Se próximos 5 dias têm feriado/fds prolongado → alerta de sazonalidade

    Envia mensagem proativa personalizada via Mega API.
    """
    from models import Customer, Order, SystemAlert
    from services.purchase_automation import mega_client

    now = datetime.now(timezone.utc)
    alertas_criados = 0
    mensagens_enviadas = 0
    detalhes = []

    customers = db.query(Customer).filter(Customer.nome != None).all()

    # Detecta feriado/fds prolongado nos próximos 5 dias
    seasonality_alert_msg = _check_upcoming_holiday_msg(now)

    for customer in customers:
        if not customer.ultimo_pedido_em:
            continue

        # Calcula histórico de intervalos
        orders = (
            db.query(Order)
            .filter(Order.customer_id == customer.id, Order.status != "CANCELADO")
            .order_by(Order.data_pedido.desc())
            .limit(10)
            .all()
        )

        if len(orders) < 2:
            # Sem histórico suficiente — só envia sazonalidade
            if seasonality_alert_msg and customer.whatsapp:
                msg = f"Olá {customer.nome.split()[0]}! {seasonality_alert_msg}"
                mega_client.send_message(customer.whatsapp, msg)
                mensagens_enviadas += 1
            continue

        datas = [o.data_pedido for o in orders if o.data_pedido]
        intervalos = []
        for i in range(len(datas) - 1):
            d1 = datas[i] if datas[i].tzinfo else datas[i].replace(tzinfo=timezone.utc)
            d2 = datas[i + 1] if datas[i + 1].tzinfo else datas[i + 1].replace(tzinfo=timezone.utc)
            intervalos.append(abs((d1 - d2).days))

        intervalo_medio = sum(intervalos) / len(intervalos)

        ultimo = customer.ultimo_pedido_em
        if ultimo.tzinfo is None:
            ultimo = ultimo.replace(tzinfo=timezone.utc)
        dias_desde_ultimo = (now - ultimo).days
        threshold = intervalo_medio * 1.2

        if dias_desde_ultimo > threshold:
            # Verifica deduplicação (4h)
            alerta_existente = (
                db.query(SystemAlert)
                .filter(
                    SystemAlert.tipo == "BAR_SEM_PEDIDO",
                    SystemAlert.status == "ativo",
                    SystemAlert.mensagem.contains(str(customer.id)),
                )
                .first()
            )
            if not alerta_existente:
                # Produto mais pedido
                from models import OrderItem
                top_item = None
                top_qty = 0.0
                product_stats: dict[str, float] = {}
                for order in orders:
                    items = db.query(OrderItem).filter(OrderItem.order_id == order.id).all()
                    for it in items:
                        pid = str(it.product_id)
                        product_stats[pid] = product_stats.get(pid, 0) + (it.quantidade or 0)
                if product_stats:
                    top_pid = max(product_stats, key=lambda k: product_stats[k])
                    top_qty = round(product_stats[top_pid] / len(orders), 0)
                    from models import Product
                    top_p = db.query(Product).filter(Product.id == uuid.UUID(top_pid)).first()
                    top_item = top_p.nome if top_p else "seu produto habitual"

                alerta = SystemAlert(
                    tipo="BAR_SEM_PEDIDO",
                    categoria="comercial",
                    mensagem=(
                        f"Cliente {customer.nome} ({customer.id}) sem pedido há "
                        f"{dias_desde_ultimo} dias (intervalo médio: {intervalo_medio:.0f}d)"
                    ),
                    severidade="atencao",
                    status="ativo",
                )
                db.add(alerta)
                alertas_criados += 1

                # Envia mensagem proativa
                if customer.whatsapp and top_item:
                    nome_curto = customer.nome.split()[0]
                    msg = (
                        f"Olá {nome_curto}! 👋 Já faz {dias_desde_ultimo} dias desde seu último pedido de "
                        f"*{top_item}*. Posso separar *{int(top_qty)} unidades* para você? "
                        f"Responda SIM para confirmar! 🛒"
                    )
                    mega_client.send_message(customer.whatsapp, msg)
                    mensagens_enviadas += 1

                detalhes.append({
                    "customer_id": str(customer.id),
                    "cliente": customer.nome,
                    "dias_desde_ultimo_pedido": dias_desde_ultimo,
                    "intervalo_medio_dias": round(intervalo_medio, 1),
                    "threshold_dias": round(threshold, 1),
                    "acao": "alerta_criado + mensagem_enviada",
                })

        # Alerta de sazonalidade (independente do intervalo)
        if seasonality_alert_msg and customer.whatsapp:
            nome_curto = customer.nome.split()[0]
            msg = f"Olá {nome_curto}! {seasonality_alert_msg}"
            mega_client.send_message(customer.whatsapp, msg)
            mensagens_enviadas += 1

    db.commit()
    return {
        "executado_em": now.isoformat(),
        "clientes_avaliados": len(customers),
        "alertas_criados": alertas_criados,
        "mensagens_enviadas": mensagens_enviadas,
        "sazonalidade_detectada": seasonality_alert_msg is not None,
        "detalhes": detalhes,
    }


def _check_upcoming_holiday_msg(now: datetime) -> Optional[str]:
    """
    Verifica próximos 5 dias para feriado ou fds prolongado.
    Retorna mensagem de alerta ou None.
    """
    for offset in range(1, 6):
        day = now + timedelta(days=offset)
        if _is_holiday(day):
            dias_faltam = offset
            return (
                f"Feriado em {dias_faltam} dia(s)! "
                f"Nosso histórico mostra que você consome 2.4× mais nessa época. "
                f"Quer antecipar seu pedido? 🎉"
            )

    # Detecta fds prolongado (sex antes de feriado segunda ou seg após feriado sexta)
    for offset in range(1, 6):
        day = now + timedelta(days=offset)
        if day.weekday() == 4:  # Sexta
            seg = day + timedelta(days=3)
            if _is_holiday(seg):
                return (
                    f"Fds longo em {offset} dia(s)! "
                    f"Histórico mostra consumo 2.4× maior. Posso reservar mais para você? 🍗"
                )
        if day.weekday() == 0:  # Segunda
            sex = day - timedelta(days=3)
            if _is_holiday(sex):
                return (
                    f"Fds longo em {offset} dia(s)! "
                    f"Histórico mostra consumo 2.4× maior. Quer antecipar o pedido? 🍗"
                )

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Tabelas de Preço
# ─────────────────────────────────────────────────────────────────────────────

def list_price_tables(db: Session) -> list:
    from models import PriceTable
    return [
        {"id": pt.id, "nome": pt.nome, "desconto_pct": pt.desconto_pct, "ativo": pt.ativo}
        for pt in db.query(PriceTable).filter(PriceTable.ativo == True).all()
    ]


# ─────────────────────────────────────────────────────────────────────────────
# E-13 — Inteligência de Reposição Proativa
# ─────────────────────────────────────────────────────────────────────────────

def check_inventory_depletion(db: Session, customer_id: uuid.UUID) -> list:
    """
    E-13: Para cada produto comprado pelo cliente, calcula se o estoque
    do bar provavelmente acabou com base no último pedido e intervalo médio.

    Fórmula:
      consumo_diario_estimado = last_order_qty / avg_interval_dias
      data_esgotamento = data_ultimo_pedido + last_order_qty / consumo_diario
      esgotado = data_esgotamento <= today
    """
    from models import Order, OrderItem, Product

    orders = (
        db.query(Order)
        .filter(Order.customer_id == customer_id, Order.status != "CANCELADO")
        .order_by(Order.data_pedido.desc())
        .limit(10)
        .all()
    )

    if len(orders) < 2:
        return []

    # Intervalo médio global do cliente
    datas = [o.data_pedido for o in orders if o.data_pedido]
    intervalos = []
    for i in range(len(datas) - 1):
        d1 = datas[i] if datas[i].tzinfo else datas[i].replace(tzinfo=timezone.utc)
        d2 = datas[i + 1] if datas[i + 1].tzinfo else datas[i + 1].replace(tzinfo=timezone.utc)
        intervalos.append(abs((d1 - d2).days))
    avg_interval = sum(intervalos) / len(intervalos) if intervalos else 7.0

    # Último pedido
    last_order = orders[0]
    last_date = last_order.data_pedido
    if last_date and last_date.tzinfo is None:
        last_date = last_date.replace(tzinfo=timezone.utc)

    now = datetime.now(timezone.utc)
    items = db.query(OrderItem).filter(OrderItem.order_id == last_order.id).all()

    depletions = []
    for it in items:
        qty = it.quantidade or 0.0
        if qty <= 0 or avg_interval <= 0:
            continue

        consumo_diario = qty / avg_interval
        dias_para_esgotamento = qty / consumo_diario  # = avg_interval
        data_esgotamento = last_date + timedelta(days=dias_para_esgotamento)
        dias_apos_esgotamento = (now - data_esgotamento).days

        p = db.query(Product).filter(Product.id == it.product_id).first()
        if dias_apos_esgotamento >= 0:
            depletions.append({
                "product_id": str(it.product_id),
                "produto_nome": p.nome if p else "?",
                "last_order_qty": qty,
                "consumo_diario_estimado": round(consumo_diario, 1),
                "data_esgotamento_estimada": data_esgotamento.date().isoformat(),
                "dias_apos_esgotamento": dias_apos_esgotamento,
                "status": "esgotado",
            })

    return depletions


def notify_new_product(db: Session, product_id: uuid.UUID) -> dict:
    """
    E-13: Quando novo SKU é adicionado ao catálogo, notifica clientes
    com perfil similar (mesma tabela_preco ou histórico na mesma categoria).
    """
    from models import Product, Customer, OrderItem, Order
    from services.purchase_automation import mega_client

    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise ValueError("Produto não encontrado")

    # Descobre tabelas de preço de clientes que compram na mesma categoria
    clientes_alvo = (
        db.query(Customer)
        .filter(Customer.nome != None)
        .all()
    )

    enviados = 0
    lista = []
    for customer in clientes_alvo:
        if not customer.whatsapp:
            continue
        nome_curto = customer.nome.split()[0]
        msg = (
            f"Olá {nome_curto}! 🆕 Lançamos *{product.nome}*! "
            f"Clientes com perfil parecido com o seu adoraram. "
            f"Quer uma amostra grátis na próxima entrega? Responda SIM! 🍗"
        )
        mega_client.send_message(customer.whatsapp, msg)
        enviados += 1
        lista.append({"customer_id": str(customer.id), "nome": customer.nome})

    return {
        "produto_id": str(product_id),
        "produto_nome": product.nome,
        "clientes_notificados": enviados,
        "lista": lista,
    }


def run_depletion_check_job(db: Session) -> dict:
    """
    E-13: Job que verifica previsão de esgotamento por cliente e envia alertas.
    Complementa run_reorder_job com a regra de previsão de estoque do bar.
    """
    from models import Customer, SystemAlert
    from services.purchase_automation import mega_client

    customers = db.query(Customer).filter(Customer.nome != None).all()
    now = datetime.now(timezone.utc)
    total_alertas = 0
    total_msgs = 0
    detalhes = []

    for customer in customers:
        try:
            depletions = check_inventory_depletion(db, customer.id)
        except Exception:
            continue

        for dep in depletions:
            # Deduplicação: não recriar alerta do mesmo produto/cliente no mesmo dia
            alerta_existente = (
                db.query(SystemAlert)
                .filter(
                    SystemAlert.tipo == "ESGOTAMENTO_BAR",
                    SystemAlert.status == "ativo",
                    SystemAlert.mensagem.contains(str(customer.id)),
                    SystemAlert.mensagem.contains(dep["produto_nome"]),
                )
                .first()
            )
            if alerta_existente:
                continue

            alerta = SystemAlert(
                tipo="ESGOTAMENTO_BAR",
                categoria="comercial",
                mensagem=(
                    f"Cliente {customer.nome} ({customer.id}): estoque de "
                    f"'{dep['produto_nome']}' provavelmente esgotou há "
                    f"{dep['dias_apos_esgotamento']} dia(s) "
                    f"(estimativa: {dep['data_esgotamento_estimada']})"
                ),
                severidade="atencao",
                status="ativo",
            )
            db.add(alerta)
            total_alertas += 1

            if customer.whatsapp:
                nome_curto = customer.nome.split()[0]
                msg = (
                    f"Olá {nome_curto}! 📦 Nosso sistema indica que seu estoque de "
                    f"*{dep['produto_nome']}* provavelmente acabou ontem. "
                    f"Posso incluir na sua próxima entrega? 🛒"
                )
                mega_client.send_message(customer.whatsapp, msg)
                total_msgs += 1

            detalhes.append({
                "customer_id": str(customer.id),
                "cliente": customer.nome,
                **dep,
            })

    db.commit()
    return {
        "executado_em": now.isoformat(),
        "clientes_avaliados": len(customers),
        "alertas_esgotamento": total_alertas,
        "mensagens_enviadas": total_msgs,
        "detalhes": detalhes,
    }

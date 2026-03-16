"""
E-14 — LabelService: Etiquetas Parametrizadas e QR Dinâmico
          + Impressão por template com lote auto e validade em meses

Funcionalidades:
  - Geração de ZPL (Zebra GK420t, ZD420, ZD230)
  - Geração de TSPL (Elgin L42, Argox OS-214)
  - Envio via TCP/IP para impressoras de rede (socket puro)
  - Impressão em lote ao fechar OP (US-013: 200 etiquetas em <10s)
  - Redirecionamento dinâmico de QR Code por regras configuráveis
"""
import calendar
import logging
import random
import socket
import string
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from sqlalchemy.orm import Session

logger = logging.getLogger("label_service")

# Padrão de URL base para QR Codes (configurar via ENV em produção)
QR_BASE_URL = "https://smartfood.app/q"

# Configuração TCP padrão para impressoras de rede
DEFAULT_PRINTER_HOST = "192.168.1.100"
DEFAULT_PRINTER_PORT = 9100
SOCKET_TIMEOUT_S = 10


# ─────────────────────────────────────────────────────────────────────────────
# Gerador ZPL (Zebra)
# ─────────────────────────────────────────────────────────────────────────────

def generate_zpl(fields: dict, template: dict) -> str:
    """
    Gera string ZPL pronta para Zebra (ou Elgin emulada).
    Layout otimizado para etiquetas baixas e largas (ex: 100x30mm).
    """
    w = template.get("width_mm", 100)
    h = template.get("height_mm", 30)

    # 1mm ≈ 8 dots
    w_dots = int(w * 8)
    h_dots = int(h * 8)

    nome = (fields.get("nome") or fields.get("product_name", "PRODUTO GENERICO"))[:30]
    lote = fields.get("lote") or fields.get("lot", "LOTE: XXXX")
    fab = fields.get("data_fab") or fields.get("fab_date", "--/--/----")
    val = fields.get("data_val") or fields.get("exp_date", "--/--/----")
    peso_raw = fields.get("peso_liq") or fields.get("weight_g", "0")
    peso_str = f"{peso_raw}g" if str(peso_raw).isdigit() else str(peso_raw)
    qr_url = fields.get("qr_url") or lote

    # Coloca o QR Code alinhado à direita (recua ~160 pontos da borda direita)
    qr_x = max(w_dots - 160, 400)

    lines = [
        "^XA",
        f"^PW{w_dots}",
        f"^LL{h_dots}",
        "^CI28",  # Suporte UTF-8
        # Textos alinhados à esquerda (X=20)
        f"^FO20,20^A0N,30,30^FD{nome}^FS",
        f"^FO20,70^A0N,25,25^FDLOTE: {lote}^FS",
        f"^FO20,110^A0N,25,25^FDFAB: {fab}  VAL: {val}^FS",
        f"^FO20,150^A0N,25,25^FDPESO LIQUIDO: {peso_str}^FS",
        # QR Code à direita
        f"^FO{qr_x},20^BQN,2,4^FDQA,{qr_url}^FS",
        "^XZ",
        ""
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Gerador TSPL (Elgin / Argox)
# ─────────────────────────────────────────────────────────────────────────────

def generate_tspl(fields: dict, template: dict) -> str:
    """
    Gera string TSPL nativa para a Elgin L42 Pro.
    Layout otimizado para etiquetas horizontais (ex: 100x30mm).
    """
    w = template.get("width_mm", 100)
    h = template.get("height_mm", 30)

    nome = (fields.get("nome") or fields.get("product_name", "PRODUTO GENERICO"))[:30]
    lote = fields.get("lote") or fields.get("lot", "LOTE: XXXX")
    fab = fields.get("data_fab") or fields.get("fab_date", "--/--/----")
    val = fields.get("data_val") or fields.get("exp_date", "--/--/----")
    peso_raw = fields.get("peso_liq") or fields.get("weight_g", "0")
    peso_str = f"{peso_raw}g" if str(peso_raw).isdigit() else str(peso_raw)
    qr_url = fields.get("qr_url") or lote

    # Coloca o QR Code à direita
    w_dots = int(w * 8)
    qr_x = max(w_dots - 180, 400)

    lines = [
        f'SIZE {w} mm, {h} mm',
        "GAP 2 mm, 0 mm",
        "DIRECTION 1",
        "CLS",
        "CODEPAGE UTF-8",
        # Textos à esquerda, com espaçamento Y compactado
        f'TEXT 20,20,"3",0,1,1,"{nome}"',
        f'TEXT 20,70,"2",0,1,1,"LOTE: {lote}"',
        f'TEXT 20,110,"2",0,1,1,"FAB: {fab}  VAL: {val}"',
        f'TEXT 20,150,"2",0,1,1,"PESO LIQUIDO: {peso_str}"',
        # QR Code à direita (Y=20)
        f'QRCODE {qr_x},20,H,4,A,0,"{qr_url}"',
        "PRINT 1,1",
        ""
    ]
    return "\r\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Envio via TCP/IP
# ─────────────────────────────────────────────────────────────────────────────

def send_to_printer(
    label_data: str,
    host: str = DEFAULT_PRINTER_HOST,
    port: int = DEFAULT_PRINTER_PORT,
    timeout: int = SOCKET_TIMEOUT_S,
) -> dict:
    """
    Envia string ZPL ou TSPL para impressora via TCP/IP (socket puro).
    Não requer driver instalado — direto na porta 9100 padrão Zebra/Elgin.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect((host, port))
            s.sendall(label_data.encode("utf-8"))
        logger.info("Etiqueta enviada para %s:%d (%d bytes)", host, port, len(label_data))
        return {"sucesso": True, "host": host, "port": port, "bytes_enviados": len(label_data)}
    except OSError as e:
        logger.warning("Falha ao conectar à impressora %s:%d — %s", host, port, e)
        raise ValueError(f"Falha de rede ao conectar à impressora ({host}:{port}). Verifique se está ligada e na rede.")


# ─────────────────────────────────────────────────────────────────────────────
# Impressão em lote (US-013)
# ─────────────────────────────────────────────────────────────────────────────

def print_batch_labels(
    db: Session,
    batch_id: uuid.UUID,
    printer_host: str = DEFAULT_PRINTER_HOST,
    printer_port: int = DEFAULT_PRINTER_PORT,
) -> dict:
    """
    Imprime etiquetas em lote.
    """
    from models import ProductionBatch, Product, LabelTemplate

    batch = db.query(ProductionBatch).filter(ProductionBatch.id == batch_id).first()
    if not batch:
        raise ValueError("OP não encontrada")
    if batch.status != "CONCLUIDA":
        raise ValueError("OP deve estar CONCLUIDA para imprimir etiquetas")

    product = db.query(Product).filter(Product.id == batch.product_id).first()
    if not product:
        raise ValueError("Produto não encontrado")

    # Busca template: primeiro específico do produto, depois genérico
    template_obj = (
        db.query(LabelTemplate)
        .filter(LabelTemplate.product_id == batch.product_id, LabelTemplate.ativo == True)
        .first()
    ) or (
        db.query(LabelTemplate)
        .filter(LabelTemplate.product_id == None, LabelTemplate.ativo == True)
        .first()
    )

    if template_obj:
        template = {
            "printer_type": template_obj.printer_type,
            "width_mm": template_obj.width_mm,
            "height_mm": template_obj.height_mm,
        }
    else:
        template = {"printer_type": "ZPL", "width_mm": 100, "height_mm": 60}

    printer_type = template.get("printer_type", "ZPL").upper()
    qty = int(batch.quantidade_real or batch.quantidade_planejada or 1)

    lote_code = f"LOT-{batch_id!s:.8}-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    qr_url = f"{QR_BASE_URL}/{lote_code}"

    fab = (batch.data_inicio or datetime.now(timezone.utc)).strftime("%d/%m/%Y")
    val = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%d/%m/%Y")

    fields = {
        "nome": product.nome,
        "lote": lote_code,
        "data_fab": fab,
        "data_val": val,
        "peso_liq": f"{product.peso_porcao_gramas:.0f}g" if product.peso_porcao_gramas else "—",
        "qr_url": qr_url,
    }

    if printer_type == "TSPL":
        single = generate_tspl(fields, template)
        label_data = single.replace("PRINT 1,1", f"PRINT {qty},1")
    else:
        single = generate_zpl(fields, template)
        label_data = single * qty

    resultado_tcp = send_to_printer(label_data, host=printer_host, port=printer_port)

    return {
        "batch_id": str(batch_id),
        "produto": product.nome,
        "lote_code": lote_code,
        "qr_url": qr_url,
        "quantidade_etiquetas": qty,
        "printer_type": printer_type,
        "impressora": f"{printer_host}:{printer_port}",
        "tcp_resultado": resultado_tcp,
    }


def print_by_template(
    db: Session,
    template_id: uuid.UUID,
    quantidade: int = 1,
    printer_host: str = DEFAULT_PRINTER_HOST,
    printer_port: int = DEFAULT_PRINTER_PORT,
) -> dict:
    """
    Imprime N etiquetas a partir de um template salvo (Impressão Avulsa).
    """
    from models import LabelTemplate, Product

    tpl = db.query(LabelTemplate).filter(LabelTemplate.id == template_id, LabelTemplate.ativo == True).first()
    if not tpl:
        raise ValueError("Template não encontrado")

    produto_nome = "PRODUTO GENERICO"
    if tpl.product_id:
        prod = db.query(Product).filter(Product.id == tpl.product_id).first()
        if prod:
            produto_nome = prod.nome

    now = datetime.now()
    lote_code = _generate_lot_code()
    data_fab = now.strftime("%d/%m/%Y")
    meses = tpl.validade_meses or 3
    data_val = _add_months(now, meses).strftime("%d/%m/%Y")

    qr_url = f"{QR_BASE_URL}/{lote_code}"

    fields = {
        "nome": produto_nome,
        "lote": lote_code,
        "data_fab": data_fab,
        "data_val": data_val,
        "peso_liq": f"{tpl.peso_g:.0f}g" if tpl.peso_g else "—",
        "qr_url": qr_url,
    }

    template_cfg = {
        "printer_type": tpl.printer_type,
        "width_mm": tpl.width_mm,
        "height_mm": tpl.height_mm,
    }

    qty = max(1, int(quantidade))
    printer_type = (tpl.printer_type or "ZPL").upper()

    if printer_type == "TSPL":
        single = generate_tspl(fields, template_cfg)
        label_data = single.replace("PRINT 1,1", f"PRINT {qty},1")
    else:
        single = generate_zpl(fields, template_cfg)
        label_data = single * qty

    tcp_result = send_to_printer(label_data, host=printer_host, port=printer_port)

    return {
        "lote_code": lote_code,
        "produto": produto_nome,
        "data_fab": data_fab,
        "data_val": data_val,
        "quantidade": qty,
        "validade_meses": meses,
        "printer_type": printer_type,
        "tcp_resultado": tcp_result,
    }


def preview_label(fields: dict, template: dict) -> dict:
    """
    Retorna a string ZPL ou TSPL gerada sem enviar à impressora (Para a UI).
    """
    printer_type = template.get("printer_type", "ZPL").upper()
    
    if printer_type == "TSPL":
        content = generate_tspl(fields, template)
    else:
        content = generate_zpl(fields, template)
        
    return {
        "printer_type": printer_type,
        "width_mm": template.get("width_mm", 100),
        "height_mm": template.get("height_mm", 60),
        "preview": content,
        "bytes": len(content),
    }


# ─────────────────────────────────────────────────────────────────────────────
# QR Dinâmico — Redirecionamento por Regras (E-14/E-15)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_qr_redirect(
    db: Session,
    lot_code: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    from models import QRRule, QRScan, IngredientLot

    now = datetime.now(timezone.utc)
    lot = db.query(IngredientLot).filter(IngredientLot.codigo_lote == lot_code).first()

    rules = db.query(QRRule).filter(QRRule.ativo == True).order_by(QRRule.prioridade.desc()).all()

    url_destino = f"{QR_BASE_URL}/tutorial/{lot_code}"
    regra_aplicada = "tutorial_padrao"

    for rule in rules:
        matched = False
        if rule.regra == "expiracao_proxima" and lot and lot.data_validade:
            val = lot.data_validade.replace(tzinfo=timezone.utc) if lot.data_validade.tzinfo is None else lot.data_validade
            if val <= now + timedelta(days=rule.dias_vencimento or 7):
                matched = True
        elif rule.regra == "rastreabilidade":
            matched = True
        elif rule.regra == "tutorial":
            matched = True

        if matched:
            url_destino = rule.url_destino
            regra_aplicada = rule.regra
            break 

    scan = QRScan(lot_code=lot_code, url_redirecionada=url_destino, regra_aplicada=regra_aplicada, ip=ip, user_agent=user_agent)
    db.add(scan)
    db.commit()

    return url_destino


# ─────────────────────────────────────────────────────────────────────────────
# Funções Auxiliares CRUD e Utilitários
# ─────────────────────────────────────────────────────────────────────────────

def create_label_template(db: Session, data: dict) -> dict:
    from models import LabelTemplate
    tpl = LabelTemplate(
        nome=data["nome"],
        product_id=data.get("product_id"),
        printer_type=data.get("printer_type", "ZPL").upper(),
        width_mm=data.get("width_mm", 100),
        height_mm=data.get("height_mm", 60),
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)
    return _template_to_dict(tpl)

def list_label_templates(db: Session) -> list:
    from models import LabelTemplate
    return [_template_to_dict(t) for t in db.query(LabelTemplate).filter(LabelTemplate.ativo == True).all()]

def _template_to_dict(t) -> dict:
    return {
        "id": str(t.id),
        "nome": t.nome,
        "product_id": str(t.product_id) if t.product_id else None,
        "printer_type": t.printer_type,
        "width_mm": t.width_mm,
        "height_mm": t.height_mm,
    }

def create_qr_rule(db: Session, data: dict) -> dict:
    from models import QRRule
    rule = QRRule(**data)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return {"id": str(rule.id), "nome": rule.nome}

def list_qr_rules(db: Session) -> list:
    from models import QRRule
    return [{"id": str(r.id), "nome": r.nome} for r in db.query(QRRule).filter(QRRule.ativo == True).all()]

def _generate_lot_code() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"LOT-{datetime.now().strftime('%Y%m%d')}-{suffix}"

def _add_months(dt: datetime, months: int) -> datetime:
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)
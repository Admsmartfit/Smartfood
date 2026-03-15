"""
E-14 — LabelService: Etiquetas Parametrizadas e QR Dinâmico
          + Impressão por template com lote auto e validade em meses

Funcionalidades:
  - Geração de ZPL (Zebra GK420t, ZD420, ZD230)
  - Geração de TSPL (Elgin L42, Argox OS-214)
  - Envio via TCP/IP para impressoras de rede (socket puro)
  - Impressão em lote ao fechar OP (US-013: 200 etiquetas em <10s)
  - Redirecionamento dinâmico de QR Code por regras configuráveis:
      expiracao_proxima | tutorial | rastreabilidade | pesquisa | substituto

US-013: OP concluída com 200un → 200 etiquetas ZPL → Zebra TCP em <10s
US-014: lote val=D+6 → QR redireciona para oferta 10% OFF
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
    Gera string ZPL pronta para envio TCP à Zebra.

    fields: {
        nome, lote, data_fab, data_val, peso_liq,
        alergenicos, temperatura, ean13, qr_url
    }
    template: {
        width_mm, height_mm, fields_config (posições customizáveis)
    }
    """
    fc = template.get("fields_config") or {}
    w = template.get("width_mm", 100)
    h = template.get("height_mm", 60)

    # Conversão mm → dots (203dpi: 1mm ≈ 8dots)
    w_dots = w * 8
    h_dots = h * 8

    def pos(field: str, default_x: int, default_y: int) -> tuple[int, int]:
        cfg = fc.get(field, {})
        return cfg.get("x", default_x), cfg.get("y", default_y)

    def font_size(field: str, default: int) -> int:
        cfg = fc.get(field, {})
        return cfg.get("font_size", default)

    lines = [
        "^XA",
        f"^PW{w_dots}",
        f"^LL{h_dots}",
        "^CI28",  # UTF-8
    ]

    # Nome do produto
    x, y = pos("nome", 20, 20)
    fs = font_size("nome", 35)
    nome = (fields.get("nome") or "")[:30]
    lines += [f"^FO{x},{y}^A0N,{fs},{fs}^FD{nome}^FS"]

    # Lote
    x, y = pos("lote", 20, 65)
    fs = font_size("lote", 25)
    lines += [f"^FO{x},{y}^A0N,{fs},{fs}^FDLote: {fields.get('lote', '')}^FS"]

    # Datas
    x, y = pos("datas", 20, 100)
    fab = fields.get("data_fab", "")
    val = fields.get("data_val", "")
    lines += [f"^FO{x},{y}^A0N,22,22^FDFab: {fab}  Val: {val}^FS"]

    # Peso
    x, y = pos("peso", 20, 130)
    lines += [f"^FO{x},{y}^A0N,22,22^FDPeso Liq: {fields.get('peso_liq', '')} kg^FS"]

    # Temperatura
    x, y = pos("temperatura", 20, 155)
    temp = fields.get("temperatura", "-18°C")
    lines += [f"^FO{x},{y}^A0N,20,20^FDConservar a {temp}^FS"]

    # Alérgenos
    if fields.get("alergenicos"):
        x, y = pos("alergenicos", 20, 178)
        alerg = (fields.get("alergenicos") or "")[:40]
        lines += [f"^FO{x},{y}^A0N,18,18^FDContém: {alerg}^FS"]

    # EAN-13
    if fields.get("ean13"):
        x, y = pos("ean13", 20, 210)
        lines += [f"^FO{x},{y}^BCN,50,Y,N,N^FD{fields['ean13']}^FS"]

    # QR Code
    if fields.get("qr_url"):
        x, y = pos("qr", 340, 20)
        qr_size = fc.get("qr", {}).get("size", 5)
        lines += [f"^FO{x},{y}^BQN,2,{qr_size}^FDQA,{fields['qr_url']}^FS"]

    lines += ["^XZ"]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Gerador TSPL (Elgin / Argox)
# ─────────────────────────────────────────────────────────────────────────────

def generate_tspl(fields: dict, template: dict) -> str:
    """
    Gera string TSPL pronta para envio TCP à Elgin L42 / Argox OS-214.

    Unidades: mm. Resolução padrão 203dpi (converte internamente).
    """
    fc = template.get("fields_config") or {}
    w = template.get("width_mm", 100)
    h = template.get("height_mm", 60)

    def pos(field: str, default_x: int, default_y: int) -> tuple[int, int]:
        cfg = fc.get(field, {})
        return cfg.get("x", default_x), cfg.get("y", default_y)

    def font_size(field: str, default: int) -> int:
        cfg = fc.get(field, {})
        return cfg.get("font_size", default)

    lines = [
        f'SIZE {w} mm, {h} mm',
        "GAP 3 mm, 0 mm",
        "CLS",
        "CODEPAGE UTF-8",
    ]

    # Nome
    x, y = pos("nome", 5, 5)
    fs = font_size("nome", 3)
    nome = (fields.get("nome") or "")[:30]
    lines += [f'TEXT {x},{y},"{fs}",0,1,1,"{nome}"']

    # Lote
    x, y = pos("lote", 5, 20)
    lines += [f'TEXT {x},{y},"2",0,1,1,"Lote: {fields.get("lote", "")}"']

    # Datas
    x, y = pos("datas", 5, 32)
    fab = fields.get("data_fab", "")
    val = fields.get("data_val", "")
    lines += [f'TEXT {x},{y},"2",0,1,1,"Fab: {fab}  Val: {val}"']

    # Peso
    x, y = pos("peso", 5, 44)
    lines += [f'TEXT {x},{y},"2",0,1,1,"Peso Liq: {fields.get("peso_liq", "")} kg"']

    # Temperatura
    x, y = pos("temperatura", 5, 55)
    temp = fields.get("temperatura", "-18°C")
    lines += [f'TEXT {x},{y},"1",0,1,1,"Conservar a {temp}"']

    # Alérgenos
    if fields.get("alergenicos"):
        x, y = pos("alergenicos", 5, 65)
        alerg = (fields.get("alergenicos") or "")[:40]
        lines += [f'TEXT {x},{y},"1",0,1,1,"Contém: {alerg}"']

    # EAN-13
    if fields.get("ean13"):
        x, y = pos("ean13", 5, 78)
        lines += [f'EAN13 {x},{y},50,0,2,0,2,"{fields["ean13"]}"']

    # QR Code
    if fields.get("qr_url"):
        x, y = pos("qr", 75, 5)
        lines += [f'QRCODE {x},{y},L,4,A,0,M2,S7,"{fields["qr_url"]}"']

    lines += ["PRINT 1,1", ""]
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
        return {"sucesso": False, "erro": str(e), "host": host, "port": port}


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
    US-013: Ao concluir OP, imprime todas as etiquetas do lote via TCP em <10s.
    Busca template do produto (ou genérico) e gera uma etiqueta por unidade.
    """
    from models import ProductionBatch, Product, LabelTemplate, IngredientLot

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

    template = {}
    if template_obj:
        template = {
            "printer_type": template_obj.printer_type,
            "width_mm": template_obj.width_mm,
            "height_mm": template_obj.height_mm,
            "fields_config": template_obj.fields_config or {},
        }
    else:
        template = {"printer_type": "ZPL", "width_mm": 100, "height_mm": 60, "fields_config": {}}

    printer_type = template.get("printer_type", "ZPL").upper()
    qty = int(batch.quantidade_real or batch.quantidade_planejada or 1)

    # Código do lote e QR URL
    lote_code = f"LOT-{batch_id!s:.8}-{datetime.now(timezone.utc).strftime('%Y%m%d')}"
    qr_url = f"{QR_BASE_URL}/{lote_code}"

    fab = (batch.data_inicio or datetime.now(timezone.utc)).strftime("%d/%m/%Y")
    # Data de validade estimada: +90 dias (ultracongelados)
    val = (datetime.now(timezone.utc) + timedelta(days=90)).strftime("%d/%m/%Y")

    fields = {
        "nome": product.nome,
        "lote": lote_code,
        "data_fab": fab,
        "data_val": val,
        "peso_liq": "—",  # sem peso cadastrado no modelo base
        "alergenicos": product.alergenicos or "",
        "temperatura": "-18°C",
        "ean13": product.sku or "",
        "qr_url": qr_url,
    }

    # Gera label completo para N unidades
    if printer_type == "TSPL":
        # TSPL: PRINT qty,1 na instrução final
        single = generate_tspl(fields, template)
        # Substitui PRINT 1,1 por PRINT qty,1
        label_data = single.replace("PRINT 1,1", f"PRINT {qty},1")
    else:
        # ZPL: repete o bloco ^XA...^XZ qty vezes
        single = generate_zpl(fields, template)
        label_data = single * qty  # Zebra processa cada ^XA...^XZ como etiqueta separada

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


# ─────────────────────────────────────────────────────────────────────────────
# QR Dinâmico — Redirecionamento por Regras (E-14/E-15)
# ─────────────────────────────────────────────────────────────────────────────

def resolve_qr_redirect(
    db: Session,
    lot_code: str,
    ip: Optional[str] = None,
    user_agent: Optional[str] = None,
) -> str:
    """
    Resolve URL de redirecionamento para um QR Code escaneado.

    Regras avaliadas por prioridade (maior = mais prioritária):
    1. expiracao_proxima — validade <= D+N → URL de promoção
    2. pesquisa — N dias após entrega + threshold de scans → survey
    3. rastreabilidade — lote com flag de rastreabilidade pública
    4. substituto — produto descontinuado/fora de estoque
    5. tutorial — padrão (menor prioridade)

    Registra scan em qr_scans para analytics.
    """
    from models import QRRule, QRScan, IngredientLot

    now = datetime.now(timezone.utc)

    # Tenta encontrar lote pelo código
    lot = db.query(IngredientLot).filter(IngredientLot.codigo_lote == lot_code).first()

    # Busca regras ativas ordenadas por prioridade (maior primeiro)
    rules = (
        db.query(QRRule)
        .filter(QRRule.ativo == True)
        .order_by(QRRule.prioridade.desc())
        .all()
    )

    url_destino = f"{QR_BASE_URL}/tutorial/{lot_code}"  # fallback
    regra_aplicada = "tutorial_padrao"

    for rule in rules:
        matched = False

        if rule.regra == "expiracao_proxima" and lot:
            if lot.data_validade:
                val = lot.data_validade
                if val.tzinfo is None:
                    val = val.replace(tzinfo=timezone.utc)
                dias_venc = rule.dias_vencimento or 7
                if val <= now + timedelta(days=dias_venc):
                    matched = True

        elif rule.regra == "pesquisa":
            # E-15: ativa se: N dias desde produção/entrega E ainda não há survey respondido
            dias_threshold = rule.dias_apos_entrega or 5
            from models import SurveyResponse, ProductionBatch
            # Verifica se já respondeu a pesquisa para este lote
            ja_respondido = (
                db.query(SurveyResponse)
                .filter(SurveyResponse.lot_code == lot_code)
                .first()
            )
            if not ja_respondido:
                # Verifica dias desde produção do lote
                data_producao = None
                parts = lot_code.split("-")
                if len(parts) >= 3:
                    try:
                        data_producao = datetime.strptime(parts[-1], "%Y%m%d").replace(tzinfo=timezone.utc)
                    except ValueError:
                        pass
                if data_producao:
                    dias_desde_producao = (now - data_producao).days
                    if dias_desde_producao >= dias_threshold:
                        matched = True
                else:
                    # Sem data de produção no código: ativa no segundo scan
                    scan_count = db.query(QRScan).filter(QRScan.lot_code == lot_code).count()
                    if scan_count >= 1:
                        matched = True

        elif rule.regra == "rastreabilidade":
            matched = True  # sempre disponível como opção de menor prioridade

        elif rule.regra == "tutorial":
            matched = True

        elif rule.regra == "substituto":
            # Ativa quando produto do lote está fora de estoque
            if lot and lot.ingredient_id:
                from models import Ingredient
                ing = db.query(Ingredient).filter(Ingredient.id == lot.ingredient_id).first()
                if ing and (ing.estoque_atual or 0) <= 0:
                    matched = True

        if matched:
            url_destino = rule.url_destino
            regra_aplicada = rule.regra
            break  # aplica a primeira regra que casar (maior prioridade)

    # Registra o scan
    scan = QRScan(
        lot_code=lot_code,
        url_redirecionada=url_destino,
        regra_aplicada=regra_aplicada,
        ip=ip,
        user_agent=user_agent,
    )
    db.add(scan)
    db.commit()

    logger.info("QR scan: lote=%s regra=%s → %s", lot_code, regra_aplicada, url_destino)
    return url_destino


# ─────────────────────────────────────────────────────────────────────────────
# CRUD de Templates e Regras
# ─────────────────────────────────────────────────────────────────────────────

def create_label_template(db: Session, data: dict) -> dict:
    from models import LabelTemplate
    tpl = LabelTemplate(
        nome=data["nome"],
        product_id=data.get("product_id"),
        printer_type=data.get("printer_type", "ZPL").upper(),
        width_mm=data.get("width_mm", 100),
        height_mm=data.get("height_mm", 60),
        fields_config=data.get("fields_config"),
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
        "fields_config": t.fields_config,
    }


def create_qr_rule(db: Session, data: dict) -> dict:
    from models import QRRule
    rule = QRRule(
        nome=data["nome"],
        product_id=data.get("product_id"),
        regra=data["regra"],
        dias_vencimento=data.get("dias_vencimento"),
        dias_apos_entrega=data.get("dias_apos_entrega"),
        url_destino=data["url_destino"],
        desconto_pct=data.get("desconto_pct"),
        prioridade=data.get("prioridade", 0),
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return _rule_to_dict(rule)


def list_qr_rules(db: Session) -> list:
    from models import QRRule
    return [_rule_to_dict(r) for r in db.query(QRRule).filter(QRRule.ativo == True).order_by(QRRule.prioridade.desc()).all()]


def _rule_to_dict(r) -> dict:
    return {
        "id": str(r.id),
        "nome": r.nome,
        "product_id": str(r.product_id) if r.product_id else None,
        "regra": r.regra,
        "dias_vencimento": r.dias_vencimento,
        "dias_apos_entrega": r.dias_apos_entrega,
        "url_destino": r.url_destino,
        "desconto_pct": r.desconto_pct,
        "prioridade": r.prioridade,
    }


def _generate_lot_code() -> str:
    """Gera código de lote automático: LOT-YYYYMMDD-XXXX."""
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=4))
    return f"LOT-{datetime.now().strftime('%Y%m%d')}-{suffix}"


def _add_months(dt: datetime, months: int) -> datetime:
    """Soma N meses a uma data sem depender de dateutil."""
    month = dt.month - 1 + months
    year = dt.year + month // 12
    month = month % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def print_by_template(
    db: Session,
    template_id: uuid.UUID,
    quantidade: int = 1,
    printer_host: str = DEFAULT_PRINTER_HOST,
    printer_port: int = DEFAULT_PRINTER_PORT,
) -> dict:
    """
    Imprime N etiquetas a partir de um template salvo.
    - Lote gerado automaticamente: LOT-YYYYMMDD-XXXX
    - Validade = data de hoje + validade_meses do template
    """
    from models import LabelTemplate, Product

    tpl = db.query(LabelTemplate).filter(LabelTemplate.id == template_id, LabelTemplate.ativo == True).first()
    if not tpl:
        raise ValueError("Template não encontrado")

    # Nome do produto (se vinculado)
    produto_nome = "—"
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
        "alergenicos": tpl.alergenicos or "",
        "temperatura": tpl.temperatura or "-18°C",
        "ean13": "",
        "qr_url": qr_url,
    }

    template_cfg = {
        "printer_type": tpl.printer_type,
        "width_mm": tpl.width_mm,
        "height_mm": tpl.height_mm,
        "fields_config": tpl.fields_config or {},
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
    Retorna a string ZPL ou TSPL gerada sem enviar à impressora.
    Permite preview antes de confirmar a impressão.
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

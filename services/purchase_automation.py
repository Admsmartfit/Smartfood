"""
E-09 — PurchaseAutomation: Cotação Hyper-Automatizada (Mega API + Gmail)

Componentes:
  MegaAPIClient   — WhatsApp via Mega API REST (stub pronto para produção)
  GmailClient     — Email via Gmail API (stub pronto para produção)
  RFQTemplate     — Geração de mensagem personalizada por fornecedor/produto
  GeminiExtractor — Extrai preço/prazo/observações de texto livre via Gemini AI
  PDFGenerator    — Gera Ordem de Compra em PDF via ReportLab
  Scoring         — 60% preço + 40% prazo para ranking de propostas
"""
import io
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Optional
import uuid

import httpx

logger = logging.getLogger("purchase_automation")

MEGA_API_URL = os.getenv("MEGA_API_URL", "http://localhost:8080")
MEGA_API_TOKEN = os.getenv("MEGA_API_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-1.5-flash"


# ─────────────────────────────────────────────────────────────────────────────
# MegaAPIClient — WhatsApp
# ─────────────────────────────────────────────────────────────────────────────

class MegaAPIClient:
    """Cliente HTTP para Mega API (WhatsApp Business)."""

    def __init__(self, base_url: str = MEGA_API_URL, token: str = MEGA_API_TOKEN):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    def send_message(self, phone: str, text: str) -> dict:
        """Envia mensagem de texto via WhatsApp."""
        payload = {"phone": phone, "message": text}
        try:
            r = httpx.post(
                f"{self.base_url}/message/sendText",
                json=payload, headers=self.headers, timeout=10
            )
            r.raise_for_status()
            logger.info("[WhatsApp→%s] mensagem enviada", phone)
            return r.json()
        except Exception as exc:
            logger.warning("[WhatsApp stub] %s → %s | erro: %s", phone, text[:60], exc)
            return {"status": "stub", "phone": phone}

    def send_document(self, phone: str, file_bytes: bytes, filename: str) -> dict:
        """Envia documento (PDF) via WhatsApp."""
        try:
            import base64
            b64 = base64.b64encode(file_bytes).decode()
            payload = {"phone": phone, "document": b64, "filename": filename}
            r = httpx.post(
                f"{self.base_url}/message/sendDocument",
                json=payload, headers=self.headers, timeout=15
            )
            r.raise_for_status()
            logger.info("[WhatsApp→%s] documento '%s' enviado", phone, filename)
            return r.json()
        except Exception as exc:
            logger.warning("[WhatsApp stub] doc %s → %s | erro: %s", filename, phone, exc)
            return {"status": "stub", "phone": phone, "filename": filename}


mega_client = MegaAPIClient()


# ─────────────────────────────────────────────────────────────────────────────
# GmailClient
# ─────────────────────────────────────────────────────────────────────────────

class GmailClient:
    """Stub para Gmail API — substitua com google-api-python-client em produção."""

    def send_email(self, to: str, subject: str, body: str, attachment_bytes: bytes = None,
                   attachment_name: str = None) -> dict:
        logger.info("[Email→%s] %s", to, subject)
        return {"status": "stub", "to": to}


gmail_client = GmailClient()


# ─────────────────────────────────────────────────────────────────────────────
# RFQTemplate — Mensagem personalizada
# ─────────────────────────────────────────────────────────────────────────────

class RFQTemplate:
    def render(
        self,
        supplier_name: str,
        qty: float,
        unidade: str,
        produto_nome: str,
        data_limite: str,
        observacoes: str = "",
    ) -> str:
        msg = (
            f"Olá {supplier_name},\n\n"
            f"Preciso cotar *{qty:.2f} {unidade}* de *{produto_nome}*.\n"
            f"Entrega necessária até: *{data_limite}*.\n"
        )
        if observacoes:
            msg += f"Observações: {observacoes}\n"
        msg += "\nQual o melhor preço? Por favor informe: preço unitário, prazo de entrega e condições de pagamento.\n\nObrigado!"
        return msg

    def render_oc(
        self,
        oc_numero: str,
        supplier_name: str,
        produto_nome: str,
        qty: float,
        unidade: str,
        preco_unit: float,
        total: float,
        data_entrega: str,
    ) -> str:
        return (
            f"Olá {supplier_name},\n\n"
            f"Segue em anexo a Ordem de Compra *#{oc_numero}*:\n"
            f"• Produto: {produto_nome}\n"
            f"• Quantidade: {qty:.2f} {unidade}\n"
            f"• Preço unitário: R$ {preco_unit:.2f}\n"
            f"• Total: R$ {total:.2f}\n"
            f"• Entrega até: {data_entrega}\n\n"
            "Confirme o recebimento desta OC. Obrigado!"
        )


rfq_template = RFQTemplate()


# ─────────────────────────────────────────────────────────────────────────────
# GeminiExtractor — Extrai preço/prazo/observações de texto livre
# ─────────────────────────────────────────────────────────────────────────────

_EXTRACTION_PROMPT = """
Analise a mensagem de cotação abaixo e extraia as informações de forma estruturada.
Retorne APENAS um JSON válido com os campos:
  "preco_unitario": float ou null,
  "prazo_dias": int ou null,
  "observacoes": string (condições especiais, pagamento, etc.)

Mensagem:
{mensagem}
"""

_REGEX_PRECO = re.compile(r"R\$\s*([\d.,]+)|(\d+[.,]\d{2})\s*(?:por|/|cada|un|kg)", re.IGNORECASE)
_REGEX_PRAZO = re.compile(r"(\d+)\s*(?:dias?|d\.u\.?)", re.IGNORECASE)


def _extract_with_regex(text: str) -> dict:
    """Fallback de extração por regex quando Gemini não está disponível."""
    preco = None
    m = _REGEX_PRECO.search(text)
    if m:
        raw = (m.group(1) or m.group(2) or "").replace(".", "").replace(",", ".")
        try:
            preco = float(raw)
        except ValueError:
            pass

    prazo = None
    m2 = _REGEX_PRAZO.search(text)
    if m2:
        try:
            prazo = int(m2.group(1))
        except ValueError:
            pass

    return {"preco_unitario": preco, "prazo_dias": prazo, "observacoes": text[:200]}


def extract_quote_from_text(text: str) -> dict:
    """
    Extrai preco_unitario, prazo_dias e observacoes de texto livre.
    Usa Gemini API se GEMINI_API_KEY configurada; fallback para regex.
    """
    if not GEMINI_API_KEY:
        logger.info("GEMINI_API_KEY não configurada — usando extração por regex")
        return _extract_with_regex(text)

    try:
        import google.generativeai as genai
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel(GEMINI_MODEL)
        prompt = _EXTRACTION_PROMPT.format(mensagem=text)
        response = model.generate_content(prompt)
        raw = response.text.strip()
        # Remove markdown code blocks se existirem
        raw = re.sub(r"```(?:json)?|```", "", raw).strip()
        return json.loads(raw)
    except Exception as exc:
        logger.warning("Gemini extraction falhou (%s) — usando regex", exc)
        return _extract_with_regex(text)


# ─────────────────────────────────────────────────────────────────────────────
# Scoring — 60% preço + 40% prazo
# ─────────────────────────────────────────────────────────────────────────────

def score_rfqs(rfqs: list) -> list:
    """
    Calcula score para ranking de propostas.
    Score = 60% (menor preço normalizado) + 40% (menor prazo normalizado).
    Retorna lista ordenada pelo melhor score (maior = melhor).
    """
    valid = [r for r in rfqs if r.get("preco_unitario") and r.get("prazo_dias")]
    if not valid:
        return rfqs

    min_preco = min(r["preco_unitario"] for r in valid)
    max_preco = max(r["preco_unitario"] for r in valid)
    min_prazo = min(r["prazo_dias"] for r in valid)
    max_prazo = max(r["prazo_dias"] for r in valid)

    for r in valid:
        # Normaliza invertido (menor valor = melhor score = 1.0)
        preco_score = (
            1.0 if max_preco == min_preco
            else (max_preco - r["preco_unitario"]) / (max_preco - min_preco)
        )
        prazo_score = (
            1.0 if max_prazo == min_prazo
            else (max_prazo - r["prazo_dias"]) / (max_prazo - min_prazo)
        )
        r["score"] = round(preco_score * 0.60 + prazo_score * 0.40, 4)

    # RFQs sem resposta recebem score 0
    for r in rfqs:
        if r not in valid:
            r["score"] = 0.0

    return sorted(rfqs, key=lambda x: x.get("score", 0), reverse=True)


# ─────────────────────────────────────────────────────────────────────────────
# PDF Generator — Ordem de Compra via ReportLab
# ─────────────────────────────────────────────────────────────────────────────

def generate_purchase_order_pdf(
    oc_numero: str,
    supplier_name: str,
    produto_nome: str,
    qty: float,
    unidade: str,
    preco_unit: float,
    total: float,
    data_entrega: str,
    empresa_nome: str = "SmartFood Ops 360",
) -> bytes:
    """
    Gera PDF da Ordem de Compra usando ReportLab.
    Fallback para texto simples se reportlab não estiver instalado.
    """
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
        from reportlab.lib import colors
        from reportlab.lib.units import cm

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
        styles = getSampleStyleSheet()
        elements = []

        # Cabeçalho
        elements.append(Paragraph(f"<b>{empresa_nome}</b>", styles["Title"]))
        elements.append(Paragraph(f"<b>ORDEM DE COMPRA #{oc_numero}</b>", styles["Heading2"]))
        elements.append(Spacer(1, 0.5*cm))
        elements.append(Paragraph(f"Data: {datetime.now().strftime('%d/%m/%Y %H:%M')}", styles["Normal"]))
        elements.append(Spacer(1, 0.5*cm))

        # Dados do fornecedor
        elements.append(Paragraph(f"<b>Fornecedor:</b> {supplier_name}", styles["Normal"]))
        elements.append(Paragraph(f"<b>Entrega até:</b> {data_entrega}", styles["Normal"]))
        elements.append(Spacer(1, 0.8*cm))

        # Tabela de itens
        data = [
            ["Produto", "Qtd", "Unidade", "Preço Unit.", "Total"],
            [produto_nome, f"{qty:.2f}", unidade, f"R$ {preco_unit:.2f}", f"R$ {total:.2f}"],
        ]
        tbl = Table(data, colWidths=[7*cm, 2*cm, 2*cm, 3*cm, 3*cm])
        tbl.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2E4057")),
            ("TEXTCOLOR",  (0, 0), (-1, 0), colors.white),
            ("FONTNAME",   (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ALIGN",      (1, 0), (-1, -1), "CENTER"),
            ("GRID",       (0, 0), (-1, -1), 0.5, colors.grey),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F5F5")]),
        ]))
        elements.append(tbl)
        elements.append(Spacer(1, 0.8*cm))
        elements.append(Paragraph(
            f"<b>TOTAL GERAL: R$ {total:.2f}</b>", styles["Heading3"]
        ))
        elements.append(Spacer(1, 1*cm))
        elements.append(Paragraph(
            "Este documento é gerado automaticamente pelo SmartFood Ops 360.",
            styles["Italic"]
        ))

        doc.build(elements)
        return buf.getvalue()

    except ImportError:
        logger.warning("ReportLab não instalado — gerando PDF como texto simples")
        content = (
            f"ORDEM DE COMPRA #{oc_numero}\n"
            f"Empresa: {empresa_nome}\n"
            f"Fornecedor: {supplier_name}\n"
            f"Produto: {produto_nome}\n"
            f"Quantidade: {qty:.2f} {unidade}\n"
            f"Preço unitário: R$ {preco_unit:.2f}\n"
            f"Total: R$ {total:.2f}\n"
            f"Entrega até: {data_entrega}\n"
            f"Gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}\n"
        )
        return content.encode("utf-8")


# ─────────────────────────────────────────────────────────────────────────────
# Orquestrador de RFQ
# ─────────────────────────────────────────────────────────────────────────────

def send_rfq(db, rfq_id: uuid.UUID) -> dict:
    """
    Envia RFQ ao fornecedor via WhatsApp + Email com mensagem personalizada.
    Atualiza status do RFQ para ENVIADO.
    """
    from models import RFQ, Supply, Supplier

    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise ValueError("RFQ não encontrado")

    supplier = db.query(Supplier).filter(Supplier.id == rfq.supplier_id).first()
    supply = db.query(Supply).filter(Supply.id == rfq.supply_id).first()

    data_limite_str = (
        rfq.data_limite.strftime("%d/%m/%Y") if rfq.data_limite else "a combinar"
    )
    msg = rfq_template.render(
        supplier_name=supplier.nome if supplier else "Fornecedor",
        qty=rfq.qty_solicitada or 1,
        unidade=supply.unidade if supply else "un",
        produto_nome=supply.nome if supply else "insumo",
        data_limite=data_limite_str,
    )

    rfq.mensagem_enviada = msg
    rfq.status = "ENVIADO"
    rfq.enviado_em = datetime.now(timezone.utc)
    db.commit()

    results = {}
    if supplier and supplier.whatsapp:
        results["whatsapp"] = mega_client.send_message(supplier.whatsapp, msg)
    if supplier and supplier.email:
        results["email"] = gmail_client.send_email(
            supplier.email,
            f"Cotação — {supply.nome if supply else 'Insumo'}",
            msg,
        )

    return {"rfq_id": str(rfq_id), "enviado": True, "canais": results}

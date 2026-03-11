"""
E-09 — Rotas de Compras Hyper-Automatizadas (Mega API + Gmail)
"""
from datetime import datetime, timezone
from typing import List, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import RFQ, Supplier, Supply, PurchaseOrder
from services.purchase_automation import (
    extract_quote_from_text,
    score_rfqs,
    send_rfq,
    generate_purchase_order_pdf,
    rfq_template,
    mega_client,
    gmail_client,
)

router = APIRouter(tags=["Compras Automation - E-09"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class RFQCreateRequest(BaseModel):
    supply_id: uuid.UUID
    supplier_ids: List[uuid.UUID]
    qty_solicitada: float
    data_limite: Optional[datetime] = None


class RFQResponse(BaseModel):
    id: uuid.UUID
    supply_id: uuid.UUID
    supplier_id: uuid.UUID
    qty_solicitada: Optional[float]
    status: str
    preco_unitario: Optional[float]
    prazo_entrega_dias: Optional[int]
    score: Optional[float]
    enviado_em: Optional[datetime]
    respondido_em: Optional[datetime]

    model_config = {"from_attributes": True}


class WebhookPayload(BaseModel):
    phone: Optional[str] = None
    from_number: Optional[str] = None
    message: str
    rfq_id: Optional[uuid.UUID] = None


class GmailWebhookPayload(BaseModel):
    from_email: Optional[str] = None
    subject: Optional[str] = None
    body: str
    rfq_id: Optional[uuid.UUID] = None


class ComparisonItem(BaseModel):
    rfq_id: str
    supplier_nome: str
    preco_unitario: Optional[float]
    prazo_dias: Optional[int]
    observacoes: Optional[str]
    score: Optional[float]
    status: str
    melhor_oferta: bool


class ApproveRequest(BaseModel):
    rfq_id: uuid.UUID


# ─── Endpoints ──────────────────────────────────────────────────────────────

@router.post("/rfqs", response_model=List[RFQResponse], status_code=201)
def create_rfqs(payload: RFQCreateRequest, db: Session = Depends(get_db)):
    """
    Cria RFQs para múltiplos fornecedores e envia via WhatsApp + Email.
    Um RFQ é criado por fornecedor para o mesmo supply.
    """
    supply = db.query(Supply).filter(Supply.id == payload.supply_id).first()
    if not supply:
        raise HTTPException(status_code=404, detail="Supply não encontrado")

    created = []
    for sup_id in payload.supplier_ids:
        supplier = db.query(Supplier).filter(Supplier.id == sup_id).first()
        if not supplier:
            continue

        rfq = RFQ(
            supply_id=payload.supply_id,
            supplier_id=sup_id,
            qty_solicitada=payload.qty_solicitada,
            data_limite=payload.data_limite,
            status="PENDENTE",
        )
        db.add(rfq)
        db.flush()  # gera ID

        # Envia imediatamente
        try:
            send_rfq(db, rfq.id)
        except Exception as exc:
            rfq.status = "ERRO_ENVIO"

        created.append(rfq)

    db.commit()
    return created


@router.get("/rfqs/{supply_id}/comparison", response_model=List[ComparisonItem])
def get_rfq_comparison(supply_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Tabela comparativa de todas as respostas de RFQ para um supply.
    Score automático: 60% preço + 40% prazo. Melhor oferta destacada.
    """
    supply = db.query(Supply).filter(Supply.id == supply_id).first()
    if not supply:
        raise HTTPException(status_code=404, detail="Supply não encontrado")

    rfqs = db.query(RFQ).filter(RFQ.supply_id == supply_id).all()

    raw_list = []
    for r in rfqs:
        supplier = db.query(Supplier).filter(Supplier.id == r.supplier_id).first()
        raw_list.append({
            "rfq_id": str(r.id),
            "rfq_obj": r,
            "supplier_nome": supplier.nome if supplier else "?",
            "preco_unitario": r.preco_unitario,
            "prazo_dias": r.prazo_entrega_dias,
            "observacoes": r.observacoes_extraidas,
            "score": r.score,
            "status": r.status,
        })

    scored = score_rfqs(raw_list)
    best_score = max((r.get("score") or 0) for r in scored) if scored else 0

    result = []
    for r in scored:
        result.append(ComparisonItem(
            rfq_id=r["rfq_id"],
            supplier_nome=r["supplier_nome"],
            preco_unitario=r["preco_unitario"],
            prazo_dias=r["prazo_dias"],
            observacoes=r["observacoes"],
            score=r.get("score"),
            status=r["status"],
            melhor_oferta=(r.get("score") == best_score and best_score > 0),
        ))
    return result


@router.post("/rfqs/{rfq_id}/approve")
def approve_rfq(rfq_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Aprova uma proposta: gera PDF da Ordem de Compra via ReportLab,
    envia ao fornecedor por Email + WhatsApp e cria registro PurchaseOrder.
    """
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ não encontrado")
    if rfq.status not in ("RESPONDIDO", "ENVIADO"):
        raise HTTPException(
            status_code=422,
            detail=f"RFQ com status '{rfq.status}' não pode ser aprovado. Deve ser RESPONDIDO."
        )
    if not rfq.preco_unitario:
        raise HTTPException(status_code=422, detail="RFQ sem preço respondido")

    supplier = db.query(Supplier).filter(Supplier.id == rfq.supplier_id).first()
    supply = db.query(Supply).filter(Supply.id == rfq.supply_id).first()

    qty = rfq.qty_solicitada or 1.0
    total = round(qty * rfq.preco_unitario, 2)
    oc_numero = str(rfq_id)[:8].upper()
    data_entrega = (
        rfq.data_limite.strftime("%d/%m/%Y") if rfq.data_limite else "a combinar"
    )

    # Gera PDF
    pdf_bytes = generate_purchase_order_pdf(
        oc_numero=oc_numero,
        supplier_name=supplier.nome if supplier else "Fornecedor",
        produto_nome=supply.nome if supply else "Insumo",
        qty=qty,
        unidade=supply.unidade if supply else "un",
        preco_unit=rfq.preco_unitario,
        total=total,
        data_entrega=data_entrega,
    )

    # Cria PurchaseOrder
    po = PurchaseOrder(
        rfq_id=rfq_id,
        supplier_id=rfq.supplier_id,
        supply_id=rfq.supply_id,
        qty_aprovada=qty,
        preco_unitario_aprovado=rfq.preco_unitario,
        total=total,
        pdf_gerado=True,
        status="ENVIADA",
        enviado_em=datetime.now(timezone.utc),
    )
    db.add(po)
    rfq.status = "APROVADO"
    db.commit()
    db.refresh(po)

    # Envia ao fornecedor
    oc_msg = rfq_template.render_oc(
        oc_numero=oc_numero,
        supplier_name=supplier.nome if supplier else "Fornecedor",
        produto_nome=supply.nome if supply else "Insumo",
        qty=qty,
        unidade=supply.unidade if supply else "un",
        preco_unit=rfq.preco_unitario,
        total=total,
        data_entrega=data_entrega,
    )
    if supplier:
        if supplier.whatsapp:
            mega_client.send_document(supplier.whatsapp, pdf_bytes, f"OC_{oc_numero}.pdf")
        if supplier.email:
            gmail_client.send_email(
                supplier.email,
                f"Ordem de Compra #{oc_numero} — SmartFood",
                oc_msg,
                attachment_bytes=pdf_bytes,
                attachment_name=f"OC_{oc_numero}.pdf",
            )

    return {
        "purchase_order_id": str(po.id),
        "oc_numero": oc_numero,
        "supplier": supplier.nome if supplier else None,
        "total": total,
        "status": po.status,
        "pdf_size_bytes": len(pdf_bytes),
    }


@router.get("/rfqs/{rfq_id}/purchase-order/pdf")
def download_purchase_order_pdf(rfq_id: uuid.UUID, db: Session = Depends(get_db)):
    """Download do PDF da Ordem de Compra de um RFQ aprovado."""
    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()
    if not rfq:
        raise HTTPException(status_code=404, detail="RFQ não encontrado")

    supplier = db.query(Supplier).filter(Supplier.id == rfq.supplier_id).first()
    supply = db.query(Supply).filter(Supply.id == rfq.supply_id).first()

    if not rfq.preco_unitario:
        raise HTTPException(status_code=422, detail="RFQ sem preço para gerar OC")

    qty = rfq.qty_solicitada or 1.0
    total = round(qty * rfq.preco_unitario, 2)
    oc_numero = str(rfq_id)[:8].upper()
    data_entrega = rfq.data_limite.strftime("%d/%m/%Y") if rfq.data_limite else "a combinar"

    pdf_bytes = generate_purchase_order_pdf(
        oc_numero=oc_numero,
        supplier_name=supplier.nome if supplier else "Fornecedor",
        produto_nome=supply.nome if supply else "Insumo",
        qty=qty,
        unidade=supply.unidade if supply else "un",
        preco_unit=rfq.preco_unitario,
        total=total,
        data_entrega=data_entrega,
    )
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=OC_{oc_numero}.pdf"},
    )


# ─── Webhooks ────────────────────────────────────────────────────────────────

@router.post("/webhooks/mega-api", status_code=200)
def webhook_mega_api(payload: WebhookPayload, db: Session = Depends(get_db)):
    """
    Webhook para respostas de WhatsApp via Mega API.
    Usa Gemini (ou regex fallback) para extrair preço/prazo/observações.
    Atualiza o RFQ correspondente e calcula score.
    """
    extracted = extract_quote_from_text(payload.message)

    rfq = None
    if payload.rfq_id:
        rfq = db.query(RFQ).filter(RFQ.id == payload.rfq_id).first()
    elif payload.phone or payload.from_number:
        phone = payload.phone or payload.from_number
        supplier = db.query(Supplier).filter(Supplier.whatsapp == phone).first()
        if supplier:
            rfq = (
                db.query(RFQ)
                .filter(RFQ.supplier_id == supplier.id, RFQ.status == "ENVIADO")
                .order_by(RFQ.enviado_em.desc())
                .first()
            )

    if rfq:
        rfq.resposta_raw = payload.message
        rfq.preco_unitario = extracted.get("preco_unitario")
        rfq.prazo_entrega_dias = extracted.get("prazo_dias")
        rfq.observacoes_extraidas = extracted.get("observacoes")
        rfq.status = "RESPONDIDO"
        rfq.respondido_em = datetime.now(timezone.utc)
        db.commit()

    return {"received": True, "extracted": extracted, "rfq_updated": rfq is not None}


@router.post("/webhooks/gmail", status_code=200)
def webhook_gmail(payload: GmailWebhookPayload, db: Session = Depends(get_db)):
    """
    Webhook para respostas de email via Gmail API.
    Mesma lógica de extração do webhook WhatsApp.
    """
    extracted = extract_quote_from_text(payload.body)

    rfq = None
    if payload.rfq_id:
        rfq = db.query(RFQ).filter(RFQ.id == payload.rfq_id).first()
    elif payload.from_email:
        supplier = db.query(Supplier).filter(Supplier.email == payload.from_email).first()
        if supplier:
            rfq = (
                db.query(RFQ)
                .filter(RFQ.supplier_id == supplier.id, RFQ.status == "ENVIADO")
                .order_by(RFQ.enviado_em.desc())
                .first()
            )

    if rfq:
        rfq.resposta_raw = payload.body
        rfq.preco_unitario = extracted.get("preco_unitario")
        rfq.prazo_entrega_dias = extracted.get("prazo_dias")
        rfq.observacoes_extraidas = extracted.get("observacoes")
        rfq.status = "RESPONDIDO"
        rfq.respondido_em = datetime.now(timezone.utc)
        db.commit()

    return {"received": True, "extracted": extracted, "rfq_updated": rfq is not None}

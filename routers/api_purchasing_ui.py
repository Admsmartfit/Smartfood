"""FE-04 — API de Compras para UI: RFQ inbox, comparação e aprovação."""
import json
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/purchasing", tags=["API — Compras UI FE-04"])
templates = Jinja2Templates(directory="templates")


@router.get("/rfq-inbox", response_class=HTMLResponse)
def rfq_inbox(request: Request, db: Session = Depends(get_db)):
    """Inbox unificado de respostas de fornecedores, atualiza a cada 30s."""
    from models import RFQ, Supplier, Supply
    from services.purchase_automation import score_rfqs

    rfqs_db = (
        db.query(RFQ)
        .filter(RFQ.status.in_(["RESPONDIDO", "APROVADO", "ENVIADO"]))
        .order_by(RFQ.respondido_em.desc().nullslast())
        .limit(50)
        .all()
    )

    raw = []
    for r in rfqs_db:
        supplier = db.query(Supplier).filter(Supplier.id == r.supplier_id).first()
        supply = db.query(Supply).filter(Supply.id == r.supply_id).first()
        raw.append({
            "rfq_id": str(r.id),
            "supply_id": str(r.supply_id),
            "supply_nome": supply.nome if supply else "—",
            "supplier_nome": supplier.nome if supplier else "—",
            "preco_unitario": r.preco_unitario,
            "prazo_dias": r.prazo_entrega_dias,
            "observacoes": r.observacoes_extraidas or "",
            "status": r.status,
            "score": r.score,
            "respondido_em": r.respondido_em.strftime("%d/%m %H:%M") if r.respondido_em else "",
        })

    scored = score_rfqs(raw) if raw else raw

    # Marca vencedor por supply_id
    best_by_supply: dict = {}
    for r in scored:
        sid = r["supply_id"]
        sc = r.get("score") or 0
        if sc > (best_by_supply.get(sid, {}).get("score") or 0):
            best_by_supply[sid] = r
    for r in scored:
        r["is_winner"] = (
            r is best_by_supply.get(r["supply_id"])
            and (r.get("score") or 0) > 0
            and r["status"] != "APROVADO"
        )

    return templates.TemplateResponse(
        "fragments/rfq_inbox.html",
        {"request": request, "rfqs": scored},
    )


@router.get("/rfqs/{supply_id}/comparison", response_class=HTMLResponse)
def rfq_comparison(
    supply_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """Tabela comparativa de fornecedores para um insumo."""
    from models import RFQ, Supplier, Supply
    from services.purchase_automation import score_rfqs

    supply = db.query(Supply).filter(Supply.id == supply_id).first()
    rfqs_db = db.query(RFQ).filter(RFQ.supply_id == supply_id).all()

    raw = []
    for r in rfqs_db:
        supplier = db.query(Supplier).filter(Supplier.id == r.supplier_id).first()
        raw.append({
            "rfq_id": str(r.id),
            "supplier_nome": supplier.nome if supplier else "—",
            "preco_unitario": r.preco_unitario,
            "prazo_dias": r.prazo_entrega_dias,
            "observacoes": r.observacoes_extraidas or "",
            "status": r.status,
            "score": r.score,
        })

    scored = score_rfqs(raw) if raw else raw
    best_score = max((r.get("score") or 0) for r in scored) if scored else 0
    for r in scored:
        r["is_winner"] = (r.get("score") == best_score and best_score > 0 and r["status"] != "APROVADO")

    return templates.TemplateResponse(
        "fragments/rfq_comparison.html",
        {
            "request": request,
            "supply": supply,
            "rfqs": scored,
            "best_score": best_score,
        },
    )


@router.post("/rfqs/{rfq_id}/approve", response_class=HTMLResponse)
def approve_rfq_ui(
    rfq_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """Aprova RFQ, gera OC PDF e retorna fragmento de confirmação."""
    from models import RFQ, Supplier, Supply, PurchaseOrder
    from datetime import datetime, timezone
    from services.purchase_automation import (
        generate_purchase_order_pdf,
        rfq_template,
        mega_client,
        gmail_client,
    )

    error_msg = None
    oc_data = {}

    rfq = db.query(RFQ).filter(RFQ.id == rfq_id).first()

    if not rfq:
        error_msg = "RFQ não encontrado."
    elif rfq.status not in ("RESPONDIDO", "ENVIADO"):
        error_msg = f"RFQ com status '{rfq.status}' não pode ser aprovado."
    elif not rfq.preco_unitario:
        error_msg = "RFQ sem preço respondido."
    else:
        try:
            supplier = db.query(Supplier).filter(Supplier.id == rfq.supplier_id).first()
            supply = db.query(Supply).filter(Supply.id == rfq.supply_id).first()

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
            if supplier:
                oc_msg = rfq_template.render_oc(
                    oc_numero=oc_numero,
                    supplier_name=supplier.nome if supplier else "Fornecedor",
                    produto_nome=supply.nome if supply else "Insumo",
                    qty=qty, unidade=supply.unidade if supply else "un",
                    preco_unit=rfq.preco_unitario, total=total,
                    data_entrega=data_entrega,
                )
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

            oc_data = {
                "oc_numero": oc_numero,
                "supplier_nome": supplier.nome if supplier else "Fornecedor",
                "supply_nome": supply.nome if supply else "Insumo",
                "qty": qty,
                "unidade": supply.unidade if supply else "un",
                "total": total,
                "pdf_url": f"/rfqs/{rfq_id}/purchase-order/pdf",
                "po_id": str(po.id),
                "whatsapp_enviado": bool(supplier and supplier.whatsapp),
                "email_enviado": bool(supplier and supplier.email),
            }
        except Exception as e:
            db.rollback()
            error_msg = str(e)

    msg_type = "success" if not error_msg else "error"
    msg_text = "OC enviada para fornecedor!" if not error_msg else f"Erro: {error_msg}"
    trigger = json.dumps({"showToast": {"message": msg_text, "type": msg_type}})

    response = templates.TemplateResponse(
        "fragments/rfq_approved.html",
        {"request": request, "oc": oc_data, "error": error_msg},
    )
    response.headers["HX-Trigger"] = trigger
    return response


@router.get("/items-to-quote", response_class=HTMLResponse)
def items_to_quote(db: Session = Depends(get_db)):
    """Lista insumos com estoque abaixo do mínimo com urgência visual e botão de ação."""
    from models import Supply

    items = (
        db.query(Supply)
        .filter(Supply.estoque_atual < Supply.estoque_minimo, Supply.estoque_minimo > 0)
        .order_by(Supply.estoque_atual)
        .limit(30)
        .all()
    )

    if not items:
        return HTMLResponse(
            """<div class="flex flex-col items-center justify-center py-8 text-gray-400">
                 <i class="ph ph-check-circle text-3xl mb-2"></i>
                 <p class="text-sm">Nenhum insumo abaixo do mínimo. Estoque OK!</p>
               </div>"""
        )

    rows = []
    for s in items:
        pct = round((s.estoque_atual or 0) / max(s.estoque_minimo, 0.01) * 100)
        deficit = round((s.estoque_minimo or 0) - (s.estoque_atual or 0), 2)
        lead = s.lead_time_dias or 0

        if pct <= 0:
            urgency_cls = "bg-red-100 border-red-300 text-red-800"
            badge = '<span class="text-xs font-bold text-red-700 bg-red-200 px-1.5 py-0.5 rounded">Urgente hoje</span>'
        elif lead > 0 and pct <= 30:
            urgency_cls = "bg-amber-50 border-amber-300 text-amber-800"
            badge = '<span class="text-xs font-medium text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">3 dias</span>'
        else:
            urgency_cls = "bg-white border-slate-200 text-gray-700"
            badge = '<span class="text-xs text-gray-400">Planejar</span>'

        action_btn = (
            f'<button hx-get="/api/purchasing/rfqs/{s.id}/comparison"'
            f' hx-target="#dialog-container" hx-swap="innerHTML"'
            f' class="ml-3 px-2 py-1.5 bg-white border border-slate-300 rounded shadow-sm'
            f' text-xs font-medium hover:bg-slate-50 transition-colors flex items-center gap-1 text-gray-700">'
            f'<i class="ph ph-scales"></i> Comparar</button>'
        )

        rows.append(
            f'<div class="flex items-center justify-between p-3 rounded-lg border {urgency_cls}">'
            f'<div class="flex-1"><p class="font-medium text-sm">{s.nome}</p>'
            f'<p class="text-xs opacity-75">Déficit: {deficit} {s.unidade or ""}</p></div>'
            f'<div class="flex items-center">{badge}{action_btn}</div></div>'
        )

    return HTMLResponse("\n".join(rows))


@router.get("/rfq-status-summary", response_class=HTMLResponse)
def rfq_status_summary(db: Session = Depends(get_db)):
    """Resumo do status de cotações em andamento."""
    from models import RFQ, Supply

    rfqs = (
        db.query(RFQ)
        .filter(RFQ.status.in_(["PENDENTE", "ENVIADO", "RESPONDIDO"]))
        .order_by(RFQ.created_at.desc())
        .limit(20)
        .all()
    )

    if not rfqs:
        return HTMLResponse(
            """<div class="flex flex-col items-center justify-center py-8 text-gray-400">
                 <i class="ph ph-clock text-3xl mb-2"></i>
                 <p class="text-sm">Nenhuma cotação em andamento.</p>
               </div>"""
        )

    status_map = {
        "PENDENTE":   ("bg-gray-100 text-gray-700",   "Pendente"),
        "ENVIADO":    ("bg-blue-100 text-blue-800",    "Enviado"),
        "RESPONDIDO": ("bg-green-100 text-green-800",  "Respondido"),
    }
    rows = []
    for r in rfqs:
        supply = db.query(Supply).filter(Supply.id == r.supply_id).first()
        sc, label = status_map.get(r.status, ("bg-gray-100 text-gray-700", r.status))
        name = supply.nome if supply else "—"
        rows.append(
            f'<div class="flex items-center justify-between p-3 rounded-lg border border-slate-200 bg-white">'
            f'<span class="text-sm text-gray-900 font-medium">{name}</span>'
            f'<span class="text-xs font-medium px-2 py-0.5 rounded-full {sc}">{label}</span>'
            f'</div>'
        )

    return HTMLResponse("\n".join(rows))


@router.post("/rfqs/bulk-send", response_class=HTMLResponse)
def bulk_send_rfqs(request: Request, db: Session = Depends(get_db)):
    """Dispara RFQs para todos os insumos com estoque abaixo do mínimo."""
    from models import Supply, Supplier, RFQ
    from services.purchase_automation import send_rfq

    supplies_low = (
        db.query(Supply)
        .filter(Supply.estoque_atual < Supply.estoque_minimo)
        .all()
    )

    sent_count = 0
    errors = []

    for supply in supplies_low:
        # Pega fornecedores que têm este supply em histórico de RFQ
        existing_suppliers = (
            db.query(RFQ.supplier_id)
            .filter(RFQ.supply_id == supply.id)
            .distinct()
            .all()
        )
        supplier_ids = [s[0] for s in existing_suppliers]

        for sup_id in supplier_ids:
            try:
                rfq = RFQ(
                    supply_id=supply.id,
                    supplier_id=sup_id,
                    qty_solicitada=max((supply.estoque_minimo or 0) - (supply.estoque_atual or 0), 1),
                    status="PENDENTE",
                )
                db.add(rfq)
                db.flush()
                send_rfq(db, rfq.id)
                sent_count += 1
            except Exception as e:
                errors.append(str(e))

    db.commit()

    trigger = json.dumps({
        "showToast": {
            "message": f"{sent_count} RFQ(s) enviados!" if not errors else f"{sent_count} enviados, {len(errors)} erros.",
            "type": "success" if not errors else "warning",
        }
    })
    response = HTMLResponse(
        content=f"""
        <div class="p-3 rounded-lg {'bg-green-50 border border-green-200' if not errors else 'bg-amber-50 border border-amber-200'} text-sm">
          <strong>{'Cotações disparadas!' if not errors else 'Parcialmente enviado'}</strong>
          {sent_count} RFQ(s) enviados para {len(supplies_low)} insumo(s) com estoque baixo.
        </div>
        """
    )
    response.headers["HX-Trigger"] = trigger
    return response

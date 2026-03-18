"""FE-04 — API de Compras para UI: RFQ inbox, comparação e aprovação unificada."""
import json
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/purchasing", tags=["API — Compras UI FE-04"])
templates = Jinja2Templates(directory="templates")

# ─── INBOX DE RESPOSTAS ───────────────────────────────────────────────────────

@router.get("/rfq-inbox", response_class=HTMLResponse)
def rfq_inbox(request: Request, db: Session = Depends(get_db)):
    from models import RFQ, Supplier, Supply, Ingredient
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

        nome_item = "—"
        if r.ingredient_id:
            ing = db.query(Ingredient).filter(Ingredient.id == r.ingredient_id).first()
            nome_item = ing.nome if ing else "—"
        elif r.supply_id:
            sup = db.query(Supply).filter(Supply.id == r.supply_id).first()
            nome_item = sup.nome if sup else "—"

        raw.append({
            "rfq_id": str(r.id),
            "item_key": f"ing_{r.ingredient_id}" if r.ingredient_id else f"sup_{r.supply_id}",
            "supply_nome": nome_item,
            "supplier_nome": supplier.nome if supplier else "—",
            "preco_unitario": r.preco_unitario,
            "prazo_dias": r.prazo_entrega_dias,
            "observacoes": r.observacoes_extraidas or "",
            "status": r.status,
            "score": r.score,
            "respondido_em": r.respondido_em.strftime("%d/%m %H:%M") if r.respondido_em else "",
        })

    scored = score_rfqs(raw) if raw else raw

    best_by_item: dict = {}
    for r in scored:
        key = r["item_key"]
        sc = r.get("score") or 0
        if sc > (best_by_item.get(key, {}).get("score") or 0):
            best_by_item[key] = r
    for r in scored:
        r["is_winner"] = (
            r is best_by_item.get(r["item_key"])
            and (r.get("score") or 0) > 0
            and r["status"] != "APROVADO"
        )

    return templates.TemplateResponse(
        "fragments/rfq_inbox.html",
        {"request": request, "rfqs": scored},
    )


# ─── COMPARAÇÃO E APROVAÇÃO ───────────────────────────────────────────────────

@router.get("/rfqs/{item_id}/comparison", response_class=HTMLResponse)
def rfq_comparison(item_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """Tabela comparativa de fornecedores para um insumo ou ingrediente."""
    from models import RFQ, Supplier, Supply, Ingredient
    from services.purchase_automation import score_rfqs

    supply = db.query(Supply).filter(Supply.id == item_id).first()
    ingredient = db.query(Ingredient).filter(Ingredient.id == item_id).first()

    class ItemMock:
        def __init__(self, nome, unidade):
            self.nome = nome
            self.unidade = unidade

    nome = supply.nome if supply else (ingredient.nome if ingredient else "Item Desconhecido")
    unidade = supply.unidade if supply else (ingredient.unidade if ingredient else "un")
    item_mock = ItemMock(nome, unidade)

    rfqs_db = (
        db.query(RFQ)
        .filter((RFQ.supply_id == item_id) | (RFQ.ingredient_id == item_id))
        .all()
    )

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
            "supply": item_mock,
            "rfqs": scored,
            "best_score": best_score,
        },
    )


@router.post("/rfqs/{rfq_id}/approve", response_class=HTMLResponse)
def approve_rfq_ui(rfq_id: uuid.UUID, request: Request, db: Session = Depends(get_db)):
    """Aprova RFQ, gera OC PDF e retorna fragmento de confirmação."""
    from models import RFQ, Supplier, Supply, Ingredient, PurchaseOrder
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
            supply = db.query(Supply).filter(Supply.id == rfq.supply_id).first() if rfq.supply_id else None
            ingredient = db.query(Ingredient).filter(Ingredient.id == rfq.ingredient_id).first() if rfq.ingredient_id else None

            nome_item = supply.nome if supply else (ingredient.nome if ingredient else "Insumo")
            unidade_item = supply.unidade if supply else (ingredient.unidade if ingredient else "un")

            qty = rfq.qty_solicitada or 1.0
            total = round(qty * rfq.preco_unitario, 2)
            oc_numero = str(rfq_id)[:8].upper()
            data_entrega = rfq.data_limite.strftime("%d/%m/%Y") if rfq.data_limite else "a combinar"

            pdf_bytes = generate_purchase_order_pdf(
                oc_numero=oc_numero,
                supplier_name=supplier.nome if supplier else "Fornecedor",
                produto_nome=nome_item,
                qty=qty,
                unidade=unidade_item,
                preco_unit=rfq.preco_unitario,
                total=total,
                data_entrega=data_entrega,
            )

            po = PurchaseOrder(
                rfq_id=rfq_id,
                supplier_id=rfq.supplier_id,
                supply_id=rfq.supply_id,
                ingredient_id=rfq.ingredient_id,
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

            if supplier:
                oc_msg = rfq_template.render_oc(
                    oc_numero=oc_numero,
                    supplier_name=supplier.nome if supplier else "Fornecedor",
                    produto_nome=nome_item,
                    qty=qty, unidade=unidade_item,
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
                "supply_nome": nome_item,
                "qty": qty,
                "unidade": unidade_item,
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


# ─── LISTA DE ALERTAS (MISTURA INGREDIENTES E EMBALAGENS) ─────────────────────

@router.get("/items-to-quote", response_class=HTMLResponse)
def items_to_quote(db: Session = Depends(get_db)):
    from models import Supply, Ingredient

    supplies = (
        db.query(Supply)
        .filter(Supply.estoque_atual < Supply.estoque_minimo, Supply.estoque_minimo > 0)
        .all()
    )
    ingredients = (
        db.query(Ingredient)
        .filter(Ingredient.estoque_atual < Ingredient.estoque_minimo, Ingredient.estoque_minimo > 0)
        .all()
    )

    items = []
    for s in supplies:
        items.append({
            "id": str(s.id), "nome": s.nome, "unidade": s.unidade,
            "atual": s.estoque_atual, "minimo": s.estoque_minimo,
            "lead": s.lead_time_dias, "tipo": "supply",
        })
    for i in ingredients:
        items.append({
            "id": str(i.id), "nome": i.nome, "unidade": i.unidade,
            "atual": i.estoque_atual, "minimo": i.estoque_minimo,
            "lead": i.lead_time_dias, "tipo": "ingredient",
        })

    items.sort(key=lambda x: x["atual"] or 0)

    if not items:
        return HTMLResponse(
            """<div class="flex flex-col items-center justify-center py-8 text-gray-400">
                 <i class="ph ph-check-circle text-3xl mb-2"></i>
                 <p class="text-sm">Nenhum item abaixo do mínimo de segurança!</p>
               </div>"""
        )

    rows = []
    for it in items[:30]:
        pct = round((it["atual"] or 0) / max(it["minimo"], 0.01) * 100)
        deficit = round((it["minimo"] or 0) - (it["atual"] or 0), 2)
        lead = it["lead"] or 0

        if pct <= 0:
            urgency_cls = "bg-red-100 border-red-300 text-red-800"
            badge = '<span class="text-xs font-bold text-red-700 bg-red-200 px-1.5 py-0.5 rounded">Urgente</span>'
        elif lead > 0 and pct <= 30:
            urgency_cls = "bg-amber-50 border-amber-300 text-amber-800"
            badge = '<span class="text-xs font-medium text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded">Atenção</span>'
        else:
            urgency_cls = "bg-white border-slate-200 text-gray-700"
            badge = '<span class="text-xs text-gray-400">Planejar</span>'

        action_btn = (
            f'<button hx-get="/api/purchasing/manual-quote/modal?item_id={it["id"]}&item_type={it["tipo"]}&deficit={deficit}"'
            f' hx-target="#dialog-container" hx-swap="innerHTML"'
            f' class="ml-3 px-3 py-1.5 bg-blue-600 hover:bg-blue-700 text-white rounded-lg'
            f' text-xs font-bold transition-colors flex items-center gap-1 shadow-sm">'
            f'<i class="ph-bold ph-paper-plane-tilt"></i> Cotar</button>'
        )

        icone_tipo = "ph-leaf text-green-600" if it["tipo"] == "ingredient" else "ph-package text-purple-600"

        rows.append(
            f'<div class="flex items-center justify-between p-3 rounded-lg border {urgency_cls}">'
            f'<div class="flex flex-1 items-center gap-2">'
            f'<i class="ph-fill {icone_tipo} text-lg"></i>'
            f'<div><p class="font-medium text-sm">{it["nome"]}</p>'
            f'<p class="text-xs font-bold opacity-80 mt-0.5">Faltam: {deficit} {it["unidade"] or ""}</p></div></div>'
            f'<div class="flex items-center gap-2">{badge}{action_btn}</div></div>'
        )

    return HTMLResponse("\n".join(rows))


@router.get("/rfq-status-summary", response_class=HTMLResponse)
def rfq_status_summary(db: Session = Depends(get_db)):
    """Resumo do status de cotações em andamento com botão Ver Opções."""
    from models import RFQ, Supply, Ingredient

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
        "PENDENTE":   ("bg-gray-100 text-gray-700",  "Pendente"),
        "ENVIADO":    ("bg-blue-100 text-blue-800",   "Enviado"),
        "RESPONDIDO": ("bg-green-100 text-green-800", "Respondido"),
    }
    rows = []
    vistos: set = set()

    for r in rfqs:
        item_id = r.supply_id or r.ingredient_id
        if not item_id or str(item_id) in vistos:
            continue
        vistos.add(str(item_id))

        nome_item = "—"
        if r.ingredient_id:
            ing = db.query(Ingredient).filter(Ingredient.id == r.ingredient_id).first()
            nome_item = ing.nome if ing else "—"
        elif r.supply_id:
            sup = db.query(Supply).filter(Supply.id == r.supply_id).first()
            nome_item = sup.nome if sup else "—"

        sc, label = status_map.get(r.status, ("bg-gray-100 text-gray-700", r.status))

        compare_btn = ""
        if r.status == "RESPONDIDO":
            compare_btn = (
                f'<button hx-get="/api/purchasing/rfqs/{item_id}/comparison"'
                f' hx-target="#dialog-container" hx-swap="innerHTML"'
                f' class="ml-2 px-2 py-1.5 bg-white border border-slate-300 rounded shadow-sm'
                f' text-xs font-bold hover:bg-slate-50 transition-colors text-blue-700">'
                f'Ver Opções</button>'
            )

        rows.append(
            f'<div class="flex items-center justify-between p-3 rounded-lg border border-slate-200 bg-white">'
            f'<span class="text-sm text-gray-900 font-medium">{nome_item}</span>'
            f'<div class="flex items-center">'
            f'<span class="text-xs font-medium px-2 py-0.5 rounded-full {sc}">{label}</span>'
            f'{compare_btn}</div></div>'
        )

    return HTMLResponse("\n".join(rows))


# ─── COTAÇÃO MANUAL ───────────────────────────────────────────────────────────

@router.get("/manual-quote/modal", response_class=HTMLResponse)
def manual_quote_modal(
    request: Request,
    item_id: str = "",
    item_type: str = "",
    deficit: float = 0.0,
    db: Session = Depends(get_db),
):
    from models import Supply, Ingredient, Supplier

    ingredients = db.query(Ingredient).order_by(Ingredient.nome).all()
    supplies = db.query(Supply).order_by(Supply.nome).all()
    suppliers = db.query(Supplier).order_by(Supplier.nome).all()

    return templates.TemplateResponse(
        "fragments/manual_quote_modal.html",
        {
            "request": request,
            "ingredients": ingredients,
            "supplies": supplies,
            "suppliers": suppliers,
            "preselected_val": f"{item_type}|{item_id}" if item_id else "",
            "preselected_qty": deficit,
        },
    )


@router.post("/manual-quote", response_class=HTMLResponse)
def create_manual_quote(
    item_data: str = Form(...),
    qty_solicitada: float = Form(...),
    supplier_ids: list[str] = Form(default=[]),
    db: Session = Depends(get_db),
):
    from models import RFQ
    from services.purchase_automation import send_rfq

    if not supplier_ids:
        r = HTMLResponse("")
        r.headers["HX-Trigger"] = json.dumps({
            "showToast": {"message": "Selecione pelo menos um fornecedor.", "type": "error"}
        })
        return r

    try:
        item_type, item_id = item_data.split("|")
    except ValueError:
        return HTMLResponse("Erro ao processar item.")

    count = 0
    for sup_id in supplier_ids:
        try:
            rfq = RFQ(
                id=uuid.uuid4(),
                supplier_id=uuid.UUID(sup_id),
                qty_solicitada=qty_solicitada,
                status="PENDENTE",
            )
            if item_type == "ingredient":
                rfq.ingredient_id = uuid.UUID(item_id)
            else:
                rfq.supply_id = uuid.UUID(item_id)

            db.add(rfq)
            db.flush()
            try:
                send_rfq(db, rfq.id)
            except Exception:
                pass
            count += 1
        except Exception:
            pass

    db.commit()

    r = HTMLResponse("")
    r.headers["HX-Trigger"] = json.dumps({
        "showToast": {"message": f"{count} cotação(ões) enviada(s) aos fornecedores!", "type": "success"},
        "refreshRfqList": True,
    })
    return r


@router.post("/rfqs/bulk-send", response_class=HTMLResponse)
def bulk_send_rfqs(db: Session = Depends(get_db)):
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

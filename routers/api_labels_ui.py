"""FE-06 — API de Etiquetas para UI: preview, impressão e QR redirect."""
import json
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(tags=["API — Etiquetas UI FE-06"])
templates = Jinja2Templates(directory="templates")


@router.post("/api/labels/preview", response_class=HTMLResponse)
async def label_preview(
    request: Request,
    product_name: str = Form(default=""),
    lot: str = Form(default=""),
    fab_date: str = Form(default=""),
    exp_date: str = Form(default=""),
    weight_g: float = Form(default=0.0),
    width_mm: int = Form(default=100),
    height_mm: int = Form(default=60),
    printer_type: str = Form(default="ZPL"),
):
    """Retorna preview HTML da etiqueta em tempo real."""
    fields = {
        "product_name": product_name,
        "lot": lot,
        "fab_date": fab_date,
        "exp_date": exp_date,
        "weight_g": weight_g,
    }
    template = {
        "width_mm": width_mm,
        "height_mm": height_mm,
        "printer_type": printer_type.upper(),
    }

    zpl_preview = ""
    try:
        from services.label_service import preview_label
        result = preview_label(fields, template)
        zpl_preview = result.get("preview", "")
    except Exception:
        pass

    return templates.TemplateResponse(
        "fragments/label_preview.html",
        {
            "request": request,
            "fields": fields,
            "template": template,
            "zpl_preview": zpl_preview,
        },
    )


@router.post("/api/labels/print/{batch_id}", response_class=HTMLResponse)
def label_print(
    batch_id: uuid.UUID,
    request: Request,
    printer_host: str = Form(default=""),
    printer_port: int = Form(default=9100),
    db: Session = Depends(get_db),
):
    """Envia etiquetas do lote para impressora via TCP."""
    from services.label_service import print_batch_labels, DEFAULT_PRINTER_HOST, DEFAULT_PRINTER_PORT

    host = printer_host.strip() or DEFAULT_PRINTER_HOST
    port = printer_port or DEFAULT_PRINTER_PORT

    error_msg = None
    result = {}
    try:
        result = print_batch_labels(db, batch_id, printer_host=host, printer_port=port)
        msg = {"showToast": {
            "message": f"{result.get('total_impressas', 0)} etiqueta(s) enviadas para {host}!",
            "type": "success",
        }}
    except Exception as e:
        error_msg = str(e)
        msg = {"showToast": {"message": f"Erro: {error_msg}", "type": "error"}}

    content = ""
    if error_msg:
        content = (
            f'<div class="flex items-center gap-3 p-3 rounded-lg bg-red-50 border border-red-200 text-sm">'
            f'<i class="ph-fill ph-x-circle text-red-600"></i>'
            f'<span class="text-red-800">{error_msg}</span></div>'
        )
    else:
        total = result.get("total_impressas", 0)
        content = (
            f'<div class="flex items-center gap-3 p-3 rounded-lg bg-green-50 border border-green-200 text-sm">'
            f'<i class="ph-fill ph-check-circle text-green-600"></i>'
            f'<span class="text-green-800"><strong>{total}</strong> etiqueta(s) enviadas para <strong>{host}:{port}</strong></span></div>'
        )

    response = HTMLResponse(content=content)
    response.headers["HX-Trigger"] = json.dumps(msg)
    return response


@router.get("/qr/{lot_code}")
def qr_redirect(lot_code: str, db: Session = Depends(get_db)):
    """Resolve QR code do lote e redireciona (302) para a URL configurada."""
    from services.label_service import resolve_qr_redirect

    try:
        result = resolve_qr_redirect(db, lot_code)
        url = result.get("redirect_url") or result.get("url", "/")
        return RedirectResponse(url=url, status_code=302)
    except Exception:
        return RedirectResponse(url="/", status_code=302)


# ─── Templates CRUD ───────────────────────────────────────────────────────────

@router.post("/api/labels/templates", response_class=HTMLResponse)
def create_template(
    request: Request,
    nome: str = Form(...),
    product_id: str = Form(default=""),
    printer_type: str = Form(default="ZPL"),
    width_mm: int = Form(default=100),
    height_mm: int = Form(default=60),
    validade_meses: int = Form(default=3),
    peso_g: float = Form(default=0.0),
    alergenicos: str = Form(default=""),
    temperatura: str = Form(default="-18°C"),
    db: Session = Depends(get_db),
):
    """Cria novo template de etiqueta e retorna a lista atualizada."""
    from models import LabelTemplate, Product

    pid = uuid.UUID(product_id) if product_id.strip() else None
    tpl = LabelTemplate(
        nome=nome.strip(),
        product_id=pid,
        printer_type=printer_type.upper(),
        width_mm=width_mm,
        height_mm=height_mm,
        validade_meses=validade_meses,
        peso_g=peso_g if peso_g > 0 else None,
        alergenicos=alergenicos.strip() or None,
        temperatura=temperatura.strip() or "-18°C",
    )
    db.add(tpl)
    db.commit()
    db.refresh(tpl)

    tpls = db.query(LabelTemplate).filter(LabelTemplate.ativo == True).order_by(LabelTemplate.nome).all()
    products = db.query(Product).filter(Product.ativo == True).order_by(Product.nome).all()
    prod_map = {str(p.id): p.nome for p in products}

    resp = templates.TemplateResponse(
        "fragments/label_templates_list.html",
        {"request": request, "templates_list": tpls, "prod_map": prod_map},
    )
    resp.headers["HX-Trigger"] = json.dumps({"showToast": {"message": f"Modelo '{nome}' criado!", "type": "success"}})
    return resp


@router.delete("/api/labels/templates/{template_id}", response_class=HTMLResponse)
def delete_template(
    template_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """Desativa (soft-delete) um template e retorna a lista atualizada."""
    from models import LabelTemplate, Product

    tpl = db.query(LabelTemplate).filter(LabelTemplate.id == template_id).first()
    nome = tpl.nome if tpl else "—"
    if tpl:
        tpl.ativo = False
        db.commit()

    tpls = db.query(LabelTemplate).filter(LabelTemplate.ativo == True).order_by(LabelTemplate.nome).all()
    products = db.query(Product).filter(Product.ativo == True).order_by(Product.nome).all()
    prod_map = {str(p.id): p.nome for p in products}

    resp = templates.TemplateResponse(
        "fragments/label_templates_list.html",
        {"request": request, "templates_list": tpls, "prod_map": prod_map},
    )
    resp.headers["HX-Trigger"] = json.dumps({"showToast": {"message": f"Modelo '{nome}' removido.", "type": "info"}})
    return resp


# ─── Impressão por template ───────────────────────────────────────────────────

@router.post("/api/labels/print-by-template", response_class=HTMLResponse)
def print_by_template(
    request: Request,
    template_id: str = Form(...),
    quantidade: int = Form(default=1),
    printer_host: str = Form(default=""),
    printer_port: int = Form(default=9100),
    db: Session = Depends(get_db),
):
    """Imprime N etiquetas usando um template salvo. Gera lote automaticamente."""
    from services.label_service import print_by_template as svc_print, DEFAULT_PRINTER_HOST, DEFAULT_PRINTER_PORT

    host = printer_host.strip() or DEFAULT_PRINTER_HOST
    port = printer_port or DEFAULT_PRINTER_PORT

    try:
        tid = uuid.UUID(template_id)
        result = svc_print(db, tid, quantidade=quantidade, printer_host=host, printer_port=port)
        content = (
            f'<div class="rounded-xl border border-green-200 bg-green-50 p-4 space-y-2">'
            f'  <div class="flex items-center gap-2 text-green-800 font-semibold text-sm">'
            f'    <i class="ph-fill ph-check-circle text-green-600 text-lg"></i>'
            f'    {result["quantidade"]} etiqueta(s) enviadas para {host}:{port}'
            f'  </div>'
            f'  <div class="grid grid-cols-2 gap-x-6 gap-y-1 text-xs text-green-700">'
            f'    <span><strong>Lote:</strong> {result["lote_code"]}</span>'
            f'    <span><strong>Fabricação:</strong> {result["data_fab"]}</span>'
            f'    <span><strong>Validade:</strong> {result["data_val"]}</span>'
            f'    <span><strong>Produto:</strong> {result["produto"]}</span>'
            f'  </div>'
            f'</div>'
        )
        msg = {"showToast": {"message": f'{result["quantidade"]} etiqueta(s) impressas! Lote: {result["lote_code"]}', "type": "success"}}
    except Exception as e:
        content = (
            f'<div class="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">'
            f'  <i class="ph-fill ph-x-circle text-red-600"></i> {e}'
            f'</div>'
        )
        msg = {"showToast": {"message": f"Erro: {e}", "type": "error"}}

    resp = HTMLResponse(content=content)
    resp.headers["HX-Trigger"] = json.dumps(msg)
    return resp

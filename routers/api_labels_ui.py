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

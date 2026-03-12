"""FE-03 — API de Produção para UI (iniciar, registrar consumo, concluir OP)."""
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/production", tags=["API — Produção UI FE-03"])
templates = Jinja2Templates(directory="templates")


@router.get("/ops", response_class=HTMLResponse)
def fragment_ops(
    request: Request,
    status: str = "",
    db: Session = Depends(get_db),
):
    """Retorna linhas da tabela de OPs (fragment para HTMX)."""
    from services.production_service import list_production_orders
    ops = list_production_orders(db, status=status or None)
    return templates.TemplateResponse(
        "fragments/op_rows.html",
        {"request": request, "ops": ops},
    )


@router.post("/{batch_id}/start", response_class=HTMLResponse)
def start_op(
    batch_id: uuid.UUID,
    request: Request,
    operador_id: str = Form(...),
    db: Session = Depends(get_db),
):
    """Inicia uma OP e retorna o card atualizado."""
    from services.production_service import start_production
    import json

    try:
        result = start_production(db, batch_id, operador_id)
        msg = {"showToast": {"message": f"OP iniciada por {operador_id}!", "type": "success"}}
    except ValueError as e:
        msg = {"showToast": {"message": str(e), "type": "error"}}
        result = {}

    response = templates.TemplateResponse(
        "fragments/op_status.html",
        {"request": request, "op": result, "batch_id": str(batch_id)},
    )
    response.headers["HX-Trigger"] = json.dumps(msg)
    return response


@router.post("/{batch_id}/complete", response_class=HTMLResponse)
def complete_op(
    batch_id: uuid.UUID,
    request: Request,
    quantidade_real: float = Form(...),
    db: Session = Depends(get_db),
):
    """Conclui uma OP e retorna o card atualizado."""
    from services.production_service import complete_production_order
    import json

    try:
        result = complete_production_order(db, batch_id=batch_id, quantidade_real=quantidade_real)
        msg = {"showToast": {"message": "OP concluída com sucesso!", "type": "success"}}
    except (ValueError, Exception) as e:
        msg = {"showToast": {"message": str(e), "type": "error"}}
        result = {}

    response = templates.TemplateResponse(
        "fragments/op_status.html",
        {"request": request, "op": result, "batch_id": str(batch_id)},
    )
    response.headers["HX-Trigger"] = json.dumps(msg)
    return response

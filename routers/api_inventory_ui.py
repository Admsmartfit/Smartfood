"""FE-03 — API de Inventário/Estoque e Recebimento NF-e para UI."""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, Query, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/inventory", tags=["API — Inventário UI FE-03"])
templates = Jinja2Templates(directory="templates")


@router.get("/search", response_class=HTMLResponse)
def inventory_search(
    request: Request,
    category: str = Query(default=""),
    status: str = Query(default=""),
    q: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Retorna linhas do inventário com barras de cobertura."""
    from models import Ingredient

    query = db.query(Ingredient).filter(Ingredient.ativo == True)
    if q:
        query = query.filter(Ingredient.nome.ilike(f"%{q}%"))

    ings = query.order_by(Ingredient.nome).all()

    items = []
    for ing in ings:
        estoque = ing.estoque_atual or 0.0
        estoque_min = ing.estoque_minimo or 0.0
        lead_time = ing.lead_time_dias or 0

        # Cobertura em dias (estimativa simples)
        consumo_diario = estoque_min / max(lead_time + 2, 1) if estoque_min > 0 else 0
        coverage_days = round(estoque / consumo_diario) if consumo_diario > 0 else 999

        # Status
        if estoque <= 0:
            ing_status = "zero"
        elif estoque_min > 0 and estoque < estoque_min:
            ing_status = "critical" if estoque < estoque_min * 0.5 else "warning"
        elif coverage_days <= lead_time:
            ing_status = "warning"
        else:
            ing_status = "ok"

        # Filtro de status
        if status and ing_status != status and not (status == "critical" and ing_status == "zero"):
            continue

        items.append({
            "id": str(ing.id),
            "nome": ing.nome,
            "unidade": ing.unidade or "",
            "estoque_atual": round(estoque, 2),
            "estoque_minimo": round(estoque_min, 2),
            "lead_time_dias": lead_time,
            "coverage_days": coverage_days if coverage_days < 999 else None,
            "status": ing_status,
            "custo_atual": ing.custo_atual or 0.0,
            # Para a barra visual: % do estoque em relação ao mínimo*1.5
            "bar_pct": min(100, round(estoque / max(estoque_min * 1.5, 0.01) * 100)),
        })

    return templates.TemplateResponse(
        "fragments/inventory_rows.html",
        {"request": request, "items": items, "query": q},
    )


@router.post("/receive-nfe", response_class=HTMLResponse)
async def receive_nfe(
    request: Request,
    nfe_xml: UploadFile = File(...),
    peso_balanca: float = Form(...),
    db: Session = Depends(get_db),
):
    """Processa XML da NF-e, valida peso e registra no estoque."""
    import json
    from services.nfe_service import parse_nfe_xml, validate_weight_divergence

    xml_content = (await nfe_xml.read()).decode("utf-8", errors="replace")

    nfe_data = {}
    weight_check = {}
    error_msg = None

    try:
        nfe_data = parse_nfe_xml(xml_content)
        peso_nfe = nfe_data.get("peso_liquido") or nfe_data.get("valor_total", 0)
        weight_check = validate_weight_divergence(
            nfe_peso=float(peso_nfe) if peso_nfe else 0,
            peso_balanca=peso_balanca,
        )
    except Exception as e:
        error_msg = str(e)

    trigger = json.dumps({
        "showToast": {
            "message": "NF-e processada!" if not error_msg else f"Erro: {error_msg}",
            "type": "success" if not error_msg else "error",
        }
    })
    response = templates.TemplateResponse(
        "fragments/nfe_result.html",
        {
            "request": request,
            "nfe": nfe_data,
            "weight_check": weight_check,
            "peso_balanca": peso_balanca,
            "error": error_msg,
        },
    )
    response.headers["HX-Trigger"] = trigger
    return response

"""FE-03/17 — API de Produção para UI (iniciar, consumo, concluir, porcionamento)."""
import json
import math
import uuid
from datetime import datetime, timezone

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


@router.post("/{batch_id}/usage", response_class=HTMLResponse)
def record_usage(
    batch_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """Registra consumo real de ingredientes e retorna fragmento com divergências."""
    from services.production_service import record_ingredient_usage
    import json

    error_msg = None
    usages = []

    try:
        form_data = {}
        result = record_ingredient_usage(db, batch_id, form_data)
        usages = result.get("usages", [])
        msg = {"showToast": {"message": "Consumo registrado!", "type": "success"}}
    except Exception as e:
        error_msg = str(e)
        msg = {"showToast": {"message": f"Erro: {error_msg}", "type": "error"}}

    response = templates.TemplateResponse(
        "fragments/usage_result.html",
        {"request": request, "usages": usages, "error": error_msg},
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


# ── FE-17: Apontamento de Porcionamento ──────────────────────────────────────

@router.get("/{batch_id}/apontamento", response_class=HTMLResponse)
def apontamento_form(
    batch_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    """Retorna fragment do formulário mobile de apontamento de porções."""
    from models import ProductionBatch
    batch = db.query(ProductionBatch).filter(ProductionBatch.id == batch_id).first()
    if not batch:
        return HTMLResponse('<p class="text-red-600">OP não encontrada.</p>')
    batch.product  # eager load
    porcoes_esperadas = None
    if batch.product and batch.product.peso_porcao_gramas:
        porcao_kg = batch.product.peso_porcao_gramas / 1000
        porcoes_esperadas = math.floor(
            (batch.quantidade_planejada or 0) / porcao_kg
        ) if porcao_kg > 0 else None
    return templates.TemplateResponse(
        "operations/fragments/production_apontamento.html",
        {"request": request, "batch": batch, "porcoes_esperadas": porcoes_esperadas},
    )


@router.post("/{batch_id}/finalizar-porcoes", response_class=HTMLResponse)
def finalizar_porcoes(
    batch_id: uuid.UUID,
    porcoes_reais: float = Form(...),
    sobra_gramas: float = Form(0.0),
    peso_medio_porcao_gramas: float = Form(0.0),
    operador_id: str = Form(""),
    db: Session = Depends(get_db),
):
    """
    FE-17 — Finaliza OP com porcionamento real.
    • Incrementa Product.estoque_atual em porcoes_reais (unidades).
    • Cria registro YieldHistory com FC/FCoc e alertas de erosão de margem.
    • Atualiza ProductionBatch.status → CONCLUIDA.
    """
    from models import ProductionBatch, Product, YieldHistory, SystemAlert

    batch = db.query(ProductionBatch).filter(ProductionBatch.id == batch_id).first()
    if not batch:
        r = HTMLResponse('<p class="text-red-600">OP não encontrada.</p>')
        r.headers["HX-Trigger"] = json.dumps(
            {"showToast": {"message": "OP não encontrada.", "type": "error"}}
        )
        return r

    produto = db.query(Product).filter(Product.id == batch.product_id).first()
    now = datetime.now(timezone.utc)

    # Detecta erosão de margem: porção real > configurada + 5%
    alerta_erosao = False
    if produto and produto.peso_porcao_gramas and peso_medio_porcao_gramas > 0:
        excesso_pct = (peso_medio_porcao_gramas - produto.peso_porcao_gramas) / produto.peso_porcao_gramas * 100
        if excesso_pct > 5:
            alerta_erosao = True
            alerta = SystemAlert(
                id=uuid.uuid4(),
                tipo="erosao_margem",
                categoria="producao",
                produto_id=batch.product_id,
                mensagem=(
                    f"Erosão de margem na OP {str(batch_id)[:8]}: porção média "
                    f"{peso_medio_porcao_gramas:.0f}g vs. {produto.peso_porcao_gramas:.0f}g configurados "
                    f"(+{excesso_pct:.1f}%). Cada unidade está pesando mais do previsto."
                ),
                severidade="critico" if excesso_pct > 10 else "atencao",
                status="ativo",
            )
            db.add(alerta)

    # Custo por porção real
    custo_por_porcao_real = None
    if porcoes_reais > 0 and batch.custo_total:
        custo_por_porcao_real = round(batch.custo_total / porcoes_reais, 4)

    # YieldHistory
    yield_rec = YieldHistory(
        id=uuid.uuid4(),
        batch_id=batch_id,
        product_id=batch.product_id,
        porcoes_esperadas=batch.porcoes_esperadas,
        porcoes_reais=porcoes_reais,
        peso_porcao_gramas_configurado=produto.peso_porcao_gramas if produto else None,
        sobra_gramas=sobra_gramas,
        custo_total_lote=batch.custo_total,
        custo_por_porcao_real=custo_por_porcao_real,
        alerta_erosao_margem=alerta_erosao,
        operador_id=operador_id.strip() or None,
    )
    db.add(yield_rec)

    # Atualiza batch
    batch.porcoes_reais_produzidas = porcoes_reais
    batch.sobra_gramas = sobra_gramas
    batch.quantidade_real = porcoes_reais
    batch.data_fim = now
    batch.status = "CONCLUIDA"

    # Incrementa estoque em unidades
    if produto:
        unidade = (produto.unidade_estoque or "unid").lower()
        if unidade == "unid":
            produto.estoque_atual = (produto.estoque_atual or 0) + porcoes_reais
        else:
            # kg: converte porções → kg
            if produto.peso_porcao_gramas:
                kg_produzidos = porcoes_reais * produto.peso_porcao_gramas / 1000
                produto.estoque_atual = (produto.estoque_atual or 0) + kg_produzidos

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        r = HTMLResponse(f'<p class="text-red-600">Erro: {e}</p>')
        r.headers["HX-Trigger"] = json.dumps(
            {"showToast": {"message": f"Erro ao finalizar: {e}", "type": "error"}}
        )
        return r

    avisos = ""
    if alerta_erosao:
        avisos = '<p class="text-amber-700 text-sm mt-1">⚠️ Alerta de erosão de margem registrado.</p>'
    if sobra_gramas > 0:
        avisos += f'<p class="text-gray-500 text-sm mt-1">Sobra: {sobra_gramas:.0f}g registrada.</p>'

    r = HTMLResponse(
        f'<div class="p-4 rounded-xl bg-green-50 border border-green-200 space-y-1">'
        f'<p class="font-semibold text-green-800 flex items-center gap-2">'
        f'<i class="ph-fill ph-check-circle text-xl"></i>'
        f'{porcoes_reais:.0f} porções estocadas com sucesso!</p>'
        f'{avisos}'
        f'<a href="/operations/production" class="text-sm text-blue-600 underline mt-2 block">'
        f'← Voltar às Ordens de Produção</a>'
        f'</div>'
    )
    r.headers["HX-Trigger"] = json.dumps(
        {"showToast": {"message": f"{porcoes_reais:.0f} porções estocadas!", "type": "success"}}
    )
    return r

"""Módulo Financeiro — Despesas Operacionais."""
import json
import uuid as _uuid
from datetime import datetime, date

from fastapi import APIRouter, Depends, Form, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/finances", tags=["API — Financeiro"])
templates = Jinja2Templates(directory="templates")


def _toast(msg: str, tipo: str = "success") -> str:
    return json.dumps({"showToast": {"message": msg, "type": tipo}})


def _ok(html: str, msg: str, tipo: str = "success") -> HTMLResponse:
    r = HTMLResponse(content=html)
    r.headers["HX-Trigger"] = _toast(msg, tipo)
    return r


def _err(msg: str) -> HTMLResponse:
    html = (
        f'<div class="flex items-center gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-800">'
        f'<i class="ph-fill ph-x-circle text-lg"></i><span>{msg}</span></div>'
    )
    r = HTMLResponse(content=html)
    r.headers["HX-Trigger"] = _toast(msg, "error")
    return r


def _status_badge(status: str) -> str:
    colors = {
        "pago": "bg-green-100 text-green-700 border-green-200",
        "pendente": "bg-amber-100 text-amber-700 border-amber-200",
        "vencido": "bg-red-100 text-red-700 border-red-200",
    }
    cls = colors.get(status, "bg-gray-100 text-gray-600 border-gray-200")
    return f'<span class="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium border {cls}">{status}</span>'


def _expense_row(exp) -> str:
    badge = _status_badge(exp.status_pagamento)
    comp = exp.data_competencia.strftime("%m/%Y") if exp.data_competencia else "—"
    venc = exp.data_vencimento.strftime("%d/%m/%Y") if exp.data_vencimento else "—"
    toggle_status = "pago" if exp.status_pagamento != "pago" else "pendente"
    toggle_label = "Marcar pago" if exp.status_pagamento != "pago" else "Marcar pendente"
    return (
        f'<tr id="exp-{exp.id}" class="odd:bg-white even:bg-slate-50 text-sm">'
        f'<td class="px-4 py-2 font-medium text-gray-900 max-w-[200px] truncate">{exp.descricao}</td>'
        f'<td class="px-4 py-2 text-gray-500">{exp.categoria_despesa}</td>'
        f'<td class="px-4 py-2 text-right font-mono font-semibold text-gray-800">R$ {exp.valor:.2f}</td>'
        f'<td class="px-4 py-2 text-center text-gray-500">{comp}</td>'
        f'<td class="px-4 py-2 text-center text-gray-500">{venc}</td>'
        f'<td class="px-4 py-2 text-center">{badge}</td>'
        f'<td class="px-4 py-2 text-center">'
        f'<div class="flex items-center justify-center gap-1">'
        f'<button hx-patch="/api/finances/expense/{exp.id}/status" '
        f'hx-vals=\'{{"status":"{toggle_status}"}}\' '
        f'hx-target="#exp-{exp.id}" hx-swap="outerHTML" '
        f'title="{toggle_label}" '
        f'class="p-1 text-blue-500 hover:text-blue-700 rounded"><i class="ph ph-check-circle"></i></button>'
        f'<button hx-delete="/api/finances/expense/{exp.id}" '
        f'hx-target="#exp-{exp.id}" hx-swap="outerHTML swap:300ms" '
        f'hx-confirm="Excluir lançamento?" '
        f'class="p-1 text-red-500 hover:text-red-700 rounded"><i class="ph ph-trash"></i></button>'
        f'</div>'
        f'</td></tr>'
    )


# ─── Listagem ──────────────────────────────────────────────────────────────────

@router.get("/expenses", response_class=HTMLResponse)
def list_expenses(
    request: Request,
    period: str = Query(default=""),
    db: Session = Depends(get_db),
):
    from models import FinancialExpense
    q = db.query(FinancialExpense)
    if period:
        try:
            year, month = int(period[:4]), int(period[5:7])
            start = datetime(year, month, 1)
            if month == 12:
                end = datetime(year + 1, 1, 1)
            else:
                end = datetime(year, month + 1, 1)
            q = q.filter(
                FinancialExpense.data_competencia >= start,
                FinancialExpense.data_competencia < end,
            )
        except Exception:
            pass
    items = q.order_by(FinancialExpense.data_competencia.desc()).all()
    rows = "".join(_expense_row(e) for e in items)
    return HTMLResponse(
        rows or '<tr><td colspan="7" class="px-4 py-8 text-center text-gray-400 text-sm">Nenhum lançamento encontrado.</td></tr>'
    )


# ─── Criação ───────────────────────────────────────────────────────────────────

@router.post("/expense", response_class=HTMLResponse)
def create_expense(
    request: Request,
    descricao: str = Form(...),
    categoria_despesa: str = Form("Outros"),
    valor: float = Form(...),
    data_competencia: str = Form(...),
    data_vencimento: str = Form(""),
    status_pagamento: str = Form("pendente"),
    db: Session = Depends(get_db),
):
    from models import FinancialExpense
    try:
        comp_dt = datetime.strptime(data_competencia, "%Y-%m") if len(data_competencia) == 7 else datetime.strptime(data_competencia, "%Y-%m-%d")
        venc_dt = datetime.strptime(data_vencimento, "%Y-%m-%d") if data_vencimento else None
        exp = FinancialExpense(
            id=_uuid.uuid4(),
            descricao=descricao.strip(),
            categoria_despesa=categoria_despesa.strip(),
            valor=valor,
            data_competencia=comp_dt,
            data_vencimento=venc_dt,
            status_pagamento=status_pagamento,
        )
        db.add(exp)
        db.commit()
        db.refresh(exp)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao lançar: {e}")

    return _ok(_expense_row(exp), f'Lançamento "{exp.descricao}" registrado!')


# ─── Atualizar status ──────────────────────────────────────────────────────────

@router.patch("/expense/{exp_id}/status", response_class=HTMLResponse)
def toggle_expense_status(
    exp_id: str,
    status: str = Form(...),
    db: Session = Depends(get_db),
):
    from models import FinancialExpense
    exp = db.query(FinancialExpense).filter(FinancialExpense.id == exp_id).first()
    if not exp:
        return _err("Lançamento não encontrado.")
    try:
        exp.status_pagamento = status
        db.commit()
        db.refresh(exp)
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao atualizar: {e}")
    return _ok(_expense_row(exp), f'Status atualizado para "{status}".')


# ─── Exclusão ──────────────────────────────────────────────────────────────────

@router.delete("/expense/{exp_id}", response_class=HTMLResponse)
def delete_expense(exp_id: str, db: Session = Depends(get_db)):
    from models import FinancialExpense
    exp = db.query(FinancialExpense).filter(FinancialExpense.id == exp_id).first()
    if not exp:
        return _err("Lançamento não encontrado.")
    try:
        db.delete(exp)
        db.commit()
    except Exception as e:
        db.rollback()
        return _err(f"Erro ao excluir: {e}")
    r = HTMLResponse("")
    r.headers["HX-Trigger"] = _toast("Lançamento excluído.", "success")
    return r


# ─── Resumo DRE (despesas por categoria) ──────────────────────────────────────

@router.get("/dre-summary")
def dre_summary(
    period: str = Query(default=""),
    db: Session = Depends(get_db),
):
    from models import FinancialExpense
    from sqlalchemy import func as sqlfunc

    if not period:
        today = date.today()
        period = f"{today.year}-{today.month:02d}"

    try:
        year, month = int(period[:4]), int(period[5:7])
        start = datetime(year, month, 1)
        end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    except Exception:
        today = date.today()
        start = datetime(today.year, today.month, 1)
        end = datetime.utcnow()

    rows = (
        db.query(
            FinancialExpense.categoria_despesa,
            sqlfunc.sum(FinancialExpense.valor).label("total"),
        )
        .filter(
            FinancialExpense.data_competencia >= start,
            FinancialExpense.data_competencia < end,
        )
        .group_by(FinancialExpense.categoria_despesa)
        .all()
    )

    total_pago = (
        db.query(sqlfunc.sum(FinancialExpense.valor))
        .filter(
            FinancialExpense.data_competencia >= start,
            FinancialExpense.data_competencia < end,
            FinancialExpense.status_pagamento == "pago",
        )
        .scalar() or 0.0
    )

    total_pendente = (
        db.query(sqlfunc.sum(FinancialExpense.valor))
        .filter(
            FinancialExpense.data_competencia >= start,
            FinancialExpense.data_competencia < end,
            FinancialExpense.status_pagamento != "pago",
        )
        .scalar() or 0.0
    )

    breakdown = {r.categoria_despesa: round(r.total, 2) for r in rows}
    total = round(sum(breakdown.values()), 2)

    return JSONResponse({
        "period": period,
        "total_despesas": total,
        "total_pago": round(total_pago, 2),
        "total_pendente": round(total_pendente, 2),
        "breakdown": breakdown,
    })

"""FE-07 — API de DRE e SPI para UI."""
import json
import io
import csv
from datetime import datetime, date

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(tags=["API — DRE / SPI UI FE-07"])
templates = Jinja2Templates(directory="templates")


def _period_to_range(period: str):
    """'2026-03' → ('2026-03-01', '2026-03-31')"""
    try:
        year, month = int(period[:4]), int(period[5:7])
        start = date(year, month, 1).isoformat()
        # último dia do mês
        if month == 12:
            end = date(year + 1, 1, 1).replace(day=1)
        else:
            end = date(year, month + 1, 1)
        from datetime import timedelta
        end = (end - timedelta(days=1)).isoformat()
        return start, end
    except Exception:
        today = date.today()
        return date(today.year, today.month, 1).isoformat(), today.isoformat()


@router.get("/api/dre/fragment", response_class=HTMLResponse)
def dre_fragment(
    request: Request,
    period: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Retorna tabela DRE do período (YYYY-MM)."""
    from services.reports_service import calculate_dre

    if not period:
        today = date.today()
        period = f"{today.year}-{today.month:02d}"

    start, end = _period_to_range(period)
    dre = {}
    error_msg = None
    try:
        dre = calculate_dre(db, start, end, "mes")
    except Exception as e:
        error_msg = str(e)

    # Despesas operacionais do período
    total_despesas_op = 0.0
    despesas_breakdown = {}
    try:
        from models import FinancialExpense
        from sqlalchemy import func as sqlfunc
        from datetime import datetime as _dt
        _start_dt = _dt.fromisoformat(start)
        _end_dt = _dt.fromisoformat(end).replace(hour=23, minute=59, second=59)
        rows = (
            db.query(
                FinancialExpense.categoria_despesa,
                sqlfunc.sum(FinancialExpense.valor).label("total"),
            )
            .filter(
                FinancialExpense.data_competencia >= _start_dt,
                FinancialExpense.data_competencia <= _end_dt,
            )
            .group_by(FinancialExpense.categoria_despesa)
            .all()
        )
        despesas_breakdown = {r.categoria_despesa: round(r.total, 2) for r in rows}
        total_despesas_op = round(sum(despesas_breakdown.values()), 2)
    except Exception:
        pass

    return templates.TemplateResponse(
        "fragments/dre_table.html",
        {
            "request": request,
            "dre": dre.get("dre_consolidado", {}),
            "periodo": dre.get("periodo", {"inicio": start, "fim": end}),
            "evolucao": dre.get("evolucao_temporal", []),
            "period": period,
            "error": error_msg,
            "total_despesas_op": total_despesas_op,
            "despesas_breakdown": despesas_breakdown,
        },
    )


@router.get("/api/dre/export")
def dre_export(
    period: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """Exporta DRE do período como CSV."""
    from services.reports_service import calculate_dre

    if not period:
        today = date.today()
        period = f"{today.year}-{today.month:02d}"

    start, end = _period_to_range(period)
    dre = calculate_dre(db, start, end, "mes").get("dre_consolidado", {})

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Item", "Valor (R$)", "%"])

    receita = dre.get("receita_bruta", 0)
    cmv = dre.get("cmv", 0)
    breakdown = dre.get("cmv_breakdown", {})
    lucro = dre.get("lucro_bruto", 0)
    margem = dre.get("margem_bruta_pct", 0)

    def pct(v):
        return f"{round(v / receita * 100, 1)}%" if receita > 0 else "—"

    writer.writerow(["Receita Bruta", f"{receita:.2f}", "100%"])
    writer.writerow(["(-) CMV Total", f"-{cmv:.2f}", pct(cmv)])
    writer.writerow(["  Insumos", f"-{breakdown.get('insumos', 0):.2f}", ""])
    writer.writerow(["  Labor", f"-{breakdown.get('labor', 0):.2f}", ""])
    writer.writerow(["  Energia", f"-{breakdown.get('energia', 0):.2f}", ""])
    writer.writerow(["(=) Lucro Bruto", f"{lucro:.2f}", f"{margem:.1f}%"])
    writer.writerow(["Total Pedidos", dre.get("total_pedidos", 0), ""])
    writer.writerow(["Ticket Médio", f"{dre.get('ticket_medio', 0):.2f}", ""])

    output.seek(0)
    filename = f"DRE_{period}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/api/fragments/suppliers-spi", response_class=HTMLResponse)
def suppliers_spi(
    request: Request,
    months: int = Query(default=6),
    db: Session = Depends(get_db),
):
    """Tabela de fornecedores com SPI scores."""
    from services.spi_service import spi_ranking

    data = {}
    error_msg = None
    try:
        data = spi_ranking(db, months=months)
    except Exception as e:
        error_msg = str(e)

    suppliers = data.get("ranking", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])

    return templates.TemplateResponse(
        "fragments/suppliers_spi.html",
        {
            "request": request,
            "suppliers": suppliers,
            "months": months,
            "error": error_msg,
        },
    )

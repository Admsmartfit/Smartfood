"""
E-16 — Rotas de Relatórios: DRE Automatizado e Relatórios de Lote

Endpoints:
  GET /reports/dre                       — DRE (P&L) por período
  GET /reports/batches/{id}              — Relatório detalhado de lote
  GET /reports/top-products              — Ranking de produtos por receita/margem
  GET /reports/margin-evolution/{id}     — Evolução de margem de produto
  GET /reports/supplier-performance      — SPI: índice de desempenho de fornecedores
"""
import uuid
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from services.reports_service import (
    calculate_dre,
    batch_report,
    top_products_report,
    margin_evolution,
    supplier_performance,
)

router = APIRouter(prefix="/reports", tags=["Relatórios e DRE - E-16"])


# ─── DRE Automatizado ────────────────────────────────────────────────────────

@router.get("/dre")
def get_dre(
    data_inicio: str = Query(..., description="Data início ISO: 2025-01-01"),
    data_fim: str = Query(..., description="Data fim ISO: 2025-12-31"),
    agrupar_por: Literal["dia", "semana", "mes", "total"] = Query(
        default="mes",
        description="Granularidade da evolução temporal"
    ),
    db: Session = Depends(get_db),
):
    """
    E-16 — DRE (Demonstração do Resultado do Exercício) automatizado.

    Calcula receita, CMV, lucro bruto e margem para o período:

    ```
    Receita Bruta  = Σ pedidos.total  (status=ENTREGUE)
    CMV            = Σ lotes.custo_total  (status=CONCLUIDA)
    Lucro Bruto    = Receita - CMV
    Margem Bruta%  = Lucro Bruto / Receita × 100
    ```

    O `CMV` é decomposto em: **insumos + labor + energia**.

    `agrupar_por`: `dia`, `semana`, `mes` ou `total` para a evolução temporal.
    """
    try:
        return calculate_dre(db, data_inicio, data_fim, agrupar_por)
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=422, detail=str(e))


# ─── Relatório de Lote ───────────────────────────────────────────────────────

@router.get("/batches/{batch_id}")
def get_batch_report(batch_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    E-16 — Relatório completo de um lote de produção.

    Inclui:
    - **Rendimento%** = quantidade_real / quantidade_planejada × 100
    - **Custo por unidade** = custo_total / quantidade_real
    - Breakdown de custos: insumos, labor, energia
    - Consumo real vs planejado por ingrediente (divergências)
    - Rastreabilidade: lotes de ingredientes consumidos
    - Status de rendimento: `ok` (≥95%), `atencao` (≥85%), `critico` (<85%)
    """
    try:
        return batch_report(db, batch_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── Top Produtos ────────────────────────────────────────────────────────────

@router.get("/top-products")
def get_top_products(
    data_inicio: str = Query(..., description="Data início ISO"),
    data_fim: str = Query(..., description="Data fim ISO"),
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """
    E-16 — Ranking de produtos por receita no período.

    Retorna para cada produto:
    - Receita total e participação percentual no faturamento
    - Volume vendido (unidades)
    - Margem média pct (da tabela order_items)
    - Ticket médio por pedido
    """
    try:
        return top_products_report(db, data_inicio, data_fim, limit)
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=422, detail=str(e))


# ─── Evolução de Margem por Produto ──────────────────────────────────────────

@router.get("/margin-evolution/{product_id}")
def get_margin_evolution(
    product_id: uuid.UUID,
    data_inicio: str = Query(..., description="Data início ISO"),
    data_fim: str = Query(..., description="Data fim ISO"),
    agrupar_por: Literal["dia", "semana", "mes"] = Query(default="mes"),
    db: Session = Depends(get_db),
):
    """
    E-16 — Evolução temporal da margem de um produto.

    Para cada período, compara:
    - `receita`: vendas do produto (pedidos entregues)
    - `custo_producao`: custo dos lotes concluídos no período
    - `lucro_bruto` e `margem_pct` calculados

    Útil para identificar tendências de compressão ou expansão de margem.
    """
    try:
        return margin_evolution(db, product_id, data_inicio, data_fim, agrupar_por)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ─── SPI — Supplier Performance Index ────────────────────────────────────────

@router.get("/supplier-performance")
def get_supplier_performance(
    data_inicio: str = Query(..., description="Data início ISO"),
    data_fim: str = Query(..., description="Data fim ISO"),
    db: Session = Depends(get_db),
):
    """
    E-16 — Índice de Desempenho de Fornecedores (SPI) no período.

    Para cada fornecedor:
    - Total de pedidos e cotações no período
    - Score médio das cotações RFQ (0-1: 60% preço + 40% prazo)
    - Prazo médio de entrega (dias)
    - Classificação: `excelente` (≥0.8), `bom` (≥0.6), `regular` (≥0.4), `ruim` (<0.4)
    """
    try:
        return supplier_performance(db, data_inicio, data_fim)
    except (ValueError, Exception) as e:
        raise HTTPException(status_code=422, detail=str(e))

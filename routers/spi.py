"""
E-17 — Rotas SPI: Índice de Performance de Fornecedores

Endpoints:
  GET  /spi/ranking                  — ranking geral (todos fornecedores)
  GET  /spi/suppliers/{id}           — SPI detalhado de um fornecedor
  POST /spi/recalculate              — força recálculo de todos os SPIs
"""
import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from services.spi_service import calculate_spi, spi_ranking, SPI_LOOKBACK_MONTHS

router = APIRouter(prefix="/spi", tags=["SPI Fornecedores - E-17"])


@router.get("/ranking")
def get_spi_ranking(
    months: int = Query(default=SPI_LOOKBACK_MONTHS, ge=1, le=24,
                        description="Janela histórica em meses"),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    """
    US-017 — Ranking de fornecedores por SPI (0-100), atualizado sob demanda.

    **Fórmula SPI:**
    ```
    SPI = (pontualidade × 40%) + (acuracidade_peso × 40%) + (score_cotacao × 20%)
    ```

    | Classificação | Faixa    |
    |---------------|----------|
    | Excelente     | ≥ 80     |
    | Bom           | 60 – 79  |
    | Regular       | 40 – 59  |
    | Ruim          | < 40     |

    - **Pontualidade**: % de pedidos com lotes recebidos até a data prevista
    - **Acuracidade de peso**: % de lotes sem divergência > 0,5%
    - **Score de cotação**: média do score RFQ (60% preço + 40% prazo)
    """
    return spi_ranking(db, months=months, limit=limit)


@router.get("/suppliers/{supplier_id}")
def get_supplier_spi(
    supplier_id: uuid.UUID,
    months: int = Query(default=SPI_LOOKBACK_MONTHS, ge=1, le=24),
    db: Session = Depends(get_db),
):
    """
    SPI detalhado de um fornecedor específico com breakdown completo:
    - Score de pontualidade (detalhamento por pedido de compra)
    - Score de acuracidade de peso (detalhamento por lote)
    - Score médio de cotações RFQ
    """
    try:
        return calculate_spi(db, supplier_id, months=months)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/recalculate")
def recalculate_all_spi(
    months: int = Query(default=SPI_LOOKBACK_MONTHS, ge=1, le=24),
    db: Session = Depends(get_db),
):
    """
    Recalcula o SPI de todos os fornecedores e retorna o ranking atualizado.
    Equivale a GET /spi/ranking mas deixa explícito que é um recálculo forçado.
    """
    return spi_ranking(db, months=months)

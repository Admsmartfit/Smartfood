import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

import models
from database import engine, get_db
from routers import bom, pricing, dashboard, demand, seasonality, alerts
from routers.inventory import router as inventory_router, production_router, traceability_router
from routers.supplies import router as supplies_router
from routers.purchasing import router as purchasing_router
from routers.receiving import router as receiving_router
from routers.production_orders import router as production_orders_router
from routers.portal import router as portal_router
from routers.labels import router as labels_router
from routers.public import router as public_router
from routers.reports import router as reports_router
from routers.spi import router as spi_router
from routers.sync import router as sync_router
from routers.mobile import router as mobile_router
from services.margin_monitor import margin_monitor_task
from services.demand_engine import daily_demand_task
from services.alert_orchestrator import alert_orchestrator_task
from services.daily_briefing_service import daily_briefing_task

logging.basicConfig(level=logging.INFO)

# Cria as tabelas se não existirem (em produção, usar Alembic)
models.Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # E-03: monitor de margem a cada 15 minutos
    margin_task = asyncio.create_task(margin_monitor_task(get_db))
    # E-04: pipeline de demanda/MRP às 23h59
    demand_task = asyncio.create_task(daily_demand_task(get_db))
    # E-06: orquestrador de alertas a cada 15 minutos
    orch_task = asyncio.create_task(alert_orchestrator_task(get_db))
    # E-18: briefing diário às 7h BRT via WhatsApp
    briefing_task = asyncio.create_task(daily_briefing_task(get_db))
    yield
    for task in (margin_task, demand_task, orch_task, briefing_task):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="SmartFood Ops 360 - Intelligence Edition",
    description="ERP industrial com IA preditiva para gestão de ultracongelados B2B",
    version="0.19.0",
    lifespan=lifespan,
)

app.include_router(bom.router)
app.include_router(pricing.router)
app.include_router(dashboard.router)
app.include_router(demand.router)
app.include_router(seasonality.router)
app.include_router(alerts.router)
app.include_router(inventory_router)
app.include_router(production_router)
app.include_router(traceability_router)
app.include_router(supplies_router)
app.include_router(purchasing_router)
app.include_router(receiving_router)
app.include_router(production_orders_router)
app.include_router(portal_router)
app.include_router(labels_router)
app.include_router(public_router)
app.include_router(reports_router)
app.include_router(spi_router)
app.include_router(sync_router)
app.include_router(mobile_router)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def read_root():
    return {
        "message": "SmartFood Ops 360 API",
        "etapas_concluidas": [
            "E-01: Modelos e Banco de Dados",
            "E-02: Fichas Técnicas com FC, FCoc e BOM",
            "E-03: Motor de Precificação e Monitor de Margem em Tempo Real",
            "E-04: Motor de Inteligência de Demanda (MRP Preditivo)",
            "E-05: Previsão de Demanda por Histórico e Sazonalidade",
            "E-06: Orquestrador de Alertas Inteligentes",
            "E-07: Gestão de Estoque com PVPS e Rastreabilidade de Lotes",
            "E-08: Gestão de Insumos Não-Alimentícios (Embalagens, Limpeza, EPI)",
            "E-09: Compras Hyper-Automation (Mega API + Gmail)",
            "E-10: Recebimento NF-e com Validação de Peso e Rastreabilidade",
            "E-11: Ordens de Produção com Máquina de Estados e Custo Real",
            "E-12: Portal B2B — Catálogo, Pedidos, Recompra Proativa e NPS",
            "E-13: Inteligência B2B — Previsão de Esgotamento e Notificação de Novo Produto",
            "E-14: Etiquetas Parametrizadas ZPL/TSPL e QR Code Dinâmico",
            "E-15: QR Dinâmico — Destinos Públicos (Rastreabilidade, Promoção, Survey, Substituto)",
            "E-16: DRE Automatizado e Relatórios de Lote (P&L, SPI, Top Produtos, Evolução de Margem)",
            "E-17: SPI — Índice de Performance de Fornecedores (Pontualidade + Acuracidade + Cotação)",
            "E-18: Modo Offline + Sync Idempotente + Briefing Diário 7h via WhatsApp",
            "E-19: PWA Mobile para Operadores (Dashboard, OPs, Scanner, Sync Offline)",
        ],
        "docs": "/docs",
    }

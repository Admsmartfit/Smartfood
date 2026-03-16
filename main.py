import asyncio
import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()  # carrega .env antes de qualquer import que use os.getenv

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates  # noqa: F401 — disponível para routers via import direto
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request as StarletteRequest
from starlette.responses import RedirectResponse

import models
from database import engine, get_db
from routers.auth import router as auth_router
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
# ── Frontend UI Routers (FE-01+) ──────────────────────────────────────────────
from routers.ui_dashboard import router as ui_dashboard_router
from routers.ui_operations import router as ui_operations_router
from routers.ui_commercial import router as ui_commercial_router
from routers.api_fragments import router as api_fragments_router
from routers.api_intelligence import router as api_intelligence_router
from routers.api_bom import router as api_bom_router
from routers.api_production_ui import router as api_production_ui_router
from routers.api_inventory_ui import router as api_inventory_ui_router
from routers.api_purchasing_ui import router as api_purchasing_ui_router
from routers.api_b2b_ui import router as api_b2b_ui_router
from routers.api_labels_ui import router as api_labels_ui_router
from routers.api_dre_ui import router as api_dre_ui_router
from routers.api_settings_ui import router as api_settings_ui_router
from routers.api_cadastro_ui import router as api_cadastro_ui_router
from routers.api_users_ui import router as api_users_ui_router
from routers.api_receiving_ui import router as api_receiving_ui_router
from routers.api_finances_ui import router as api_finances_ui_router
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


# Caminhos que não precisam de autenticação
_AUTH_SKIP = ("/login", "/static", "/public", "/favicon.ico", "/qr/", "/docs", "/openapi")


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in _AUTH_SKIP):
            return await call_next(request)
        if not request.session.get("user_id"):
            return RedirectResponse("/login", status_code=302)
        return await call_next(request)


app = FastAPI(
    title="SmartFood Ops 360 - Intelligence Edition",
    description="ERP industrial com IA preditiva para gestão de ultracongelados B2B",
    version="0.20.0",
    lifespan=lifespan,
)

app.add_middleware(AuthMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=os.getenv("SECRET_KEY", "smartfood-secret-change-in-production"),
    session_cookie="sf_session",
    max_age=28800,  # 8 horas
    same_site="lax",
    https_only=False,
)

app.include_router(auth_router)


@app.get('/favicon.ico', include_in_schema=False)
async def favicon():
    import os
    from fastapi.responses import FileResponse, Response
    if os.path.exists("static/favicon.ico"):
        return FileResponse("static/favicon.ico")
    return Response(status_code=204)

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
# ── Frontend UI (FE-01+) — ordem importa: UI antes do mount de static ─────────
app.include_router(ui_dashboard_router)
app.include_router(ui_operations_router)
app.include_router(ui_commercial_router)
app.include_router(api_fragments_router)
app.include_router(api_intelligence_router)
app.include_router(api_bom_router)
app.include_router(api_production_ui_router)
app.include_router(api_inventory_ui_router)
app.include_router(api_purchasing_ui_router)
app.include_router(api_b2b_ui_router)
app.include_router(api_labels_ui_router)
app.include_router(api_dre_ui_router)
app.include_router(api_settings_ui_router)
app.include_router(api_cadastro_ui_router)
app.include_router(api_users_ui_router)
app.include_router(api_receiving_ui_router)
app.include_router(api_finances_ui_router)
app.mount("/static", StaticFiles(directory="static"), name="static")

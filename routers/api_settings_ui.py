"""FE-08 — API de Configurações para UI."""
import json
import os

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/settings", tags=["API — Configurações UI FE-08"])
templates = Jinja2Templates(directory="templates")

# Chave das configurações salvas no banco (SystemAlert como store) ou env vars
_SETTINGS_KEYS = [
    "margem_minima_pct",
    "alerta_estoque_dias",
    "mega_api_token",
    "mega_api_instance",
    "gmail_user",
    "empresa_nome",
    "empresa_cnpj",
    "empresa_endereco",
    "impressora_host",
    "impressora_porta",
    "notif_whatsapp",
    "notif_email",
    "notif_alertas_criticos",
]


@router.post("/save", response_class=HTMLResponse)
async def save_settings(request: Request, db: Session = Depends(get_db)):
    """Salva configurações via form e retorna toast de confirmação."""
    form = await request.form()

    saved = []
    errors = []

    # Persiste em variáveis de ambiente de processo (runtime) como fallback simples
    # Em produção, usar tabela Settings ou arquivo .env persistente
    for key in _SETTINGS_KEYS:
        val = form.get(key, "")
        if val:
            try:
                os.environ[key.upper()] = str(val)
                saved.append(key)
            except Exception as e:
                errors.append(f"{key}: {e}")

    if errors:
        msg = f"Parcialmente salvo. Erros: {'; '.join(errors)}"
        msg_type = "warning"
        content_cls = "bg-amber-50 border-amber-200 text-amber-800"
        icon = "ph-warning"
    else:
        msg = f"{len(saved)} configuração(ões) salva(s) com sucesso!"
        msg_type = "success"
        content_cls = "bg-green-50 border-green-200 text-green-800"
        icon = "ph-check-circle"

    trigger = json.dumps({"showToast": {"message": msg, "type": msg_type}})
    content = (
        f'<div class="flex items-center gap-3 p-3 rounded-lg border {content_cls} text-sm">'
        f'<i class="ph-fill {icon} text-lg flex-shrink-0"></i>'
        f'<span>{msg}</span></div>'
    )
    response = HTMLResponse(content=content)
    response.headers["HX-Trigger"] = trigger
    return response


@router.get("/current", response_class=HTMLResponse)
def current_settings(request: Request):
    """Retorna os valores actuais das configurações para preencher o form."""
    current = {k: os.environ.get(k.upper(), "") for k in _SETTINGS_KEYS}
    return templates.TemplateResponse(
        "settings/index.html",
        {"request": request, "settings": current},
    )

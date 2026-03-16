"""Gestão de Utilizadores — listagem e criação via UI (HTMX)."""
import json
import uuid as _uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db
from services.auth_service import AdminOnly

router = APIRouter(prefix="/api/users", tags=["API — Utilizadores UI"])
templates = Jinja2Templates(directory="templates")

_PERFIS = ["operador", "chef", "admin"]


def _toast(msg: str, tipo: str = "success") -> str:
    return json.dumps({"showToast": {"message": msg, "type": tipo}})


def _err(msg: str) -> HTMLResponse:
    html = (
        f'<div class="flex items-center gap-2 p-3 rounded-lg bg-red-50 border border-red-200 text-sm text-red-800">'
        f'<i class="ph-fill ph-x-circle text-lg"></i><span>{msg}</span></div>'
    )
    r = HTMLResponse(content=html)
    r.headers["HX-Trigger"] = _toast(msg, "error")
    return r


@router.get("", response_class=HTMLResponse)
def list_users(request: Request, db: Session = Depends(get_db), _=AdminOnly):
    from models import User
    users = db.query(User).order_by(User.nome).all()
    return templates.TemplateResponse(
        "settings/fragments/users_rows.html",
        {"request": request, "users": users},
    )


@router.post("", response_class=HTMLResponse)
def create_user(
    request: Request,
    nome: str = Form(...),
    email: str = Form(...),
    perfil: str = Form("operador"),
    pin_code: str = Form(""),
    db: Session = Depends(get_db),
    _=AdminOnly,
):
    from models import User

    if perfil not in _PERFIS:
        return _err(f"Perfil inválido. Use: {', '.join(_PERFIS)}")

    pin = pin_code.strip()
    if pin and (not pin.isdigit() or len(pin) != 4):
        return _err("PIN deve ter exatamente 4 dígitos numéricos.")

    try:
        u = User(
            id=_uuid.uuid4(),
            nome=nome.strip(),
            email=email.strip().lower(),
            perfil=perfil,
            pin_code=pin or None,
            ativo=True,
        )
        db.add(u)
        db.commit()
        db.refresh(u)
    except Exception as e:
        db.rollback()
        msg = "E-mail já cadastrado." if "UNIQUE" in str(e).upper() else f"Erro: {e}"
        return _err(msg)

    perfil_badge = {
        "admin": "bg-red-100 text-red-700",
        "chef": "bg-orange-100 text-orange-700",
        "operador": "bg-blue-100 text-blue-700",
    }.get(u.perfil, "bg-gray-100 text-gray-700")

    row = (
        f'<tr id="usr-{u.id}" class="odd:bg-white even:bg-slate-50 text-sm">'
        f'<td class="px-4 py-2 font-medium text-gray-900">{u.nome}</td>'
        f'<td class="px-4 py-2 text-gray-500">{u.email}</td>'
        f'<td class="px-4 py-2">'
        f'  <span class="px-2 py-0.5 rounded-full text-xs font-semibold {perfil_badge}">{u.perfil}</span>'
        f'</td>'
        f'<td class="px-4 py-2 text-center text-gray-400">'
        f'  {"••••" if u.pin_code else "—"}'
        f'</td>'
        f'<td class="px-4 py-2 text-center">'
        f'  <span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium '
        f'bg-green-100 text-green-700"><i class="ph-fill ph-check-circle"></i> Ativo</span>'
        f'</td>'
        f'</tr>'
    )
    r = HTMLResponse(content=row)
    r.headers["HX-Trigger"] = _toast(f'Utilizador "{u.nome}" criado!')
    return r


@router.patch("/{user_id}/toggle", response_class=HTMLResponse)
def toggle_user(user_id: str, db: Session = Depends(get_db), _=AdminOnly):
    from models import User
    try:
        u = db.query(User).filter(User.id == _uuid.UUID(user_id)).first()
        if not u:
            return _err("Utilizador não encontrado.")
        u.ativo = not u.ativo
        db.commit()
    except Exception as e:
        db.rollback()
        return _err(f"Erro: {e}")

    estado = "ativado" if u.ativo else "desativado"
    r = HTMLResponse(
        f'<span class="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs font-medium '
        f'{"bg-green-100 text-green-700" if u.ativo else "bg-gray-100 text-gray-500"}">'
        f'<i class="ph-fill {"ph-check-circle" if u.ativo else "ph-x-circle"}"></i> '
        f'{"Ativo" if u.ativo else "Inativo"}</span>'
    )
    r.headers["HX-Trigger"] = _toast(f'"{u.nome}" {estado}.', "success" if u.ativo else "warning")
    return r

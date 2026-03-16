"""Autenticação — Login e Logout."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(tags=["Auth"])
templates = Jinja2Templates(directory="templates")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    # Se já tem sessão, vai directo para o dashboard
    if request.session.get("user_id"):
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse("auth/login.html", {"request": request, "error": None})


@router.post("/login", response_class=HTMLResponse)
def login_submit(
    request: Request,
    email: str = Form(...),
    pin_code: str = Form(...),
    db: Session = Depends(get_db),
):
    from models import User

    email = email.strip().lower()
    pin = pin_code.strip()

    user = db.query(User).filter(User.email == email, User.ativo == True).first()  # noqa: E712

    if not user or user.pin_code != pin:
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "E-mail ou PIN incorretos."},
            status_code=401,
        )

    request.session["user_id"] = str(user.id)
    request.session["user_nome"] = user.nome
    request.session["user_perfil"] = user.perfil

    return RedirectResponse("/dashboard", status_code=302)


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=302)

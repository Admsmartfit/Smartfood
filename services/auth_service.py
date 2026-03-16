"""RBAC — Dependências de autenticação e controlo de acesso por perfil."""
import uuid

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from database import get_db


def get_current_user(request: Request, db: Session = Depends(get_db)):
    """Lê o user_id da sessão e devolve o modelo User. 401 se não autenticado."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Não autenticado")
    from models import User
    try:
        uid = uuid.UUID(user_id)
    except ValueError:
        raise HTTPException(status_code=401, detail="Sessão inválida")
    user = db.query(User).filter(User.id == uid, User.ativo == True).first()  # noqa: E712
    if not user:
        raise HTTPException(status_code=401, detail="Utilizador não encontrado ou inativo")
    return user


def require_role(allowed_roles: list[str]):
    """
    Fábrica de dependências. Uso nos routers:
        @router.get("/settings")
        def settings(request, _=Depends(require_role(["admin"]))):
            ...
    Lança 403 se o perfil do utilizador não estiver na lista.
    """
    def checker(user=Depends(get_current_user)):
        if user.perfil not in allowed_roles:
            raise HTTPException(
                status_code=403,
                detail=f"Acesso negado. Perfil necessário: {', '.join(allowed_roles)}",
            )
        return user
    return checker


# Atalhos prontos a usar
AdminOnly   = Depends(require_role(["admin"]))
AdminOrChef = Depends(require_role(["admin", "chef"]))
AnyRole     = Depends(require_role(["admin", "chef", "operador"]))

"""
E-14 — Rotas de Etiquetas Parametrizadas e QR Dinâmico

Endpoints:
  POST   /labels/templates              — cria template de etiqueta
  GET    /labels/templates              — lista templates
  POST   /labels/preview               — preview ZPL/TSPL sem imprimir
  POST   /production-orders/{id}/print-labels — imprime lote via TCP (US-013)
  GET    /qr/{lot_code}                — redirecionamento dinâmico (US-014)
  POST   /qr-rules                     — configura regra de redirecionamento
  GET    /qr-rules                     — lista regras ativas
"""
from typing import Any, Dict, Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services.label_service import (
    create_label_template,
    list_label_templates,
    preview_label,
    print_batch_labels,
    resolve_qr_redirect,
    create_qr_rule,
    list_qr_rules,
    DEFAULT_PRINTER_HOST,
    DEFAULT_PRINTER_PORT,
)

router = APIRouter(tags=["Etiquetas e QR Dinâmico - E-14"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class LabelTemplateCreate(BaseModel):
    nome: str
    product_id: Optional[uuid.UUID] = None
    printer_type: str = "ZPL"   # ZPL | TSPL
    width_mm: int = 100
    height_mm: int = 60
    fields_config: Optional[Dict[str, Any]] = None


class LabelPreviewRequest(BaseModel):
    fields: Dict[str, Any]
    template: Dict[str, Any]


class PrintLabelsRequest(BaseModel):
    printer_host: str = DEFAULT_PRINTER_HOST
    printer_port: int = DEFAULT_PRINTER_PORT


class QRRuleCreate(BaseModel):
    nome: str
    product_id: Optional[uuid.UUID] = None
    regra: str  # expiracao_proxima | tutorial | rastreabilidade | pesquisa | substituto
    dias_vencimento: Optional[int] = None
    dias_apos_entrega: Optional[int] = None
    url_destino: str
    desconto_pct: Optional[float] = None
    prioridade: int = 0


# ─── Templates de Etiqueta ───────────────────────────────────────────────────

@router.post("/labels/templates", status_code=201)
def create_template(payload: LabelTemplateCreate, db: Session = Depends(get_db)):
    """
    Cria template de etiqueta parametrizado.

    `printer_type`: `ZPL` para Zebra (GK420t, ZD420, ZD230) ou `TSPL` para Elgin L42 / Argox OS-214.

    `fields_config` (opcional): posições customizáveis de cada campo:
    ```json
    {
      "nome":        {"x": 20, "y": 20, "font_size": 35},
      "lote":        {"x": 20, "y": 65},
      "qr":          {"x": 340, "y": 20, "size": 5},
      "ean13":       {"x": 20, "y": 210}
    }
    ```
    Presets de tamanho: 100×60mm, 100×40mm, 75×50mm, 50×25mm.
    """
    printer_type = payload.printer_type.upper()
    if printer_type not in ("ZPL", "TSPL"):
        raise HTTPException(status_code=422, detail="printer_type deve ser ZPL ou TSPL")
    return create_label_template(db, {
        "nome": payload.nome,
        "product_id": payload.product_id,
        "printer_type": printer_type,
        "width_mm": payload.width_mm,
        "height_mm": payload.height_mm,
        "fields_config": payload.fields_config,
    })


@router.get("/labels/templates")
def get_templates(db: Session = Depends(get_db)):
    """Lista todos os templates de etiqueta ativos."""
    return list_label_templates(db)


@router.post("/labels/preview")
def label_preview(payload: LabelPreviewRequest):
    """
    Gera preview da etiqueta (ZPL ou TSPL) sem enviar à impressora.
    Permite validar o layout antes da impressão em lote.

    Retorna a string de comandos gerada + tamanho em bytes.
    """
    return preview_label(payload.fields, payload.template)


# ─── Impressão em Lote (US-013) ──────────────────────────────────────────────

@router.post("/production-orders/{batch_id}/print-labels")
def print_labels(
    batch_id: uuid.UUID,
    payload: PrintLabelsRequest,
    db: Session = Depends(get_db),
):
    """
    US-013: Imprime todas as etiquetas do lote ao concluir OP.

    - OP deve estar com status CONCLUIDA
    - Busca template do produto (ou genérico)
    - Gera ZPL/TSPL com: nome, lote, fab, val, peso, QR URL, EAN-13
    - Envia para a Zebra/Elgin via TCP/IP (porta 9100 padrão)
    - Target: 200 etiquetas em <10s

    `printer_host`: IP da impressora na rede local (ex: 192.168.1.100)
    `printer_port`: Porta TCP (padrão: 9100)
    """
    try:
        return print_batch_labels(
            db=db,
            batch_id=batch_id,
            printer_host=payload.printer_host,
            printer_port=payload.printer_port,
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ─── QR Dinâmico — Redirecionamento (US-014) ─────────────────────────────────

@router.get("/qr/{lot_code}")
def qr_redirect(lot_code: str, request: Request, db: Session = Depends(get_db)):
    """
    US-014: Redirecionamento dinâmico do QR Code por regras configuráveis.

    O QR Code na etiqueta aponta sempre para `/qr/{lot_code}`.
    Este endpoint avalia as regras em ordem de prioridade e redireciona:

    | Regra              | Condição                        | Destino                      |
    |--------------------|----------------------------------|------------------------------|
    | expiracao_proxima  | validade ≤ D+7                   | Oferta 10% OFF               |
    | pesquisa           | 2º scan + N dias pós-entrega     | Formulário de satisfação      |
    | rastreabilidade    | QR lido por consumidor final     | Página pública de origem      |
    | substituto         | Produto esgotado/descontinuado   | Página de produto substituto  |
    | tutorial (padrão)  | Nenhuma regra acima se aplica    | Vídeo de preparo <60s         |

    Registra cada leitura em `qr_scans` para analytics.
    """
    ip = request.client.host if request.client else None
    ua = request.headers.get("user-agent")
    url = resolve_qr_redirect(db, lot_code, ip=ip, user_agent=ua)
    return RedirectResponse(url=url, status_code=302)


@router.get("/qr/{lot_code}/preview")
def qr_redirect_preview(lot_code: str, db: Session = Depends(get_db)):
    """
    Retorna para qual URL o QR Code redirecionaria (sem registrar scan).
    Útil para debugging de regras.
    """
    from services.label_service import resolve_qr_redirect as _resolve
    from models import QRScan
    # Resolve sem commit real — usa snapshot
    url = _resolve(db, lot_code)
    # Desfaz o scan registrado (preview não deve ser contado)
    scan = db.query(QRScan).filter(QRScan.lot_code == lot_code).order_by(QRScan.created_at.desc()).first()
    if scan:
        db.delete(scan)
        db.commit()
    return {"lot_code": lot_code, "url_destino": url}


# ─── Regras de QR ────────────────────────────────────────────────────────────

@router.post("/qr-rules", status_code=201)
def create_rule(payload: QRRuleCreate, db: Session = Depends(get_db)):
    """
    Cria regra de redirecionamento de QR Code.

    Regras disponíveis:
    - `expiracao_proxima`: redireciona para promoção quando validade ≤ `dias_vencimento` dias
    - `pesquisa`: redireciona para survey de satisfação N dias após entrega
    - `rastreabilidade`: página pública de origem e ingredientes
    - `substituto`: redireciona para produto substituto quando estoque zerado
    - `tutorial`: URL de vídeo de preparo (use como regra padrão, prioridade 0)

    Regras são avaliadas em ordem decrescente de `prioridade`.
    """
    valid_regras = {"expiracao_proxima", "tutorial", "rastreabilidade", "pesquisa", "substituto"}
    if payload.regra not in valid_regras:
        raise HTTPException(status_code=422, detail=f"regra inválida. Válidas: {sorted(valid_regras)}")
    return create_qr_rule(db, payload.model_dump())


@router.get("/qr-rules")
def get_qr_rules(db: Session = Depends(get_db)):
    """Lista todas as regras de QR ativas, ordenadas por prioridade (maior primeiro)."""
    return list_qr_rules(db)

"""
E-19 — Rotas PWA Mobile para Operadores

Endpoints otimizados para o app móvel (baixa latência, payloads enxutos):
  GET  /mobile                              — serve o shell PWA (mobile.html)
  GET  /mobile/dashboard                    — KPIs + alertas para o operador
  GET  /mobile/production-orders/active     — OPs ativas do dia
  GET  /mobile/production-orders/{id}       — detalhe de uma OP
  POST /mobile/production-orders/{id}/quick-start — inicia OP (simplificado)
  POST /mobile/production-orders/{id}/complete    — conclui OP com qty_real
  GET  /mobile/barcode/{code}               — lookup de produto/lote por código
  GET  /mobile/ingredients/{id}/stock       — consulta estoque de insumo
  GET  /mobile/offline-bundle               — bundle completo para SQLite local
"""
import uuid
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Header
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/mobile", tags=["PWA Mobile Operadores - E-19"])

STATIC_DIR = Path(__file__).parent.parent / "static"


# ─── Schemas ────────────────────────────────────────────────────────────────

class QuickStartRequest(BaseModel):
    operador_id: str


class CompleteOpRequest(BaseModel):
    quantidade_real: float
    custo_energia_kwh: Optional[float] = None
    labor_cost_per_min: Optional[float] = None


# ─── Shell PWA ───────────────────────────────────────────────────────────────

@router.get("", response_class=FileResponse, include_in_schema=False)
@router.get("/", response_class=FileResponse, include_in_schema=False)
def pwa_shell():
    """Serve o shell HTML do PWA mobile."""
    html_file = STATIC_DIR / "mobile.html"
    if not html_file.exists():
        return HTMLResponse("<h1>PWA shell não encontrado</h1>", status_code=404)
    return FileResponse(str(html_file), media_type="text/html")


# ─── Dashboard ───────────────────────────────────────────────────────────────

@router.get("/dashboard")
def mobile_dashboard(db: Session = Depends(get_db)):
    """
    US-021 — KPIs e alertas para o painel do operador mobile.

    Retorna payload enxuto com:
    - ops_ativas: total de OPs APROVADA ou EM_PRODUCAO
    - total_alertas: alertas não reconhecidos
    - entregas_hoje: pedidos B2B com entrega no dia
    - compras_urgentes: insumos abaixo do mínimo
    - alertas_recentes: lista resumida dos últimos 5 alertas
    """
    from datetime import date, datetime, timedelta, timezone
    from models import ProductionBatch, SystemAlert, Order, Ingredient

    hoje = date.today()
    inicio_dia = datetime.combine(hoje, datetime.min.time()).replace(tzinfo=timezone.utc)
    fim_dia = inicio_dia + timedelta(days=1)

    # KPIs
    ops_ativas = (
        db.query(ProductionBatch)
        .filter(ProductionBatch.status.in_(["APROVADA", "EM_PRODUCAO"]))
        .count()
    )

    alertas = db.query(SystemAlert).filter(SystemAlert.status == "ativo").all()

    entregas_hoje = (
        db.query(Order)
        .filter(
            Order.data_entrega_prevista >= inicio_dia,
            Order.data_entrega_prevista < fim_dia,
            Order.status.in_(["CONFIRMADO", "EM_PRODUCAO", "PRONTO"]),
        )
        .count()
    )

    # Compras urgentes (estoque ≤ 0 ou abaixo do mínimo)
    ings = db.query(Ingredient).filter(Ingredient.ativo == True).all()
    compras_urgentes = 0
    for ing in ings:
        estoque = ing.estoque_atual or 0.0
        estoque_min = getattr(ing, "estoque_minimo", None) or (
            (ing.consumo_medio_diario or 0) * ((ing.lead_time_dias or 3) + 2)
            if hasattr(ing, "consumo_medio_diario") else 0.0
        )
        if estoque <= 0 or (estoque_min > 0 and estoque < estoque_min):
            compras_urgentes += 1

    # Alertas recentes formatados para mobile
    alertas_recentes = []
    for a in sorted(alertas, key=lambda x: x.created_at or datetime.min, reverse=True)[:5]:
        icone = {"MARGEM": "💰", "ESTOQUE": "📦", "DEMANDA": "📈", "VENCIMENTO": "⏰"}.get(
            (a.tipo or "").upper(), "⚠️"
        )
        alertas_recentes.append({
            "id": str(a.id),
            "tipo": a.tipo,
            "titulo": a.mensagem[:60] if a.mensagem else a.tipo,
            "detalhe": a.mensagem[60:] if a.mensagem and len(a.mensagem) > 60 else "",
            "icone": icone,
            "severidade": a.severidade,
            "criado_em": a.created_at.isoformat() if a.created_at else None,
        })

    return {
        "ops_ativas": ops_ativas,
        "total_alertas": len(alertas),
        "entregas_hoje": entregas_hoje,
        "compras_urgentes": compras_urgentes,
        "alertas_recentes": alertas_recentes,
    }


# ─── Ordens de Produção ───────────────────────────────────────────────────────

@router.get("/production-orders/active")
def active_production_orders(db: Session = Depends(get_db)):
    """
    US-021 — Lista OPs ativas (APROVADA + EM_PRODUCAO) com payload mobile enxuto.
    """
    from models import ProductionBatch, Product

    ops = (
        db.query(ProductionBatch)
        .filter(ProductionBatch.status.in_(["APROVADA", "EM_PRODUCAO", "PAUSADA"]))
        .order_by(ProductionBatch.data_inicio)
        .all()
    )

    result = []
    for op in ops:
        p = db.query(Product).filter(Product.id == op.product_id).first()
        result.append({
            "id": str(op.id),
            "produto": p.nome if p else "?",
            "produto_id": str(op.product_id),
            "quantidade_planejada": op.quantidade_planejada,
            "status": op.status,
            "operador_id": op.operador_id,
            "data_inicio": op.data_inicio.isoformat() if op.data_inicio else None,
        })
    return result


@router.get("/production-orders/{batch_id}")
def get_production_order_detail(batch_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    Detalhe completo de uma OP para a tela de execução mobile.
    Inclui ingredientes necessários para o checklist do operador.
    """
    from models import ProductionBatch, Product, BOMItem, Ingredient

    op = db.query(ProductionBatch).filter(ProductionBatch.id == batch_id).first()
    if not op:
        raise HTTPException(status_code=404, detail="OP não encontrada")

    p = db.query(Product).filter(Product.id == op.product_id).first()

    # Ingredientes do BOM para checklist
    bom_items = db.query(BOMItem).filter(BOMItem.product_id == op.product_id).all()
    ingredientes = []
    for item in bom_items:
        ing = db.query(Ingredient).filter(Ingredient.id == item.ingredient_id).first()
        qty_necessaria = (item.quantidade or 0) * (op.quantidade_planejada or 0)
        ingredientes.append({
            "ingrediente_id": str(item.ingredient_id),
            "nome": ing.nome if ing else "?",
            "unidade": ing.unidade if ing else "",
            "quantidade_necessaria": round(qty_necessaria, 3),
            "estoque_atual": ing.estoque_atual if ing else None,
            "suficiente": (ing.estoque_atual or 0) >= qty_necessaria if ing else None,
        })

    return {
        "id": str(op.id),
        "produto": p.nome if p else "?",
        "produto_id": str(op.product_id),
        "quantidade_planejada": op.quantidade_planejada,
        "quantidade_real": op.quantidade_real,
        "status": op.status,
        "operador_id": op.operador_id,
        "data_inicio": op.data_inicio.isoformat() if op.data_inicio else None,
        "data_fim": op.data_fim.isoformat() if op.data_fim else None,
        "ingredientes": ingredientes,
        "custo_total": op.custo_total,
        "modo_preparo": (p.modo_preparo_interno if p and p.modo_preparo_interno else "Sem instruções cadastradas."),
    }


@router.post("/production-orders/{batch_id}/quick-start")
def quick_start_production(
    batch_id: uuid.UUID,
    body: QuickStartRequest,
    db: Session = Depends(get_db),
):
    """
    US-021 — Inicia uma OP com fluxo simplificado mobile (1 toque).
    Equivale ao endpoint padrão mas retorna payload enxuto.
    """
    from services.production_service import start_production

    try:
        start_production(db, batch_id, body.operador_id)
        return {
            "ok": True,
            "batch_id": str(batch_id),
            "status": "EM_PRODUCAO",
            "operador_id": body.operador_id,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/production-orders/{batch_id}/complete")
def complete_production_mobile(
    batch_id: uuid.UUID,
    body: CompleteOpRequest,
    db: Session = Depends(get_db),
):
    """
    US-021 — Conclui uma OP com quantidade real (fluxo mobile).
    """
    from services.production_service import complete_production_order

    try:
        result = complete_production_order(
            db,
            batch_id=batch_id,
            quantidade_real=body.quantidade_real,
            custo_energia_kwh=body.custo_energia_kwh,
            labor_cost_per_min=body.labor_cost_per_min,
        )
        return {
            "ok": True,
            "batch_id": str(batch_id),
            "status": "CONCLUIDA",
            "quantidade_real": body.quantidade_real,
            "custo_total": result.get("custo_total"),
            "rendimento_pct": result.get("rendimento_pct"),
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─── Barcode Lookup ───────────────────────────────────────────────────────────

@router.get("/barcode/{code}")
def barcode_lookup(code: str, db: Session = Depends(get_db)):
    """
    US-021 — Lookup de produto ou lote por código EAN/QR/Lote.

    Estratégia de busca:
    1. Código de lote (prefixo LOT-) → IngredientLot + Ingredient
    2. EAN-13/8 numérico → Product.ean_code
    3. Nome parcial → Product (fallback)
    """
    from models import Product, Ingredient, IngredientLot

    # 1. Lote
    if code.upper().startswith("LOT-"):
        lot = db.query(IngredientLot).filter(IngredientLot.lot_code == code.upper()).first()
        if lot:
            ing = db.query(Ingredient).filter(Ingredient.id == lot.ingredient_id).first()
            return {
                "tipo": "lote",
                "lote": lot.lot_code,
                "nome": ing.nome if ing else "?",
                "ingrediente_id": str(lot.ingredient_id),
                "quantidade": lot.quantidade,
                "data_validade": lot.data_validade.isoformat() if lot.data_validade else None,
                "estoque_atual": ing.estoque_atual if ing else None,
            }

    # 2. SKU ou numérico → produto
    if code.isdigit() or len(code) <= 20:
        prod = db.query(Product).filter(
            (Product.sku == code) | (Product.nome.ilike(f"%{code}%"))
        ).first()
        if prod:
            return {
                "tipo": "produto",
                "nome": prod.nome,
                "produto_id": str(prod.id),
                "sku": prod.sku,
                "preco_venda": prod.preco_venda,
                "estoque_atual": prod.estoque_atual,
                "unidade": prod.unidade,
            }

    # 3. Ingrediente por nome
    ing = db.query(Ingredient).filter(
        Ingredient.nome.ilike(f"%{code}%")
    ).first()
    if ing:
        return {
            "tipo": "ingrediente",
            "nome": ing.nome,
            "ingrediente_id": str(ing.id),
            "unidade": ing.unidade,
            "estoque_atual": ing.estoque_atual,
            "estoque_minimo": getattr(ing, "estoque_minimo", None),
        }

    raise HTTPException(status_code=404, detail=f"Código não encontrado: {code}")


# ─── Estoque de Insumo ───────────────────────────────────────────────────────

@router.get("/ingredients/{ingredient_id}/stock")
def ingredient_stock(ingredient_id: uuid.UUID, db: Session = Depends(get_db)):
    """Consulta estoque atual de um insumo (para validação pré-produção)."""
    from models import Ingredient

    ing = db.query(Ingredient).filter(Ingredient.id == ingredient_id).first()
    if not ing:
        raise HTTPException(status_code=404, detail="Insumo não encontrado")

    estoque_min = getattr(ing, "estoque_minimo", None) or 0.0
    return {
        "ingrediente_id": str(ing.id),
        "nome": ing.nome,
        "unidade": ing.unidade,
        "estoque_atual": ing.estoque_atual or 0.0,
        "estoque_minimo": estoque_min,
        "status": (
            "ZERO" if (ing.estoque_atual or 0) <= 0
            else "CRITICO" if estoque_min > 0 and (ing.estoque_atual or 0) < estoque_min
            else "OK"
        ),
    }


# ─── Offline Bundle ───────────────────────────────────────────────────────────

@router.get("/offline-bundle")
def offline_bundle(db: Session = Depends(get_db)):
    """
    US-019 — Pacote de dados para seeding do SQLite local do device.

    Retorna payload com todos os dados necessários para operar offline:
    - produtos: catálogo com preços
    - ingredientes: estoque e mínimos
    - ops_ativas: OPs APROVADA e EM_PRODUCAO
    - bom_items: ficha técnica por produto
    - clientes: cadastro para pedidos

    O device usa este bundle para popular o SQLite local.
    Ao reconectar, os eventos são enviados via POST /sync.
    """
    from datetime import datetime, timezone
    from models import Product, Ingredient, ProductionBatch, BOMItem, Customer

    # Produtos ativos
    produtos = [
        {
            "id": str(p.id),
            "nome": p.nome,
            "ean_code": p.ean_code,
            "unidade": p.unidade,
            "preco_venda": p.preco_venda,
            "estoque_atual": p.estoque_atual,
        }
        for p in db.query(Product).filter(Product.ativo == True).all()
    ]

    # Ingredientes ativos
    ingredientes = [
        {
            "id": str(i.id),
            "nome": i.nome,
            "unidade": i.unidade,
            "estoque_atual": i.estoque_atual or 0.0,
            "estoque_minimo": getattr(i, "estoque_minimo", None) or 0.0,
            "lead_time_dias": i.lead_time_dias or 0,
        }
        for i in db.query(Ingredient).filter(Ingredient.ativo == True).all()
    ]

    # OPs ativas
    ops = db.query(ProductionBatch).filter(
        ProductionBatch.status.in_(["APROVADA", "EM_PRODUCAO"])
    ).all()
    ops_data = []
    for op in ops:
        p = db.query(Product).filter(Product.id == op.product_id).first()
        ops_data.append({
            "id": str(op.id),
            "produto_id": str(op.product_id),
            "produto": p.nome if p else "?",
            "quantidade_planejada": op.quantidade_planejada,
            "status": op.status,
        })

    # BOM items
    bom_items = [
        {
            "product_id": str(b.product_id),
            "ingredient_id": str(b.ingredient_id),
            "quantidade": b.quantidade,
            "unidade": b.unidade,
        }
        for b in db.query(BOMItem).all()
    ]

    # Clientes (nome + whatsapp para pedidos)
    clientes = [
        {
            "id": str(c.id),
            "nome": c.nome,
            "whatsapp": c.whatsapp,
            "grupo": c.grupo,
        }
        for c in db.query(Customer).filter(Customer.ativo == True).all()
    ]

    return {
        "gerado_em": datetime.now(timezone.utc).isoformat(),
        "versao": "1",
        "produtos": produtos,
        "ingredientes": ingredientes,
        "ops_ativas": ops_data,
        "bom_items": bom_items,
        "clientes": clientes,
    }

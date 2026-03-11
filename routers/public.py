"""
E-15 — Endpoints Públicos: Destinos do QR Code Dinâmico

Estes endpoints são páginas públicas (sem autenticação) para onde o QR redireciona:

  GET /public/lot/{lot_code}              — rastreabilidade pública do lote
  GET /public/promotion/{lot_code}        — oferta de 10% OFF por vencimento próximo
  GET /public/survey/{lot_code}           — pesquisa de satisfação (2 perguntas)
  POST /public/survey/{lot_code}          — submete respostas da pesquisa
  GET /public/substitute/{product_id}    — sugestão de produto substituto
  GET /qr/analytics/{lot_code}           — analytics de scans (uso interno)

Regras QR (recapitulando E-14/E-15):
  expiracao_proxima  → /public/promotion/{lot_code}
  rastreabilidade    → /public/lot/{lot_code}
  pesquisa           → /public/survey/{lot_code}
  substituto         → /public/substitute/{product_id}
  tutorial (default) → URL externa do vídeo
"""
from datetime import datetime, timedelta, timezone
from typing import Optional
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(tags=["QR Público - E-15"])


# ─── Schemas ────────────────────────────────────────────────────────────────

class SurveySubmit(BaseModel):
    nota_sabor: int
    nota_entrega: int
    comentario: str = ""

    @field_validator("nota_sabor", "nota_entrega")
    @classmethod
    def nota_valida(cls, v: int) -> int:
        if not (0 <= v <= 10):
            raise ValueError("Nota deve ser entre 0 e 10")
        return v


# ─── Rastreabilidade Pública (E-15: Rastreio de Lote) ───────────────────────

@router.get("/public/lot/{lot_code}")
def public_lot_traceability(lot_code: str, db: Session = Depends(get_db)):
    """
    E-15 — Página pública de rastreabilidade do lote.
    Exibe origem, data de produção, ingredientes e ausência de conservantes.
    Acessível pelo consumidor final via QR Code na embalagem.

    Conteúdo:
    - Produto e lote
    - Data de fabricação e validade
    - Ingredientes (BOM do produto)
    - Temperatura de conservação
    - Informações nutricionais e alérgenos
    - Certificação: "sem conservantes artificiais"
    """
    from models import IngredientLot, ProductionBatch, Product, BOMItem, Ingredient

    lot = db.query(IngredientLot).filter(IngredientLot.codigo_lote == lot_code).first()

    # Tenta encontrar o batch pelo código de lote
    batch = None
    product = None
    bom_ingredientes = []

    if lot and lot.ingredient_id:
        # Lote de ingrediente → busca batch que o consumiu
        from models import LotConsumption
        consumo = (
            db.query(LotConsumption)
            .filter(LotConsumption.ingredient_lot_id == lot.id)
            .first()
        )
        if consumo:
            batch = db.query(ProductionBatch).filter(
                ProductionBatch.id == consumo.production_batch_id
            ).first()
    else:
        # Tenta parsear como batch diretamente (lot_code gerado pelo label_service)
        # Formato: LOT-{batch_id[:8]}-{YYYYMMDD}
        parts = lot_code.split("-")
        if len(parts) >= 2:
            # Busca batch por prefixo do id
            batches = db.query(ProductionBatch).all()
            for b in batches:
                if str(b.id).replace("-", "")[:8].upper() == parts[1].upper():
                    batch = b
                    break

    if batch:
        product = db.query(Product).filter(Product.id == batch.product_id).first()
        if product:
            bom_items = db.query(BOMItem).filter(BOMItem.product_id == product.id).all()
            for item in bom_items:
                if item.ingredient_id:
                    ing = db.query(Ingredient).filter(Ingredient.id == item.ingredient_id).first()
                    if ing:
                        bom_ingredientes.append({
                            "ingrediente": ing.nome,
                            "quantidade": item.quantidade,
                            "unidade": item.unidade or ing.unidade,
                        })

    return {
        "lot_code": lot_code,
        "produto": product.nome if product else "Produto SmartFood",
        "sku": product.sku if product else None,
        "data_fabricacao": (
            batch.data_inicio.date().isoformat()
            if batch and batch.data_inicio
            else None
        ),
        "data_validade": (
            (batch.data_inicio + timedelta(days=90)).date().isoformat()
            if batch and batch.data_inicio
            else None
        ),
        "temperatura_conservacao": "-18°C (ultracongelado)",
        "info_nutricional": product.info_nutricional if product else None,
        "alergenicos": product.alergenicos if product else None,
        "ingredientes_bom": bom_ingredientes,
        "certificacoes": [
            "Sem conservantes artificiais",
            "Produzido sob APPCC",
            "Lote rastreável do campo ao balcão",
        ],
        "descricao_marketing": product.descricao_marketing if product else None,
    }


# ─── Promoção por Vencimento (E-15: expiracao_proxima) ───────────────────────

@router.get("/public/promotion/{lot_code}")
def public_promotion(lot_code: str, db: Session = Depends(get_db)):
    """
    E-15 — Página de promoção por vencimento próximo.
    Ativada quando lote tem validade ≤ D+7.
    Exibe oferta de 10% de desconto + botão de pedido.
    """
    from models import IngredientLot, QRRule

    lot = db.query(IngredientLot).filter(IngredientLot.codigo_lote == lot_code).first()

    # Desconto configurável via regra QR, padrão 10%
    desconto_pct = 10.0
    rule = (
        db.query(QRRule)
        .filter(QRRule.regra == "expiracao_proxima", QRRule.ativo == True)
        .order_by(QRRule.prioridade.desc())
        .first()
    )
    if rule and rule.desconto_pct:
        desconto_pct = rule.desconto_pct

    data_val = None
    dias_restantes = None
    produto_nome = "Produto SmartFood"

    if lot:
        if lot.data_validade:
            now = datetime.now(timezone.utc)
            val = lot.data_validade
            if val.tzinfo is None:
                val = val.replace(tzinfo=timezone.utc)
            data_val = val.date().isoformat()
            dias_restantes = (val - now).days

    return {
        "lot_code": lot_code,
        "produto": produto_nome,
        "data_validade": data_val,
        "dias_para_vencimento": dias_restantes,
        "oferta": {
            "desconto_pct": desconto_pct,
            "descricao": f"{int(desconto_pct)}% de desconto hoje!",
            "validade_oferta": "Válido apenas hoje",
            "cta_texto": "Peça agora com desconto",
            "cta_url": "/orders?promocao=vencimento&lote=" + lot_code,
        },
        "mensagem": (
            f"Este produto vence em {dias_restantes} dia(s). "
            f"Aproveite {int(desconto_pct)}% de desconto e garanta seu estoque agora!"
        ) if dias_restantes is not None else (
            f"Oferta especial! {int(desconto_pct)}% de desconto neste produto."
        ),
    }


# ─── Pesquisa de Satisfação (E-15: pesquisa) ────────────────────────────────

@router.get("/public/survey/{lot_code}")
def public_survey_form(lot_code: str, db: Session = Depends(get_db)):
    """
    E-15 — Formulário de pesquisa de satisfação (2 perguntas).
    Ativada após 5 dias da entrega, no primeiro scan do QR após esse período.
    """
    from models import SurveyResponse

    # Verifica se já respondeu
    already_answered = (
        db.query(SurveyResponse)
        .filter(SurveyResponse.lot_code == lot_code)
        .first()
    )

    return {
        "lot_code": lot_code,
        "titulo": "Como foi a experiência com este produto?",
        "ja_respondido": already_answered is not None,
        "perguntas": [
            {
                "campo": "nota_sabor",
                "pergunta": "Como você avalia o SABOR do produto?",
                "escala": "0 = Péssimo, 10 = Excelente",
                "tipo": "nota_0_10",
            },
            {
                "campo": "nota_entrega",
                "pergunta": "Como você avalia a ENTREGA (temperatura, prazo, embalagem)?",
                "escala": "0 = Péssimo, 10 = Excelente",
                "tipo": "nota_0_10",
            },
            {
                "campo": "comentario",
                "pergunta": "Algum comentário? (opcional)",
                "tipo": "texto_livre",
            },
        ],
        "submit_url": f"/public/survey/{lot_code}",
        "metodo": "POST",
    }


@router.post("/public/survey/{lot_code}", status_code=201)
def public_survey_submit(
    lot_code: str,
    payload: SurveySubmit,
    request: Request,
    db: Session = Depends(get_db),
):
    """
    E-15 — Submete resposta da pesquisa de satisfação via QR Code.
    Registra nota de sabor, nota de entrega e comentário opcional.
    """
    from models import SurveyResponse

    existing = db.query(SurveyResponse).filter(SurveyResponse.lot_code == lot_code).first()
    if existing:
        raise HTTPException(status_code=409, detail="Pesquisa já respondida para este lote")

    ip = request.client.host if request.client else None
    resp = SurveyResponse(
        lot_code=lot_code,
        nota_sabor=payload.nota_sabor,
        nota_entrega=payload.nota_entrega,
        comentario=payload.comentario or None,
        ip=ip,
    )
    db.add(resp)
    db.commit()

    media_sabor = payload.nota_sabor
    media_entrega = payload.nota_entrega
    nps_medio = round((media_sabor + media_entrega) / 2, 1)

    def classify(n: int) -> str:
        if n >= 9:
            return "promotor"
        elif n >= 7:
            return "neutro"
        return "detrator"

    return {
        "mensagem": "Obrigado pelo feedback! Sua opinião nos ajuda a melhorar.",
        "lot_code": lot_code,
        "nota_sabor": payload.nota_sabor,
        "nota_entrega": payload.nota_entrega,
        "nps_medio": nps_medio,
        "classificacao": classify(int(nps_medio)),
    }


# ─── Produto Substituto (E-15: substituto) ───────────────────────────────────

@router.get("/public/substitute/{product_id}")
def public_substitute(product_id: uuid.UUID, db: Session = Depends(get_db)):
    """
    E-15 — Página de produto substituto.
    Ativada quando produto é descontinuado ou está com estoque zerado.
    Exibe sugestão de produto similar disponível.
    """
    from models import Product

    original = db.query(Product).filter(Product.id == product_id).first()

    # Busca produto substituto: mesma categoria, ativo, com estoque
    substitute = None
    if original:
        substitute = (
            db.query(Product)
            .filter(
                Product.categoria == original.categoria,
                Product.ativo == True,
                Product.id != product_id,
                Product.estoque_atual > 0,
            )
            .order_by(Product.estoque_atual.desc())
            .first()
        )

    return {
        "produto_original": {
            "id": str(product_id),
            "nome": original.nome if original else "Produto indisponível",
            "disponivel": (original.ativo and (original.estoque_atual or 0) > 0) if original else False,
        },
        "substituto_sugerido": {
            "id": str(substitute.id) if substitute else None,
            "nome": substitute.nome if substitute else None,
            "categoria": substitute.categoria if substitute else None,
            "estoque_disponivel": substitute.estoque_atual if substitute else None,
            "foto_url": substitute.foto_url if substitute else None,
            "descricao": substitute.descricao_marketing if substitute else None,
            "cta_url": f"/orders?product_id={substitute.id}" if substitute else None,
        } if substitute else None,
        "mensagem": (
            f"O produto *{original.nome if original else ''}* está temporariamente indisponível. "
            f"Experimente *{substitute.nome}* — mesma categoria, mesmo padrão SmartFood!"
        ) if substitute else "Produto indisponível no momento. Em breve voltará ao catálogo.",
    }


# ─── Analytics de QR Scans (uso interno) ────────────────────────────────────

@router.get("/qr/analytics/{lot_code}")
def qr_analytics(lot_code: str, db: Session = Depends(get_db)):
    """
    E-15 — Analytics de leituras do QR Code por lote.
    Retorna: total de scans, distribuição por regra, IPs únicos, linha do tempo.
    """
    from models import QRScan, SurveyResponse
    from sqlalchemy import func

    scans = db.query(QRScan).filter(QRScan.lot_code == lot_code).all()

    por_regra: dict[str, int] = {}
    for s in scans:
        regra = s.regra_aplicada or "desconhecida"
        por_regra[regra] = por_regra.get(regra, 0) + 1

    ips_unicos = len({s.ip for s in scans if s.ip})

    survey_count = db.query(SurveyResponse).filter(SurveyResponse.lot_code == lot_code).count()
    survey_data = db.query(SurveyResponse).filter(SurveyResponse.lot_code == lot_code).all()

    media_sabor = None
    media_entrega = None
    if survey_data:
        notas_sabor = [s.nota_sabor for s in survey_data if s.nota_sabor is not None]
        notas_entrega = [s.nota_entrega for s in survey_data if s.nota_entrega is not None]
        if notas_sabor:
            media_sabor = round(sum(notas_sabor) / len(notas_sabor), 1)
        if notas_entrega:
            media_entrega = round(sum(notas_entrega) / len(notas_entrega), 1)

    return {
        "lot_code": lot_code,
        "total_scans": len(scans),
        "ips_unicos": ips_unicos,
        "distribuicao_por_regra": por_regra,
        "surveys": {
            "total_respondidos": survey_count,
            "media_nota_sabor": media_sabor,
            "media_nota_entrega": media_entrega,
        },
        "linha_do_tempo": [
            {
                "scaneado_em": s.created_at.isoformat() if s.created_at else None,
                "regra": s.regra_aplicada,
                "url": s.url_redirecionada,
            }
            for s in sorted(scans, key=lambda x: x.created_at or datetime.min)
        ],
    }


@router.get("/qr/analytics")
def qr_analytics_global(
    limit: int = 20,
    db: Session = Depends(get_db),
):
    """E-15 — Top lotes por número de scans (visão geral)."""
    from models import QRScan
    from sqlalchemy import func

    results = (
        db.query(QRScan.lot_code, func.count(QRScan.id).label("total_scans"))
        .group_by(QRScan.lot_code)
        .order_by(func.count(QRScan.id).desc())
        .limit(limit)
        .all()
    )
    return [{"lot_code": r.lot_code, "total_scans": r.total_scans} for r in results]

"""
FE-10/11/12 + E-20 — UI de Recebimento NF-e (HTMX)

Endpoints:
  GET  /api/receiving/pending           → tabela de NF-e pendentes (fragment)
  POST /api/receiving/sync-gateway      → baixa notas do gateway (Focus NFE)
  POST /api/receiving/upload-xml        → upload manual de XML
  GET  /api/receiving/{nfe_id}/conferencia → tela de conferência inline
  POST /api/receiving/{nfe_id}/dar-entrada → finaliza recebimento + atualiza estoque
  GET  /api/receiving/manual-form       → fragment do formulário manual
  POST /api/receiving/manual            → lançamento manual "Sem Nota"
"""
import json
import uuid as _uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import get_db

router = APIRouter(prefix="/api/receiving", tags=["API — Recebimento UI"])
templates = Jinja2Templates(directory="templates")

_TOLERANCIA_PCT = 0.5  # ±0.5% divergência aceitável


def _toast(msg: str, tipo: str = "success") -> str:
    return json.dumps({"showToast": {"message": msg, "type": tipo}})


def _err_html(msg: str) -> HTMLResponse:
    html = (
        f'<div class="flex items-center gap-2 p-3 rounded-lg bg-red-50 border border-red-200 '
        f'text-sm text-red-800"><i class="ph-fill ph-x-circle text-lg"></i><span>{msg}</span></div>'
    )
    r = HTMLResponse(content=html)
    r.headers["HX-Trigger"] = _toast(msg, "error")
    return r


# ── FE-10: Dashboard — lista NF-e pendentes ──────────────────────────────────

@router.get("/pending", response_class=HTMLResponse)
def list_pending(
    request: Request,
    q: str = "",
    status: str = "",
    db: Session = Depends(get_db),
):
    """Retorna fragment <tbody> com NF-e capturadas."""
    from models import NFePending

    query = db.query(NFePending).order_by(NFePending.created_at.desc())
    if q:
        query = query.filter(
            NFePending.numero.ilike(f"%{q}%")
            | NFePending.emitente_nome.ilike(f"%{q}%")
            | NFePending.emitente_cnpj.ilike(f"%{q}%")
            | NFePending.chave.ilike(f"%{q}%")
        )
    if status:
        query = query.filter(NFePending.status == status)

    notas = query.limit(100).all()
    return templates.TemplateResponse(
        "operations/fragments/nfe_rows.html",
        {"request": request, "notas": notas},
    )


# ── E-20: Sincronizar com gateway fiscal ─────────────────────────────────────

@router.post("/sync-gateway", response_class=HTMLResponse)
def sync_gateway(db: Session = Depends(get_db)):
    """Puxa notas pendentes do gateway Focus NFE e armazena NFePending."""
    from models import NFePending, Supplier
    from services.nfe_gateway_service import NFeGateway
    from services.nfe_service import parse_nfe_xml

    gw = NFeGateway()
    notas_api = gw.buscar_notas_pendentes()

    novas = 0
    erros = 0
    for nota_api in notas_api:
        chave = nota_api.get("chave", "")
        if not chave:
            continue
        # Já existe?
        if db.query(NFePending).filter(NFePending.chave == chave).first():
            continue

        xml = gw.download_xml(chave)
        if not xml:
            erros += 1
            continue

        parsed = parse_nfe_xml(xml)
        if not parsed.get("raw_ok"):
            erros += 1
            continue

        # Tenta vincular fornecedor pelo CNPJ
        cnpj = (parsed["emitente"].get("cnpj") or "").replace(".", "").replace("-", "").replace("/", "")
        supplier = None
        if cnpj:
            supplier = (
                db.query(Supplier)
                .filter(Supplier.nome.ilike(f"%{parsed['emitente'].get('nome', '')}%"))
                .first()
            )

        data_emissao = None
        raw_data = parsed.get("data_emissao", "")
        if raw_data:
            try:
                data_emissao = datetime.fromisoformat(raw_data[:19])
            except Exception:
                pass

        nfe = NFePending(
            id=_uuid.uuid4(),
            chave=chave,
            numero=parsed.get("numero"),
            serie=parsed.get("serie"),
            data_emissao=data_emissao,
            emitente_nome=parsed["emitente"].get("nome"),
            emitente_cnpj=parsed["emitente"].get("cnpj"),
            supplier_id=supplier.id if supplier else None,
            valor_total=parsed["totais"].get("valor_nf", 0.0),
            peso_bruto_declarado=parsed["totais"].get("peso_bruto", 0.0),
            xml_content=xml,
            itens_json=parsed.get("itens", []),
            status="pendente",
        )
        db.add(nfe)
        gw.manifestar_ciencia(chave)
        novas += 1

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        return _err_html(f"Erro ao gravar notas: {e}")

    msg = f"{novas} nota(s) nova(s) importada(s)."
    if erros:
        msg += f" {erros} com erro."
    r = HTMLResponse(
        f'<div class="text-sm text-green-700 font-medium flex items-center gap-1">'
        f'<i class="ph ph-check-circle"></i> {msg}</div>'
    )
    r.headers["HX-Trigger"] = json.dumps({
        "showToast": {"message": msg, "type": "success" if not erros else "warning"},
        "refreshNFePending": True,
    })
    return r


# ── FE-10: Upload manual de XML ───────────────────────────────────────────────

@router.post("/upload-xml", response_class=HTMLResponse)
async def upload_xml(
    nfe_xml: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Recebe upload de arquivo XML e cria NFePending."""
    from models import NFePending
    from services.nfe_service import parse_nfe_xml

    content = (await nfe_xml.read()).decode("utf-8", errors="replace")
    parsed = parse_nfe_xml(content)
    if not parsed.get("raw_ok"):
        return _err_html(f"XML inválido: {parsed.get('erro', 'formato não reconhecido')}")

    chave = parsed.get("chave", "") or f"manual_{_uuid.uuid4().hex[:12]}"
    if db.query(NFePending).filter(NFePending.chave == chave).first():
        return _err_html(f"NF-e {parsed.get('numero', chave)} já foi importada.")

    data_emissao = None
    try:
        raw = parsed.get("data_emissao", "")
        if raw:
            data_emissao = datetime.fromisoformat(raw[:19])
    except Exception:
        pass

    nfe = NFePending(
        id=_uuid.uuid4(),
        chave=chave,
        numero=parsed.get("numero"),
        serie=parsed.get("serie"),
        data_emissao=data_emissao,
        emitente_nome=parsed["emitente"].get("nome"),
        emitente_cnpj=parsed["emitente"].get("cnpj"),
        valor_total=parsed["totais"].get("valor_nf", 0.0),
        peso_bruto_declarado=parsed["totais"].get("peso_bruto", 0.0),
        xml_content=content,
        itens_json=parsed.get("itens", []),
        status="pendente",
    )
    db.add(nfe)
    try:
        db.commit()
        db.refresh(nfe)
    except Exception as e:
        db.rollback()
        return _err_html(f"Erro ao salvar: {e}")

    r = HTMLResponse(
        f'<div class="text-sm text-green-700 font-medium flex items-center gap-2">'
        f'<i class="ph ph-check-circle text-lg"></i>'
        f'NF-e nº {nfe.numero or nfe.chave[:8]} importada! '
        f'<a href="/operations/receiving/{nfe.id}/conferencia" class="underline font-semibold">'
        f'Iniciar conferência →</a></div>'
    )
    r.headers["HX-Trigger"] = json.dumps({
        "showToast": {"message": f"NF-e {nfe.numero} importada!", "type": "success"},
        "refreshNFePending": True,
    })
    return r


# ── FE-11: Tela de Conferência (fragment) ─────────────────────────────────────

@router.get("/{nfe_id}/conferencia-fragment", response_class=HTMLResponse)
def conferencia_fragment(
    nfe_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    from models import NFePending, Ingredient

    nfe = db.query(NFePending).filter(NFePending.id == nfe_id).first()
    if not nfe:
        return HTMLResponse('<p class="text-red-600">NF-e não encontrada.</p>')

    ingredients = db.query(Ingredient).filter(Ingredient.ativo == True).order_by(Ingredient.nome).all()
    return templates.TemplateResponse(
        "operations/fragments/nfe_conferencia.html",
        {"request": request, "nfe": nfe, "ingredients": ingredients,
         "itens": nfe.itens_json or [], "tolerancia": _TOLERANCIA_PCT},
    )


# ── FE-11: Dar Entrada no Estoque ────────────────────────────────────────────

@router.post("/{nfe_id}/dar-entrada", response_class=HTMLResponse)
def dar_entrada(
    nfe_id: str,
    conferencias_json: str = Form("[]"),
    conferido_por: str = Form(""),
    db: Session = Depends(get_db),
):
    """
    Recebe as pesagens reais da conferência, cria IngredientLot por item
    e atualiza estoque_atual. Registra divergências em SystemAlert.
    """
    from models import NFePending, IngredientLot, Ingredient, SystemAlert

    nfe = db.query(NFePending).filter(NFePending.id == nfe_id).first()
    if not nfe:
        return _err_html("NF-e não encontrada.")

    try:
        conferencias = json.loads(conferencias_json)
    except Exception:
        return _err_html("Dados de conferência inválidos.")

    alertas_gerados = 0
    lotes_criados = 0
    now = datetime.now(timezone.utc)

    try:
        for conf in conferencias:
            ingredient_id = conf.get("ingredient_id")
            qty_declarada = float(conf.get("qty_declarada", 0) or 0)
            qty_real = float(conf.get("qty_real", 0) or 0)
            vun = float(conf.get("preco_unitario", 0) or 0)

            if not ingredient_id or qty_real <= 0:
                continue

            # Calcula divergência
            div_pct = 0.0
            if qty_declarada > 0:
                div_pct = abs((qty_real - qty_declarada) / qty_declarada) * 100

            # Cria lote
            lote = IngredientLot(
                id=_uuid.uuid4(),
                ingredient_id=_uuid.UUID(ingredient_id),
                numero_lote=f"NF{nfe.numero or 'S'}-{now.strftime('%Y%m%d')}",
                fornecedor_nome=nfe.emitente_nome or "—",
                quantidade_recebida=qty_real,
                quantidade_atual=qty_real,
                data_recebimento=now,
                data_validade=conf.get("data_validade")
                    and datetime.fromisoformat(conf["data_validade"])
                    or datetime(now.year + 1, now.month, now.day),
                nfe_chave=nfe.chave,
                nfe_peso_declarado=qty_declarada,
                peso_balanca=qty_real,
                divergencia_pct=div_pct,
                status="ativo",
            )
            db.add(lote)

            # Atualiza estoque_atual do ingrediente
            ing = db.query(Ingredient).filter(Ingredient.id == _uuid.UUID(ingredient_id)).first()
            if ing:
                ing.estoque_atual = (ing.estoque_atual or 0) + qty_real
                if vun > 0:
                    ing.custo_atual = vun

            # Alerta de divergência
            if div_pct > _TOLERANCIA_PCT:
                alerta = SystemAlert(
                    id=_uuid.uuid4(),
                    tipo="divergencia_nfe",
                    categoria="qualidade",
                    ingredient_id=_uuid.UUID(ingredient_id),
                    mensagem=(
                        f"Divergência de {div_pct:.1f}% na NF-e {nfe.numero}: "
                        f"declarado {qty_declarada:.3f} kg, recebido {qty_real:.3f} kg."
                    ),
                    severidade="critico" if div_pct > 5 else "atencao",
                    status="ativo",
                )
                db.add(alerta)
                alertas_gerados += 1

            lotes_criados += 1

        # Finaliza NF-e
        nfe.status = "lancada"
        nfe.conferido_por = conferido_por.strip() or "sistema"
        nfe.lancado_em = now

        db.commit()
    except Exception as e:
        db.rollback()
        return _err_html(f"Erro ao dar entrada: {e}")

    msg = f"{lotes_criados} lote(s) criado(s). Estoque atualizado."
    if alertas_gerados:
        msg += f" ⚠️ {alertas_gerados} alerta(s) de divergência gerado(s)."

    r = HTMLResponse(
        f'<div class="flex flex-col gap-1 p-4 rounded-xl bg-green-50 border border-green-200">'
        f'<p class="text-green-800 font-semibold flex items-center gap-2">'
        f'<i class="ph-fill ph-check-circle text-xl"></i> Recebimento concluído!</p>'
        f'<p class="text-sm text-green-700">{msg}</p>'
        f'<a href="/operations/receiving" class="text-sm text-blue-600 underline mt-1">'
        f'← Voltar ao painel</a>'
        f'</div>'
    )
    r.headers["HX-Trigger"] = _toast(msg, "success" if not alertas_gerados else "warning")
    return r


# ── FE-12: Lançamento Manual ──────────────────────────────────────────────────

@router.get("/manual-form", response_class=HTMLResponse)
def manual_form(request: Request, db: Session = Depends(get_db)):
    from models import Ingredient, Supplier
    ingredients = db.query(Ingredient).filter(Ingredient.ativo == True).order_by(Ingredient.nome).all()
    suppliers = db.query(Supplier).order_by(Supplier.nome).all()
    return templates.TemplateResponse(
        "operations/fragments/nfe_manual_form.html",
        {"request": request, "ingredients": ingredients, "suppliers": suppliers},
    )


@router.post("/manual", response_class=HTMLResponse)
def manual_entrada(
    ingredient_id: str = Form(...),
    quantidade: float = Form(...),
    preco_unitario: float = Form(0.0),
    fornecedor_nome: str = Form(""),
    data_validade: str = Form(""),
    conferido_por: str = Form(""),
    db: Session = Depends(get_db),
):
    """FE-12 — Lança lote manual 'Sem Nota' para regularização posterior."""
    from models import IngredientLot, Ingredient

    try:
        ing_uuid = _uuid.UUID(ingredient_id)
    except ValueError:
        return _err_html("Ingrediente inválido.")

    ing = db.query(Ingredient).filter(Ingredient.id == ing_uuid).first()
    if not ing:
        return _err_html("Ingrediente não encontrado.")

    if quantidade <= 0:
        return _err_html("Quantidade deve ser maior que zero.")

    now = datetime.now(timezone.utc)
    val_dt = now.replace(year=now.year + 1)
    if data_validade.strip():
        try:
            val_dt = datetime.fromisoformat(data_validade.strip())
        except Exception:
            pass

    try:
        lote = IngredientLot(
            id=_uuid.uuid4(),
            ingredient_id=ing_uuid,
            numero_lote=f"MANUAL-{now.strftime('%Y%m%d%H%M')}",
            fornecedor_nome=fornecedor_nome.strip() or "Lançamento manual",
            quantidade_recebida=quantidade,
            quantidade_atual=quantidade,
            data_recebimento=now,
            data_validade=val_dt,
            nfe_chave=None,
            status="ativo",
        )
        db.add(lote)
        ing.estoque_atual = (ing.estoque_atual or 0) + quantidade
        if preco_unitario > 0:
            ing.custo_atual = preco_unitario
        db.commit()
    except Exception as e:
        db.rollback()
        return _err_html(f"Erro ao lançar: {e}")

    r = HTMLResponse(
        f'<div class="flex items-center gap-2 p-3 rounded-lg bg-green-50 border border-green-200 text-sm text-green-800">'
        f'<i class="ph-fill ph-check-circle text-lg"></i>'
        f'<span>{quantidade:.3f} {ing.unidade} de <strong>{ing.nome}</strong> lançado(s) no estoque.</span>'
        f'</div>'
    )
    r.headers["HX-Trigger"] = _toast(f"{ing.nome}: +{quantidade} {ing.unidade} lançado.", "success")
    return r

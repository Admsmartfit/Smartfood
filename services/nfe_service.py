"""
E-10 — Recebimento com Balança e Validação de NF-e XML

Parser completo de NF-e XML (padrão SEFAZ v4.0):
  - Extrai cabeçalho, emitente, destinatário, itens e totais
  - Compara peso_balanca vs peso_nf com tolerância configurável (padrão ±0.5%)
  - Gera alerta e aciona notificação automática ao fornecedor via WhatsApp/Email
  - Suporte a multi-item (vários insumos em uma mesma NF-e)

Compatível com lxml (produção) ou xml.etree.ElementTree (fallback).
"""
import logging
from typing import Optional
import uuid

from sqlalchemy.orm import Session

logger = logging.getLogger("nfe_service")

DEFAULT_TOLERANCE_PCT = 0.5  # ±0.5%

# Namespace NF-e SEFAZ
_NFE_NS = "http://www.portalfiscal.inf.br/nfe"


# ─────────────────────────────────────────────────────────────────────────────
# Parser de NF-e XML
# ─────────────────────────────────────────────────────────────────────────────

def _get_parser():
    try:
        from lxml import etree
        return etree, True
    except ImportError:
        import xml.etree.ElementTree as etree
        return etree, False


def _find_text(root, path: str, ns: str = _NFE_NS) -> Optional[str]:
    """Busca texto em elemento com ou sem namespace."""
    el = root.find(f".//{{{ns}}}{path}")
    if el is None:
        el = root.find(f".//{path}")
    return el.text.strip() if el is not None and el.text else None


def _find_float(root, path: str, ns: str = _NFE_NS) -> Optional[float]:
    val = _find_text(root, path, ns)
    if val is None:
        return None
    try:
        return float(val.replace(",", "."))
    except ValueError:
        return None


def parse_nfe_xml(xml_content: str) -> dict:
    """
    Parseia NF-e XML padrão SEFAZ v4.0.

    Retorna dict com:
      chave, numero, serie, data_emissao,
      emitente: {nome, cnpj},
      itens: [{numero, descricao, ncm, unidade, qty, preco_unit, valor_total}],
      totais: {valor_nf, peso_bruto, peso_liquido},
      raw_ok: bool
    """
    etree, is_lxml = _get_parser()

    try:
        if is_lxml:
            root = etree.fromstring(xml_content.encode())
        else:
            root = etree.fromstring(xml_content)
    except Exception as exc:
        logger.error("Falha ao parsear XML: %s", exc)
        return {"raw_ok": False, "erro": str(exc), "itens": []}

    # Cabeçalho
    chave = _find_text(root, "chNFe") or _find_text(root, "Id") or ""
    if chave.startswith("NFe"):
        chave = chave[3:]

    resultado = {
        "raw_ok": True,
        "chave": chave,
        "numero": _find_text(root, "nNF") or "",
        "serie": _find_text(root, "serie") or "",
        "data_emissao": _find_text(root, "dhEmi") or _find_text(root, "dEmi") or "",
        "emitente": {
            "nome": _find_text(root, "xNome") or "",
            "cnpj": _find_text(root, "CNPJ") or "",
        },
        "totais": {
            "valor_nf": _find_float(root, "vNF") or 0.0,
            "peso_bruto": _find_float(root, "pesoB") or 0.0,
            "peso_liquido": _find_float(root, "pesoL") or 0.0,
        },
        "itens": [],
    }

    # Itens (det)
    ns = _NFE_NS
    items_els = root.findall(f".//{{{ns}}}det") or root.findall(".//det")
    for det in items_els:
        prod = det.find(f"{{{ns}}}prod") or det.find("prod")
        if prod is None:
            continue

        def _p(tag):
            el = prod.find(f"{{{ns}}}{tag}") or prod.find(tag)
            return el.text.strip() if el is not None and el.text else None

        try:
            qty = float((_p("qCom") or "0").replace(",", "."))
            preco_unit = float((_p("vUnCom") or "0").replace(",", "."))
            valor_total = float((_p("vProd") or "0").replace(",", "."))
        except ValueError:
            qty = preco_unit = valor_total = 0.0

        resultado["itens"].append({
            "numero_item": det.get(f"{{{ns}}}nItem") or det.get("nItem") or len(resultado["itens"]) + 1,
            "descricao": _p("xProd") or "",
            "ncm": _p("NCM") or "",
            "codigo": _p("cProd") or "",
            "unidade": _p("uCom") or "un",
            "qty": qty,
            "preco_unit": preco_unit,
            "valor_total": valor_total,
        })

    return resultado


# ─────────────────────────────────────────────────────────────────────────────
# Validação de Divergência
# ─────────────────────────────────────────────────────────────────────────────

def validate_weight_divergence(
    peso_balanca: float,
    peso_nf: float,
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
) -> dict:
    """
    Compara peso da balança com peso declarado na NF-e.
    Retorna: divergencia_kg, divergencia_pct, dentro_tolerancia, acao_recomendada.
    """
    if peso_nf <= 0:
        return {
            "divergencia_kg": 0.0,
            "divergencia_pct": 0.0,
            "dentro_tolerancia": True,
            "acao_recomendada": "peso_nf_zero — não foi possível calcular",
        }

    divergencia_kg = peso_balanca - peso_nf
    divergencia_pct = abs(divergencia_kg) / peso_nf * 100
    dentro = divergencia_pct <= tolerance_pct

    if dentro:
        acao = "OK — dentro da tolerância configurada"
    elif divergencia_kg < 0:
        acao = (
            f"FALTA {abs(divergencia_kg):.3f}kg ({divergencia_pct:.2f}% abaixo da NF-e). "
            "Acionar fornecedor para correção ou devolução parcial."
        )
    else:
        acao = (
            f"EXCESSO {divergencia_kg:.3f}kg ({divergencia_pct:.2f}% acima da NF-e). "
            "Verificar erro de pesagem ou cobrar diferença na próxima nota."
        )

    return {
        "peso_balanca": peso_balanca,
        "peso_nf": peso_nf,
        "divergencia_kg": round(divergencia_kg, 4),
        "divergencia_pct": round(divergencia_pct, 4),
        "dentro_tolerancia": dentro,
        "tolerancia_configurada_pct": tolerance_pct,
        "acao_recomendada": acao,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Recebimento Multi-item de NF-e
# ─────────────────────────────────────────────────────────────────────────────

def receive_nfe_full(
    db: Session,
    nfe_xml: str,
    peso_balanca_total: Optional[float],
    ingredient_map: dict,  # {codigo_nfe: ingredient_id} mapeamento item→ingrediente
    numero_lote_prefix: str = "NF",
    data_validade_map: dict = None,  # {ingredient_id: datetime}
    tolerance_pct: float = DEFAULT_TOLERANCE_PCT,
    fornecedor_whatsapp: Optional[str] = None,
    fornecedor_email: Optional[str] = None,
) -> dict:
    """
    Recebimento completo de NF-e com múltiplos insumos.

    - Parseia o XML
    - Valida divergência de peso total
    - Para cada item mapeado, chama receive_ingredient() do inventory_service
    - Notifica fornecedor automaticamente se divergência > tolerância

    Args:
        ingredient_map: {codigo_nfe_item: ingredient_id (UUID)} — mapeia itens da NF-e
        data_validade_map: {str(ingredient_id): datetime} — validade por ingrediente
    """
    from services.inventory_service import receive_ingredient
    from datetime import datetime, timezone, timedelta

    nfe = parse_nfe_xml(nfe_xml)
    if not nfe["raw_ok"]:
        return {"sucesso": False, "erro": nfe.get("erro"), "lotes_criados": []}

    totais = nfe["totais"]
    peso_nf_total = totais.get("peso_bruto") or totais.get("peso_liquido") or 0.0

    # Valida divergência de peso total
    weight_check = None
    divergencia_alerta = False
    if peso_balanca_total is not None and peso_nf_total > 0:
        weight_check = validate_weight_divergence(peso_balanca_total, peso_nf_total, tolerance_pct)
        divergencia_alerta = not weight_check["dentro_tolerancia"]

    # Cria alerta e notifica fornecedor se divergência
    if divergencia_alerta:
        _create_divergence_alert(db, nfe, weight_check, fornecedor_whatsapp, fornecedor_email)

    # Recebe cada item mapeado
    lotes_criados = []
    data_validade_map = data_validade_map or {}
    default_validade = datetime.now(timezone.utc) + timedelta(days=180)

    for item in nfe["itens"]:
        codigo = str(item.get("codigo", ""))
        ing_id = ingredient_map.get(codigo)
        if not ing_id:
            logger.info("Item '%s' (cód. %s) não mapeado — ignorado", item["descricao"], codigo)
            continue

        ing_uuid = uuid.UUID(str(ing_id)) if not isinstance(ing_id, uuid.UUID) else ing_id
        validade = data_validade_map.get(str(ing_uuid), default_validade)
        numero_lote = f"{numero_lote_prefix}-{nfe['numero']}-{codigo}"

        try:
            resultado = receive_ingredient(
                db=db,
                ingredient_id=ing_uuid,
                numero_lote=numero_lote,
                quantidade=item["qty"],
                data_validade=validade,
                fornecedor_nome=nfe["emitente"]["nome"],
                nfe_xml=nfe_xml,
                divergence_tolerance_pct=tolerance_pct,
            )
            lotes_criados.append({
                "item_nfe": item["descricao"],
                "ingredient_id": str(ing_uuid),
                **resultado,
            })
        except Exception as exc:
            logger.error("Erro ao receber item %s: %s", codigo, exc)
            lotes_criados.append({
                "item_nfe": item["descricao"],
                "ingredient_id": str(ing_uuid),
                "erro": str(exc),
            })

    return {
        "sucesso": True,
        "nfe_chave": nfe["chave"],
        "nfe_numero": nfe["numero"],
        "emitente": nfe["emitente"],
        "total_itens_nfe": len(nfe["itens"]),
        "itens_recebidos": len(lotes_criados),
        "lotes_criados": lotes_criados,
        "validacao_peso": weight_check,
        "divergencia_alertada": divergencia_alerta,
    }


def _create_divergence_alert(db, nfe: dict, weight_check: dict,
                              whatsapp: Optional[str], email: Optional[str]):
    """Cria SystemAlert e notifica fornecedor por WhatsApp/Email."""
    from models import SystemAlert

    msg = (
        f"Divergência de peso no recebimento NF-e {nfe['numero']} "
        f"(fornecedor: {nfe['emitente']['nome']}): "
        f"balança={weight_check['peso_balanca']:.3f}kg, "
        f"NF-e={weight_check['peso_nf']:.3f}kg "
        f"({weight_check['divergencia_pct']:.2f}% — acima da tolerância). "
        f"{weight_check['acao_recomendada']}"
    )
    alert = SystemAlert(
        tipo="DIVERGENCIA_RECEBIMENTO",
        categoria="estoque",
        mensagem=msg,
        severidade="atencao",
        status="ativo",
    )
    db.add(alert)
    db.commit()

    # Notifica fornecedor
    try:
        from services.purchase_automation import mega_client, gmail_client
        notif_msg = (
            f"Olá {nfe['emitente']['nome']},\n\n"
            f"Identificamos divergência no recebimento da NF-e {nfe['numero']}:\n"
            f"• Peso na NF-e: {weight_check['peso_nf']:.3f} kg\n"
            f"• Peso na balança: {weight_check['peso_balanca']:.3f} kg\n"
            f"• Divergência: {weight_check['divergencia_pct']:.2f}%\n\n"
            "Por favor, entre em contato para regularização. Obrigado."
        )
        if whatsapp:
            mega_client.send_message(whatsapp, notif_msg)
        if email:
            gmail_client.send_email(email, f"Divergência NF-e {nfe['numero']}", notif_msg)
    except Exception as exc:
        logger.warning("Notificação de divergência falhou: %s", exc)

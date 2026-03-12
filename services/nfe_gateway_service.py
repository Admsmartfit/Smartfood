"""
E-20 — Serviço de Gateway NF-e

Integra com gateways fiscais (Focus NFE / NFE.io / Arquivei) para baixar
automaticamente NF-e dirigidas ao CNPJ da empresa.

Modo de operação:
  - PRODUÇÃO: usa variáveis de ambiente NFE_GATEWAY_TOKEN + NFE_CNPJ
  - DESENVOLVIMENTO: retorna mock de XML de teste quando token não está configurado

Uso típico (background task ou endpoint manual):
    from services.nfe_gateway_service import NFeGateway
    gw = NFeGateway()
    pendentes = gw.buscar_notas_pendentes()
    for nota in pendentes:
        xml = gw.download_xml(nota["chave"])
        ...
"""
import logging
import os
from typing import Optional

import httpx

logger = logging.getLogger("nfe_gateway")

_FOCUS_BASE = "https://api.focusnfe.com.br/v2"
_NFE_IO_BASE = "https://api.nfe.io/v1"


class NFeGateway:
    """
    Abstração sobre o gateway fiscal configurado.
    Suporta Focus NFE (padrão) — extensível para outros providers.
    """

    def __init__(self):
        self.token: str = os.environ.get("NFE_GATEWAY_TOKEN", "")
        self.cnpj: str = os.environ.get("NFE_CNPJ", "").replace("/", "").replace("-", "").replace(".", "")
        self.mock_mode: bool = not bool(self.token)

        if self.mock_mode:
            logger.warning("NFE_GATEWAY_TOKEN não configurado — usando modo mock.")

    # ── Consulta de notas disponíveis ──────────────────────────────────────

    def buscar_notas_pendentes(self, pagina: int = 1) -> list[dict]:
        """
        Retorna lista de NF-e disponíveis para download (status = autorizado).
        Cada item: {chave, numero, data_emissao, emitente_nome, emitente_cnpj, valor_total}
        """
        if self.mock_mode:
            return self._mock_notas()

        try:
            r = httpx.get(
                f"{_FOCUS_BASE}/nfe",
                params={"cnpj_destinatario": self.cnpj, "status": "autorizado", "pagina": pagina},
                auth=(self.token, ""),
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
            return [self._normalizar_focus(item) for item in data]
        except httpx.HTTPError as exc:
            logger.error("Erro ao consultar gateway NF-e: %s", exc)
            return []

    def download_xml(self, chave: str) -> Optional[str]:
        """Baixa o XML completo da NF-e pela chave de acesso (44 dígitos)."""
        if self.mock_mode:
            return self._mock_xml(chave)

        try:
            r = httpx.get(
                f"{_FOCUS_BASE}/nfe/{chave}.xml",
                auth=(self.token, ""),
                timeout=15,
            )
            r.raise_for_status()
            return r.text
        except httpx.HTTPError as exc:
            logger.error("Erro ao baixar XML da chave %s: %s", chave, exc)
            return None

    def manifestar_ciencia(self, chave: str) -> bool:
        """Manifesta 'Ciência da Operação' na SEFAZ (evita prazo vencer)."""
        if self.mock_mode:
            logger.info("[MOCK] Manifestação de ciência: %s", chave)
            return True
        try:
            r = httpx.post(
                f"{_FOCUS_BASE}/nfe/{chave}/manifestacao",
                json={"tipo": "210210"},  # código SEFAZ: Ciência da Operação
                auth=(self.token, ""),
                timeout=10,
            )
            return r.status_code in (200, 201)
        except httpx.HTTPError:
            return False

    # ── Normalização de formato Focus NFE → interno ────────────────────────

    @staticmethod
    def _normalizar_focus(item: dict) -> dict:
        return {
            "chave": item.get("chave_nfe", ""),
            "numero": item.get("numero", ""),
            "data_emissao": item.get("data_emissao", ""),
            "emitente_nome": item.get("emitente", {}).get("nome", ""),
            "emitente_cnpj": item.get("emitente", {}).get("cnpj", ""),
            "valor_total": float(item.get("valor_total", 0) or 0),
        }

    # ── Mock para desenvolvimento ──────────────────────────────────────────

    @staticmethod
    def _mock_notas() -> list[dict]:
        return [
            {
                "chave": "35240312345678000195550010000012341000012340",
                "numero": "1234",
                "data_emissao": "2026-03-10T10:00:00",
                "emitente_nome": "DISTRIBUIDORA TESTE LTDA",
                "emitente_cnpj": "12.345.678/0001-95",
                "valor_total": 1580.50,
            },
            {
                "chave": "35240398765432000110550010000009871000009876",
                "numero": "987",
                "data_emissao": "2026-03-11T14:30:00",
                "emitente_nome": "FRIGORÍFICO MODELO S/A",
                "emitente_cnpj": "98.765.432/0001-10",
                "valor_total": 3240.00,
            },
        ]

    @staticmethod
    def _mock_xml(chave: str) -> str:
        """XML mínimo válido para testes (estrutura NF-e v4.0)."""
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<nfeProc xmlns="http://www.portalfiscal.inf.br/nfe" versao="4.00">
  <NFe>
    <infNFe Id="NFe{chave}" versao="4.00">
      <ide>
        <nNF>1234</nNF>
        <serie>1</serie>
        <dhEmi>2026-03-10T10:00:00-03:00</dhEmi>
      </ide>
      <emit>
        <CNPJ>12345678000195</CNPJ>
        <xNome>DISTRIBUIDORA TESTE LTDA</xNome>
      </emit>
      <det nItem="1">
        <prod>
          <cProd>FRG001</cProd>
          <xProd>FRANGO INTEIRO CONGELADO</xProd>
          <NCM>02071200</NCM>
          <uCom>KG</uCom>
          <qCom>50.000</qCom>
          <vUnCom>12.50</vUnCom>
          <vProd>625.00</vProd>
        </prod>
      </det>
      <det nItem="2">
        <prod>
          <cProd>PRK001</cProd>
          <xProd>PERNIL SUÍNO RESFRIADO</xProd>
          <NCM>02031900</NCM>
          <uCom>KG</uCom>
          <qCom>75.500</qCom>
          <vUnCom>12.66</vUnCom>
          <vProd>955.50</vProd>
        </prod>
      </det>
      <total>
        <ICMSTot>
          <vNF>1580.50</vNF>
        </ICMSTot>
        <transp>
          <pesoL>125.500</pesoL>
          <pesoB>127.000</pesoB>
        </transp>
      </total>
    </infNFe>
  </NFe>
</nfeProc>"""

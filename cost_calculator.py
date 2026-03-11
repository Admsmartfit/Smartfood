"""
E-02 — Calculadora de Custo de Fichas Técnicas
Lógica pura em Python, independente do framework web.

Fórmula mestre:
    Preço = [(Custo_Insumo × FC ÷ FCoc) + Custo_Embalagem + Labor_min × Tempo + Energia] × Markup
"""
import os
from typing import List, Any

# Defaults configuráveis via variáveis de ambiente
DEFAULT_LABOR_COST_PER_MIN: float = float(os.getenv("LABOR_COST_PER_MIN", "0.21"))
DEFAULT_ENERGY_COST: float = float(os.getenv("ENERGY_COST_PER_UNIT", "0.50"))


def calculate_product_cost(
    product: Any,
    bom_items: List[Any],
    custo_labor_min: float = DEFAULT_LABOR_COST_PER_MIN,
    tempo_producao_min: float | None = None,
    custo_energia: float | None = None,
) -> dict:
    """
    Calcula o custo completo de um produto a partir de sua BOM.

    Args:
        product:            Instância do modelo Product (com fc, fcoc, markup, etc.)
        bom_items:          Lista de BOMItem com .ingredient e .supply carregados
        custo_labor_min:    Custo de mão-de-obra por minuto (R$/min)
        tempo_producao_min: Tempo de produção em minutos (usa product.tempo_producao_min se None)
        custo_energia:      Custo de energia por lote em R$ (usa product.custo_energia se None)

    Returns:
        dict com custo_insumos, custo_embalagem, custo_labor, custo_energia,
        custo_total, preco_sugerido, margem_pct e alertas.
    """
    alertas: List[str] = []

    fc: float = product.fc if product.fc is not None else 1.0
    fcoc: float = product.fcoc if product.fcoc is not None else 1.0
    markup: float = product.markup if product.markup is not None else 1.0
    margem_minima: float = product.margem_minima if product.margem_minima is not None else 0.0

    # Validação de FC
    if fc < 1.0:
        alertas.append(
            f"FC inválido: valor {fc:.3f} está abaixo de 1.0. "
            "Verifique o Fator de Correção do produto."
        )

    # Custo de insumos alimentícios: Custo_Insumo × quantidade × FC ÷ FCoc
    custo_insumos: float = 0.0
    for item in bom_items:
        if item.ingredient_id and item.ingredient:
            custo_unit = (item.ingredient.custo_atual or 0.0) * item.quantidade * fc / fcoc
            custo_insumos += custo_unit

    # Custo de embalagem / insumos não-alimentícios
    custo_embalagem: float = 0.0
    for item in bom_items:
        if item.supply_id and item.supply:
            custo_unit = (item.supply.custo_atual or 0.0) * item.quantidade
            custo_embalagem += custo_unit

    # Mão-de-obra
    _tempo: float = (
        tempo_producao_min
        if tempo_producao_min is not None
        else (getattr(product, "tempo_producao_min", None) or 30.0)
    )
    custo_labor: float = custo_labor_min * _tempo

    # Energia
    _energia: float = (
        custo_energia
        if custo_energia is not None
        else (getattr(product, "custo_energia", None) or DEFAULT_ENERGY_COST)
    )

    custo_total: float = custo_insumos + custo_embalagem + custo_labor + _energia
    preco_sugerido: float = custo_total * markup
    margem_pct: float = (
        (preco_sugerido - custo_total) / preco_sugerido * 100
        if preco_sugerido > 0
        else 0.0
    )

    # Validação de margem
    if margem_pct < margem_minima:
        alertas.append(
            f"Margem calculada ({margem_pct:.1f}%) abaixo da margem mínima "
            f"configurada ({margem_minima:.1f}%). Revise o markup ou custos."
        )

    return {
        "produto_id": product.id,
        "produto_nome": product.nome,
        "fc": fc,
        "fcoc": fcoc,
        "custo_insumos": round(custo_insumos, 4),
        "custo_embalagem": round(custo_embalagem, 4),
        "custo_labor": round(custo_labor, 4),
        "custo_energia": round(_energia, 4),
        "custo_total": round(custo_total, 4),
        "markup": markup,
        "preco_sugerido": round(preco_sugerido, 2),
        "margem_pct": round(margem_pct, 2),
        "margem_minima": margem_minima,
        "alertas": alertas,
    }

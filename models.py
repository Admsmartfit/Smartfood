from sqlalchemy import Column, String, Float, Integer, ForeignKey, DateTime, JSON, Boolean, Table, Text, Index
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
import uuid
from database import Base, GUID

class TimestampMixin:
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

# --- Models ---

class Product(Base, TimestampMixin):
    __tablename__ = "products"
    
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    sku = Column(String, unique=True, index=True)
    categoria = Column(String)
    fc = Column(Float, default=1.0, comment="Fator de Correção")
    fcoc = Column(Float, default=1.0, comment="Fator de Cocção")
    markup = Column(Float, default=1.0)
    margem_minima = Column(Float, default=0.0)
    tempo_producao_min = Column(Float, default=30.0, comment="Tempo de produção em minutos")
    custo_energia = Column(Float, default=0.50, comment="Custo de energia por lote (R$)")
    estoque_atual = Column(Float, default=0.0, comment="Estoque de produto acabado (unidades)")
    estoque_seguranca_pct = Column(Float, default=15.0, comment="% de segurança sobre a previsão")
    ativo = Column(Boolean, default=True)
    # REQ-02: Ficha Técnica Operacional
    rendimento_por_lote = Column(Float, default=1.0,
                                 comment="Qtd gerada por 1 Lote Padrão (ex: 100 un, 5 kg)")
    modo_preparo_interno = Column(Text, nullable=True,
                                  comment="Instruções operacionais para a cozinha (não vai para o QR público)")
    # E-21: Porcionamento industrial
    peso_porcao_gramas = Column(Float, nullable=True,
                                comment="Peso de cada porção/unidade em gramas (ex: 350g)")
    unidade_estoque = Column(String, default="unid",
                             comment="'unid' ou 'kg' — modo de incremento do estoque ao finalizar OP")
    # E-12: Catálogo B2B
    foto_url = Column(String, nullable=True)
    descricao_marketing = Column(Text, nullable=True)
    info_nutricional = Column(JSON, nullable=True, comment="Dict com calorias, proteinas, carboidratos, gorduras, sodio")
    alergenicos = Column(String, nullable=True, comment="Lista separada por vírgula")
    instrucoes_preparo_url = Column(String, nullable=True)

    bom_items = relationship("BOMItem", back_populates="product")
    production_batches = relationship("ProductionBatch", back_populates="product")
    order_items = relationship("OrderItem", back_populates="product")

class Ingredient(Base, TimestampMixin):
    __tablename__ = "ingredients"
    
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False, unique=True, index=True)  # REQ-05: unicidade
    unidade = Column(String)  # kg, g, un, etc
    fc_medio = Column(Float, default=1.0)
    custo_atual = Column(Float)
    estoque_atual = Column(Float, default=0.0)
    estoque_minimo = Column(Float, default=0.0)
    lead_time_dias = Column(Integer, default=0)
    ativo = Column(Boolean, default=True)  # REQ-01: soft-delete

    bom_items = relationship("BOMItem", back_populates="ingredient")

class Supply(Base, TimestampMixin):
    __tablename__ = "supplies"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False, unique=True, index=True)  # REQ-05: unicidade
    tipo = Column(String)  # embalagem_primaria|embalagem_secundaria|etiqueta|limpeza|epi|outros
    unidade = Column(String)
    custo_atual = Column(Float, default=0.0)
    estoque_atual = Column(Float, default=0.0)
    estoque_minimo = Column(Float, default=0.0)
    lead_time_dias = Column(Integer, default=0)
    consumo_por_lote = Column(Float, default=0.0)   # embalagens: consumo por lote de produção
    consumo_diario_fixo = Column(Float, default=0.0, comment="Limpeza/EPI: consumo diário por operador")
    ativo = Column(Boolean, default=True)  # REQ-01: soft-delete

    bom_items = relationship("BOMItem", back_populates="supply")

class BOMItem(Base, TimestampMixin):
    __tablename__ = "bom_items"
    
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    product_id = Column(GUID(), ForeignKey("products.id"))
    ingredient_id = Column(GUID(), ForeignKey("ingredients.id"), nullable=True)
    supply_id = Column(GUID(), ForeignKey("supplies.id"), nullable=True)
    quantidade = Column(Float, nullable=False)
    unidade = Column(String)
    perda_esperada_pct = Column(Float, default=0.0)
    
    product = relationship("Product", back_populates="bom_items")
    ingredient = relationship("Ingredient", back_populates="bom_items")
    supply = relationship("Supply", back_populates="bom_items")

class ProductionBatch(Base, TimestampMixin):
    __tablename__ = "production_batches"
    __table_args__ = (
        Index("idx_batch_product_id", "product_id"),
        Index("idx_batch_status", "status"),
    )
    
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    product_id = Column(GUID(), ForeignKey("products.id"))
    quantidade_planejada = Column(Float)
    quantidade_real = Column(Float)
    data_inicio = Column(DateTime)
    data_fim = Column(DateTime)
    custo_total = Column(Float)
    custo_labor = Column(Float, nullable=True, comment="Labor cost calculado pelo tempo real")
    custo_energia_real = Column(Float, nullable=True)
    operador_id = Column(String, nullable=True, comment="ID ou nome do operador que iniciou")
    status = Column(String, default="RASCUNHO")  # RASCUNHO|APROVADA|EM_PRODUCAO|CONCLUIDA|CANCELADA
    motivo_cancelamento = Column(String, nullable=True)
    # E-21: Porcionamento
    porcoes_esperadas = Column(Float, nullable=True,
                               comment="Nº de porções calculadas com base na ficha técnica")
    porcoes_reais_produzidas = Column(Float, nullable=True,
                                      comment="Nº real apontado pelo operador ao finalizar")
    sobra_gramas = Column(Float, nullable=True,
                          comment="Sobra de massa/recheio em gramas após porcionamento")

    product = relationship("Product", back_populates="production_batches")
    ingredient_usages = relationship("BatchIngredientUsage", back_populates="batch")

class BatchIngredientUsage(Base, TimestampMixin):
    __tablename__ = "batch_ingredient_usage"
    
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    batch_id = Column(GUID(), ForeignKey("production_batches.id"))
    ingredient_id = Column(GUID(), ForeignKey("ingredients.id"), nullable=True)  # REQ-03
    supply_id = Column(GUID(), ForeignKey("supplies.id"), nullable=True)  # REQ-03: apontamento de perdas de embalagens
    qty_planejada = Column(Float)
    qty_real = Column(Float)
    custo_unitario = Column(Float)
    divergencia_pct = Column(Float)

    batch = relationship("ProductionBatch", back_populates="ingredient_usages")
    ingredient = relationship("Ingredient", backref="batch_usages")
    supply = relationship("Supply", backref="batch_usages")

class DemandEvent(Base, TimestampMixin):
    __tablename__ = "demand_events"
    __table_args__ = (
        Index("idx_demand_produto_id", "produto_id"),
        Index("idx_demand_data_pedido", "data_pedido"),
    )
    
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    produto_id = Column(GUID(), ForeignKey("products.id"))
    cliente_id = Column(GUID(), ForeignKey("customers.id"), nullable=True)
    quantidade = Column(Float)
    data_pedido = Column(DateTime, index=True)
    data_entrega = Column(DateTime)
    canal = Column(String)
    sazonalidade_tag = Column(String)  # fim_de_semana|feriado|dia_util

class DemandForecast(Base, TimestampMixin):
    __tablename__ = "demand_forecasts"
    
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    produto_id = Column(GUID(), ForeignKey("products.id"))
    periodo = Column(String)  # semana|mes
    qty_prevista = Column(Float)
    confianca_pct = Column(Float)
    modelo_used = Column(String)
    
    # Indices are handled at the end or via Model arguments

class SystemAlert(Base, TimestampMixin):
    __tablename__ = "system_alerts"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    tipo = Column(String)
    categoria = Column(String)  # financeiro|estoque|producao|capacidade|demanda|comercial|qualidade
    produto_id = Column(GUID(), ForeignKey("products.id"), nullable=True)
    supply_id = Column(GUID(), ForeignKey("supplies.id"), nullable=True)
    ingredient_id = Column(GUID(), ForeignKey("ingredients.id"), nullable=True)  # REQ-04: rastreabilidade de alertas de insumo
    mensagem = Column(Text)
    severidade = Column(String)  # critico|atencao|info
    status = Column(String)  # ativo|resolvido|snoozed
    resolvido_em = Column(DateTime)
    snoozed_until = Column(DateTime, nullable=True)
    last_notified_at = Column(DateTime, nullable=True)


class NotificationPreference(Base, TimestampMixin):
    """Preferências de notificação por usuário e tipo de alerta."""
    __tablename__ = "notification_preferences"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    user_id = Column(String, nullable=False, index=True)
    alert_tipo = Column(String, nullable=False)
    canal_push = Column(Boolean, default=True)
    canal_whatsapp = Column(Boolean, default=False)
    canal_email = Column(Boolean, default=False)
    ativo = Column(Boolean, default=True)

class Supplier(Base, TimestampMixin):
    __tablename__ = "suppliers"
    
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    tipo = Column(String)
    whatsapp = Column(String)
    email = Column(String)
    spi_score = Column(Float, default=0.0)
    lead_time_medio_dias = Column(Integer, default=0)

class RFQ(Base, TimestampMixin):
    __tablename__ = "rfqs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    supply_id = Column(GUID(), ForeignKey("supplies.id"))
    supplier_id = Column(GUID(), ForeignKey("suppliers.id"))
    qty_solicitada = Column(Float, nullable=True)
    data_limite = Column(DateTime, nullable=True)
    mensagem_enviada = Column(Text, nullable=True)
    preco_unitario = Column(Float, nullable=True)
    prazo_entrega_dias = Column(Integer, nullable=True)
    resposta_raw = Column(Text, nullable=True)
    observacoes_extraidas = Column(Text, nullable=True)
    score = Column(Float, nullable=True, comment="60% preço + 40% prazo")
    status = Column(String, default="PENDENTE")  # PENDENTE|ENVIADO|RESPONDIDO|APROVADO|REJEITADO
    enviado_em = Column(DateTime, nullable=True)
    respondido_em = Column(DateTime, nullable=True)

    supplier = relationship("Supplier", backref="rfqs")
    supply = relationship("Supply", backref="rfqs")


class PurchaseOrder(Base, TimestampMixin):
    """Ordem de Compra gerada após aprovação de RFQ."""
    __tablename__ = "purchase_orders"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    rfq_id = Column(GUID(), ForeignKey("rfqs.id"), nullable=False)
    supplier_id = Column(GUID(), ForeignKey("suppliers.id"), nullable=False)
    supply_id = Column(GUID(), ForeignKey("supplies.id"), nullable=False)
    qty_aprovada = Column(Float, nullable=False)
    preco_unitario_aprovado = Column(Float, nullable=False)
    total = Column(Float, nullable=False)
    pdf_gerado = Column(Boolean, default=False)
    status = Column(String, default="RASCUNHO")  # RASCUNHO|ENVIADA|CONFIRMADA
    enviado_em = Column(DateTime, nullable=True)

    rfq = relationship("RFQ", backref="purchase_order")
    supplier = relationship("Supplier", backref="purchase_orders")
    supply = relationship("Supply", backref="purchase_orders")

class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    whatsapp = Column(String)
    email = Column(String)
    tabela_preco_id = Column(String)
    historico_volume_mensal = Column(Float)
    ultimo_pedido_em = Column(DateTime)
    
    orders = relationship("Order", back_populates="customer")

class Order(Base, TimestampMixin):
    __tablename__ = "orders"
    __table_args__ = (
        Index("idx_orders_customer_id", "customer_id"),
        Index("idx_orders_status", "status"),
        Index("idx_orders_data_pedido", "data_pedido"),
    )
    
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    customer_id = Column(GUID(), ForeignKey("customers.id"))
    status = Column(String)
    total = Column(Float)
    data_pedido = Column(DateTime)
    data_entrega_prevista = Column(DateTime)
    canal = Column(String)
    
    customer = relationship("Customer", back_populates="orders")
    items = relationship("OrderItem", back_populates="order")

class OrderItem(Base, TimestampMixin):
    __tablename__ = "order_items"
    
    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    order_id = Column(GUID(), ForeignKey("orders.id"))
    product_id = Column(GUID(), ForeignKey("products.id"))
    quantidade = Column(Float)
    preco_unitario = Column(Float)
    margem_pct = Column(Float)
    
    order = relationship("Order", back_populates="items")
    product = relationship("Product", back_populates="order_items")


class IngredientLot(Base, TimestampMixin):
    """Lote de insumo recebido — rastreabilidade PVPS."""
    __tablename__ = "ingredient_lots"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    ingredient_id = Column(GUID(), ForeignKey("ingredients.id"), nullable=False)
    numero_lote = Column(String, nullable=False)
    fornecedor_nome = Column(String, nullable=True)
    quantidade_recebida = Column(Float, nullable=False)
    quantidade_atual = Column(Float, nullable=False)
    data_recebimento = Column(DateTime, nullable=False)
    data_validade = Column(DateTime, nullable=False)
    nfe_chave = Column(String, nullable=True)
    nfe_peso_declarado = Column(Float, nullable=True)
    peso_balanca = Column(Float, nullable=True)
    divergencia_pct = Column(Float, nullable=True)
    status = Column(String, default="ativo")  # ativo|consumido|vencido

    ingredient = relationship("Ingredient", backref="lots")
    consumptions = relationship("LotConsumption", back_populates="lot")


class LotConsumption(Base, TimestampMixin):
    """Consumo de lote de insumo por lote de produção (rastreabilidade)."""
    __tablename__ = "lot_consumptions"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    production_batch_id = Column(GUID(), ForeignKey("production_batches.id"))
    ingredient_lot_id = Column(GUID(), ForeignKey("ingredient_lots.id"))
    quantidade = Column(Float, nullable=False)
    consumido_em = Column(DateTime, nullable=False)

    lot = relationship("IngredientLot", back_populates="consumptions")
    batch = relationship("ProductionBatch", backref="lot_consumptions")


class InventoryAdjustment(Base, TimestampMixin):
    """Ajuste manual de estoque com justificativa — trilha de auditoria."""
    __tablename__ = "inventory_adjustments"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    ingredient_id = Column(GUID(), ForeignKey("ingredients.id"), nullable=False)
    qty_ajuste = Column(Float, nullable=False, comment="Positivo=entrada, negativo=saída")
    motivo = Column(String, nullable=False)
    foto_base64 = Column(Text, nullable=True)
    ajustado_por = Column(String, nullable=True)
    ajustado_em = Column(DateTime, nullable=False)

    ingredient = relationship("Ingredient", backref="adjustments")


class SeasonalEvent(Base, TimestampMixin):
    """Eventos especiais com fator multiplicador manual (Copa, show local, etc.)."""
    __tablename__ = "seasonal_events"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    data_inicio = Column(DateTime, nullable=False)
    data_fim = Column(DateTime, nullable=False)
    fator_multiplicador = Column(Float, nullable=False, comment="Ex: 2.8 para Copa do Mundo")
    produto_id = Column(GUID(), ForeignKey("products.id"), nullable=True,
                        comment="NULL = aplica-se a todos os produtos")
    ativo = Column(Boolean, default=True)


class PriceTable(Base, TimestampMixin):
    """E-12 — Tabela de preços segmentada por grupo de cliente."""
    __tablename__ = "price_tables"

    id = Column(String, primary_key=True, comment="Ex: 'A', 'B', 'C'")
    nome = Column(String, nullable=False, comment="Ex: 'Grandes Redes', 'Bares Parceiros', 'Spot'")
    desconto_pct = Column(Float, default=0.0,
                          comment="% de desconto sobre o preço sugerido (0=sem desconto, 10=10% off)")
    ativo = Column(Boolean, default=True)


class NPSSurvey(Base, TimestampMixin):
    """E-12 — Pesquisa NPS enviada ao cliente após entrega."""
    __tablename__ = "nps_surveys"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    order_id = Column(GUID(), ForeignKey("orders.id"), nullable=False)
    customer_id = Column(GUID(), ForeignKey("customers.id"), nullable=False)
    nota = Column(Integer, nullable=True, comment="0-10")
    comentario = Column(Text, nullable=True)
    enviado_em = Column(DateTime, nullable=True)
    respondido_em = Column(DateTime, nullable=True)
    canal = Column(String, default="whatsapp")


# ─── E-14 — Módulo de Etiquetas e QR Dinâmico ────────────────────────────────

class LabelTemplate(Base, TimestampMixin):
    """Template de etiqueta parametrizado por produto/impressora."""
    __tablename__ = "label_templates"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    product_id = Column(GUID(), ForeignKey("products.id"), nullable=True,
                        comment="NULL = template genérico")
    printer_type = Column(String, default="ZPL", comment="ZPL (Zebra) ou TSPL (Elgin/Argox)")
    width_mm = Column(Integer, default=100)
    height_mm = Column(Integer, default=60)
    fields_config = Column(JSON, nullable=True,
                           comment="Dict com posição e tamanho de cada campo: {nome:{x,y,font_size},...}")
    ativo = Column(Boolean, default=True)


class QRRule(Base, TimestampMixin):
    """Regra de redirecionamento dinâmico do QR Code impresso na etiqueta."""
    __tablename__ = "qr_rules"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    product_id = Column(GUID(), ForeignKey("products.id"), nullable=True,
                        comment="NULL = aplica a todos os produtos")
    regra = Column(String, nullable=False,
                   comment="expiracao_proxima | tutorial | rastreabilidade | pesquisa | substituto")
    dias_vencimento = Column(Integer, nullable=True,
                             comment="Ativa regra quando validade <= D+N (ex: 7)")
    dias_apos_entrega = Column(Integer, nullable=True,
                               comment="Ativa regra de pesquisa N dias após entrega")
    url_destino = Column(String, nullable=False)
    desconto_pct = Column(Float, nullable=True, comment="Para regra expiracao_proxima")
    prioridade = Column(Integer, default=0, comment="Maior = mais prioritário")
    ativo = Column(Boolean, default=True)


class QRScan(Base, TimestampMixin):
    """Registro de cada leitura de QR Code (para analytics e regras de pesquisa)."""
    __tablename__ = "qr_scans"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    lot_code = Column(String, nullable=False, index=True)
    url_redirecionada = Column(String, nullable=False)
    regra_aplicada = Column(String, nullable=True)
    ip = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)


class SurveyResponse(Base, TimestampMixin):
    """E-15 — Resposta à pesquisa de satisfação ativada pelo QR Code."""
    __tablename__ = "survey_responses"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    lot_code = Column(String, nullable=False, index=True)
    nota_sabor = Column(Integer, nullable=True, comment="0-10: nota para o sabor do produto")
    nota_entrega = Column(Integer, nullable=True, comment="0-10: nota para a entrega")
    comentario = Column(Text, nullable=True)
    ip = Column(String, nullable=True)


class YieldHistory(Base, TimestampMixin):
    """
    E-21 — Histórico de rendimento por lote de produção.
    Registra FC e FCoc reais medidos pelo operador para análise de perdas
    e sugestão de ajuste nas fichas técnicas.
    """
    __tablename__ = "yield_history"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    batch_id = Column(GUID(), ForeignKey("production_batches.id"), nullable=False)
    product_id = Column(GUID(), ForeignKey("products.id"), nullable=False)
    # Pesagens do insumo principal (wizard de rendimento)
    peso_bruto_kg = Column(Float, nullable=True, comment="Peso bruto (como saiu da embalagem)")
    peso_limpo_kg = Column(Float, nullable=True, comment="Peso após degelo/limpeza")
    peso_final_kg = Column(Float, nullable=True, comment="Peso após cozimento/processamento")
    fc_real = Column(Float, nullable=True, comment="FC calculado: bruto/limpo")
    fcoc_real = Column(Float, nullable=True, comment="FCoc calculado: limpo/final")
    # Porcionamento
    porcoes_esperadas = Column(Float, nullable=True)
    porcoes_reais = Column(Float, nullable=True)
    peso_porcao_gramas_configurado = Column(Float, nullable=True)
    sobra_gramas = Column(Float, nullable=True)
    # Custo
    custo_total_lote = Column(Float, nullable=True)
    custo_por_porcao_real = Column(Float, nullable=True)
    # Alertas
    alerta_erosao_margem = Column(Boolean, default=False)
    operador_id = Column(String, nullable=True)

    batch = relationship("ProductionBatch", backref="yield_records")
    product = relationship("Product", backref="yield_history")


class NFePending(Base, TimestampMixin):
    """
    E-20 — Cabeçalho de NF-e capturada (gateway ou upload manual)
    aguardando conferência física e lançamento no estoque.
    """
    __tablename__ = "nfe_pending"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    chave = Column(String(44), unique=True, index=True, nullable=False,
                   comment="Chave de acesso NF-e (44 dígitos)")
    numero = Column(String, nullable=True)
    serie = Column(String, nullable=True)
    data_emissao = Column(DateTime, nullable=True)
    emitente_nome = Column(String, nullable=True)
    emitente_cnpj = Column(String(18), index=True, nullable=True)
    supplier_id = Column(GUID(), ForeignKey("suppliers.id"), nullable=True)
    valor_total = Column(Float, default=0.0)
    peso_bruto_declarado = Column(Float, default=0.0,
                                  comment="Peso bruto total declarado na NF-e (kg)")
    xml_content = Column(Text, nullable=False,
                          comment="XML bruto armazenado para reprocessamento")
    itens_json = Column(JSON, nullable=False,
                         comment="Lista de itens parseados do XML")
    status = Column(String, default="pendente",
                    comment="pendente | em_conferencia | conferida | lancada | cancelada")
    conferido_por = Column(String, nullable=True,
                            comment="Nome/PIN do funcionário que conferiu")
    lancado_em = Column(DateTime, nullable=True)

    supplier = relationship("Supplier", backref="nfes_recebidas")


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    nome = Column(String, nullable=False)
    email = Column(String, unique=True, index=True, nullable=False)
    perfil = Column(String, nullable=False, default="operador",
                    comment="chef | operador | admin")
    pin_code = Column(String(4), nullable=True,
                      comment="PIN de 4 dígitos para login rápido no tablet")
    ativo = Column(Boolean, default=True)


class SyncEvent(Base, TimestampMixin):
    """
    E-18 — Evento de sincronização offline.
    Dispositivos móveis/tablets gravam eventos em SQLite e enviam via POST /sync.
    O servidor processa de forma idempotente usando event_id.
    """
    __tablename__ = "sync_events"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)
    event_id = Column(String, nullable=False, unique=True, index=True,
                      comment="ID único gerado pelo device (UUID). Garante idempotência.")
    device_id = Column(String, nullable=False, index=True,
                       comment="Identificador do dispositivo (tablet/celular do operador)")
    event_type = Column(String, nullable=False,
                        comment="ingredient_usage | inventory_adjustment | order_status | production_start | production_complete")
    payload = Column(JSON, nullable=False, comment="Dados do evento serializado")
    status = Column(String, default="pendente",
                    comment="pendente | processado | erro | ignorado (duplicata)")
    erro_msg = Column(Text, nullable=True)
    synced_at = Column(DateTime, nullable=True, comment="Timestamp da criação no device (UTC)")

-- ============================================================
-- SmartFood Ops 360 — Schema SQL Completo
-- Gerado a partir de models.py (SQLAlchemy → SQLite/PostgreSQL)
-- ============================================================

-- ─── customers ───────────────────────────────────────────────
CREATE TABLE customers (
    id          UUID        NOT NULL PRIMARY KEY,
    nome        VARCHAR     NOT NULL,
    whatsapp    VARCHAR,
    email       VARCHAR,
    tabela_preco_id             VARCHAR,
    historico_volume_mensal     FLOAT,
    ultimo_pedido_em            TIMESTAMP WITHOUT TIME ZONE,
    -- Fase 1: Cadastro completo
    cnpj                        VARCHAR UNIQUE,
    razao_social                VARCHAR,
    nome_representante          VARCHAR,
    telefone_representante      VARCHAR,
    telefone_vendedor           VARCHAR,
    endereco_completo           VARCHAR,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── suppliers ───────────────────────────────────────────────
CREATE TABLE suppliers (
    id          UUID        NOT NULL PRIMARY KEY,
    nome        VARCHAR     NOT NULL,
    tipo        VARCHAR,
    whatsapp    VARCHAR,
    email       VARCHAR,
    spi_score   FLOAT       DEFAULT 0.0,
    lead_time_medio_dias        INTEGER DEFAULT 0,
    -- Fase 1: Cadastro completo
    cnpj                        VARCHAR UNIQUE,
    razao_social                VARCHAR,
    nome_representante          VARCHAR,
    telefone_representante      VARCHAR,
    telefone_vendedor           VARCHAR,
    endereco_completo           VARCHAR,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── ingredients ─────────────────────────────────────────────
CREATE TABLE ingredients (
    id              UUID        NOT NULL PRIMARY KEY,
    nome            VARCHAR     NOT NULL UNIQUE,
    unidade         VARCHAR,
    fc_medio        FLOAT       DEFAULT 1.0,
    custo_atual     FLOAT,
    estoque_atual   FLOAT       DEFAULT 0.0,
    estoque_minimo  FLOAT       DEFAULT 0.0,
    lead_time_dias  INTEGER     DEFAULT 0,
    ativo           BOOLEAN     DEFAULT TRUE,
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at      TIMESTAMP WITH TIME ZONE
);

-- ─── supplies ────────────────────────────────────────────────
CREATE TABLE supplies (
    id                  UUID    NOT NULL PRIMARY KEY,
    nome                VARCHAR NOT NULL UNIQUE,
    tipo                VARCHAR,
    unidade             VARCHAR,
    custo_atual         FLOAT   DEFAULT 0.0,
    estoque_atual       FLOAT   DEFAULT 0.0,
    estoque_minimo      FLOAT   DEFAULT 0.0,
    lead_time_dias      INTEGER DEFAULT 0,
    consumo_por_lote    FLOAT   DEFAULT 0.0,
    consumo_diario_fixo FLOAT   DEFAULT 0.0,
    ativo               BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── products ────────────────────────────────────────────────
CREATE TABLE products (
    id                      UUID    NOT NULL PRIMARY KEY,
    nome                    VARCHAR NOT NULL,
    sku                     VARCHAR UNIQUE,
    categoria               VARCHAR,
    fc                      FLOAT   DEFAULT 1.0,
    fcoc                    FLOAT   DEFAULT 1.0,
    markup                  FLOAT   DEFAULT 1.0,
    margem_minima           FLOAT   DEFAULT 0.0,
    tempo_producao_min      FLOAT   DEFAULT 30.0,
    custo_energia           FLOAT   DEFAULT 0.50,
    estoque_atual           FLOAT   DEFAULT 0.0,
    estoque_seguranca_pct   FLOAT   DEFAULT 15.0,
    ativo                   BOOLEAN DEFAULT TRUE,
    rendimento_por_lote     FLOAT   DEFAULT 1.0,
    modo_preparo_interno    TEXT,
    peso_porcao_gramas      FLOAT,
    unidade_estoque         VARCHAR DEFAULT 'unid',
    foto_url                VARCHAR,
    descricao_marketing     TEXT,
    info_nutricional        JSON,
    alergenicos             VARCHAR,
    instrucoes_preparo_url  VARCHAR,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

COMMENT ON TABLE products    IS 'Produtos acabados (petiscos ultracongelados)';
COMMENT ON TABLE ingredients IS 'Insumos alimentícios com controle de FC e custo';
COMMENT ON TABLE supplies    IS 'Insumos não-alimentícios (embalagens, limpeza)';

-- ─── bom_items ───────────────────────────────────────────────
CREATE TABLE bom_items (
    id                  UUID    NOT NULL PRIMARY KEY,
    product_id          UUID    REFERENCES products(id),
    ingredient_id       UUID    REFERENCES ingredients(id),
    supply_id           UUID    REFERENCES supplies(id),
    quantidade          FLOAT   NOT NULL,
    unidade             VARCHAR,
    perda_esperada_pct  FLOAT   DEFAULT 0.0,
    perda_processo_kg   FLOAT   DEFAULT 0.0,  -- Fase 3: perda por etapa do processo
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

COMMENT ON TABLE bom_items IS 'Ficha técnica / Estrutura do produto (Bill of Materials)';

-- ─── production_batches ──────────────────────────────────────
CREATE TABLE production_batches (
    id                      UUID    NOT NULL PRIMARY KEY,
    product_id              UUID    REFERENCES products(id),
    quantidade_planejada    FLOAT,
    quantidade_real         FLOAT,
    data_inicio             TIMESTAMP WITHOUT TIME ZONE,
    data_fim                TIMESTAMP WITHOUT TIME ZONE,
    custo_total             FLOAT,
    custo_labor             FLOAT,
    custo_energia_real      FLOAT,
    operador_id             VARCHAR,
    status                  VARCHAR DEFAULT 'RASCUNHO',
    motivo_cancelamento     VARCHAR,
    porcoes_esperadas       FLOAT,
    porcoes_reais_produzidas FLOAT,
    sobra_gramas            FLOAT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

COMMENT ON TABLE production_batches IS 'Lotes de produção industrial';

-- ─── batch_ingredient_usage ──────────────────────────────────
CREATE TABLE batch_ingredient_usage (
    id              UUID    NOT NULL PRIMARY KEY,
    batch_id        UUID    REFERENCES production_batches(id),
    ingredient_id   UUID    REFERENCES ingredients(id),
    supply_id       UUID    REFERENCES supplies(id),
    qty_planejada   FLOAT,
    qty_real        FLOAT,
    custo_unitario  FLOAT,
    divergencia_pct FLOAT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── orders ──────────────────────────────────────────────────
CREATE TABLE orders (
    id                      UUID    NOT NULL PRIMARY KEY,
    customer_id             UUID    REFERENCES customers(id),
    status                  VARCHAR,
    total                   FLOAT,
    data_pedido             TIMESTAMP WITHOUT TIME ZONE,
    data_entrega_prevista   TIMESTAMP WITHOUT TIME ZONE,
    canal                   VARCHAR,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── order_items ─────────────────────────────────────────────
CREATE TABLE order_items (
    id              UUID    NOT NULL PRIMARY KEY,
    order_id        UUID    REFERENCES orders(id),
    product_id      UUID    REFERENCES products(id),
    quantidade      FLOAT,
    preco_unitario  FLOAT,
    margem_pct      FLOAT,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── demand_events ───────────────────────────────────────────
CREATE TABLE demand_events (
    id              UUID    NOT NULL PRIMARY KEY,
    produto_id      UUID    REFERENCES products(id),
    cliente_id      UUID    REFERENCES customers(id),
    quantidade      FLOAT,
    data_pedido     TIMESTAMP WITHOUT TIME ZONE,
    data_entrega    TIMESTAMP WITHOUT TIME ZONE,
    canal           VARCHAR,
    sazonalidade_tag VARCHAR,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

COMMENT ON TABLE demand_events IS 'Histórico de eventos para o motor de inteligência';

-- ─── demand_forecasts ────────────────────────────────────────
CREATE TABLE demand_forecasts (
    id              UUID    NOT NULL PRIMARY KEY,
    produto_id      UUID    REFERENCES products(id),
    periodo         VARCHAR,
    qty_prevista    FLOAT,
    confianca_pct   FLOAT,
    modelo_used     VARCHAR,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── rfqs ────────────────────────────────────────────────────
CREATE TABLE rfqs (
    id                      UUID    NOT NULL PRIMARY KEY,
    supply_id               UUID    REFERENCES supplies(id),
    supplier_id             UUID    REFERENCES suppliers(id),
    qty_solicitada          FLOAT,
    data_limite             TIMESTAMP WITHOUT TIME ZONE,
    mensagem_enviada        TEXT,
    preco_unitario          FLOAT,
    prazo_entrega_dias      INTEGER,
    resposta_raw            TEXT,
    observacoes_extraidas   TEXT,
    score                   FLOAT,
    status                  VARCHAR DEFAULT 'PENDENTE',
    enviado_em              TIMESTAMP WITHOUT TIME ZONE,
    respondido_em           TIMESTAMP WITHOUT TIME ZONE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── purchase_orders ─────────────────────────────────────────
CREATE TABLE purchase_orders (
    id                      UUID    NOT NULL PRIMARY KEY,
    rfq_id                  UUID    NOT NULL REFERENCES rfqs(id),
    supplier_id             UUID    NOT NULL REFERENCES suppliers(id),
    supply_id               UUID    NOT NULL REFERENCES supplies(id),
    qty_aprovada            FLOAT   NOT NULL,
    preco_unitario_aprovado FLOAT   NOT NULL,
    total                   FLOAT   NOT NULL,
    pdf_gerado              BOOLEAN DEFAULT FALSE,
    status                  VARCHAR DEFAULT 'RASCUNHO',
    enviado_em              TIMESTAMP WITHOUT TIME ZONE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── system_alerts ───────────────────────────────────────────
CREATE TABLE system_alerts (
    id              UUID    NOT NULL PRIMARY KEY,
    tipo            VARCHAR,
    categoria       VARCHAR,
    produto_id      UUID    REFERENCES products(id),
    supply_id       UUID    REFERENCES supplies(id),
    ingredient_id   UUID    REFERENCES ingredients(id),
    mensagem        TEXT,
    severidade      VARCHAR,
    status          VARCHAR,
    resolvido_em    TIMESTAMP WITHOUT TIME ZONE,
    snoozed_until   TIMESTAMP WITHOUT TIME ZONE,
    last_notified_at TIMESTAMP WITHOUT TIME ZONE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── notification_preferences ────────────────────────────────
CREATE TABLE notification_preferences (
    id              UUID    NOT NULL PRIMARY KEY,
    user_id         VARCHAR NOT NULL,
    alert_tipo      VARCHAR NOT NULL,
    canal_push      BOOLEAN DEFAULT TRUE,
    canal_whatsapp  BOOLEAN DEFAULT FALSE,
    canal_email     BOOLEAN DEFAULT FALSE,
    ativo           BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── ingredient_lots ─────────────────────────────────────────
CREATE TABLE ingredient_lots (
    id                  UUID    NOT NULL PRIMARY KEY,
    ingredient_id       UUID    NOT NULL REFERENCES ingredients(id),
    numero_lote         VARCHAR NOT NULL,
    fornecedor_nome     VARCHAR,
    quantidade_recebida FLOAT   NOT NULL,
    quantidade_atual    FLOAT   NOT NULL,
    data_recebimento    TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    data_validade       TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    nfe_chave           VARCHAR,
    nfe_peso_declarado  FLOAT,
    peso_balanca        FLOAT,
    divergencia_pct     FLOAT,
    status              VARCHAR DEFAULT 'ativo',
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── lot_consumptions ────────────────────────────────────────
CREATE TABLE lot_consumptions (
    id                  UUID    NOT NULL PRIMARY KEY,
    production_batch_id UUID    REFERENCES production_batches(id),
    ingredient_lot_id   UUID    REFERENCES ingredient_lots(id),
    quantidade          FLOAT   NOT NULL,
    consumido_em        TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── inventory_adjustments ───────────────────────────────────
CREATE TABLE inventory_adjustments (
    id              UUID    NOT NULL PRIMARY KEY,
    ingredient_id   UUID    NOT NULL REFERENCES ingredients(id),
    qty_ajuste      FLOAT   NOT NULL,
    motivo          VARCHAR NOT NULL,
    foto_base64     TEXT,
    ajustado_por    VARCHAR,
    ajustado_em     TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── seasonal_events ─────────────────────────────────────────
CREATE TABLE seasonal_events (
    id                  UUID    NOT NULL PRIMARY KEY,
    nome                VARCHAR NOT NULL,
    data_inicio         TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    data_fim            TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    fator_multiplicador FLOAT   NOT NULL,
    produto_id          UUID    REFERENCES products(id),
    ativo               BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── price_tables ────────────────────────────────────────────
CREATE TABLE price_tables (
    id          VARCHAR NOT NULL PRIMARY KEY,
    nome        VARCHAR NOT NULL,
    desconto_pct FLOAT  DEFAULT 0.0,
    ativo       BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── nps_surveys ─────────────────────────────────────────────
CREATE TABLE nps_surveys (
    id              UUID    NOT NULL PRIMARY KEY,
    order_id        UUID    NOT NULL REFERENCES orders(id),
    customer_id     UUID    NOT NULL REFERENCES customers(id),
    nota            INTEGER,
    comentario      TEXT,
    enviado_em      TIMESTAMP WITHOUT TIME ZONE,
    respondido_em   TIMESTAMP WITHOUT TIME ZONE,
    canal           VARCHAR DEFAULT 'whatsapp',
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── label_templates ─────────────────────────────────────────
CREATE TABLE label_templates (
    id              UUID    NOT NULL PRIMARY KEY,
    nome            VARCHAR NOT NULL,
    product_id      UUID    REFERENCES products(id),
    printer_type    VARCHAR DEFAULT 'ZPL',
    width_mm        INTEGER DEFAULT 100,
    height_mm       INTEGER DEFAULT 60,
    fields_config   JSON,
    ativo           BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── qr_rules ────────────────────────────────────────────────
CREATE TABLE qr_rules (
    id                  UUID    NOT NULL PRIMARY KEY,
    nome                VARCHAR NOT NULL,
    product_id          UUID    REFERENCES products(id),
    regra               VARCHAR NOT NULL,
    dias_vencimento     INTEGER,
    dias_apos_entrega   INTEGER,
    url_destino         VARCHAR NOT NULL,
    desconto_pct        FLOAT,
    prioridade          INTEGER DEFAULT 0,
    ativo               BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── qr_scans ────────────────────────────────────────────────
CREATE TABLE qr_scans (
    id                  UUID    NOT NULL PRIMARY KEY,
    lot_code            VARCHAR NOT NULL,
    url_redirecionada   VARCHAR NOT NULL,
    regra_aplicada      VARCHAR,
    ip                  VARCHAR,
    user_agent          VARCHAR,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── survey_responses ────────────────────────────────────────
CREATE TABLE survey_responses (
    id              UUID    NOT NULL PRIMARY KEY,
    lot_code        VARCHAR NOT NULL,
    nota_sabor      INTEGER,
    nota_entrega    INTEGER,
    comentario      TEXT,
    ip              VARCHAR,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── yield_history ───────────────────────────────────────────
CREATE TABLE yield_history (
    id                              UUID    NOT NULL PRIMARY KEY,
    batch_id                        UUID    NOT NULL REFERENCES production_batches(id),
    product_id                      UUID    NOT NULL REFERENCES products(id),
    peso_bruto_kg                   FLOAT,
    peso_limpo_kg                   FLOAT,
    peso_final_kg                   FLOAT,
    fc_real                         FLOAT,
    fcoc_real                       FLOAT,
    porcoes_esperadas               FLOAT,
    porcoes_reais                   FLOAT,
    peso_porcao_gramas_configurado  FLOAT,
    sobra_gramas                    FLOAT,
    custo_total_lote                FLOAT,
    custo_por_porcao_real           FLOAT,
    alerta_erosao_margem            BOOLEAN DEFAULT FALSE,
    operador_id                     VARCHAR,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── nfe_pending ─────────────────────────────────────────────
CREATE TABLE nfe_pending (
    id                      UUID        NOT NULL PRIMARY KEY,
    chave                   VARCHAR(44) NOT NULL UNIQUE,
    numero                  VARCHAR,
    serie                   VARCHAR,
    data_emissao            TIMESTAMP WITHOUT TIME ZONE,
    emitente_nome           VARCHAR,
    emitente_cnpj           VARCHAR(18),
    supplier_id             UUID        REFERENCES suppliers(id),
    valor_total             FLOAT       DEFAULT 0.0,
    peso_bruto_declarado    FLOAT       DEFAULT 0.0,
    xml_content             TEXT        NOT NULL,
    itens_json              JSON        NOT NULL,
    status                  VARCHAR     DEFAULT 'pendente',
    conferido_por           VARCHAR,
    lancado_em              TIMESTAMP WITHOUT TIME ZONE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── users ───────────────────────────────────────────────────
CREATE TABLE users (
    id          UUID        NOT NULL PRIMARY KEY,
    nome        VARCHAR     NOT NULL,
    email       VARCHAR     NOT NULL UNIQUE,
    perfil      VARCHAR     NOT NULL DEFAULT 'operador',
    pin_code    VARCHAR(4),
    ativo       BOOLEAN     DEFAULT TRUE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── sync_events ─────────────────────────────────────────────
CREATE TABLE sync_events (
    id          UUID    NOT NULL PRIMARY KEY,
    event_id    VARCHAR NOT NULL UNIQUE,
    device_id   VARCHAR NOT NULL,
    event_type  VARCHAR NOT NULL,
    payload     JSON    NOT NULL,
    status      VARCHAR DEFAULT 'pendente',
    erro_msg    TEXT,
    synced_at   TIMESTAMP WITHOUT TIME ZONE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ============================================================
-- FASE 1 — Melhorias Estruturais
-- ============================================================

-- ─── categories ──────────────────────────────────────────────
CREATE TABLE categories (
    id          UUID    NOT NULL PRIMARY KEY,
    nome        VARCHAR NOT NULL UNIQUE,
    tipo        VARCHAR DEFAULT 'Insumo',   -- Insumo | Embalagem | Produto Final
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── ingredient_manufacturers ────────────────────────────────
CREATE TABLE ingredient_manufacturers (
    id                      UUID    NOT NULL PRIMARY KEY,
    ingredient_id           UUID    NOT NULL REFERENCES ingredients(id),
    nome_fabricante         VARCHAR NOT NULL,
    percentual_rendimento   FLOAT   DEFAULT 100.0,
    pontuacao_qualidade     INTEGER DEFAULT 3,  -- 1 a 5
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── supplier_ingredients (catálogo do fornecedor) ───────────
CREATE TABLE supplier_ingredients (
    id                          UUID    NOT NULL PRIMARY KEY,
    supplier_id                 UUID    NOT NULL REFERENCES suppliers(id),
    ingredient_id               UUID    NOT NULL REFERENCES ingredients(id),
    ingredient_manufacturer_id  UUID    REFERENCES ingredient_manufacturers(id),
    preco_ultima_compra         FLOAT,
    data_atualizacao            TIMESTAMP WITHOUT TIME ZONE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ============================================================
-- FASE 3 — Evolução da Ficha Técnica
-- ============================================================

-- ─── equipments ──────────────────────────────────────────────
CREATE TABLE equipments (
    id          UUID    NOT NULL PRIMARY KEY,
    nome        VARCHAR NOT NULL,
    descricao   VARCHAR,
    ativo       BOOLEAN DEFAULT TRUE,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── equipment_parameters ────────────────────────────────────
CREATE TABLE equipment_parameters (
    id              UUID    NOT NULL PRIMARY KEY,
    equipment_id    UUID    NOT NULL REFERENCES equipments(id),
    nome_parametro  VARCHAR NOT NULL,
    valor_padrao    VARCHAR,           -- texto livre (ex: "180", "1500 RPM")
    unidade_medida  VARCHAR,           -- ex: "°C", "RPM", "min"
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ─── bom_equipments ──────────────────────────────────────────
CREATE TABLE bom_equipments (
    id              UUID    NOT NULL PRIMARY KEY,
    product_id      UUID    NOT NULL REFERENCES products(id),
    equipment_id    UUID    NOT NULL REFERENCES equipments(id),
    parametros_json JSON,              -- {"Velocidade": 1500, "Temperatura": 180}
    perda_processo_kg FLOAT DEFAULT 0.0,
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ============================================================
-- FASE 4 — Módulo Financeiro Integrado à DRE
-- ============================================================

-- ─── financial_expenses ──────────────────────────────────────
CREATE TABLE financial_expenses (
    id                  UUID    NOT NULL PRIMARY KEY,
    descricao           VARCHAR NOT NULL,
    categoria_despesa   VARCHAR DEFAULT 'Outros',  -- Aluguel|Luz|Água|Impostos|Folha|Outros
    valor               FLOAT   NOT NULL,
    data_competencia    TIMESTAMP WITHOUT TIME ZONE NOT NULL,
    data_vencimento     TIMESTAMP WITHOUT TIME ZONE,
    status_pagamento    VARCHAR DEFAULT 'pendente', -- pendente|pago|vencido
    created_at  TIMESTAMP WITH TIME ZONE DEFAULT now(),
    updated_at  TIMESTAMP WITH TIME ZONE
);

-- ============================================================
-- ÍNDICES
-- ============================================================
CREATE INDEX idx_batch_product_id   ON production_batches(product_id);
CREATE INDEX idx_batch_status       ON production_batches(status);
CREATE INDEX idx_demand_produto_id  ON demand_events(produto_id);
CREATE INDEX idx_demand_data_pedido ON demand_events(data_pedido);
CREATE INDEX idx_orders_customer_id ON orders(customer_id);
CREATE INDEX idx_orders_status      ON orders(status);
CREATE INDEX idx_orders_data_pedido ON orders(data_pedido);
CREATE INDEX idx_qr_scans_lot_code  ON qr_scans(lot_code);
CREATE INDEX idx_sync_event_id      ON sync_events(event_id);
CREATE INDEX idx_sync_device_id     ON sync_events(device_id);
CREATE INDEX idx_nfe_emitente_cnpj  ON nfe_pending(emitente_cnpj);
CREATE INDEX idx_ing_mfr_ingredient ON ingredient_manufacturers(ingredient_id);
CREATE INDEX idx_sup_ing_supplier   ON supplier_ingredients(supplier_id);
CREATE INDEX idx_bom_eq_product     ON bom_equipments(product_id);
CREATE INDEX idx_fin_exp_competencia ON financial_expenses(data_competencia);
CREATE INDEX idx_fin_exp_status     ON financial_expenses(status_pagamento);

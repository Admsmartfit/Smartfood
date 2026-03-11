-- Table: customers

CREATE TABLE customers (
	id UUID NOT NULL, 
	nome VARCHAR NOT NULL, 
	whatsapp VARCHAR, 
	email VARCHAR, 
	tabela_preco_id VARCHAR, 
	historico_volume_mensal FLOAT, 
	ultimo_pedido_em TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

-- Table: ingredients

CREATE TABLE ingredients (
	id UUID NOT NULL, 
	nome VARCHAR NOT NULL, 
	unidade VARCHAR, 
	fc_medio FLOAT, 
	custo_atual FLOAT, 
	estoque_atual FLOAT, 
	estoque_minimo FLOAT, 
	lead_time_dias INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

-- Table: products

CREATE TABLE products (
	id UUID NOT NULL, 
	nome VARCHAR NOT NULL, 
	sku VARCHAR, 
	categoria VARCHAR, 
	fc FLOAT, 
	fcoc FLOAT, 
	markup FLOAT, 
	margem_minima FLOAT, 
	ativo BOOLEAN, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

-- Table: suppliers

CREATE TABLE suppliers (
	id UUID NOT NULL, 
	nome VARCHAR NOT NULL, 
	tipo VARCHAR, 
	whatsapp VARCHAR, 
	email VARCHAR, 
	spi_score FLOAT, 
	lead_time_medio_dias INTEGER, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

-- Table: supplies

CREATE TABLE supplies (
	id UUID NOT NULL, 
	nome VARCHAR NOT NULL, 
	tipo VARCHAR, 
	unidade VARCHAR, 
	estoque_atual FLOAT, 
	estoque_minimo FLOAT, 
	lead_time_dias INTEGER, 
	consumo_por_lote FLOAT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id)
)

;

-- Table: bom_items

CREATE TABLE bom_items (
	id UUID NOT NULL, 
	product_id UUID, 
	ingredient_id UUID, 
	supply_id UUID, 
	quantidade FLOAT NOT NULL, 
	unidade VARCHAR, 
	perda_esperada_pct FLOAT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id), 
	FOREIGN KEY(ingredient_id) REFERENCES ingredients (id), 
	FOREIGN KEY(supply_id) REFERENCES supplies (id)
)

;

-- Table: demand_events

CREATE TABLE demand_events (
	id UUID NOT NULL, 
	produto_id UUID, 
	cliente_id UUID, 
	quantidade FLOAT, 
	data_pedido TIMESTAMP WITHOUT TIME ZONE, 
	data_entrega TIMESTAMP WITHOUT TIME ZONE, 
	canal VARCHAR, 
	sazonalidade_tag VARCHAR, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(produto_id) REFERENCES products (id), 
	FOREIGN KEY(cliente_id) REFERENCES customers (id)
)

;

-- Table: demand_forecasts

CREATE TABLE demand_forecasts (
	id UUID NOT NULL, 
	produto_id UUID, 
	periodo VARCHAR, 
	qty_prevista FLOAT, 
	confianca_pct FLOAT, 
	modelo_used VARCHAR, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(produto_id) REFERENCES products (id)
)

;

-- Table: orders

CREATE TABLE orders (
	id UUID NOT NULL, 
	customer_id UUID, 
	status VARCHAR, 
	total FLOAT, 
	data_pedido TIMESTAMP WITHOUT TIME ZONE, 
	data_entrega_prevista TIMESTAMP WITHOUT TIME ZONE, 
	canal VARCHAR, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(customer_id) REFERENCES customers (id)
)

;

-- Table: production_batches

CREATE TABLE production_batches (
	id UUID NOT NULL, 
	product_id UUID, 
	quantidade_planejada FLOAT, 
	quantidade_real FLOAT, 
	data_inicio TIMESTAMP WITHOUT TIME ZONE, 
	data_fim TIMESTAMP WITHOUT TIME ZONE, 
	custo_total FLOAT, 
	status VARCHAR, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
)

;

-- Table: rfqs

CREATE TABLE rfqs (
	id UUID NOT NULL, 
	supply_id UUID, 
	supplier_id UUID, 
	preco_unitario FLOAT, 
	prazo_entrega_dias INTEGER, 
	status VARCHAR, 
	enviado_em TIMESTAMP WITHOUT TIME ZONE, 
	respondido_em TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(supply_id) REFERENCES supplies (id), 
	FOREIGN KEY(supplier_id) REFERENCES suppliers (id)
)

;

-- Table: system_alerts

CREATE TABLE system_alerts (
	id UUID NOT NULL, 
	tipo VARCHAR, 
	produto_id UUID, 
	supply_id UUID, 
	mensagem TEXT, 
	severidade VARCHAR, 
	status VARCHAR, 
	resolvido_em TIMESTAMP WITHOUT TIME ZONE, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(produto_id) REFERENCES products (id), 
	FOREIGN KEY(supply_id) REFERENCES supplies (id)
)

;

-- Table: batch_ingredient_usage

CREATE TABLE batch_ingredient_usage (
	id UUID NOT NULL, 
	batch_id UUID, 
	ingredient_id UUID, 
	qty_planejada FLOAT, 
	qty_real FLOAT, 
	custo_unitario FLOAT, 
	divergencia_pct FLOAT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(batch_id) REFERENCES production_batches (id), 
	FOREIGN KEY(ingredient_id) REFERENCES ingredients (id)
)

;

-- Table: order_items

CREATE TABLE order_items (
	id UUID NOT NULL, 
	order_id UUID, 
	product_id UUID, 
	quantidade FLOAT, 
	preco_unitario FLOAT, 
	margem_pct FLOAT, 
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(), 
	updated_at TIMESTAMP WITH TIME ZONE, 
	PRIMARY KEY (id), 
	FOREIGN KEY(order_id) REFERENCES orders (id), 
	FOREIGN KEY(product_id) REFERENCES products (id)
)

;


-- COMENTÁRIOS DE NEGÓCIO
COMMENT ON TABLE products IS 'Produtos acabados (petiscos ultracongelados)';
COMMENT ON TABLE ingredients IS 'Insumos alimentícios com controle de FC e custo';
COMMENT ON TABLE supplies IS 'Insumos não-alimentícios (embalagens, limpeza)';
COMMENT ON TABLE bom_items IS 'Ficha técnica / Estrutura do produto (Bill of Materials)';
COMMENT ON TABLE production_batches IS 'Lotes de produção industrial';
COMMENT ON TABLE demand_events IS 'Histórico de eventos para o motor de inteligência';

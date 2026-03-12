# SmartFood Ops 360 — Manual de Teste Local (Windows)

> **Ambiente:** Python 3.13 · Windows 11 · **SQLite** (sem PostgreSQL necessário)
> **Versão:** 0.20.0 · Intelligence Edition + Frontend Hypermedia (FE-01 a FE-08)
> **Tempo:** ~5 minutos do zero até o app rodando

---

## ATENÇÃO — Use o Prompt de Comando (cmd), NÃO o PowerShell

O PowerShell trata `--` como operador especial e quebra vários comandos.
Abra sempre o **Prompt de Comando**:
- Tecla `Win` → digite `cmd` → Enter

---

## PASSO 1 — Ir para a pasta do projeto

```cmd
cd C:\Users\ralan\Smartfood
```

---

## PASSO 2 — Criar o ambiente virtual

```cmd
python -m venv venv
```

Ativar:
```cmd
venv\Scripts\activate
```

O prompt muda para `(venv) C:\Users\ralan\Smartfood>`. Isso confirma que está ativo.

> Toda vez que abrir um novo cmd para o projeto, repita `venv\Scripts\activate`.

---

## PASSO 3 — Instalar dependências

```cmd
pip install fastapi "uvicorn[standard]" sqlalchemy psycopg2-binary pydantic holidays httpx reportlab google-generativeai lxml python-multipart python-dotenv
```

Aguarde a instalação completa (~2 minutos).

---

## PASSO 4 — Subir a API

```cmd
uvicorn main:app --reload --port 8000
```

Na primeira execução você verá:

```
INFO:     Started server process
INFO:     Application startup complete.
INFO:     MarginMonitor iniciado — ciclo a cada 15 minutos
INFO:     Uvicorn running on http://0.0.0.0:8000
```

O banco de dados **`smartfood.db`** é criado automaticamente na pasta do projeto (SQLite, sem instalação).

---

## PASSO 5 — Acessar o sistema

Abra o navegador e acesse o **Dashboard principal**:

```
http://localhost:8000/dashboard
```

### Mapa completo de URLs

| Área | URL |
|---|---|
| **Dashboard** (KPIs, monitor de margem, alertas) | http://localhost:8000/dashboard |
| **Fichas Técnicas (BOM)** | http://localhost:8000/operations/bom |
| **Estoque / Inventário** | http://localhost:8000/operations/inventory |
| **Recebimento NF-e** | http://localhost:8000/operations/receiving |
| **Ordens de Produção** | http://localhost:8000/operations/production |
| **Etiquetas** (editor + preview ZPL/TSPL) | http://localhost:8000/operations/labels |
| **Cotações / Compras (RFQ)** | http://localhost:8000/commercial/purchasing |
| **Pedidos B2B** (Kanban) | http://localhost:8000/commercial/orders |
| **Reposição Proativa** (Inteligência B2B) | http://localhost:8000/commercial/b2b-intelligence |
| **Fornecedores / SPI** | http://localhost:8000/commercial/suppliers |
| **DRE e Relatórios** | http://localhost:8000/commercial/dre |
| **Portal B2B** (catálogo clientes) | http://localhost:8000/portal/catalog |
| **Configurações** | http://localhost:8000/settings |
| **App Mobile PWA** | http://localhost:8000/mobile |
| **Previsão de Demanda** | http://localhost:8000/intelligence/forecast |
| **Central de Alertas** | http://localhost:8000/intelligence/alerts |
| **Simulador "E se?"** | http://localhost:8000/intelligence/simulator |
| **Briefing diário preview** | http://localhost:8000/briefing/preview |
| **Documentação Swagger** | http://localhost:8000/docs |

---

## PASSO 6 — Popular o banco e testar (15 minutos)

### 6.1 — Cadastrar dados base (via Swagger)

Acesse `http://localhost:8000/docs` e execute nesta ordem:

**1. POST `/ingredients`** — cadastre 2 ingredientes
```json
{"nome": "Frango CMS", "unidade": "kg", "custo_atual": 8.50, "estoque_atual": 100, "estoque_minimo": 20}
```
```json
{"nome": "Farinha de Trigo", "unidade": "kg", "custo_atual": 3.20, "estoque_atual": 50, "estoque_minimo": 10}
```

**2. POST `/products`** — cadastre 1 produto
```json
{"nome": "Coxinha 200g", "sku": "COX200", "markup": 2.5, "margem_minima": 30}
```

**3. POST `/customers`** — cadastre 1 cliente
```json
{"nome": "Bar do Zé", "whatsapp": "11999990000", "email": "ze@bardoze.com"}
```

**4. POST `/suppliers`** — cadastre 1 fornecedor
```json
{"nome": "Frigorífico Alfa", "whatsapp": "11988880000"}
```

### 6.2 — Testar o Frontend (no navegador)

Após cadastrar os dados acima, abra o navegador e verifique cada módulo:

**Dashboard** → `http://localhost:8000/dashboard`
- Os 4 KPI cards carregam via HTMX (skeleton → dados reais)
- O monitor de margem exibe a tabela de produtos
- O painel de alertas atualiza a cada 60 segundos

**Fichas Técnicas** → `http://localhost:8000/operations/bom`
- Busca ao vivo por produto (HTMX, sem reload)
- Clique num produto para abrir o detalhe com cálculo de custo

**Estoque** → `http://localhost:8000/operations/inventory`
- Filtro por status (OK / Atenção / Crítico) sem reload de página
- Barra de cobertura colorida por dias restantes

**Ordens de Produção** → `http://localhost:8000/operations/production`
- Filtros de status (Pendente / Aprovada / Em Produção / Concluída)
- Botões Iniciar / Concluir atualizam a linha via HTMX

**DRE** → `http://localhost:8000/commercial/dre`
- Selecione o mês no seletor e veja KPIs + tabela carregar
- Botão "Exportar CSV" faz download do arquivo

**Configurações** → `http://localhost:8000/settings`
- Preencha Mega API token, limites de margem e impressora
- Clique "Salvar" — toast de confirmação aparece sem reload

### 6.3 — Testar o PWA (opcional)

1. No Chrome, abra `http://localhost:8000/dashboard`
2. Clique nos 3 pontos → "Instalar SmartFood Ops 360"
3. O app abre em janela própria como app nativo
4. Desative o Wi-Fi — o banner offline aparece e o polling é suspenso automaticamente

---

## Parar e reiniciar

**Parar:** `CTRL + C` no terminal onde o uvicorn está rodando.

**Reiniciar:**
```cmd
cd C:\Users\ralan\Smartfood
venv\Scripts\activate
uvicorn main:app --reload --port 8000
```

**Limpar o banco e começar do zero:**
```cmd
del smartfood.db
uvicorn main:app --reload --port 8000
```

---

## Usar PostgreSQL (produção)

Quando quiser usar PostgreSQL em vez de SQLite, crie um arquivo `.env` na pasta do projeto:

```cmd
(
echo DATABASE_URL=postgresql://postgres:SUA_SENHA@localhost/smartfood
echo MEGA_API_TOKEN=token_teste
echo MEGA_API_INSTANCE=sua-instancia
echo GEMINI_API_KEY=
echo MANAGER_PHONES=
echo GMAIL_USER=
) > .env
```

Crie o banco no PostgreSQL (via cmd, não PowerShell):
```cmd
"C:\Program Files\PostgreSQL\18\bin\psql.exe" -U postgres -c "CREATE DATABASE smartfood;"
```

Reinicie o uvicorn — ele detecta o `.env` automaticamente.

---

## Solução de problemas

### `ModuleNotFoundError: No module named 'xxx'`
```cmd
venv\Scripts\activate
pip install nome-do-modulo
```

### `Address already in use` (porta 8000 ocupada)
```cmd
netstat -ano | findstr :8000
taskkill /PID NUMERO_DO_PID /F
```

### Página em branco ou erro 404 em `/dashboard`
Verifique se o uvicorn iniciou sem erros de importação. Os routers de UI precisam carregar antes do `app.mount("/static", ...)`.

### KPIs mostram zeros
Normal com banco vazio. Cadastre ingredientes, produtos e clientes conforme o Passo 6.1.

### Erro 500 em endpoints com banco vazio
Normal — banco vazio retorna listas vazias. Se retornar 500, verifique o log do uvicorn no terminal.

### Toast "Erro na requisição" ao abrir o Dashboard offline
Esperado. O service worker serve o HTML do cache, mas os fragmentos HTMX de polling (`every 60s`) são automaticamente suspensos quando `navigator.onLine === false`.

### `--` não funciona no PowerShell
Use o **Prompt de Comando** (`cmd`), não o PowerShell.

---

## Arquitetura resumida (para referência)

```
GET /dashboard          → templates/dashboard/index.html  (página completa)
GET /api/fragments/kpis → templates/fragments/kpis.html   (HTMX fragment)
GET /api/fragments/margin-table → fragments/margin_table.html
GET /api/dre/fragment   → fragments/dre_table.html
GET /api/fragments/suppliers-spi → fragments/suppliers_spi.html
POST /api/intelligence/simulate  → fragments/simulate_result.html
```

Todos os fragmentos retornam HTML puro — sem JSON, sem JavaScript extra.
O HTMX injeta o fragmento no DOM via `hx-target` + `hx-swap`.

---

*SmartFood Ops 360 v0.20.0 — SQLite para testes, PostgreSQL para produção*

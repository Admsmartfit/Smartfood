# SmartFood Ops 360 — Manual de Teste Local (Windows)

> **Ambiente:** Python 3.13 · Windows 11 · **SQLite** (sem PostgreSQL necessário)
> **Tempo:** ~5 minutos do zero até a API rodando

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
INFO:     Daily briefing daemon iniciado
INFO:     Uvicorn running on http://0.0.0.0:8000
```

O banco de dados **`smartfood.db`** é criado automaticamente na pasta do projeto (SQLite, sem instalação).

---

## PASSO 5 — Acessar

Abra o navegador:

| O que acessar | URL |
|---|---|
| **Documentação Swagger** (testar todos os endpoints) | http://localhost:8000/docs |
| **App Mobile PWA** | http://localhost:8000/mobile |
| **Raiz da API** (lista etapas) | http://localhost:8000/ |
| Briefing diário preview | http://localhost:8000/briefing/preview |
| Ranking de fornecedores | http://localhost:8000/spi/ranking |

---

## PASSO 6 — Testar rapidamente (10 minutos)

Acesse `http://localhost:8000/docs` e execute nesta ordem:

1. **POST `/ingredients`** — cadastre 2 ingredientes
   ```json
   {"nome": "Frango CMS", "unidade": "kg", "custo_atual": 8.50, "estoque_atual": 100, "estoque_minimo": 20}
   ```
2. **POST `/products`** — cadastre 1 produto
   ```json
   {"nome": "Coxinha 200g", "sku": "COX200", "markup": 2.5, "margem_minima": 30}
   ```
3. **POST `/customers`** — cadastre 1 cliente
   ```json
   {"nome": "Bar do Zé", "whatsapp": "11999990000"}
   ```
4. **GET `/mobile/dashboard`** — veja os KPIs (ainda zerados, mas sem erro)
5. **GET `/briefing/preview`** — preview do briefing diário
6. **GET `/mobile/offline-bundle`** — bundle para o PWA offline

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
echo GEMINI_API_KEY=
echo MANAGER_PHONES=
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

### Erro 500 em endpoints com banco vazio
Normal — banco vazio retorna listas vazias. Se retornar 500, verifique o log do uvicorn no terminal.

### `--` não funciona no PowerShell
Use o **Prompt de Comando** (`cmd`), não o PowerShell.

---

*SmartFood Ops 360 v0.19.0 — SQLite para testes, PostgreSQL para produção*

## Backup MCP Orchestrator Gateway (FastAPI + LangGraph)

This server is a **backup replacement** for an upstream MCP/orchestrator backend that routes requests to **multiple LLM providers**.

It exposes **OpenAI-compatible** endpoints (AI Builder style paths):
- `GET /backend/v1/models`
- `POST /backend/v1/chat/completions`
- `POST /backend/v1/agents/methodology/summary-image` (LangGraph image pipeline)

### Services to run (for LangGraph to control the app)

1. **LiteLLM proxy** (LLM backend used by the gateway’s LangGraph flows)  
   - Run: `litellm --config litellm_config.yaml` (default: `http://localhost:4000`)  
   - Config: `litellm_config.yaml` (model_list, API keys)  
   - Env: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` as needed

2. **Gateway (this app)** — already running under uvicorn  
   - Run: `uvicorn orchestrator_backup.main:app --host 0.0.0.0 --port 8010`  
   - Config: `mcp_gateway_config.yaml` (points at the LiteLLM proxy)  
   - Env: `MCP_GATEWAY_TOKEN`, `LITELLM_PROXY_BASE_URL` (optional, default `http://localhost:4000`), `LITELLM_PROXY_KEY`

LangGraph runs **in-process** inside the gateway; all LLM calls go to the LiteLLM proxy. So you need **both** services: LiteLLM proxy + uvicorn gateway.

### Auth: MCP_GATEWAY_TOKEN vs LITELLM_PROXY_KEY vs LITELLM_MASTER_KEY

| Env var | Where it’s used | Purpose |
|--------|------------------|--------|
| **MCP_GATEWAY_TOKEN** | This backup gateway (port 8010) | Protects **this** gateway. Clients (e.g. frontend) must send `Authorization: Bearer <MCP_GATEWAY_TOKEN>` when calling `/backend/v1/*`. |
| **LITELLM_PROXY_KEY** | This backup gateway → LiteLLM proxy | Key **this gateway** uses when it calls the LiteLLM proxy (chat, image pipeline). Set where you run the gateway (e.g. same env as uvicorn). Often same as `LITELLM_MASTER_KEY` or a virtual key from the proxy. |
| **LITELLM_MASTER_KEY** | LiteLLM proxy (port 4000) | Used by the **LiteLLM proxy** only. Set where you run `litellm --config ...`. Required for the proxy’s Admin UI at `http://0.0.0.0:4000/ui/login/`. Set in the proxy’s `.env` or `config.yaml` as `general_settings: master_key`. See [LiteLLM virtual keys](https://docs.litellm.ai/docs/proxy/virtual_keys). |

**Error “Master Key not set for Proxy” at `/ui/login/`:**  
Set `LITELLM_MASTER_KEY` in the **LiteLLM proxy** process (the one serving port 4000), not in the gateway. Example: `export LITELLM_MASTER_KEY=sk-...` before running `litellm --config litellm_config.yaml`.

**Error “Not connected to DB” at `/ui/login`:**  
LiteLLM Proxy uses **PostgreSQL** for UI login (keys, sessions). It does **not** use MongoDB. Start Postgres, set `DATABASE_URL`, then run the proxy:

```bash
# From paper_chat_app/backend/orchestrator_backup
docker compose -f docker-compose.litellm-db.yml up -d
export DATABASE_URL="postgresql://litellm:litellm@127.0.0.1:5432/litellm"
litellm --config litellm_config.yaml
```

**Error "Unable to find Prisma binaries" / "prisma generate":**  
With pip-installed LiteLLM + `database_url`, run once: `cd $(python -c "import litellm,os; print(os.path.dirname(litellm.__file__))")/proxy && python -m prisma generate --schema schema.prisma`

Then open http://localhost:4000/ui and log in with username `admin`, password = your `master_key` (from `litellm_config.yaml` or `LITELLM_MASTER_KEY`).

### Auth gateway (shared token)

All `backend/v1/*` routes on **this** gateway require:

- `Authorization: Bearer <token>`

Configure the token via env var (default):

- `MCP_GATEWAY_TOKEN`

### Config (new “MCP-style” gateway config)

By default it loads:

- `paper_chat_app/backend/orchestrator_backup/mcp_gateway_config.yaml`

Override with:

- `MCP_GATEWAY_CONFIG_PATH=/abs/path/to/config.yaml`

Each provider is **OpenAI-compatible** (`/v1/chat/completions` style), so you can point it at:
- AI Builders backend (as fallback)
- OpenAI
- Any OpenAI-compatible proxy (vLLM, LiteLLM, etc.)

### Run

From `paper_chat_app/backend/` (or `orchestrator_backup/` for LiteLLM):

**Terminal 1 – PostgreSQL for LiteLLM UI (optional; required only for http://localhost:4000/ui login):**

```bash
cd paper_chat_app/backend/orchestrator_backup
docker compose -f docker-compose.litellm-db.yml up -d
export DATABASE_URL="postgresql://litellm:litellm@127.0.0.1:5432/litellm"
```

**Terminal 2 – LiteLLM proxy (required for LLM calls):**

```bash
cd paper_chat_app/backend/orchestrator_backup
# If using UI login, ensure DATABASE_URL is set (see above)
litellm --config litellm_config.yaml
# Serves OpenAI-compatible API at http://localhost:4000
```

**Terminal 3 – Gateway (uvicorn):**

```bash
cd paper_chat_app/backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export MCP_GATEWAY_TOKEN="change-me"
export LITELLM_PROXY_KEY="sk-..."     # key for LiteLLM proxy (if proxy requires auth)
# export LITELLM_PROXY_BASE_URL="http://localhost:4000"  # optional, default

uvicorn orchestrator_backup.main:app --host 0.0.0.0 --port 8010
```

### Example request

```bash
curl -sS http://localhost:8010/backend/v1/models \
  -H "Authorization: Bearer $MCP_GATEWAY_TOKEN"

curl -sS http://localhost:8010/backend/v1/chat/completions \
  -H "Authorization: Bearer $MCP_GATEWAY_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "grok-4-fast",
    "messages": [{"role":"user","content":"Say hi in one sentence."}],
    "temperature": 0.2
  }'
```

### How orchestration works (LangGraph)

The LangGraph graph:
- routes by `model` -> chooses provider from config
- calls the provider with LangChain `ChatOpenAI`
- returns an OpenAI-compatible response JSON


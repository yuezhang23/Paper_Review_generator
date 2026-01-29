## Backup MCP Orchestrator Gateway (FastAPI + LangGraph)

This server is a **backup replacement** for an upstream MCP/orchestrator backend that routes requests to **multiple LLM providers**.

It exposes **OpenAI-compatible** endpoints (AI Builder style paths):
- `GET /backend/v1/models`
- `POST /backend/v1/chat/completions`

### Auth gateway (shared token)

All `backend/v1/*` routes require:

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

From `paper_chat_app/backend/`:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export MCP_GATEWAY_TOKEN="change-me"
export AI_BUILDER_TOKEN="..."          # if using ai_builders provider
# export OPENAI_API_KEY="..."          # if using openai provider

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


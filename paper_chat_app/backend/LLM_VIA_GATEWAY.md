# Backend Architecture: Split Non-LLM (8000) and Gateway (8010)

When `USE_GATEWAY_ORCHESTRATOR=true` (via `./start.sh --with-gateway`):

- **Port 8000** (main.py): Non-LLM endpoints only
- **Port 8010** (orchestrator_backup): All LLM endpoints and gateway routes

## Endpoints by Server

### Main backend (8000) — non-LLM
| Endpoint | Description |
|----------|-------------|
| `GET /` | Root |
| `GET /health` | Health check |
| `GET /suggestions` | Paper query suggestions |
| `GET /api/file-info` | Resolve file_ids → metadata (for gateway) |
| `POST /api/get-paper-reviews` | OpenReview paper reviews |
| `POST /api/upload-files` | Upload files |
| `GET /api/files/{file_id}` | Get file info |
| `GET /api/reviews/{filename}` | Serve review files |
| `POST /api/search-review-from-openreview` | Deprecated alias |
| `POST /api/get-paper-context` | Deprecated alias |

### Gateway (8010) — LLM
| Endpoint | Description |
|----------|-------------|
| `GET /api/models` | List models (frontend format) |
| `GET /api/gateway/models` | Same |
| `POST /api/chat` | Chat with paper context |
| `POST /api/chat/multi-model` | Multi-model chat |
| `POST /api/chat/stream` | Streaming chat |
| `POST /api/summary` | Paper summary (RAG) |
| `POST /api/generate-summary-image` | Methodology diagram |
| `GET /backend/v1/models` | Gateway models (OpenAI format) |
| `POST /backend/v1/chat/completions` | Gateway chat completions |
| `POST /backend/v1/agents/methodology/summary-image` | Gateway image agent |

## File resolution (file_ids)

When the frontend uploads files to main (8000), it receives `file_ids`. For chat/summary/image on the gateway (8010), the gateway calls `GET {MAIN_BACKEND_URL}/api/file-info?file_ids=...` to fetch file metadata (including `pdf_path`, `text_content`). `ensure_file_info_from_main_backend()` in utils populates `file_storage` on the gateway before processing.

## Configuration

- **utils.py**: `get_ai_builder_base_url()` → `http://localhost:8010/backend/v1` when gateway enabled
- **utils.py**: `get_ai_client()` uses that base_url
- **orchestrator_backup/main.py**: Sets `MAIN_BACKEND_URL=http://localhost:8000` so gateway can resolve file_ids
- **start.sh**: Runs main (8000) and gateway (8010) when `--with-gateway`

## Model resolution (LangGraph)

- **Text**: `resolve_model(cfg, preferred, "text")` from `mcp_gateway_config.yaml`
- **Image**: `resolve_model(cfg, preferred, "image")` for image-capable models

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Ensure package roots are on path whether this file is run from
# orchestrator_backup/ (python main.py) or imported from backend/main.py
_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(_this_dir)
for _d in (_this_dir, _parent_dir):
    if _d not in sys.path:
        sys.path.insert(0, _d)

# When gateway runs standalone (port 8010), ensure env for LLM routing
os.environ.setdefault("USE_GATEWAY_ORCHESTRATOR", "true")
os.environ.setdefault("GATEWAY_ORCHESTRATOR_URL", "http://localhost:8010")
os.environ.setdefault("MAIN_BACKEND_URL", "http://localhost:8000")

from auth import require_bearer_token
from config import GatewayConfig, list_all_models, load_gateway_config
from graph import build_chat_graph, build_image_agent_graph
from image_methodos_generator.image_method_generator import ImageGenerationRequest

# LLM service routers (chat, summary, image generation)
from summary_generator.main import router as summary_router
from image_methodos_generator.main import router as image_methodos_generator_router
from chatbot_service import router as chatbot_router


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionsRequest(BaseModel):
    model: str = Field(..., description="Model ID (e.g., grok-4-fast, gpt-5, gemini-2.5-pro)")
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False


def create_gateway_router() -> APIRouter:
    """
    Build an APIRouter with /backend/v1/* routes (models, chat/completions, methodology/summary-image).
    Include this router in the main app when USE_GATEWAY_ORCHESTRATOR=true for a single server on port 8010.
    """
    cfg_path = os.getenv("MCP_GATEWAY_CONFIG_PATH") or os.path.join(
        os.path.dirname(__file__),
        "mcp_gateway_config.yaml",
    )
    cfg: GatewayConfig = load_gateway_config(cfg_path)
    chat_graph = build_chat_graph(cfg)
    _image_graph: Optional[Any] = None

    def get_image_graph():
        nonlocal _image_graph
        if _image_graph is None:
            _image_graph = build_image_agent_graph(cfg)
        return _image_graph

    def _auth(authorization: str | None = Header(default=None)) -> None:
        require_bearer_token(authorization=authorization, expected_token=cfg.token)

    router = APIRouter(prefix="/backend/v1", tags=["gateway"])

    @router.get("/models", dependencies=[Depends(_auth)])
    async def models():
        return {"object": "list", "data": list_all_models(cfg)}

    @router.post("/chat/completions", dependencies=[Depends(_auth)])
    async def chat_completions(req: ChatCompletionsRequest):
        if req.stream:
            raise HTTPException(status_code=400, detail="stream=true not implemented in backup gateway yet")
        state = {
            "model": req.model,
            "messages": [m.model_dump() for m in req.messages],
            "temperature": req.temperature,
            "max_tokens": req.max_tokens,
        }
        out = chat_graph.invoke(state)
        resp = out.get("response_obj")
        if not resp:
            raise HTTPException(status_code=500, detail="No response from orchestrator graph")
        return resp

    async def _run_image_graph(req: ImageGenerationRequest):
        try:
            image_graph = get_image_graph()
        except RuntimeError as e:
            if "Missing API key" in str(e):
                raise HTTPException(
                    status_code=503,
                    detail="Image pipeline unavailable: set LITELLM_PROXY_KEY (or the provider API key env) and retry.",
                ) from e
            raise
        req_dict = req.model_dump()
        model = req_dict.get("model") or None
        state = {"request": req_dict, "model": model}
        out = await image_graph.ainvoke(state)
        return {
            "image_url": out.get("image_url"),
            "image_bytes_b64": out.get("image_bytes_b64"),
            "revised_prompt": out.get("whiteboard_prompt"),
            "methodology_steps": out.get("interpretation_preview"),
        }

    @router.post("/images/generations", dependencies=[Depends(_auth)])
    async def methodology_summary_image(req: ImageGenerationRequest):
        return await _run_image_graph(req)

    @router.post("/agents/methodology/summary-image", dependencies=[Depends(_auth)])
    async def methodology_summary_image_agent(req: ImageGenerationRequest):
        """Alias for proxy from main backend (8010) when calling /backend/v1/agents/methodology/summary-image."""
        return await _run_image_graph(req)

    return router


def _models_from_config(cfg: GatewayConfig) -> list:
    """Map config models to frontend format."""
    models = list_all_models(cfg)
    return [
        {"id": m.get("id", ""), "name": m.get("id", "Unknown"), "description": f"Model via {m.get('owned_by', 'gateway')}"}
        for m in models if isinstance(m, dict) and m.get("id")
    ]


def create_app() -> FastAPI:
    """
    Standalone gateway app (port 8010). All LLM endpoints run here.
    Main backend (8000) has non-LLM endpoints only.
    """
    cfg_path = os.getenv("MCP_GATEWAY_CONFIG_PATH") or os.path.join(
        os.path.dirname(__file__),
        "mcp_gateway_config.yaml",
    )
    cfg: GatewayConfig = load_gateway_config(cfg_path)
    app = FastAPI(title="Paper Chat Gateway (LLM)", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Gateway routes: /backend/v1/models, /backend/v1/chat/completions, /backend/v1/agents/methodology/summary-image
    app.include_router(create_gateway_router())
    # LLM service routers: /api/chat, /api/summary, /api/generate-summary-image
    app.include_router(summary_router)
    app.include_router(chatbot_router)
    app.include_router(image_methodos_generator_router)

    @app.get("/api/models")
    async def api_models():
        """Get models in frontend format (alias for /api/gateway/models)."""
        return {"models": _models_from_config(cfg)}

    @app.get("/api/gateway/models")
    async def api_gateway_models():
        """Get models from gateway in frontend format."""
        return {"models": _models_from_config(cfg)}

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    @app.get("/")
    async def root():
        return {
            "name": "paper-chat-gateway",
            "status": "running",
            "port": 8010,
            "config_path": cfg_path,
            "providers": [p.name for p in cfg.providers],
        }
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8010")))


from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running as script: ensure backend/ is on path for image_methodos_generator
_backend = Path(__file__).resolve().parent.parent
if str(_backend) not in sys.path:
    sys.path.insert(0, str(_backend))

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from auth import require_bearer_token
from config import GatewayConfig, list_all_models, load_gateway_config
from graph import build_chat_graph, build_image_agent_graph
from image_methodos_generator.image_method_generator import ImageGenerationRequest


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatCompletionsRequest(BaseModel):
    model: str = Field(..., description="Model ID (e.g., grok-4-fast, gpt-5, gemini-2.5-pro)")
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    stream: bool = False


def create_app() -> FastAPI:
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

    app = FastAPI(title="Backup MCP Orchestrator Gateway", version="0.1.0")

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def _auth(authorization: str | None = Header(default=None)) -> None:
        require_bearer_token(authorization=authorization, expected_token=cfg.token)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    # OpenAI-compatible models endpoint (matching AI Builder style path)
    @app.get("/backend/v1/models", dependencies=[Depends(_auth)])
    async def models():
        return {"object": "list", "data": list_all_models(cfg)}


    # OpenAI-compatible chat completions endpoint (matching AI Builder style path)
    @app.post("/backend/v1/chat/completions", dependencies=[Depends(_auth)])
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

    @app.post("/backend/v1/agents/methodology/summary-image", dependencies=[Depends(_auth)])
    async def methodology_summary_image(req: ImageGenerationRequest):
        """
        Agentic endpoint that mirrors /api/generate-summary-image, but runs the
        full image-methodology pipeline through a LangGraph.
        """
        try:
            image_graph = get_image_graph()
        except RuntimeError as e:
            if "Missing API key" in str(e):
                raise HTTPException(
                    status_code=503,
                    detail="Image pipeline unavailable: set LITELLM_PROXY_KEY (or the provider API key env) and retry.",
                ) from e
            raise
        state = {"request": req.model_dump()}
        out = await image_graph.ainvoke(state)

        return {
            "image_url": out.get("image_url"),
            "image_bytes_b64": out.get("image_bytes_b64"),
            "revised_prompt": out.get("whiteboard_prompt"),
            "methodology_steps": out.get("interpretation_preview"),
        }

    @app.get("/")
    async def root():
        return {
            "name": "backup-mcp-orchestrator-gateway",
            "status": "running",
            "config_path": cfg_path,
            "providers": [p.name for p in cfg.providers],
        }

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8010")))


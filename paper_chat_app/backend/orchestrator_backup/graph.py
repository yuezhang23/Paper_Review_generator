from __future__ import annotations

import base64
import time
import uuid
from typing import Any, Dict, List, Optional, TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph

from config import GatewayConfig, get_provider_for_model
from llm_clients import (
    from_ai_message,
    get_openai_client,
    get_openai_compatible_chat_model,
    to_langchain_messages,
)

# Reuse the existing methodology/image backend for an agentic flow graph.
from image_methodos_generator.image_method_generator import (
    ImageGenerationRequest,
    combine_and_validate_chunks,
    generate_image as _generate_image,
    generate_interpretation,
    generate_whiteboard_prompt,
    resolve_pdf_and_index,
    retrieve_methodology_chunks,
    save_interpretation_and_create_request_dir,
)


class ChatState(TypedDict, total=False):
    model: str
    messages: List[Dict[str, Any]]
    temperature: float
    max_tokens: Optional[int]
    provider_name: str
    response_text: str
    response_obj: Dict[str, Any]


def _route_node(cfg: GatewayConfig):
    def _route(state: ChatState) -> ChatState:
        model = state.get("model") or ""
        provider = get_provider_for_model(cfg, model)
        return {"provider_name": provider.name}

    return _route


def _call_provider_node(cfg: GatewayConfig):
    providers_by_name = {p.name: p for p in cfg.providers}

    def _call(state: ChatState) -> ChatState:
        model = state.get("model") or ""
        provider_name = state.get("provider_name") or ""
        provider = providers_by_name.get(provider_name) or get_provider_for_model(cfg, model)

        temperature = float(state.get("temperature", 0.7))
        max_tokens = state.get("max_tokens")
        messages = state.get("messages") or []

        if provider.type != "openai_compatible":
            raise RuntimeError(f"Unsupported provider type: {provider.type}")

        llm = get_openai_compatible_chat_model(
            provider=provider,
            model=model if model else (provider.default_model or (provider.models[0] if provider.models else "")),
            temperature=temperature,
            max_tokens=max_tokens,
        )

        lc_messages = to_langchain_messages(messages)
        ai: AIMessage = llm.invoke(lc_messages)
        text = from_ai_message(ai)

        created = int(time.time())
        resp = {
            "id": f"chatcmpl_{uuid.uuid4().hex}",
            "object": "chat.completion",
            "created": created,
            "model": model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": text},
                    "finish_reason": "stop",
                }
            ],
        }
        return {"response_text": text, "response_obj": resp}
    return _call


def build_chat_graph(cfg: GatewayConfig):
    g = StateGraph(ChatState)
    g.add_node("route", _route_node(cfg))
    g.add_node("call_provider", _call_provider_node(cfg))

    g.add_edge(START, "route")
    g.add_edge("route", "call_provider")
    g.add_edge("call_provider", END)

    return g.compile()


# -----------------------------------------------------------------------------
# Agentic image methodology flow graph
# -----------------------------------------------------------------------------
class ImageAgentState(TypedDict, total=False):
    request: Dict[str, Any]
    pdf_path: str
    index: Any
    cache_key: str
    retrieved_content: str
    interpretation_preview: str
    request_dir: str
    interpretation_path: str
    whiteboard_prompt: str
    image_bytes_b64: str
    image_url: str


async def _resolve_pdf_node(state: ImageAgentState) -> ImageAgentState:
    req_dict = state.get("request") or {}
    req = ImageGenerationRequest(**req_dict)
    pdf_path, index, cache_key = await resolve_pdf_and_index(req)
    return {
        "pdf_path": pdf_path,
        "index": index,
        "cache_key": cache_key,
    }


async def _retrieve_chunks_node(state: ImageAgentState) -> ImageAgentState:
    cache_key = state["cache_key"]
    index = state["index"]
    method_zone_chunks, detail_chunks = await retrieve_methodology_chunks(cache_key, index)
    retrieved_content = combine_and_validate_chunks(method_zone_chunks, detail_chunks)
    return {
        "retrieved_content": retrieved_content,
    }


def _make_interpretation_node(cfg: GatewayConfig):
    provider = get_provider_for_model(cfg, "supermind-agent-v1")
    ai_client = get_openai_client(provider)

    async def _node(state: ImageAgentState) -> ImageAgentState:
        retrieved_content = state["retrieved_content"]
        interpretation_preview = await generate_interpretation(ai_client, retrieved_content)
        return {"interpretation_preview": interpretation_preview}

    return _node


async def _save_interpretation_node(state: ImageAgentState) -> ImageAgentState:
    interpretation_preview = state["interpretation_preview"]
    request_dir, interpretation_path = save_interpretation_and_create_request_dir(interpretation_preview)
    return {
        "request_dir": request_dir,
        "interpretation_path": interpretation_path,
    }


def _make_whiteboard_prompt_node(cfg: GatewayConfig):
    provider = get_provider_for_model(cfg, "supermind-agent-v1")
    ai_client = get_openai_client(provider)

    async def _node(state: ImageAgentState) -> ImageAgentState:
        interpretation_path = state["interpretation_path"]
        request_dir = state["request_dir"]
        whiteboard_prompt = await generate_whiteboard_prompt(
            interpretation_path, request_dir, ai_client=ai_client
        )
        return {"whiteboard_prompt": whiteboard_prompt}
    return _node


def _make_generate_image_node(cfg: GatewayConfig):
    provider = get_provider_for_model(cfg, "supermind-agent-v1")
    ai_client = get_openai_client(provider)

    async def _node(state: ImageAgentState) -> ImageAgentState:
        whiteboard_prompt = state["whiteboard_prompt"]
        request_dir = state["request_dir"]
        image_bytes, image_url = await _generate_image(
            ai_client=ai_client,
            whiteboard_prompt=whiteboard_prompt,
            request_dir=request_dir,
            criticize_image=True,
        )
        image_bytes_b64 = base64.b64encode(image_bytes).decode("utf-8") if image_bytes else ""
        return {
            "image_bytes_b64": image_bytes_b64,
            "image_url": image_url,
        }

    return _node


def build_image_agent_graph(cfg: GatewayConfig):
    """
    Agentic LangGraph that mirrors the 7-step image methodology pipeline:
    1) resolve PDF + index
    2) retrieve methodology chunks
    3) combine/validate chunks
    4) generate interpretation (LLM)
    5) save interpretation + create request dir
    6) generate whiteboard prompt (3-layer generator)
    7) generate/rank image

    Uses cfg to build an OpenAI-compatible client from gateway providers instead of
    get_ai_client() / AI Builder API, so the pipeline works when that API is off.
    """
    g = StateGraph(ImageAgentState)
    g.add_node("resolve_pdf", _resolve_pdf_node)
    g.add_node("retrieve_chunks", _retrieve_chunks_node)
    g.add_node("interpretation", _make_interpretation_node(cfg))
    g.add_node("save_interpretation", _save_interpretation_node)
    g.add_node("whiteboard_prompt", _make_whiteboard_prompt_node(cfg))
    g.add_node("generate_image", _make_generate_image_node(cfg))

    g.add_edge(START, "resolve_pdf")
    g.add_edge("resolve_pdf", "retrieve_chunks")
    g.add_edge("retrieve_chunks", "interpretation")
    g.add_edge("interpretation", "save_interpretation")
    g.add_edge("save_interpretation", "whiteboard_prompt")
    g.add_edge("whiteboard_prompt", "generate_image")
    g.add_edge("generate_image", END)

    return g.compile()


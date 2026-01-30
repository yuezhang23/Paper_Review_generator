from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List

import openai
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI

from config import ProviderConfig


def to_langchain_messages(messages: List[Dict[str, Any]]) -> List[BaseMessage]:
    out: List[BaseMessage] = []
    for m in messages:
        role = (m.get("role") or "").lower()
        content = m.get("content")
        if content is None:
            content = ""
        if role == "system":
            out.append(SystemMessage(content=str(content)))
        elif role == "assistant":
            out.append(AIMessage(content=str(content)))
        else:
            out.append(HumanMessage(content=str(content)))
    return out


def from_ai_message(msg: AIMessage) -> str:
    # AIMessage.content can be str or list[dict] depending on tool calling.
    if isinstance(msg.content, str):
        return msg.content
    try:
        return str(msg.content)
    except Exception:
        return ""


@lru_cache(maxsize=64)
def _chat_model_cache_key(
    provider_name: str,
    base_url: str,
    api_key: str,
    model: str,
    timeout_s: float,
) -> str:
    return f"{provider_name}|{base_url}|{model}|{timeout_s}|{hash(api_key)}"


def get_openai_compatible_chat_model(
    provider: ProviderConfig,
    model: str,
    temperature: float,
    max_tokens: int | None,
) -> ChatOpenAI:
    api_key = provider.api_key
    if not api_key:
        raise RuntimeError(f"Missing API key env var: {provider.api_key_env} for provider {provider.name}")

    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=provider.effective_base_url,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=provider.timeout_s,
    )


def get_openai_client(provider: ProviderConfig) -> openai.OpenAI:
    """
    Build a raw openai.OpenAI client from a ProviderConfig.
    Used by the image methodology pipeline (interpretation, image gen) so it can
    use gateway config providers instead of get_ai_client() / AI Builder API.
    """
    api_key = provider.api_key
    if not api_key:
        raise RuntimeError(
            f"Missing API key env var: {provider.api_key_env} for provider {provider.name}"
        )

    return openai.OpenAI(
        base_url=provider.effective_base_url,
        api_key=api_key,
        timeout=float(provider.timeout_s),
    )


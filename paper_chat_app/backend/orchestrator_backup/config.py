from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover
    yaml = None


@dataclass(frozen=True)
class ProviderConfig:
    name: str
    type: str  
    base_url: str
    api_key_env: str
    models: List[str]
    default_model: Optional[str] = None
    timeout_s: float = 60.0
    base_url_env: Optional[str] = None  

    @property
    def api_key(self) -> Optional[str]:
        return os.getenv(self.api_key_env)

    @property
    def effective_base_url(self) -> str:
        """Resolved base URL: from base_url_env if set and present, else base_url."""
        if self.base_url_env:
            url = os.getenv(self.base_url_env)
            if url:
                return url.rstrip("/")
        return self.base_url.rstrip("/")


@dataclass(frozen=True)
class GatewayConfig:
    token_env: str
    providers: List[ProviderConfig]

    @property
    def token(self) -> Optional[str]:
        return os.getenv(self.token_env)


def _parse_config_obj(obj: Dict[str, Any]) -> GatewayConfig:
    gateway = obj.get("gateway") or {}
    token_env = gateway.get("token_env") or "MCP_GATEWAY_TOKEN"

    providers_obj = obj.get("providers") or []
    providers: List[ProviderConfig] = []
    for p in providers_obj:
        providers.append(
            ProviderConfig(
                name=str(p["name"]),
                type=str(p.get("type", "openai_compatible")),
                base_url=str(p["base_url"]),
                api_key_env=str(p.get("api_key_env", "OPENAI_API_KEY")),
                models=list(p.get("models") or []),
                default_model=p.get("default_model"),
                timeout_s=float(p.get("timeout_s", 60.0)),
                base_url_env=p.get("base_url_env"),
            )
        )
    if not providers:
        raise ValueError("No providers configured. Add at least one provider in config.")

    return GatewayConfig(token_env=token_env, providers=providers)


def load_gateway_config(path: str) -> GatewayConfig:
    with open(path, "r", encoding="utf-8") as f:
        raw = f.read()

    lower = path.lower()
    if lower.endswith((".yaml", ".yml")):
        if yaml is None:
            raise RuntimeError("PyYAML is required to load YAML config. Install PyYAML>=6.0.")
        obj = yaml.safe_load(raw) or {}
    elif lower.endswith(".json"):
        obj = json.loads(raw)
    else:
        if yaml is not None:
            try:
                obj = yaml.safe_load(raw) or {}
            except Exception:
                obj = json.loads(raw)
        else:
            obj = json.loads(raw)

    if not isinstance(obj, dict):
        raise ValueError("Config file must contain an object at the top level.")

    return _parse_config_obj(obj)


def get_provider_for_model(cfg: GatewayConfig, model: str) -> ProviderConfig:
    for p in cfg.providers:
        if model in p.models:
            return p

    for p in cfg.providers:
        if p.default_model:
            return p
    return cfg.providers[0]


def list_all_models(cfg: GatewayConfig) -> List[Dict[str, Any]]:
    """
    Return OpenAI-compatible /models payload list entries.
    """
    out: List[Dict[str, Any]] = []
    for p in cfg.providers:
        for m in p.models:
            out.append(
                {
                    "id": m,
                    "object": "model",
                    "owned_by": p.name,
                }
            )

    seen = set()
    deduped = []
    for item in out:
        mid = item["id"]
        if mid in seen:
            continue
        seen.add(mid)
        deduped.append(item)
    return deduped


def _is_image_model(model_id: str) -> bool:
    """True if this model ID is for image generation (e.g. openai/gpt-image-1.5)."""
    return "image" in model_id.lower()


def _all_models_from_config(cfg: GatewayConfig) -> List[str]:
    """Deduplicated list of all model IDs from all providers."""
    seen: set = set()
    out: List[str] = []
    for p in cfg.providers:
        for m in p.models:
            if m not in seen:
                seen.add(m)
                out.append(m)
    return out


def resolve_model(
    cfg: GatewayConfig,
    preferred: Optional[str],
    use_case: str,
) -> Optional[str]:
    """
    Resolve the effective model from gateway config by return type (use_case).

    - use_case "text" or "chat": prefer a text/chat model (exclude image models).
      Returns preferred if it is in config and not an image model; else default_model
      if not image; else first text model in config.
    - use_case "image": prefer an image-capable model. Returns preferred if in config
      and is image model; else first model whose id contains "image"; also maps
      gpt-image-1.5 -> openai/gpt-image-1.5 when the latter is in config.

    Returns None only when use_case is "image" and no image model is in config.
    """
    all_models = _all_models_from_config(cfg)
    if not all_models:
        return preferred

    if use_case in ("text", "chat"):
        text_models = [m for m in all_models if not _is_image_model(m)]
        if not text_models:
            text_models = all_models
        if preferred and preferred in text_models:
            return preferred
        default = None
        for p in cfg.providers:
            if p.default_model and not _is_image_model(p.default_model) and p.default_model in all_models:
                default = p.default_model
                break
        if default:
            return default
        return text_models[0] if text_models else all_models[0]

    if use_case == "image":
        image_models = [m for m in all_models if _is_image_model(m)]
        if preferred and preferred in all_models and _is_image_model(preferred):
            return preferred
        if preferred == "gpt-image-1.5":
            for m in image_models:
                if "gpt-image" in m:
                    return m
        if image_models:
            return image_models[0]
        return None

    return preferred if preferred in all_models else (all_models[0] if all_models else None)


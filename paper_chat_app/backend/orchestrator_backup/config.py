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


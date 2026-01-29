from __future__ import annotations
from fastapi import Header, HTTPException


def require_bearer_token(
    authorization: str | None,
    expected_token: str | None,
) -> None:
    """
    Enforce a simple gateway auth:
      Authorization: Bearer <token>
    """
    if not expected_token:
        raise HTTPException(
            status_code=500,
            detail="Gateway token not configured. Set MCP_GATEWAY_TOKEN (or configured token_env).",
        )

    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    parts = authorization.split(" ", 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authorization must be Bearer token")

    provided = parts[1].strip()
    if provided != expected_token:
        raise HTTPException(status_code=403, detail="Invalid token")



async def bearer_auth_dependency(
    authorization: str | None = Header(default=None),
) -> str | None:
    # This is filled by the FastAPI app via dependency injection closure.
    return authorization


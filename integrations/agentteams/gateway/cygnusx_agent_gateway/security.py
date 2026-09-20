"""Simple service identity verification for Manager-only Gateway access."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, status

from .config import GatewaySettings


def require_manager(settings: GatewaySettings, identity: str | None, token: str | None) -> str:
    if not identity or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Gateway identity"
        )
    configured_token = settings.identity_secrets().get(identity)
    if configured_token is None or not secrets.compare_digest(configured_token, token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid Gateway identity"
        )
    if identity != "bioops-manager":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Manager identity required"
        )
    return identity

"""Service identity and short-lived, action-scoped approval tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import HTTPException, status

from .config import BridgeSettings
from .models import ApprovalAction
from .worker_tokens import WorkerTokenStore


async def require_identity(
    settings: BridgeSettings,
    token_store: WorkerTokenStore | None,
    x_bridge_identity: str | None,
    x_bridge_token: str | None,
) -> str:
    """Authenticate a Worker service identity without accepting an OmicHub JWT.

    Either the static ``BRIDGE_IDENTITIES`` shared secret (legacy deployments) or a
    valid, unrevoked per-worker token issued via ``/v1/worker-tokens`` passes. A
    worker token binds its identity: the header identity must match the token's.
    """
    if not x_bridge_identity or not x_bridge_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Bridge identity required"
        )
    expected = settings.identity_secrets().get(x_bridge_identity)
    if expected is not None and secrets.compare_digest(expected, x_bridge_token):
        return x_bridge_identity
    if token_store is not None:
        record = await token_store.lookup(x_bridge_token)
        if record is not None:
            if record.revoked_at is not None:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker token revoked"
                )
            if record.expires_at is not None and record.expires_at <= datetime.now(UTC):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED, detail="Worker token expired"
                )
            if record.identity != x_bridge_identity:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Worker token identity mismatch",
                )
            return record.identity
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bridge identity denied")


def require_role(identity: str, *allowed: str) -> None:
    if identity not in allowed:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Identity is not allowed")


class ApprovalSigner:
    def __init__(self, secret: str) -> None:
        self._secret = secret.encode()

    def issue(
        self,
        *,
        case_id: str,
        action: ApprovalAction,
        work_item_id: str | None,
        flow_id: str | None,
        task_id: str | None,
        ttl_seconds: int,
    ) -> tuple[str, str, datetime]:
        expires_at = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        claims = {
            "approval_id": secrets.token_urlsafe(12),
            "case_id": case_id,
            "action": action,
            "work_item_id": work_item_id,
            "flow_id": flow_id,
            "task_id": task_id,
            "exp": int(expires_at.timestamp()),
        }
        payload = _encode(claims)
        signature = hmac.new(self._secret, payload.encode(), hashlib.sha256).digest()
        return f"{payload}.{_encode_bytes(signature)}", claims["approval_id"], expires_at

    def verify(
        self,
        token: str,
        *,
        case_id: str,
        action: ApprovalAction,
        work_item_id: str | None = None,
        flow_id: str | None = None,
        task_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            payload, provided_signature = token.split(".", maxsplit=1)
            signature = _decode_bytes(provided_signature)
            expected = hmac.new(self._secret, payload.encode(), hashlib.sha256).digest()
            claims = json.loads(_decode_bytes(payload))
        except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid approval token"
            ) from exc
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid approval token"
            )
        if claims.get("exp", 0) < int(datetime.now(UTC).timestamp()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Approval token expired"
            )
        expected_values = {"case_id": case_id, "action": action}
        if work_item_id is not None:
            expected_values["work_item_id"] = work_item_id
        if flow_id is not None:
            expected_values["flow_id"] = flow_id
        if task_id is not None:
            expected_values["task_id"] = task_id
        if any(claims.get(key) != value for key, value in expected_values.items()):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Approval scope mismatch"
            )
        return claims


def _encode(value: dict[str, Any]) -> str:
    return _encode_bytes(json.dumps(value, separators=(",", ":"), sort_keys=True).encode())


def _encode_bytes(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode_bytes(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

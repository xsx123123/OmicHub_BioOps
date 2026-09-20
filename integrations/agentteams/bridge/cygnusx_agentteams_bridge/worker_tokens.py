"""Revocable per-worker access tokens; the Bridge stores hashes, never raw tokens."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import HTTPException, status

from .models import WorkerTokenRecord
from .shared_state import RedisStateBackend


class WorkerTokenStore:
    """Dual-mode (Redis snapshot / local JSON) store for revocable Worker tokens."""

    def __init__(
        self,
        path: str,
        state_store_url: str = "",
        state_store_key_prefix: str = "cygnusx:agentteams:worker-tokens",
    ) -> None:
        self._path = Path(path)
        self._tokens = self._load()
        self._shared_state = (
            RedisStateBackend(state_store_url, state_store_key_prefix) if state_store_url else None
        )
        self._local_lock = asyncio.Lock()

    @asynccontextmanager
    async def _synchronized(self) -> AsyncIterator[None]:
        async with self._local_lock:
            if self._shared_state is None:
                yield
                return
            async with self._shared_state.lock():
                await self._reload_shared_locked()
                yield

    async def _reload_shared_locked(self) -> None:
        if self._shared_state is None:
            return
        raw = await self._shared_state.get_snapshot()
        if not raw:
            self._tokens = {}
            return
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Bridge shared WorkerTokenStore snapshot is invalid") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("Bridge shared WorkerTokenStore snapshot must be an object")
        self._tokens = {
            token_id: WorkerTokenRecord.model_validate(value)
            for token_id, value in decoded.items()
            if isinstance(token_id, str) and isinstance(value, dict)
        }

    async def aclose(self) -> None:
        if self._shared_state is not None:
            await self._shared_state.aclose()

    def _load(self) -> dict[str, WorkerTokenRecord]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        tokens: dict[str, WorkerTokenRecord] = {}
        for token_id, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            try:
                tokens[str(token_id)] = WorkerTokenRecord.model_validate(payload)
            except ValueError:
                continue
        return tokens

    async def issue(
        self,
        *,
        identity: str,
        ttl_seconds: int | None = None,
        note: str = "",
    ) -> tuple[str, WorkerTokenRecord]:
        """Create a token; the raw value is returned once and only its hash persists."""
        token = f"omw_{secrets.token_urlsafe(32)}"
        now = datetime.now(UTC)
        record = WorkerTokenRecord(
            token_id=secrets.token_urlsafe(12),
            token_hash=self._hash(token),
            identity=identity,
            note=note,
            created_at=now,
            expires_at=(now + timedelta(seconds=ttl_seconds)) if ttl_seconds else None,
        )
        async with self._synchronized():
            self._tokens[record.token_id] = record
            await self._persist()
        return token, record

    async def revoke(self, token_id: str) -> WorkerTokenRecord:
        async with self._synchronized():
            record = self._tokens.get(token_id)
            if record is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Worker token not found"
                )
            if record.revoked_at is None:
                record.revoked_at = datetime.now(UTC)
                await self._persist()
            return record

    async def list(self) -> list[WorkerTokenRecord]:
        async with self._synchronized():
            return sorted(self._tokens.values(), key=lambda record: record.created_at, reverse=True)

    async def lookup(self, token: str) -> WorkerTokenRecord | None:
        """Return the record whose hash matches, regardless of revocation/expiry state."""
        token_hash = self._hash(token)
        async with self._synchronized():
            for record in self._tokens.values():
                if secrets.compare_digest(record.token_hash, token_hash):
                    return record
        return None

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    async def _persist(self) -> None:
        encoded = json.dumps(
            {
                token_id: record.model_dump(mode="json")
                for token_id, record in self._tokens.items()
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if self._shared_state is not None:
            await self._shared_state.set_snapshot(encoded)
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.{os.getpid()}.tmp")
        try:
            temporary.write_text(encoded, encoding="utf-8")
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)

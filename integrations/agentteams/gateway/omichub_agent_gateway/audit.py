"""Append-only JSONL audit event writer compatible with the Bridge envelope."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4


class AuditStore:
    def __init__(self, path: str) -> None:
        self._path = Path(path)
        self._lock = asyncio.Lock()

    async def record(
        self, *, case_id: str, actor: str, event_type: str, payload: dict[str, object]
    ) -> tuple[str, datetime]:
        event_id = str(uuid4())
        recorded_at = datetime.now(UTC)
        event = {
            "event_id": event_id,
            "recorded_at": recorded_at.isoformat(),
            "case_id": case_id,
            "actor": actor,
            "event_type": event_type,
            "payload": payload,
        }
        encoded = json.dumps(event, ensure_ascii=False, separators=(",", ":")) + "\n"
        async with self._lock:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            _append(self._path, encoded)
        return event_id, recorded_at


def _append(path: Path, value: str) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(value)

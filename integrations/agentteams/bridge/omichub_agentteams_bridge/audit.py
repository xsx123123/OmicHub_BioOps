"""Bridge-owned append-only JSONL audit index, intentionally separate from OmicHub data."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from .shared_state import RedisStateBackend


def json_default(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class AuditStore:
    def __init__(
        self,
        path: str,
        state_store_url: str = "",
        state_store_key_prefix: str = "omichub:agentteams:audit",
        on_event: Any = None,
    ) -> None:
        self._path = Path(path)
        self._idempotency: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._on_event = on_event
        self._shared_state = (
            RedisStateBackend(state_store_url, state_store_key_prefix) if state_store_url else None
        )
        if self._shared_state is None:
            self._load()
        from asyncio import Lock

        self._lock = Lock()

    @property
    def _event_stream_key(self) -> str:
        if self._shared_state is None:
            raise RuntimeError("Redis audit stream is not configured")
        return f"{self._shared_state.data_key}:events"

    @property
    def _receipt_key_prefix(self) -> str:
        if self._shared_state is None:
            raise RuntimeError("Redis audit receipts are not configured")
        return f"{self._shared_state.data_key}:receipt:"

    async def aclose(self) -> None:
        if self._shared_state is not None:
            await self._shared_state.aclose()

    async def _shared_events(self, case_id: str | None = None) -> list[dict[str, Any]]:
        if self._shared_state is None:
            raise RuntimeError("Redis audit stream is not configured")
        records = await self._shared_state.client.xrange(self._event_stream_key, min="-", max="+")
        events: list[dict[str, Any]] = []
        for _, fields in records:
            encoded = fields.get("event")
            if not isinstance(encoded, str):
                continue
            try:
                event = json.loads(encoded)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or (case_id is not None and event.get("case_id") != case_id):
                continue
            events.append(event)
        return events

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            lines = self._path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, dict) or not isinstance(event.get("case_id"), str):
                continue
            self._events.setdefault(event["case_id"], []).append(event)
            payload = event.get("payload")
            if event.get("event_type") != "omic_task.submitted" or not isinstance(payload, dict):
                continue
            idempotency_key = payload.get("idempotency_key")
            receipt = payload.get("receipt")
            if isinstance(idempotency_key, str) and isinstance(receipt, dict):
                self._idempotency[idempotency_key] = receipt

    async def get_receipt(self, idempotency_key: str) -> dict[str, Any] | None:
        if self._shared_state is not None:
            encoded = await self._shared_state.client.get(f"{self._receipt_key_prefix}{idempotency_key}")
            if not isinstance(encoded, str):
                return None
            try:
                receipt = json.loads(encoded)
            except json.JSONDecodeError:
                return None
            return receipt if isinstance(receipt, dict) else None
        async with self._lock:
            return self._idempotency.get(idempotency_key)

    async def save_receipt(self, idempotency_key: str, receipt: dict[str, Any]) -> None:
        if self._shared_state is not None:
            await self._shared_state.client.set(
                f"{self._receipt_key_prefix}{idempotency_key}",
                json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), default=json_default),
            )
            return
        async with self._lock:
            self._idempotency[idempotency_key] = receipt

    async def record(
        self, *, case_id: str, actor: str, event_type: str, payload: dict[str, Any]
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
        encoded = json.dumps(
            event,
            ensure_ascii=False,
            separators=(",", ":"),
            default=json_default,
        ) + "\n"
        if self._shared_state is not None:
            await self._shared_state.client.xadd(self._event_stream_key, {"event": encoded.rstrip("\n")})
            self._notify(event)
            return event_id, recorded_at
        async with self._lock:
            self._events.setdefault(case_id, []).append(event)
            self._path.parent.mkdir(parents=True, exist_ok=True)
            _append(self._path, encoded)
        self._notify(event)
        return event_id, recorded_at

    def _notify(self, event: dict[str, Any]) -> None:
        """Invoke the append hook (room mirror); hook failures never break auditing."""
        if self._on_event is None:
            return
        try:
            self._on_event(event)
        except Exception:
            logging.getLogger(__name__).warning(
                "audit append hook failed for case %s", event.get("case_id"), exc_info=True
            )

    async def all_events(self) -> list[dict[str, Any]]:
        """Return every recorded event (one-shot rebuild source for the room mirror)."""
        if self._shared_state is not None:
            return await self._shared_events()
        async with self._lock:
            return [event for events in self._events.values() for event in events]

    async def list_events(self, case_id: str) -> list[dict[str, Any]]:
        if self._shared_state is not None:
            return await self._shared_events(case_id)
        async with self._lock:
            return [*self._events.get(case_id, [])]

    async def delete_events(self, case_id: str) -> int:
        """Remove all audit events of a Case; used by Case GC (trims the Redis stream too)."""
        if self._shared_state is not None:
            records = await self._shared_state.client.xrange(self._event_stream_key, min="-", max="+")
            removed = 0
            for record_id, fields in records:
                encoded = fields.get("event")
                if not isinstance(encoded, str):
                    continue
                try:
                    event = json.loads(encoded)
                except json.JSONDecodeError:
                    continue
                if isinstance(event, dict) and event.get("case_id") == case_id:
                    await self._shared_state.client.xdel(self._event_stream_key, record_id)
                    removed += 1
            return removed
        async with self._lock:
            events = self._events.pop(case_id, [])
            if not events:
                return 0
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("w", encoding="utf-8") as file:
                for case_events in self._events.values():
                    for event in case_events:
                        file.write(
                            json.dumps(
                                event,
                                ensure_ascii=False,
                                separators=(",", ":"),
                                default=json_default,
                            )
                            + "\n"
                        )
            return len(events)

    async def metrics(self) -> dict[str, int]:
        if self._shared_state is not None:
            all_events = [
                event for event in await self._shared_events() if event.get("case_id") != "__bridge_health__"
            ]
            return _event_metrics(all_events)
        async with self._lock:
            all_events = [
                event
                for case_id, events in self._events.items()
                if case_id != "__bridge_health__"
                for event in events
            ]
            return _event_metrics(all_events)

    async def worker_heartbeats(self, workers: set[str]) -> dict[str, datetime | None]:
        """Return the latest inbox-poll event for each Worker identity."""
        if self._shared_state is not None:
            return _worker_heartbeats(await self._shared_events("__bridge_health__"), workers)
        async with self._lock:
            return _worker_heartbeats(self._events.get("__bridge_health__", []), workers)


def _append(path: Path, value: str) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(value)


def _event_metrics(events: list[dict[str, Any]]) -> dict[str, int]:
    by_case: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        case_id = event.get("case_id")
        if isinstance(case_id, str):
            by_case.setdefault(case_id, []).append(event)
    terminal_types = {"case.closed", "case.cancelled"}
    end_to_end_ms: list[int] = []
    approval_wait_ms: list[int] = []
    stale_cutoff = datetime.now(UTC) - timedelta(hours=2)
    stale_nonterminal_case_count = 0
    for case_events in by_case.values():
        ordered = sorted(case_events, key=lambda item: str(item.get("recorded_at") or ""))
        created_at = _event_time(next((item for item in ordered if item.get("event_type") == "case.created"), None))
        terminal_at = _event_time(
            next((item for item in reversed(ordered) if item.get("event_type") in terminal_types), None)
        )
        if created_at and terminal_at:
            end_to_end_ms.append(max(0, int((terminal_at - created_at).total_seconds() * 1000)))
        frozen_at = _event_time(
            next((item for item in ordered if item.get("event_type") == "planning.frozen"), None)
        )
        approved_at = _event_time(
            next(
                (
                    item
                    for item in ordered
                    if item.get("event_type") in {"general_plan.approved", "approval.resolved"}
                ),
                None,
            )
        )
        if frozen_at and approved_at and approved_at >= frozen_at:
            approval_wait_ms.append(int((approved_at - frozen_at).total_seconds() * 1000))
        last_at = _event_time(ordered[-1] if ordered else None)
        if terminal_at is None and last_at and last_at < stale_cutoff:
            stale_nonterminal_case_count += 1
    cancelled_case_count = sum(
        event.get("event_type") == "case.cancelled" for event in events
    )
    case_count = len(by_case)
    return {
        "case_count": case_count,
        "event_count": len(events),
        "submitted_task_count": sum(
            event.get("event_type") == "omic_task.submitted" for event in events
        ),
        "quality_decision_count": sum(
            event.get("event_type") == "quality.decision" for event in events
        ),
        "closed_case_count": sum(event.get("event_type") == "case.closed" for event in events),
        "cancelled_case_count": cancelled_case_count,
        "case_cancel_rate_bps": int(cancelled_case_count * 10_000 / case_count) if case_count else 0,
        "work_item_failure_count": sum(
            event.get("event_type") in {"skill.failed", "analysis_submission.failed"}
            for event in events
        ),
        "work_item_retry_count": sum(
            event.get("event_type") in {"case.retry_queued", "work_item.retry_scheduled"}
            for event in events
        ),
        "stale_nonterminal_case_count": stale_nonterminal_case_count,
        "case_end_to_end_p95_ms": _p95(end_to_end_ms),
        "approval_wait_p95_ms": _p95(approval_wait_ms),
    }


def _event_time(event: dict[str, Any] | None) -> datetime | None:
    if not event:
        return None
    try:
        value = datetime.fromisoformat(str(event.get("recorded_at") or ""))
    except ValueError:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, (95 * len(ordered) + 99) // 100 - 1)]


def _worker_heartbeats(
    events: list[dict[str, Any]], workers: set[str]
) -> dict[str, datetime | None]:
    latest = {worker: None for worker in workers}
    for event in events:
        actor = event.get("actor")
        if actor not in latest or event.get("event_type") != "worker.inbox_polled":
            continue
        try:
            recorded_at = datetime.fromisoformat(str(event["recorded_at"]))
        except (KeyError, TypeError, ValueError):
            continue
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=UTC)
        if latest[actor] is None or recorded_at > latest[actor]:
            latest[actor] = recorded_at
    return latest

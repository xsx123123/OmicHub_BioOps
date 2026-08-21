"""Bridge-owned append-only audit index, intentionally separate from OmicHub data.

持久化分级口径（MinIO 模式下生效）：
- business 事件（room.user_message / room.agent_message / case.* / approval.* 等）
  进 MinIO 持久事件流（事实源）；
- stream 事件（room.agent_stream，见 STREAM_EVENT_TYPES）：打字机增量，
  不进 MinIO 持久流（避免每 24 字符一次整卷读-改-写的写放大），
  走 Redis 热缓存 + 内存索引 + _notify，SSE 轮询读取时合并进事件页；
  历史重放以 room.agent_message 终态为准。与 operational 的区别：stream
  事件有在线消费方（SSE 打字机契约），必须可被读到，不只是计数。
- operational 事件（心跳/轮询/typing，见 OPERATIONAL_EVENT_TYPES）不进持久流，
  只做 Redis INCR 指标计数（无 Redis 时进程内计数）。
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

from .minio_store import MinioBridgeStorage, json_default
from .models import is_room_namespace_case_id
from .shared_state import RedisStateBackend

# 与 room_mirror.TRANSIENT_EVENT_TYPES 同口径（room.typing / worker.inbox_polled），
# 另含 worker.heartbeat（work item 租约心跳，每 Worker 数秒一条，与
# worker.inbox_polled 同级噪音）。仅在 MinIO 模式下拦截：历史 Redis/本地模式的
# 行为保持不变。
OPERATIONAL_EVENT_TYPES = frozenset({"worker.inbox_polled", "worker.heartbeat", "room.typing"})

# 瞬态业务事件（手册阶段 0 修复 4）：有在线消费方（房间页 SSE 打字机），
# 必须可读但不进 MinIO 持久流；仅 MinIO 模式拦截，Redis/本地模式行为不变。
STREAM_EVENT_TYPES = frozenset({"room.agent_stream"})


class AuditStore:
    def __init__(
        self,
        path: str,
        state_store_url: str = "",
        state_store_key_prefix: str = "omichub:agentteams:audit",
        on_event: Any = None,
        *,
        minio_storage: MinioBridgeStorage | None = None,
    ) -> None:
        self._path = Path(path)
        self._minio = minio_storage
        self._idempotency: dict[str, dict[str, Any]] = {}
        self._events: dict[str, list[dict[str, Any]]] = {}
        self._operational_counts: dict[str, int] = {}
        self._on_event = on_event
        self._shared_state = (
            RedisStateBackend(state_store_url, state_store_key_prefix) if state_store_url else None
        )
        if self._minio is not None:
            # MinIO 是事实源：启动时全量恢复（任何读取/解析失败直接抛错，拒绝启动）。
            self._load_minio()
        elif self._shared_state is None:
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

    def _ingest(self, event: dict[str, Any]) -> None:
        """Index one event into the in-memory mirror (and the idempotency receipts)."""
        case_id = event.get("case_id")
        if not isinstance(case_id, str):
            return
        self._events.setdefault(case_id, []).append(event)
        payload = event.get("payload")
        if event.get("event_type") != "omic_task.submitted" or not isinstance(payload, dict):
            return
        idempotency_key = payload.get("idempotency_key")
        receipt = payload.get("receipt")
        if isinstance(idempotency_key, str) and isinstance(receipt, dict):
            self._idempotency[idempotency_key] = receipt

    def _load_minio(self) -> None:
        try:
            # 幂等 receipt 直读独立对象（手册阶段 2 修复 2）：不依赖事件流
            # 全量重放的完成度即可恢复幂等索引；事件重放（下方 _ingest）
            # 会覆盖同 key receipt，内容与对象一致。
            self._idempotency.update(self._minio.read_receipts())  # type: ignore[union-attr]
            for case_id in self._minio.list_case_ids():  # type: ignore[union-attr]
                for event in self._minio.read_events(case_id):  # type: ignore[union-attr]
                    self._ingest(event)
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError("Bridge AuditStore MinIO recovery failed") from exc

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
            self._ingest(event)

    async def get_receipt(self, idempotency_key: str) -> dict[str, Any] | None:
        if self._minio is not None:
            # MinIO 是事实源：内存索引（启动时已从 receipts/ 对象 + 事件流重建）
            # 未命中时直读对象，覆盖跨副本/索引缺失窗口。
            async with self._lock:
                cached = self._idempotency.get(idempotency_key)
            if cached is not None:
                return cached
            receipt = self._minio.read_receipt(idempotency_key)
            if receipt is not None:
                async with self._lock:
                    self._idempotency[idempotency_key] = receipt
            return receipt
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
        if self._minio is not None:
            # 写顺序硬约束（与 record 同口径）：MinIO 落盘成功 → 内存索引 →
            # Redis 热缓存（失败仅告警）。MinIO 写失败即操作失败，直接抛出。
            self._minio.write_receipt(idempotency_key, receipt)
            async with self._lock:
                self._idempotency[idempotency_key] = receipt
            if self._shared_state is not None:
                try:
                    await self._shared_state.client.set(
                        f"{self._receipt_key_prefix}{idempotency_key}",
                        json.dumps(receipt, ensure_ascii=False, separators=(",", ":"), default=json_default),
                    )
                except Exception:
                    logging.getLogger(__name__).warning(
                        "Redis receipt hot-cache update failed after MinIO persist; "
                        "MinIO remains the source of truth",
                        exc_info=True,
                    )
            return
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
        if self._minio is not None:
            if event_type in OPERATIONAL_EVENT_TYPES:
                # operational 事件（心跳/轮询/typing）不进 MinIO 持久流，
                # 只做指标计数并保持调用方契约（照常返回 event_id/recorded_at）。
                await self._count_operational(event_type)
                return event_id, recorded_at
            if event_type in STREAM_EVENT_TYPES:
                # 瞬态业务事件（room.agent_stream 打字机增量）：不写 MinIO，
                # 消除每 24 字符一次整卷读-改-写的写放大；走 Redis 热缓存 +
                # 内存索引 + 通知钩子，SSE 轮询经 list_events 合并读回。
                # Redis 失败降级为进程内索引（与 business 路径热缓存口径一致）。
                if self._shared_state is not None:
                    try:
                        await self._shared_state.client.xadd(
                            self._event_stream_key, {"event": encoded.rstrip("\n")}
                        )
                    except Exception:
                        logging.getLogger(__name__).warning(
                            "Redis transient stream write failed; in-memory index only",
                            exc_info=True,
                        )
                self._ingest(event)
                self._notify(event)
                return event_id, recorded_at
            # 写入顺序硬约束：MinIO 落盘成功 → Redis 热缓存 → 内存索引 → _notify
            # （room mirror 等副作用）。MinIO 写失败即操作失败，直接抛出，
            # 禁止"先缓存后补写"，Redis/内存不会出现幽灵成功态。
            await self._minio.append_event(case_id, event)
            if self._shared_state is not None:
                try:
                    await self._shared_state.client.xadd(
                        self._event_stream_key, {"event": encoded.rstrip("\n")}
                    )
                except Exception:
                    logging.getLogger(__name__).warning(
                        "Redis audit hot-cache update failed after MinIO persist; "
                        "MinIO remains the source of truth",
                        exc_info=True,
                    )
            self._ingest(event)
            self._notify(event)
            return event_id, recorded_at
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

    async def _count_operational(self, event_type: str) -> None:
        """INCR the operational-event metric (<prefix>:metrics:events:{event_type})."""
        if self._shared_state is not None:
            try:
                await self._shared_state.client.incr(
                    f"{self._shared_state.key_prefix}:metrics:events:{event_type}"
                )
                return
            except Exception:
                logging.getLogger(__name__).warning(
                    "Redis operational-event counter failed for %s", event_type, exc_info=True
                )
        async with self._lock:
            self._operational_counts[event_type] = self._operational_counts.get(event_type, 0) + 1

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
        if self._minio is not None:
            # 读路径直接走 MinIO 事实源，跨副本不会出现内存/缓存陈旧。
            return [
                event
                for case_id in self._minio.list_case_ids()
                for event in self._minio.read_events(case_id)
            ]
        if self._shared_state is not None:
            return await self._shared_events()
        async with self._lock:
            return [event for events in self._events.values() for event in events]

    async def list_events(self, case_id: str) -> list[dict[str, Any]]:
        if self._minio is not None:
            persisted = self._minio.read_events(case_id)
            # 合并瞬态 stream 事件（room.agent_stream）：MinIO 事实源 + Redis/内存
            # 瞬态补充，按 recorded_at 排序；以 event_id 去重（升级前写入 MinIO 的
            # 历史 agent_stream 与 Redis 热缓存可能同时存在）。
            transient = await self._stream_events(case_id)
            if not transient:
                return persisted
            seen = {event.get("event_id") for event in persisted}
            merged = [
                *persisted,
                *(event for event in transient if event.get("event_id") not in seen),
            ]
            merged.sort(key=lambda event: str(event.get("recorded_at") or ""))
            return merged
        if self._shared_state is not None:
            return await self._shared_events(case_id)
        async with self._lock:
            return [*self._events.get(case_id, [])]

    async def _stream_events(self, case_id: str) -> list[dict[str, Any]]:
        """Transient stream events of a Case: Redis hot cache first, in-memory fallback."""
        if self._shared_state is not None:
            try:
                shared = await self._shared_events(case_id)
                return [
                    event for event in shared if event.get("event_type") in STREAM_EVENT_TYPES
                ]
            except Exception:
                logging.getLogger(__name__).warning(
                    "Redis transient stream read failed for case %s; using in-memory index",
                    case_id,
                    exc_info=True,
                )
        async with self._lock:
            return [
                event
                for event in self._events.get(case_id, [])
                if event.get("event_type") in STREAM_EVENT_TYPES
            ]

    async def delete_events(self, case_id: str) -> int:
        """Remove all audit events of a Case; used by Case GC (trims the Redis stream too)."""
        if self._minio is not None:
            # 对象删除语义：移除该 Case 的全部事件卷对象。
            removed = self._minio.delete_event_objects(case_id)
            async with self._lock:
                self._events.pop(case_id, None)
            if self._shared_state is not None:
                await self._trim_shared_stream(case_id)
            return removed
        if self._shared_state is not None:
            return await self._trim_shared_stream(case_id)
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

    async def _trim_shared_stream(self, case_id: str) -> int:
        """Delete one Case's entries from the Redis hot-cache stream; returns the count."""
        if self._shared_state is None:
            return 0
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

    async def metrics(self) -> dict[str, int]:
        # 房间命名空间事件流（room-<room_id>）不是工单，与 __bridge_health__ 一样
        # 不计入 Case 运营指标；但其事件量单独按命名空间展平暴露（C1 观测项，
        # 见 _room_event_metrics）。operational 事件（心跳/轮询/typing）不进持久流，
        # 其聚合计数以 operational_events__<event_type> 展平键随指标暴露，
        # 供监控面板消费（统一审计总线 Part 3.4 口径）。
        if self._minio is not None:
            all_events = [
                event
                for case_id in self._minio.list_case_ids()
                if case_id != "__bridge_health__" and not is_room_namespace_case_id(case_id)
                for event in self._minio.read_events(case_id)
            ]
            # 房间事件量只读内存索引（启动恢复与 record 路径已填充），
            # 不为指标新增 MinIO 全量扫描。
            async with self._lock:
                room_events = [
                    event
                    for case_id, events in self._events.items()
                    if is_room_namespace_case_id(case_id)
                    for event in events
                ]
            return await self._with_operational_metrics(
                {**_event_metrics(all_events), **_room_event_metrics(room_events)}
            )
        if self._shared_state is not None:
            shared_events = await self._shared_events()
            all_events = [
                event
                for event in shared_events
                if event.get("case_id") != "__bridge_health__"
                and not is_room_namespace_case_id(str(event.get("case_id") or ""))
            ]
            room_events = [
                event
                for event in shared_events
                if is_room_namespace_case_id(str(event.get("case_id") or ""))
            ]
            return await self._with_operational_metrics(
                {**_event_metrics(all_events), **_room_event_metrics(room_events)}
            )
        async with self._lock:
            all_events = [
                event
                for case_id, events in self._events.items()
                if case_id != "__bridge_health__" and not is_room_namespace_case_id(case_id)
                for event in events
            ]
            room_events = [
                event
                for case_id, events in self._events.items()
                if is_room_namespace_case_id(case_id)
                for event in events
            ]
            return {**_event_metrics(all_events), **_room_event_metrics(room_events)}

    async def _with_operational_metrics(self, metrics: dict[str, int]) -> dict[str, int]:
        """附加 operational 事件聚合计数（Redis 计数 key + 进程内兜底计数合并）。"""
        counts: dict[str, int] = {}
        if self._shared_state is not None:
            prefix = f"{self._shared_state.key_prefix}:metrics:events:"
            try:
                async for key in self._shared_state.client.scan_iter(match=f"{prefix}*"):
                    event_type = str(key)[len(prefix):]
                    if not event_type:
                        continue
                    value = await self._shared_state.client.get(key)
                    counts[event_type] = int(value or 0)
            except Exception:
                logging.getLogger(__name__).warning(
                    "Redis operational-event metric read failed", exc_info=True
                )
        async with self._lock:
            for event_type, count in self._operational_counts.items():
                counts[event_type] = counts.get(event_type, 0) + count
        for event_type, count in counts.items():
            metrics[f"operational_events__{event_type}"] = count
        return metrics

    async def worker_heartbeats(self, workers: set[str]) -> dict[str, datetime | None]:
        """Return the latest inbox-poll event for each Worker identity."""
        if self._minio is not None:
            return _worker_heartbeats(self._minio.read_events("__bridge_health__"), workers)
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
    room_provision_success_count = sum(event.get("event_type") == "room.created" for event in events)
    room_provision_failure_count = sum(
        event.get("event_type") == "room.provisioning_failed" for event in events
    )
    room_provision_attempt_count = room_provision_success_count + room_provision_failure_count
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
        "room_provision_success_count": room_provision_success_count,
        "room_provision_failure_count": room_provision_failure_count,
        "room_provision_success_rate_bps": (
            int(room_provision_success_count * 10_000 / room_provision_attempt_count)
            if room_provision_attempt_count
            else 0
        ),
    }


def _room_event_metrics(events: list[dict[str, Any]]) -> dict[str, int]:
    """房间命名空间（room-<id>）事件量指标：按命名空间展平，business 与瞬态分开。

    C1 观测项（闲聊数据进事实源）：房间事件流与 Case 事件一样持久化，
    需要按房间暴露事件量供容量监控与 GC/归档决策消费。数据只来自内存索引
    或已取出的共享事件清单，不为指标新增 MinIO 全量扫描。operational 事件
    （心跳/轮询/typing）已由 operational_events__<event_type> 键覆盖，此处不计。
    """
    business: dict[str, int] = {}
    stream: dict[str, int] = {}
    for event in events:
        case_id = str(event.get("case_id") or "")
        if not case_id:
            continue
        event_type = str(event.get("event_type") or "")
        if event_type in OPERATIONAL_EVENT_TYPES:
            continue
        if event_type in STREAM_EVENT_TYPES:
            stream[case_id] = stream.get(case_id, 0) + 1
        else:
            business[case_id] = business.get(case_id, 0) + 1
    room_ids = sorted(set(business) | set(stream))
    metrics: dict[str, int] = {"room_namespace_count": len(room_ids)}
    for case_id in room_ids:
        metrics[f"room_events__{case_id}"] = business.get(case_id, 0)
        metrics[f"room_stream_events__{case_id}"] = stream.get(case_id, 0)
    return metrics


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

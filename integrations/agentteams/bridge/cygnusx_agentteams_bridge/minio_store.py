"""MinIO persistence adapter for the AgentTeams Bridge.

设计口径（docs/info/26.8.21/协作室架构升级方案-MinIO持久化与Case解耦及L4前置收尾.md Part 1）：
MinIO 是事实源，Redis 只是热缓存/分布式锁，本地 JSON 文件在本模式下废除，
Bridge 容器重建后零状态损失。

对象布局（bucket 默认 ``agentteams``）：

    cases/{case_id}/events/audit.jsonl            # 事件流首卷
    cases/{case_id}/events/audit-YYYYMMDD.jsonl   # 单对象超阈值后按天分卷（-N 防同日冲突）
    cases/{case_id}/snapshot.json                 # 状态快照（envelope 内嵌 last_event_id）

S3 没有原生 append：``append_event`` 用读-改-写实现追加语义，并以 per-case
asyncio 锁串行化同一 Case 的写入。Bridge 审计事件体量小（每事件一行 JSON），
读-改-写的代价可接受；换来的是单对象自包含、恢复时无需多对象合并排序之外
的任何协调。任何读/写/解析失败都直接抛错（fail fast），绝不静默降级。
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import json
import logging
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

logger = logging.getLogger(__name__)

_DEFAULT_MAX_EVENT_OBJECT_BYTES = 50 * 1024 * 1024


def json_default(value: Any) -> Any:
    """JSON serializer fallback shared by audit/minio paths (datetime/Path/BaseModel)."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def _is_no_such_key(exc: Exception) -> bool:
    """Match MinIO S3Error NoSuchKey and the test fake's NoSuchKey without importing minio."""
    return exc.__class__.__name__ == "NoSuchKey" or getattr(exc, "code", None) == "NoSuchKey"


class MinioBridgeStorage:
    """MinIO-backed persistence for Case snapshots and per-case audit event streams.

    ``client`` 可注入（测试用进程内 fake，接口与 ``minio.Minio`` 的
    put_object/get_object/list_objects/remove_object/bucket_exists 子集一致）；
    未注入时用与主后端相同的 ``minio`` SDK 按 endpoint/凭证构造。
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str = "agentteams",
        secure: bool = False,
        *,
        client: Any | None = None,
        max_event_object_bytes: int = _DEFAULT_MAX_EVENT_OBJECT_BYTES,
    ) -> None:
        self._bucket = bucket
        self._max_event_object_bytes = max_event_object_bytes
        self._case_locks: dict[str, asyncio.Lock] = {}
        self._last_event_ids: dict[str, str] = {}
        self._last_write_latency_ms: int | None = None
        if client is not None:
            self._client = client
            return
        from urllib.parse import urlparse

        try:
            from minio import Minio
        except ImportError as exc:  # pragma: no cover - deployment dependency guard
            raise RuntimeError("MinIO persistence requires the minio package") from exc
        parsed = urlparse(endpoint if "://" in endpoint else f"http://{endpoint}")
        self._client = Minio(
            parsed.netloc or parsed.path,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure or parsed.scheme == "https",
        )

    @classmethod
    def from_settings(cls, settings: Any) -> MinioBridgeStorage | None:
        """Build the adapter from BridgeSettings; ``None`` when MinIO is not configured."""
        endpoint = str(getattr(settings, "minio_endpoint", "") or "").strip()
        if not endpoint:
            return None
        return cls(
            endpoint,
            str(getattr(settings, "minio_access_key", "") or ""),
            str(getattr(settings, "minio_secret_key", "") or ""),
            str(getattr(settings, "minio_bucket", "") or "agentteams"),
            bool(getattr(settings, "minio_secure", False)),
            max_event_object_bytes=int(
                getattr(settings, "minio_event_object_max_bytes", 0)
                or _DEFAULT_MAX_EVENT_OBJECT_BYTES
            ),
        )

    # ------------------------------------------------------------------
    # key layout
    # ------------------------------------------------------------------
    @staticmethod
    def case_prefix(case_id: str) -> str:
        return f"cases/{case_id}/"

    @classmethod
    def events_prefix(cls, case_id: str) -> str:
        return f"{cls.case_prefix(case_id)}events/"

    @classmethod
    def snapshot_key(cls, case_id: str) -> str:
        return f"{cls.case_prefix(case_id)}snapshot.json"

    # 幂等 receipt 独立对象（手册阶段 2 修复 2）：不放在 cases/ 前缀下，
    # Case GC 的 delete_case_objects 不会清掉它——删除 Case 后相同
    # idempotency_key 的重试仍应命中原 receipt。
    @classmethod
    def receipt_key(cls, idempotency_key: str) -> str:
        return f"receipts/{idempotency_key}.json"

    # ------------------------------------------------------------------
    # sync client primitives (minio SDK is synchronous, same as the main backend)
    # ------------------------------------------------------------------
    def _get(self, key: str) -> bytes | None:
        response = None
        try:
            response = self._client.get_object(self._bucket, key)
            return response.read()
        except Exception as exc:
            if _is_no_such_key(exc):
                return None
            raise RuntimeError(f"MinIO read failed for object {key}") from exc
        finally:
            if response is not None:
                response.close()
                response.release_conn()

    def _put(self, key: str, data: bytes) -> None:
        started = time.perf_counter()
        try:
            self._client.put_object(
                self._bucket,
                key,
                io.BytesIO(data),
                length=len(data),
                content_type="application/json",
            )
        except Exception as exc:
            raise RuntimeError(f"MinIO write failed for object {key}") from exc
        self._last_write_latency_ms = int((time.perf_counter() - started) * 1000)

    def _list_keys(self, prefix: str) -> list[str]:
        try:
            objects = self._client.list_objects(self._bucket, prefix=prefix, recursive=True)
            return sorted(str(item.object_name) for item in objects)
        except Exception as exc:
            raise RuntimeError(f"MinIO list failed for prefix {prefix}") from exc

    def _remove(self, key: str) -> None:
        try:
            self._client.remove_object(self._bucket, key)
        except Exception as exc:
            raise RuntimeError(f"MinIO delete failed for object {key}") from exc

    # ------------------------------------------------------------------
    # event stream (append via read-modify-write with per-case asyncio lock)
    # ------------------------------------------------------------------
    def _event_volume_keys(self, case_id: str) -> list[str]:
        keys = [
            key
            for key in self._list_keys(self.events_prefix(case_id))
            if key.endswith(".jsonl")
        ]
        # audit.jsonl 是首卷，其余按天分卷字典序即时间序（audit- 比 audit. 字典序小，
        # 所以首卷必须显式排在最前）。
        return sorted(keys, key=lambda key: (0 if key.endswith("/audit.jsonl") else 1, key))

    def _next_volume_key(self, case_id: str, existing: list[str]) -> str:
        day = datetime.now(UTC).strftime("%Y%m%d")
        base = f"{self.events_prefix(case_id)}audit-{day}"
        candidate = f"{base}.jsonl"
        counter = 2
        while candidate in existing:
            candidate = f"{base}-{counter}.jsonl"
            counter += 1
        return candidate

    async def append_event(self, case_id: str, event: dict[str, Any]) -> None:
        """Append one audit event; raises on any MinIO failure (fail fast)."""
        line = (
            json.dumps(event, ensure_ascii=False, separators=(",", ":"), default=json_default)
            + "\n"
        ).encode("utf-8")
        lock = self._case_locks.setdefault(case_id, asyncio.Lock())
        async with lock:
            volumes = self._event_volume_keys(case_id)
            tail = volumes[-1] if volumes else f"{self.events_prefix(case_id)}audit.jsonl"
            existing = self._get(tail) or b""
            if existing and len(existing) + len(line) > self._max_event_object_bytes:
                tail = self._next_volume_key(case_id, volumes)
                existing = b""
            self._put(tail, existing + line)
            event_id = event.get("event_id")
            if isinstance(event_id, str) and event_id:
                self._last_event_ids[case_id] = event_id

    def read_events(self, case_id: str) -> list[dict[str, Any]]:
        """Read the full event stream in order; any corruption raises (fail fast)."""
        events: list[dict[str, Any]] = []
        for key in self._event_volume_keys(case_id):
            data = self._get(key)
            if data is None:
                raise RuntimeError(f"MinIO event object vanished after listing: {key}")
            for line in data.decode("utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise RuntimeError(f"MinIO event object {key} contains a corrupt line") from exc
                if not isinstance(event, dict):
                    raise RuntimeError(f"MinIO event object {key} contains a non-object entry")
                events.append(event)
        if events:
            last_id = events[-1].get("event_id")
            if isinstance(last_id, str) and last_id:
                self._last_event_ids[case_id] = last_id
        return events

    # ------------------------------------------------------------------
    # snapshots (envelope embeds last_event_id for continuity validation)
    # ------------------------------------------------------------------
    def last_event_id(self, case_id: str) -> str | None:
        return self._last_event_ids.get(case_id)

    def write_snapshot(self, case_id: str, case_payload: dict[str, Any]) -> None:
        envelope = {
            "version": 1,
            "case_id": case_id,
            "saved_at": datetime.now(UTC).isoformat(),
            "last_event_id": self._last_event_ids.get(case_id),
            "case": case_payload,
        }
        self._put(
            self.snapshot_key(case_id),
            json.dumps(envelope, ensure_ascii=False, default=json_default).encode("utf-8"),
        )

    def read_snapshot(self, case_id: str) -> dict[str, Any] | None:
        """Return the snapshot envelope; missing object -> None, corruption -> RuntimeError."""
        key = self.snapshot_key(case_id)
        data = self._get(key)
        if data is None:
            return None
        try:
            envelope = json.loads(data)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"MinIO snapshot object {key} cannot be parsed") from exc
        if not isinstance(envelope, dict) or not isinstance(envelope.get("case"), dict):
            raise RuntimeError(f"MinIO snapshot object {key} has an invalid envelope")
        return envelope

    # ------------------------------------------------------------------
    # idempotency receipts (手册阶段 2 修复 2：随快照节奏入 MinIO，重启直读恢复)
    # ------------------------------------------------------------------
    def write_receipt(self, idempotency_key: str, receipt: dict[str, Any]) -> None:
        envelope = {
            "version": 1,
            "idempotency_key": idempotency_key,
            "saved_at": datetime.now(UTC).isoformat(),
            "receipt": receipt,
        }
        self._put(
            self.receipt_key(idempotency_key),
            json.dumps(envelope, ensure_ascii=False, default=json_default).encode("utf-8"),
        )

    def read_receipt(self, idempotency_key: str) -> dict[str, Any] | None:
        """Return one receipt; missing object -> None, corruption -> RuntimeError."""
        key = self.receipt_key(idempotency_key)
        data = self._get(key)
        if data is None:
            return None
        try:
            envelope = json.loads(data)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"MinIO receipt object {key} cannot be parsed") from exc
        if not isinstance(envelope, dict) or not isinstance(envelope.get("receipt"), dict):
            raise RuntimeError(f"MinIO receipt object {key} has an invalid envelope")
        return envelope["receipt"]

    def read_receipts(self) -> dict[str, dict[str, Any]]:
        """Startup recovery: load every persisted receipt (fail fast on corruption)."""
        receipts: dict[str, dict[str, Any]] = {}
        for key in self._list_keys("receipts/"):
            name = key.rsplit("/", 1)[-1]
            if not name.endswith(".json"):
                continue
            receipt = self.read_receipt(name[: -len(".json")])
            if receipt is not None:
                receipts[name[: -len(".json")]] = receipt
        return receipts

    def list_case_ids(self) -> list[str]:
        case_ids: set[str] = set()
        for key in self._list_keys("cases/"):
            parts = key.split("/")
            if len(parts) >= 3 and parts[1]:
                case_ids.add(parts[1])
        return sorted(case_ids)

    def recover_cases(self) -> dict[str, dict[str, Any]]:
        """Startup recovery: snapshot per case + continuity check against the event stream.

        校验协议：snapshot.json 内嵌的 last_event_id 非空时必须存在于该 Case 的事件流中
        （对不上即拒绝启动）。last_event_id 为 None 是合法瞬时态——写顺序是"先状态快照、
        后审计事件"（service 层先 CaseStore 后 AuditStore），快照可能恰好写在第一条
        事件落盘之前；marker 落后于流尾同样合法（快照只断言事件流的一个前缀）。
        事件流本身按卷序完整读入，同时重建 per-case last_event_id 供后续快照内嵌。
        任何读取/解析/校验失败都抛 RuntimeError——与本地 JSON 时代 _load 的
        fail-fast 语义一致。
        """
        snapshots: dict[str, dict[str, Any]] = {}
        for case_id in self.list_case_ids():
            events = self.read_events(case_id)
            envelope = self.read_snapshot(case_id)
            if envelope is None:
                # 只有事件没有快照：迁移中途态，事件流仍是事实，状态由事件侧保留。
                logger.warning("case %s has an event stream but no snapshot object", case_id)
                continue
            marker = envelope.get("last_event_id")
            if marker is not None:
                event_ids = [event.get("event_id") for event in events]
                if marker not in event_ids:
                    raise RuntimeError(
                        f"case {case_id} snapshot last_event_id {marker!r} is not in the event stream; "
                        "refusing to start with an inconsistent snapshot"
                    )
            snapshots[case_id] = envelope["case"]
        return snapshots

    # ------------------------------------------------------------------
    # deletion (object-delete semantics; used by Case GC)
    # ------------------------------------------------------------------
    def delete_event_objects(self, case_id: str) -> int:
        """Delete all event volume objects of a Case; returns the number of events removed."""
        removed = len(self.read_events(case_id))
        for key in self._event_volume_keys(case_id):
            self._remove(key)
        self._events_deleted(case_id)
        return removed

    def delete_case_objects(self, case_id: str) -> None:
        """Delete every remaining object of a Case (snapshot + residual objects)."""
        for key in self._list_keys(self.case_prefix(case_id)):
            self._remove(key)
        self._events_deleted(case_id)

    def _events_deleted(self, case_id: str) -> None:
        self._last_event_ids.pop(case_id, None)

    # ------------------------------------------------------------------
    # room namespace archive（协作室房间事件GC与归档口径 §2：归档 ≠ 删除）
    # 事件卷整体迁到冷存前缀 archive/rooms/<room_id>/events/...，在线审计链
    # 查询不再加载；反向回搬即恢复。与 Case GC 的 delete_* 语义完全隔离。
    # ------------------------------------------------------------------
    @staticmethod
    def archive_rooms_prefix() -> str:
        return "archive/rooms/"

    @classmethod
    def archived_room_prefix(cls, room_id: str) -> str:
        return f"{cls.archive_rooms_prefix()}{room_id}/"

    @classmethod
    def archived_events_prefix(cls, room_id: str) -> str:
        return f"{cls.archived_room_prefix(room_id)}events/"

    def list_archived_room_ids(self) -> list[str]:
        """Startup recovery: enumerate rooms with an archived event stream."""
        room_ids: set[str] = set()
        for key in self._list_keys(self.archive_rooms_prefix()):
            parts = key.split("/")
            if len(parts) >= 3 and parts[2]:
                room_ids.add(parts[2])
        return sorted(room_ids)

    def room_namespace_archived(self, room_id: str) -> bool:
        """Prefix probe: any object under the room's cold prefix means archived."""
        return bool(self._list_keys(self.archived_room_prefix(room_id)))

    def archive_event_volumes(self, case_id: str, room_id: str) -> dict[str, Any]:
        """Migrate the event volumes of a room namespace to the cold archive prefix.

        逐对象两阶段、失败不留半迁状态：
        1. 复制阶段：全部在线卷先复制到冷存，冷存齐全前不动任何在线对象；
           任一复制失败即回滚已写的冷存副本后抛出，在线侧保持原样。
        2. 删除阶段：冷存副本已完整，逐个删在线卷；此处失败只可能造成
           在线残留（数据不丢），抛出显式的部分迁移错误，重试幂等
           （复制按同 key 覆盖）。
        """
        online_keys = self._event_volume_keys(case_id)
        if not online_keys:
            raise RuntimeError(f"room namespace {case_id} has no online event volumes to archive")
        events_prefix = self.events_prefix(case_id)
        cold_prefix = self.archived_events_prefix(room_id)
        copied: list[tuple[str, str]] = []
        try:
            for key in online_keys:
                data = self._get(key)
                if data is None:
                    raise RuntimeError(f"MinIO event object vanished after listing: {key}")
                cold_key = f"{cold_prefix}{key[len(events_prefix):]}"
                self._put(cold_key, data)
                copied.append((key, cold_key))
        except Exception:
            for _online_key, cold_key in copied:
                with contextlib.suppress(Exception):
                    self._remove(cold_key)
            raise
        deleted: list[str] = []
        try:
            for online_key, _cold_key in copied:
                self._remove(online_key)
                deleted.append(online_key)
        except Exception as exc:
            remaining = [key for key, _ in copied if key not in deleted]
            raise RuntimeError(
                f"room namespace {case_id} partially archived: cold copies complete under "
                f"{cold_prefix}, online objects left: {remaining}"
            ) from exc
        self._events_deleted(case_id)
        # 快照连续性：事件卷入冷存后，快照内嵌的 last_event_id 在线上流中已
        # 不存在，recover_cases 的连续性校验会拒绝启动；重置为 None（协议内的
        # 合法瞬时态，解除归档或后续写入后由下一次快照重建）。
        envelope = self.read_snapshot(case_id)
        if envelope is not None and envelope.get("last_event_id") is not None:
            envelope["last_event_id"] = None
            envelope["saved_at"] = datetime.now(UTC).isoformat()
            self._put(
                self.snapshot_key(case_id),
                json.dumps(envelope, ensure_ascii=False, default=json_default).encode("utf-8"),
            )
        return {
            "archive_prefix": cold_prefix,
            "migrated_objects": [cold_key for _, cold_key in copied],
        }

    def unarchive_event_volumes(self, case_id: str, room_id: str) -> dict[str, Any]:
        """Move an archived room namespace's event volumes back online.

        与 archive_event_volumes 对称的两阶段复制-删除；在线卷已存在时拒绝
        回搬（防止覆盖归档窗口内意外写入的在线事件），调用方先消化冲突。
        """
        if self._event_volume_keys(case_id):
            raise RuntimeError(
                f"room namespace {case_id} already has online event volumes; refusing to unarchive"
            )
        cold_prefix = self.archived_events_prefix(room_id)
        cold_keys = [
            key for key in self._list_keys(cold_prefix) if key.endswith(".jsonl")
        ]
        if not cold_keys:
            raise RuntimeError(f"room {room_id} has no archived event volumes")
        events_prefix = self.events_prefix(case_id)
        copied: list[tuple[str, str]] = []
        try:
            for key in cold_keys:
                data = self._get(key)
                if data is None:
                    raise RuntimeError(f"MinIO event object vanished after listing: {key}")
                online_key = f"{events_prefix}{key[len(cold_prefix):]}"
                self._put(online_key, data)
                copied.append((key, online_key))
        except Exception:
            for _cold_key, online_key in copied:
                with contextlib.suppress(Exception):
                    self._remove(online_key)
            raise
        deleted: list[str] = []
        try:
            for cold_key, _online_key in copied:
                self._remove(cold_key)
                deleted.append(cold_key)
        except Exception as exc:
            remaining = [key for key, _ in copied if key not in deleted]
            raise RuntimeError(
                f"room {room_id} partially unarchived: online copies complete under "
                f"{events_prefix}, cold objects left: {remaining}"
            ) from exc
        return {
            "restored_from": cold_prefix,
            "restored_objects": [online_key for _, online_key in copied],
        }

    # ------------------------------------------------------------------
    # health (/healthz extension)
    # ------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        try:
            reachable = bool(self._client.bucket_exists(self._bucket))
        except Exception:
            reachable = False
        return {
            "reachable": reachable,
            "last_write_latency_ms": self._last_write_latency_ms,
        }


__all__ = ["MinioBridgeStorage", "json_default"]

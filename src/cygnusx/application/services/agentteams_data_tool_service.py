"""Read-only evidence tools used by AgentTeams consultations."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.agentteams_service import AgentTeamsService
from cygnusx.application.services.agentteams_service import ROOM_NAMESPACE_ID_PREFIX
from cygnusx.application.services.agentteams_service import room_namespace_case_id
from cygnusx.application.services.agentteams_consultation_telemetry_service import (
    AgentTeamsConsultationTelemetryService,
)
from cygnusx.application.services.flow_registry import get_flow_registry
from cygnusx.application.services.pipeline_result_service import PipelineResultService
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import BusinessError, ValidationError
from cygnusx.infrastructure.storage import get_path_factory
from cygnusx.infrastructure.storage.minio_store import MinioStore
from cygnusx.infrastructure.database.models.chat import (
    AgentTeamsRoomMemberModel,
    AgentTeamsRoomModel,
    AgentTeamsTurnRecordModel,
)
from sqlalchemy import select

# Bridge 事件流为 oldest-first 游标分页（平台侧单页上限 100）。房间命名空间流里
# room.agent_stream / room.typing 等高频事件会迅速占满首页，只取首页会漏掉
# 最新消息，因此消息读取沿 next_cursor 翻到流末尾；页数上限防止异常流失控。
_ROOM_EVENTS_SCAN_PAGE_LIMIT = 100
_ROOM_EVENTS_SCAN_MAX_PAGES = 50


class AgentTeamsDataToolService:
    def __init__(
        self,
        *,
        case_service: AgentTeamsService | None = None,
        minio_store: MinioStore | None = None,
        telemetry_service: AgentTeamsConsultationTelemetryService | None = None,
    ) -> None:
        settings = get_settings()
        self._settings = settings
        self._case_service = case_service or AgentTeamsService(settings)
        self._minio_store = minio_store or MinioStore(settings)
        self._telemetry_service = telemetry_service or AgentTeamsConsultationTelemetryService()

    async def task_result_summary(
        self, *, user_id: str, task_id: str, context: ToolInvocationContext
    ) -> dict[str, Any]:
        self._require_context_user(user_id, context)
        return await PipelineResultService(context).get_task_summary(task_id)

    async def task_file_preview(
        self,
        *,
        user_id: str,
        task_id: str,
        path: str,
        max_bytes: int = 20_000,
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        self._require_context_user(user_id, context)
        return await PipelineResultService(context).preview_task_file(
            task_id, path, max_bytes=self._bounded_bytes(max_bytes)
        )

    async def workspace_file_preview(
        self,
        *,
        user_id: str,
        path: str,
        max_bytes: int = 20_000,
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        self._require_context_user(user_id, context)
        workspace = get_path_factory().user_root(user_id).resolve()
        return await PipelineResultService(context).preview_workspace_file(
            workspace, path, max_bytes=self._bounded_bytes(max_bytes)
        )

    async def room_messages_read(
        self,
        *,
        user_id: str,
        room_id: str | None = None,
        limit: int = 20,
        before: str | None = None,
        after: str | None = None,
        include_thinking: bool = False,
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        """Read the current room's persisted message events without Case scope."""
        self._require_context_user(user_id, context)
        bound_room_id = str(context.extra.get("room_id") or "").strip()
        requested_room_id = self._normalize_requested_room_id(room_id) or bound_room_id
        if not requested_room_id or requested_room_id != bound_room_id:
            raise ValidationError("ROOM_ACCESS_DENIED: room_id 不属于当前会话绑定房间")
        requested_limit = int(limit)
        max_limit = max(1, int(self._settings.room_messages_read_max_limit))
        if requested_limit < 1 or requested_limit > max_limit:
            raise ValidationError(
                f"ROOM_LIMIT_INVALID: limit 必须在 1..{max_limit} 范围内"
            )
        room = await context.db.scalar(
            select(AgentTeamsRoomModel).where(AgentTeamsRoomModel.room_id == requested_room_id)
        )
        if room is None:
            raise ValidationError("ROOM_NOT_FOUND: 房间不存在")
        member = await context.db.scalar(
            select(AgentTeamsRoomMemberModel.id).where(
                AgentTeamsRoomMemberModel.room_id == requested_room_id,
                AgentTeamsRoomMemberModel.user_id == user_id,
                AgentTeamsRoomMemberModel.status == "accepted",
            )
        )
        if room.owner_id != user_id and member is None:
            raise ValidationError("ROOM_ACCESS_DENIED: 当前用户不是该房间成员")

        namespace = room_namespace_case_id(requested_room_id)
        event_items, scan_truncated = await self._scan_room_events(namespace, room.owner_id)
        if room.case_id:
            case_events, case_truncated = await self._scan_room_events(room.case_id, room.owner_id)
            event_items.extend(case_events)
            scan_truncated = scan_truncated or case_truncated
        messages: list[dict[str, Any]] = []
        for event in event_items:
            if not isinstance(event, dict) or event.get("event_type") not in {
                "room.user_message",
                "room.agent_message",
            }:
                continue
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            nested = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
            content = str(nested.get("content") or "").strip()
            if not content:
                continue
            recorded_at = str(event.get("recorded_at") or "")
            if before and recorded_at >= before:
                continue
            if after and recorded_at <= after:
                continue
            messages.append(
                {
                    "message_id": str(event.get("event_id") or ""),
                    "role": "agent" if event.get("event_type") == "room.agent_message" else "user",
                    "agent_id": str(nested.get("agent_id") or "") or None,
                    "content": content,
                    "recorded_at": recorded_at,
                    "event_type": event.get("event_type"),
                }
            )
        messages.sort(key=lambda item: (item["recorded_at"], item["message_id"]))
        messages = messages[-requested_limit:]
        if include_thinking:
            turn_rows = list(
                await context.db.scalars(
                    select(AgentTeamsTurnRecordModel)
                    .where(AgentTeamsTurnRecordModel.case_id == namespace)
                    .order_by(AgentTeamsTurnRecordModel.recorded_at.desc())
                    .limit(requested_limit)
                )
            )
            thinking_by_agent: dict[str, str] = {}
            for row in turn_rows:
                if not row.s3_uri:
                    continue
                key = str(row.s3_uri).split(f"cases/{namespace}/", 1)[-1]
                try:
                    payload = json.loads(
                        self._minio_store.read_turn_record(namespace, key, max_bytes=200_000)
                    )
                except Exception:
                    continue
                reasoning = str(payload.get("reasoning_text") or "").strip()
                if reasoning:
                    thinking_by_agent.setdefault(str(row.agent_id), reasoning[:4_000])
            for message in messages:
                if message.get("agent_id") in thinking_by_agent:
                    message["thinking"] = thinking_by_agent[message["agent_id"]]
        return {
            "room_id": requested_room_id,
            "messages": messages,
            "count": len(messages),
            "next_before": messages[0]["recorded_at"] if messages else None,
            "next_after": messages[-1]["recorded_at"] if messages else None,
            "scan_truncated": scan_truncated,
        }

    async def room_facts_query(
        self,
        *,
        user_id: str,
        room_id: str | None = None,
        template: str = "event_timeline",
        limit: int = 50,
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        """Room-scoped peer of Case introspection; never changes Case metrics scope."""
        if template not in {"event_timeline", "messages"}:
            raise ValidationError("ROOM_TEMPLATE_INVALID: 仅支持 event_timeline 或 messages")
        if template == "messages":
            return await self.room_messages_read(
                user_id=user_id, room_id=room_id, limit=limit, context=context
            )
        self._require_context_user(user_id, context)
        bound_room_id = str(context.extra.get("room_id") or "").strip()
        requested_room_id = self._normalize_requested_room_id(room_id) or bound_room_id
        if requested_room_id != bound_room_id or not bound_room_id:
            raise ValidationError("ROOM_ACCESS_DENIED: room_id 不属于当前会话绑定房间")
        max_limit = max(1, min(int(self._settings.room_messages_read_max_limit), 200))
        if limit < 1 or limit > max_limit:
            raise ValidationError(f"ROOM_LIMIT_INVALID: limit 必须在 1..{max_limit} 范围内")
        room = await context.db.scalar(
            select(AgentTeamsRoomModel).where(AgentTeamsRoomModel.room_id == bound_room_id)
        )
        if room is None:
            raise ValidationError("ROOM_NOT_FOUND: 房间不存在")
        events = await self._case_service.get_case_events(
            room_namespace_case_id(bound_room_id), room.owner_id, limit=limit
        )
        rows = [
            {
                "event_id": str(event.get("event_id") or ""),
                "recorded_at": str(event.get("recorded_at") or ""),
                "event_type": str(event.get("event_type") or ""),
                "actor": str(event.get("actor") or ""),
                "summary": str((event.get("payload") or {}).get("summary") or ""),
            }
            for event in events.get("events", [])
            if isinstance(event, dict)
        ]
        return {
            "room_id": bound_room_id,
            "template": "event_timeline",
            "rows": rows,
            "row_count": len(rows),
            "total_count": len(rows),
            "truncated": bool(events.get("next_cursor")),
            "next_cursor": events.get("next_cursor"),
        }

    async def artifact_fetch(
        self,
        *,
        user_id: str,
        case_id: str,
        artifact_ref: str,
        dest_name: str | None = None,
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        self._require_context_user(user_id, context)
        await self._case_service.get_case(case_id, user_id)
        destination_root = Path(
            str(context.extra.get("workdir") or f"/data/cygnusx/output/agentteams/{case_id}/downloads")
        ).resolve()
        requested_name = dest_name or PurePosixPath(artifact_ref.replace("\\", "/")).name
        if not requested_name or Path(requested_name).name != requested_name:
            raise ValidationError("dest_name 必须是单个安全文件名")
        destination_root.mkdir(parents=True, exist_ok=True)
        destination = (destination_root / requested_name).resolve()
        if destination.parent != destination_root:
            raise ValidationError("产物目标路径越界")

        max_bytes = int(self._settings.agentteams_artifact_fetch_max_mb) * 1024 * 1024
        parsed = urlparse(artifact_ref)
        if parsed.scheme == "s3":
            if parsed.netloc != self._minio_store.bucket:
                raise ValidationError("artifact_ref bucket 不受信任")
            parts = PurePosixPath(parsed.path.lstrip("/")).parts
            if len(parts) < 3 or parts[0] != case_id:
                raise ValidationError("artifact_ref 不属于当前 Case")
            key = "/".join(parts[1:])
            metadata = next(
                (item for item in self._minio_store.list_case_objects(case_id) if item.key == key),
                None,
            )
            if metadata is None:
                raise ValidationError("产物不存在")
            if metadata.size_bytes > max_bytes:
                raise ValidationError(
                    f"产物超过 {self._settings.agentteams_artifact_fetch_max_mb}MB 上限"
                )
            self._minio_store.fetch_case_object(case_id, key, destination)
        else:
            workspace = get_path_factory().workspace_dir(user_id).resolve()
            reader = PipelineResultService(context)
            source = await reader._resolve_preview_path(workspace, artifact_ref)
            rel_path = reader._factory.relative_to_root(source)
            info = await reader._backend.stat(rel_path)
            if info is None:
                raise ValidationError("产物不存在")
            if info["size"] > max_bytes:
                raise ValidationError(
                    f"产物超过 {self._settings.agentteams_artifact_fetch_max_mb}MB 上限"
                )
            destination.write_bytes(await reader._backend.read(rel_path))

        size = destination.stat().st_size
        if size > max_bytes:
            destination.unlink(missing_ok=True)
            raise BusinessError("下载产物超过允许大小")
        digest = hashlib.sha256()
        with destination.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        await self._telemetry_service.record_artifact_fetch(size_bytes=size)
        return {
            "local_path": str(destination),
            "size_bytes": size,
            "sha256": digest.hexdigest(),
        }

    async def task_compare_metrics(
        self,
        *,
        user_id: str,
        task_ids: list[str],
        fields: list[str],
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        self._require_context_user(user_id, context)
        reader = PipelineResultService(context)
        comparisons: list[dict[str, Any]] = []
        for task_id in task_ids:
            summary = await reader.get_task_summary(task_id)
            metrics = summary.get("metrics") or {}
            comparisons.append(
                {
                    "task_id": task_id,
                    "flow_id": summary.get("flow_id"),
                    "status": summary.get("status"),
                    "metrics": {field: metrics.get(field) for field in fields},
                }
            )
        return {"fields": fields, "tasks": comparisons}

    async def rule_threshold_lookup(
        self,
        *,
        user_id: str,
        flow_id: str,
        metric_name: str,
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        self._require_context_user(user_id, context)
        registry = get_flow_registry()
        registry.reload()
        registered = next(
            (
                flow
                for flow in registry.flows.values()
                if flow_id in {flow.id, flow.definition.flow.bridge_workflow}
            ),
            None,
        )
        if registered is None:
            raise ValidationError(f"未知流程: {flow_id}")
        thresholds = registered.definition.delivery.thresholds
        if metric_name not in thresholds:
            raise ValidationError(f"流程 {flow_id} 未配置指标 {metric_name} 的阈值")
        return {
            "flow_id": registered.definition.flow.bridge_workflow,
            "metric_name": metric_name,
            "threshold": thresholds[metric_name],
            "rule_version": registered.definition.flow.version,
        }

    @staticmethod
    def _bounded_bytes(value: int) -> int:
        return min(max(int(value), 1), 20_000)

    @staticmethod
    def _require_context_user(user_id: str, context: ToolInvocationContext) -> None:
        if user_id != context.user_id:
            raise ValidationError("工具调用用户与受控上下文不一致")

    async def _scan_room_events(
        self, case_id: str, owner_id: str
    ) -> tuple[list[dict[str, Any]], bool]:
        """沿 Bridge next_cursor 翻页取回完整事件流（oldest-first）。

        返回 (事件列表, 是否因页数上限截断)。只取首页会漏掉最新消息：
        房间流里 room.agent_stream/room.typing 等高频事件会迅速占满首页，
        把 room.user_message/room.agent_message 挤出读取窗口。
        """
        events: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(_ROOM_EVENTS_SCAN_MAX_PAGES):
            page = await self._case_service.get_case_events(
                case_id, owner_id, cursor=cursor, limit=_ROOM_EVENTS_SCAN_PAGE_LIMIT
            )
            items = page.get("events", []) if isinstance(page, dict) else []
            if not items:
                break
            events.extend(item for item in items if isinstance(item, dict))
            cursor = page.get("next_cursor") if isinstance(page, dict) else None
            if not cursor:
                return events, False
        return events, bool(cursor)

    @staticmethod
    def _normalize_requested_room_id(room_id: str | None) -> str:
        """剥掉房间命名空间前缀后再与绑定 room_id 比较。

        Agent 在会诊上下文里看到的房间标识常是 Bridge 房间命名空间 case_id
        （``room-<room_id>``，见 ``room_namespace_case_id``），它与绑定的裸
        room_id 指向同一房间；原样比较会把合法调用误判为越权。
        """
        value = str(room_id or "").strip()
        if value.startswith(ROOM_NAMESPACE_ID_PREFIX):
            return value[len(ROOM_NAMESPACE_ID_PREFIX) :]
        return value


__all__ = ["AgentTeamsDataToolService"]

"""Read-only evidence tools used by AgentTeams consultations."""

from __future__ import annotations

import hashlib
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.agentteams_service import AgentTeamsService
from omichub.application.services.agentteams_consultation_telemetry_service import (
    AgentTeamsConsultationTelemetryService,
)
from omichub.application.services.flow_registry import get_flow_registry
from omichub.application.services.pipeline_result_service import PipelineResultService
from omichub.core.config import get_settings
from omichub.core.exceptions import BusinessError, ValidationError
from omichub.infrastructure.storage import get_path_factory
from omichub.infrastructure.storage.minio_store import MinioStore


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
            str(context.extra.get("workdir") or f"/data/omichub/output/agentteams/{case_id}/downloads")
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


__all__ = ["AgentTeamsDataToolService"]

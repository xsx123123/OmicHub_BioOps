"""Application service for the initial MAS Run and Artifact Registry APIs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.mas import (
    MASApprovalResolveRequest,
    MASApprovalResponse,
    MASArtifactRegisterRequest,
    MASArtifactResponse,
    MASNodeProgressResponse,
    MASRunCreateRequest,
    MASRunProgressResponse,
    MASRunResponse,
)
from omichub.application.services.a2a_event_service import A2AEventService
from omichub.application.services.artifact_service import ArtifactService
from omichub.application.services.mas_plan_validator import MASPlanValidator
from omichub.core.config import get_settings
from omichub.core.exceptions import BusinessError, NotFoundError
from omichub.domain.mas.models import A2AEvent, A2AEventType, AgentRecipient, AgentSender
from omichub.domain.mas.workspace import WorkspaceLayout
from omichub.infrastructure.database.models.mas import MASArtifactModel, MASRunModel
from omichub.infrastructure.database.repositories.mas_repository import MASRepository
from omichub.infrastructure.mas.agent_capabilities import load_agent_capabilities
from omichub.infrastructure.mas.artifact_schemas import load_artifact_schemas


class MASService:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = MASRepository(session)
        self._settings = get_settings()
        self._workspace = WorkspaceLayout(self._settings.mas_workspace_root)
        self._artifacts = ArtifactService(self._workspace)
        self._plan_validator = MASPlanValidator(
            load_agent_capabilities(self._settings.mas_agent_capabilities_yaml),
            load_artifact_schemas(self._settings.mas_artifact_schemas_yaml),
        )

    def _ensure_enabled(self) -> None:
        if not self._settings.mas_enabled:
            raise BusinessError("MAS 功能尚未启用")

    async def create_run(self, user_id: str, request: MASRunCreateRequest) -> MASRunResponse:
        self._ensure_enabled()
        self._plan_validator.validate(request.plan)
        run = await self._repository.create_run(
            user_id=UUID(user_id),
            plan=request.plan,
            context_summary=request.context_summary,
            session_id=request.session_id,
            workspace_id=request.workspace_id,
            project_id=request.project_id,
        )
        self._workspace.initialize_run(run.id)
        return self._run_response(run)

    async def get_run(self, user_id: str, run_id: UUID) -> MASRunResponse:
        self._ensure_enabled()
        return self._run_response(await self._owned_run(user_id, run_id))

    async def list_runs(self, user_id: str) -> list[MASRunResponse]:
        self._ensure_enabled()
        runs = await self._repository.list_runs_for_user(UUID(user_id))
        return [self._run_response(run) for run in runs]

    async def cancel_run(self, user_id: str, run_id: UUID) -> MASRunResponse:
        """Request cancellation without deleting auditable Run or Artifact metadata."""
        self._ensure_enabled()
        run = await self._owned_run(user_id, run_id)
        cancellable = {"queued", "running", "paused_for_input", "cancelling"}
        if run.status not in cancellable:
            raise BusinessError(f"当前 MAS Run 状态 {run.status} 不允许取消")
        if run.status != "cancelling":
            run.status = "cancelling"
            run.version += 1
        return self._run_response(run)

    async def retry_failed_node(
        self, user_id: str, run_id: UUID, node_key: str
    ) -> MASRunResponse:
        """用户显式重试一个失败节点，仍经既有 A2A outbox 调度。"""
        self._ensure_enabled()
        run = await self._owned_run(user_id, run_id)
        node = await self._repository.get_node(run_id, node_key)
        if node is None:
            raise NotFoundError("MAS 节点不存在")
        if node.status != "failed":
            raise BusinessError("仅失败节点可手动重试")
        if node.attempt_count >= node.max_attempts:
            raise BusinessError("节点已达到最大重试次数")
        if not await self._repository.transition_node(
            node_id=node.id,
            expected_version=node.version,
            current_status="failed",
            target_status="ready",
            attempt_count=node.attempt_count + 1,
        ):
            raise BusinessError("重试节点时发生并发冲突")
        node_version = node.version + 1
        if run.status == "failed":
            if not await self._repository.transition_run(
                run_id=run.id,
                expected_version=run.version,
                current_status="failed",
                target_status="running",
            ):
                raise BusinessError("恢复 MAS Run 时发生并发冲突")
            run.status = "running"
            run.version += 1
        await A2AEventService(self._session).record(
            A2AEvent(
                event_type=A2AEventType.NODE_READY,
                trace_id=f"mas:{run.id}:manual-retry",
                run_id=run.id,
                node_key=node.node_key,
                sender=AgentSender(kind="user", id=user_id, attempt_count=node.attempt_count + 1),
                recipient=AgentRecipient(kind="worker", id=node.agent_id),
                status="ready",
                intent=node.intent,
                dedupe_key=(
                    f"{run.id}:{node.node_key}:attempt_{node.attempt_count + 1}:"
                    f"node.ready:state_version_{node_version}"
                ),
                state_version=node_version,
            )
        )
        return self._run_response(run)

    async def approve_run(self, user_id: str, run_id: UUID) -> MASRunResponse:
        """Queue a user-confirmed plan; execution never starts from an unapproved draft."""
        self._ensure_enabled()
        run = await self._owned_run(user_id, run_id)
        if run.status != "awaiting_approval":
            raise BusinessError(f"当前 MAS Run 状态 {run.status} 不允许确认计划")
        run.status = "queued"
        run.version += 1
        await A2AEventService(self._session).record(
            A2AEvent(
                event_type=A2AEventType.PLAN_APPROVED,
                trace_id=f"mas:{run.id}",
                run_id=run.id,
                sender=AgentSender(kind="system", id="mas-hitl"),
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="approved",
                intent="execute_approved_plan",
                dedupe_key=f"{run.id}:plan.approved:state_version_{run.version}",
                state_version=run.version,
            )
        )
        return self._run_response(run)

    async def register_artifact(
        self, user_id: str, run_id: UUID, request: MASArtifactRegisterRequest
    ) -> MASArtifactResponse:
        self._ensure_enabled()
        await self._owned_run(user_id, run_id)
        artifact = request.artifact
        if artifact.run_id != run_id:
            raise BusinessError("Artifact 的 run_id 与请求路径不一致")
        artifact = self._artifacts.validate(artifact)
        return self._artifact_response(await self._repository.save_artifact(artifact))

    async def list_artifacts(self, user_id: str, run_id: UUID) -> list[MASArtifactResponse]:
        self._ensure_enabled()
        await self._owned_run(user_id, run_id)
        return [
            self._artifact_response(item) for item in await self._repository.list_artifacts(run_id)
        ]

    async def resolve_artifact_download(
        self, user_id: str, run_id: UUID, artifact_id: UUID
    ) -> tuple[MASArtifactModel, Path]:
        """返回经 Run 归属和 workspace 边界校验的单个文件产物。"""
        self._ensure_enabled()
        await self._owned_run(user_id, run_id)
        artifact = await self._repository.get_artifact(run_id, artifact_id)
        if artifact is None:
            raise NotFoundError("MAS Artifact 不存在")
        try:
            path = self._workspace.resolve_container_path(
                run_id,
                self._workspace.to_container_path(run_id, artifact.workspace_path),
            )
        except Exception as exc:  # noqa: BLE001
            raise BusinessError("MAS Artifact 路径不合法") from exc
        if not path.is_file():
            raise NotFoundError("MAS Artifact 文件不存在或不可下载")
        return artifact, path

    async def get_progress(self, user_id: str, run_id: UUID) -> MASRunProgressResponse:
        self._ensure_enabled()
        run = await self._owned_run(user_id, run_id)
        nodes = await self._repository.list_nodes(run_id)
        return MASRunProgressResponse(
            run_id=run.id,
            status=run.status,
            version=run.version,
            nodes=[
                MASNodeProgressResponse(
                    key=node.node_key,
                    agent_id=node.agent_id,
                    intent=node.intent,
                    status=node.status,
                    attempt_count=node.attempt_count,
                )
                for node in nodes
            ],
        )

    async def stream_progress(
        self, user_id: str, run_id: UUID, poll_interval_seconds: float = 2.0
    ) -> AsyncIterator[str]:
        """Emit a small metadata-only SSE projection until the Run reaches a terminal state."""
        terminal_states = {"succeeded", "succeeded_with_warnings", "failed", "cancelled", "rejected"}
        last_payload: str | None = None
        while True:
            progress = await self.get_progress(user_id, run_id)
            payload = progress.model_dump_json()
            if payload != last_payload:
                yield f"event: progress\ndata: {payload}\n\n"
                last_payload = payload
            if progress.status in terminal_states:
                yield "event: complete\ndata: {}\n\n"
                return
            await asyncio.sleep(poll_interval_seconds)

    async def list_approvals(self, user_id: str, run_id: UUID) -> list[MASApprovalResponse]:
        self._ensure_enabled()
        await self._owned_run(user_id, run_id)
        nodes = await self._repository.list_nodes(run_id)
        return [
            self._approval_response(item, nodes)
            for item in await self._repository.list_approvals(run_id)
        ]

    async def resolve_approval(
        self,
        user_id: str,
        run_id: UUID,
        approval_id: UUID,
        request: MASApprovalResolveRequest,
    ) -> MASRunResponse:
        self._ensure_enabled()
        run = await self._owned_run(user_id, run_id)
        approval = await self._repository.get_approval(run_id, approval_id)
        if approval is None or approval.status != "pending":
            raise NotFoundError("MAS 审批不存在、已过期或已处理")
        if approval.node_id is None:
            raise BusinessError("MAS 审批缺少关联节点")
        nodes = await self._repository.list_nodes(run_id)
        node = next((item for item in nodes if item.id == approval.node_id), None)
        if node is None or node.status != "waiting_approval":
            raise BusinessError("关联节点不处于等待审批状态")

        approval.status = "approved" if request.approved else "rejected"
        approval.response = request.response
        if not request.approved:
            await self._repository.transition_node(
                node_id=node.id,
                expected_version=node.version,
                current_status="waiting_approval",
                target_status="failed",
            )
            if run.status == "paused_for_input":
                if not await self._repository.transition_run(
                    run_id=run.id,
                    expected_version=run.version,
                    current_status="paused_for_input",
                    target_status="failed",
                ):
                    raise BusinessError("拒绝审批时发生并发冲突")
                run.status = "failed"
                run.version += 1
            return self._run_response(run)

        if approval.kind == "quality_gate_failed":
            from omichub.domain.mas.quality_gate import QCOverrideRequest

            try:
                override = QCOverrideRequest.model_validate(request.response)
            except ValueError as exc:
                raise BusinessError("QC 覆盖必须提供至少 10 个字符的审计原因") from exc
            node.parameters = {**node.parameters, "qc_override_reason": override.reason}

        if not await self._repository.transition_node(
            node_id=node.id,
            expected_version=node.version,
            current_status="waiting_approval",
            target_status="ready",
        ):
            raise BusinessError("审批恢复节点时发生并发冲突")
        next_node_version = node.version + 1
        if run.status != "paused_for_input" or not await self._repository.transition_run(
            run_id=run.id,
            expected_version=run.version,
            current_status="paused_for_input",
            target_status="queued",
        ):
            raise BusinessError("审批恢复 Run 时发生并发冲突")
        run.status = "queued"
        run.version += 1
        await A2AEventService(self._session).record(
            A2AEvent(
                event_type=A2AEventType.PLAN_APPROVED,
                trace_id=f"mas:{run.id}",
                run_id=run.id,
                sender=AgentSender(kind="system", id="mas-hitl"),
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="approved",
                intent="resume_approved_node",
                dedupe_key=f"{run.id}:approval.{approval.id}:run.resume:state_version_{run.version}",
                state_version=run.version,
            )
        )
        await A2AEventService(self._session).record(
            A2AEvent(
                event_type=A2AEventType.NODE_READY,
                trace_id=f"mas:{run.id}",
                run_id=run.id,
                node_key=node.node_key,
                sender=AgentSender(kind="system", id="mas-hitl"),
                recipient=AgentRecipient(kind="worker", id=node.agent_id),
                status="ready",
                intent=node.intent,
                dedupe_key=(
                    f"{run.id}:{node.node_key}:attempt_{node.attempt_count}:"
                    f"node.ready:state_version_{next_node_version}"
                ),
                state_version=next_node_version,
            )
        )
        return self._run_response(run)

    async def _owned_run(self, user_id: str, run_id: UUID) -> MASRunModel:
        run = await self._repository.get_run_for_user(run_id, UUID(user_id))
        if run is None:
            raise NotFoundError("MAS Run 不存在或无权访问")
        return run

    @staticmethod
    def _run_response(run: MASRunModel) -> MASRunResponse:
        return MASRunResponse(
            id=run.id,
            plan_id=run.plan_id,
            status=run.status,
            version=run.version,
            context_summary=run.context_summary,
            project_id=run.project_id,
            created_at=run.created_at,
            finished_at=run.finished_at,
        )

    @staticmethod
    def _artifact_response(artifact: MASArtifactModel) -> MASArtifactResponse:
        return MASArtifactResponse(
            id=artifact.id,
            logical_name=artifact.logical_name,
            kind=artifact.kind,
            workspace_path=artifact.workspace_path,
            media_type=artifact.media_type,
            size_bytes=artifact.size_bytes,
            sha256=artifact.sha256,
            state=artifact.state,
            version=artifact.version,
            project_id=artifact.project_id,
            created_at=artifact.created_at,
        )

    @staticmethod
    def _approval_response(approval, nodes) -> MASApprovalResponse:
        node = next((item for item in nodes if item.id == approval.node_id), None)
        return MASApprovalResponse(
            id=approval.id,
            node_key=node.node_key if node else None,
            kind=approval.kind,
            prompt=approval.prompt,
            options=approval.options,
            status=approval.status,
            response=approval.response,
            created_at=approval.created_at,
        )

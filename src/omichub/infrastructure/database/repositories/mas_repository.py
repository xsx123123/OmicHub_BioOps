"""SQLAlchemy repository for MAS durable metadata."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.domain.mas.models import ExecutionPlan, MASArtifact
from omichub.infrastructure.database.models.mas import (
    MASA2AEventModel,
    MASApprovalModel,
    MASArtifactModel,
    MASNodeModel,
    MASPlanModel,
    MASRunModel,
)


class MASRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_run(
        self,
        *,
        user_id: UUID,
        plan: ExecutionPlan,
        context_summary: dict[str, object],
        session_id: UUID | None,
        workspace_id: UUID | None,
        project_id: str | None,
    ) -> MASRunModel:
        plan_payload = plan.model_dump(mode="json")
        plan_hash = hashlib.sha256(
            json.dumps(plan_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        run_id = uuid4()
        plan_id = uuid4()
        plan_model = MASPlanModel(
            id=plan_id,
            run_id=run_id,
            schema_version=plan.schema_version,
            plan_json=plan_payload,
            plan_hash=plan_hash,
            validated_at=datetime.now(UTC),
            created_by=user_id,
        )
        run = MASRunModel(
            id=run_id,
            user_id=user_id,
            session_id=session_id,
            workspace_id=workspace_id,
            project_id=project_id,
            plan_id=plan_id,
            status="awaiting_approval",
            context_summary=context_summary,
        )
        self._session.add_all([plan_model, run])
        for node in plan.nodes:
            self._session.add(
                MASNodeModel(
                    run_id=run_id,
                    node_key=node.key,
                    agent_id=node.agent_id,
                    intent=node.intent,
                    depends_on=list(node.depends_on),
                    input_contract=node.input_contract,
                    output_contract=node.output_contract,
                    parameters=node.parameters,
                    resources=node.resources,
                    max_attempts=node.max_attempts,
                    idempotency_key=f"{run_id}:{node.key}:attempt:0",
                )
            )
        await self._session.flush()
        return run

    async def get_run_for_user(self, run_id: UUID, user_id: UUID) -> MASRunModel | None:
        result = await self._session.execute(
            select(MASRunModel).where(MASRunModel.id == run_id, MASRunModel.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_runs_for_user(self, user_id: UUID) -> list[MASRunModel]:
        result = await self._session.execute(
            select(MASRunModel)
            .where(MASRunModel.user_id == user_id)
            .order_by(MASRunModel.created_at.desc())
        )
        return list(result.scalars())

    async def save_artifact(self, artifact: MASArtifact) -> MASArtifactModel:
        project_id = await self._session.scalar(
            select(MASRunModel.project_id).where(MASRunModel.id == artifact.run_id)
        )
        model = MASArtifactModel(
            id=artifact.id,
            run_id=artifact.run_id,
            project_id=project_id,
            logical_name=artifact.logical_name,
            kind=artifact.kind.value,
            workspace_path=artifact.workspace_path,
            media_type=artifact.media_type,
            size_bytes=artifact.size_bytes,
            sha256=artifact.sha256,
            schema_version=artifact.schema_version,
            summary=artifact.summary,
            meta=artifact.metadata,
            visibility=artifact.visibility.value,
            state=artifact.state.value,
            storage_class=artifact.storage_class.value,
            version=artifact.version,
            reference_count=artifact.reference_count,
            lease_expires_at=artifact.lease_expires_at,
        )
        self._session.add(model)
        await self._session.flush()
        return model

    async def list_artifacts(self, run_id: UUID) -> list[MASArtifactModel]:
        result = await self._session.execute(
            select(MASArtifactModel)
            .where(MASArtifactModel.run_id == run_id)
            .order_by(MASArtifactModel.logical_name, MASArtifactModel.version.desc())
        )
        return list(result.scalars())

    async def get_artifact(self, run_id: UUID, artifact_id: UUID) -> MASArtifactModel | None:
        result = await self._session.execute(
            select(MASArtifactModel).where(
                MASArtifactModel.run_id == run_id,
                MASArtifactModel.id == artifact_id,
            )
        )
        return result.scalar_one_or_none()

    async def node_id_for_key(self, run_id: UUID, node_key: str) -> UUID | None:
        result = await self._session.execute(
            select(MASNodeModel.id).where(
                MASNodeModel.run_id == run_id, MASNodeModel.node_key == node_key
            )
        )
        return result.scalar_one_or_none()

    async def add_outbox_event(
        self,
        *,
        event_id: UUID,
        run_id: UUID,
        node_id: UUID | None,
        event_type: str,
        payload: dict[str, object],
        dedupe_key: str,
        occurred_at: datetime,
    ) -> MASA2AEventModel:
        event = MASA2AEventModel(
            event_id=event_id,
            run_id=run_id,
            node_id=node_id,
            event_type=event_type,
            payload=payload,
            dedupe_key=dedupe_key,
            occurred_at=occurred_at,
            delivery_status="pending",
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def pending_outbox_events(self, limit: int = 100) -> list[MASA2AEventModel]:
        result = await self._session.execute(
            select(MASA2AEventModel)
            .where(MASA2AEventModel.published_at.is_(None))
            .order_by(MASA2AEventModel.occurred_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars())

    async def get_run(self, run_id: UUID) -> MASRunModel | None:
        result = await self._session.execute(select(MASRunModel).where(MASRunModel.id == run_id))
        return result.scalar_one_or_none()

    async def get_plan_for_run(self, run_id: UUID) -> MASPlanModel | None:
        result = await self._session.execute(
            select(MASPlanModel).where(MASPlanModel.run_id == run_id)
        )
        return result.scalar_one_or_none()

    async def get_node(self, run_id: UUID, node_key: str) -> MASNodeModel | None:
        result = await self._session.execute(
            select(MASNodeModel).where(
                MASNodeModel.run_id == run_id, MASNodeModel.node_key == node_key
            )
        )
        return result.scalar_one_or_none()

    async def create_approval(
        self, *, run_id: UUID, node_id: UUID, kind: str, prompt: str, options: list[dict[str, object]]
    ) -> MASApprovalModel:
        approval = MASApprovalModel(
            run_id=run_id,
            node_id=node_id,
            kind=kind,
            prompt=prompt,
            options=options,
            status="pending",
        )
        self._session.add(approval)
        await self._session.flush()
        return approval

    async def list_approvals(self, run_id: UUID) -> list[MASApprovalModel]:
        result = await self._session.execute(
            select(MASApprovalModel)
            .where(MASApprovalModel.run_id == run_id)
            .order_by(MASApprovalModel.created_at.desc())
        )
        return list(result.scalars())

    async def get_approval(self, run_id: UUID, approval_id: UUID) -> MASApprovalModel | None:
        result = await self._session.execute(
            select(MASApprovalModel).where(
                MASApprovalModel.id == approval_id, MASApprovalModel.run_id == run_id
            )
        )
        return result.scalar_one_or_none()

    async def list_nodes(self, run_id: UUID) -> list[MASNodeModel]:
        result = await self._session.execute(
            select(MASNodeModel)
            .where(MASNodeModel.run_id == run_id)
            .order_by(MASNodeModel.node_key)
        )
        return list(result.scalars())

    async def transition_node(
        self,
        *,
        node_id: UUID,
        expected_version: int,
        current_status: str,
        target_status: str,
        attempt_count: int | None = None,
    ) -> bool:
        values: dict[str, object] = {"status": target_status, "version": expected_version + 1}
        if attempt_count is not None:
            values["attempt_count"] = attempt_count
        result = await self._session.execute(
            update(MASNodeModel)
            .where(
                MASNodeModel.id == node_id,
                MASNodeModel.version == expected_version,
                MASNodeModel.status == current_status,
            )
            .values(**values)
        )
        return result.rowcount == 1

    async def transition_run(
        self, *, run_id: UUID, expected_version: int, current_status: str, target_status: str
    ) -> bool:
        result = await self._session.execute(
            update(MASRunModel)
            .where(
                MASRunModel.id == run_id,
                MASRunModel.version == expected_version,
                MASRunModel.status == current_status,
            )
            .values(status=target_status, version=expected_version + 1)
        )
        return result.rowcount == 1

    async def get_outbox_event(self, event_id: UUID) -> MASA2AEventModel | None:
        result = await self._session.execute(
            select(MASA2AEventModel).where(MASA2AEventModel.event_id == event_id)
        )
        return result.scalar_one_or_none()

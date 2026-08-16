"""Idempotent scheduler-side consumer for persisted A2A events."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.services.mas_scheduler_service import MASSchedulerService
from omichub.domain.mas.models import A2AEvent, A2AEventType
from omichub.infrastructure.database.repositories.mas_repository import MASRepository


class MASEventConsumerService:
    def __init__(self, session: AsyncSession) -> None:
        self._repository = MASRepository(session)
        self._scheduler = MASSchedulerService(session)

    async def consume(self, event_id: UUID) -> bool:
        """Apply a known event once; the event row is the durable idempotency record."""
        stored = await self._repository.get_outbox_event(event_id)
        if stored is None or stored.delivery_status == "processed":
            return False
        event = A2AEvent.model_validate(stored.payload)
        if event.event_type == A2AEventType.PLAN_APPROVED:
            run = await self._repository.get_run(event.run_id)
            if run is not None and run.status == "queued":
                transitioned = await self._repository.transition_run(
                    run_id=run.id,
                    expected_version=run.version,
                    current_status="queued",
                    target_status="running",
                )
                if transitioned:
                    await self._scheduler.unlock_ready_nodes(event.run_id, event.trace_id)
        elif event.event_type == A2AEventType.NODE_READY:
            await self._scheduler.dispatch_ready_node(event.run_id, event.node_key or "", event.trace_id)
        elif event.event_type == A2AEventType.NODE_SUCCEEDED:
            await self._scheduler.mark_node_succeeded(event)
        elif event.event_type == A2AEventType.NODE_FAILED:
            await self._scheduler.handle_node_failure(event)
        stored.delivery_status = "processed"
        return True

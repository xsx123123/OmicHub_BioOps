"""Replayable PostgreSQL-backed Run event publisher."""

import asyncio
from datetime import UTC, datetime

from celery import shared_task
from sqlalchemy import select

from cygnusx.infrastructure.database.models.run_event import RunEventModel
from cygnusx.infrastructure.database.session import get_session_factory
from cygnusx.infrastructure.mas.redis_streams import RunEventStreamPublisher


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.run_events.publish_pending")
def publish_pending() -> dict[str, int]:
    return asyncio.run(_publish_pending())


async def _publish_pending(limit: int = 100) -> dict[str, int]:
    published = 0
    async with get_session_factory()() as session:
        rows = await session.scalars(
            select(RunEventModel)
            .where(RunEventModel.published_at.is_(None))
            .order_by(RunEventModel.occurred_at.asc())
            .limit(limit)
        )
        publisher = RunEventStreamPublisher()
        for event in rows.all():
            payload = {
                "schema_version": "cygnusx.run_event.v1",
                "event_id": str(event.id),
                "run_id": str(event.run_id),
                "task_id": str(event.task_id) if event.task_id else None,
                "project_slug": event.project_slug,
                "executor": event.executor,
                "status": event.status,
                "phase": event.phase,
                "progress": event.progress,
                "rule": event.rule,
                "sequence": event.sequence,
                "occurred_at": event.occurred_at.isoformat(),
                "payload": event.payload,
            }
            await publisher.publish(str(event.id), payload)
            event.published_at = datetime.now(UTC)
            published += 1
        await session.commit()
    return {"published": published}

"""Transactional A2A Outbox service and Redis Stream publisher."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.domain.mas.models import A2AEvent
from cygnusx.infrastructure.database.repositories.mas_repository import MASRepository
from cygnusx.infrastructure.mas.redis_streams import RedisStreamPublisher


class A2AEventService:
    def __init__(
        self, session: AsyncSession, publisher: RedisStreamPublisher | None = None
    ) -> None:
        self._session = session
        self._repository = MASRepository(session)
        self._publisher = publisher or RedisStreamPublisher()

    async def record(self, event: A2AEvent) -> bool:
        """Persist an event in the current transaction; duplicate keys are idempotent no-ops."""
        node_id = None
        if event.node_key is not None:
            node_id = await self._repository.node_id_for_key(event.run_id, event.node_key)
            if node_id is None:
                raise ValueError(
                    f"MAS node {event.node_key!r} does not belong to run {event.run_id}"
                )
        try:
            async with self._session.begin_nested():
                await self._repository.add_outbox_event(
                    event_id=event.event_id,
                    run_id=event.run_id,
                    node_id=node_id,
                    event_type=event.event_type.value,
                    payload=event.model_dump(mode="json"),
                    dedupe_key=event.dedupe_key,
                    occurred_at=event.occurred_at,
                )
        except IntegrityError:
            return False
        return True

    async def publish_pending(self, limit: int = 100) -> int:
        """Publish persisted events; failed Redis writes intentionally remain pending for replay."""
        published = 0
        for event in await self._repository.pending_outbox_events(limit):
            await self._publisher.publish(str(event.event_id), event.payload)
            event.published_at = datetime.now(UTC)
            event.delivery_status = "published"
            published += 1
        await self._session.flush()
        return published

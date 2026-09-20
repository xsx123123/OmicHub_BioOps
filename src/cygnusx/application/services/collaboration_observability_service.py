"""Persistence and aggregation for unified collaboration capability degradations."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.database.models.chat import CollaborationDegradationEventModel


class CollaborationObservabilityService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record_degradation(
        self,
        *,
        session_id: str,
        message_id: str | None,
        user_id: str | None,
        intent: str,
        reason: str,
    ) -> None:
        self._db.add(
            CollaborationDegradationEventModel(
                session_id=session_id,
                message_id=message_id,
                user_id=user_id,
                intent=intent[:20],
                reason=reason[:180],
            )
        )
        await self._db.flush()

    async def degradation_counts(self, *, days: int = 7) -> dict[str, int]:
        since = datetime.now(UTC) - timedelta(days=days)
        rows = await self._db.execute(
            select(
                CollaborationDegradationEventModel.intent,
                func.count(CollaborationDegradationEventModel.id),
            )
            .where(CollaborationDegradationEventModel.created_at >= since)
            .group_by(CollaborationDegradationEventModel.intent)
        )
        counts = {"fanout": 0, "consult": 0, "case": 0, "dag": 0}
        counts.update({str(intent): int(total) for intent, total in rows.all()})
        return counts

"""FactStore abstraction for the v2 memory facts.

The application depends on ``FactStore`` so the persistence backend can be
replaced without changing memory assembly or extraction code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import select

from omichub.infrastructure.database.models.agent_memory import MemoryFactModel


@dataclass(slots=True)
class MemoryFactCreate:
    user_id: str
    agent_id: str
    scope: str
    content: str
    keywords: list[str] = field(default_factory=list)
    embedding: list[float] | None = None
    embedding_model: str | None = None
    source_session_id: str | None = None
    source_message_ids: list[str] = field(default_factory=list)
    confidence: float = 0.8
    content_hash: str | None = None


@dataclass(slots=True)
class MemoryFact:
    id: int
    user_id: str
    agent_id: str
    scope: str
    content: str
    keywords: list[str] | None
    embedding: list[float] | None
    embedding_model: str | None
    source_session_id: str | None
    source_message_ids: list[str] | None
    confidence: float
    status: str
    created_at: datetime
    last_recalled_at: datetime | None
    similarity: float | None = None


class FactStore(Protocol):
    async def insert(self, fact: MemoryFactCreate) -> MemoryFact: ...

    async def search(
        self, user_id: str, agent_id: str, query_vector: list[float], limit: int = 10
    ) -> list[MemoryFact]: ...

    async def supersede(self, old_id: int, new_fact: MemoryFactCreate) -> MemoryFact: ...

    async def archive(self, fact_id: int) -> None: ...

    async def touch_recalled(self, fact_ids: list[int]) -> None: ...


class PostgresFactStore:
    """Postgres/pgvector implementation of ``FactStore``."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def insert(self, fact: MemoryFactCreate) -> MemoryFact:
        content_hash = fact.content_hash or _content_hash(fact.content)
        existing = await self._session.scalar(
            select(MemoryFactModel).where(
                MemoryFactModel.user_id == fact.user_id,
                MemoryFactModel.agent_id == fact.agent_id,
                MemoryFactModel.content_hash == content_hash,
            )
        )
        if existing is not None:
            return _to_fact(existing)
        model = MemoryFactModel(
            user_id=fact.user_id,
            agent_id=fact.agent_id,
            scope=fact.scope,
            content=fact.content,
            content_hash=content_hash,
            keywords=fact.keywords,
            embedding=fact.embedding,
            embedding_model=fact.embedding_model,
            source_session_id=fact.source_session_id,
            source_message_ids=fact.source_message_ids,
            confidence=fact.confidence,
        )
        self._session.add(model)
        await self._session.flush()
        return _to_fact(model)

    async def search(
        self, user_id: str, agent_id: str, query_vector: list[float], limit: int = 10
    ) -> list[MemoryFact]:
        distance = MemoryFactModel.embedding.cosine_distance(query_vector)
        rows = await self._session.execute(
            select(MemoryFactModel, distance.label("distance"))
            .where(
                MemoryFactModel.user_id == user_id,
                MemoryFactModel.agent_id == agent_id,
                MemoryFactModel.status == "active",
                MemoryFactModel.embedding.is_not(None),
            )
            .order_by(distance)
            .limit(max(1, min(limit, 100)))
        )
        return [_to_fact(model, similarity=1 - float(distance_value)) for model, distance_value in rows]

    async def supersede(self, old_id: int, new_fact: MemoryFactCreate) -> MemoryFact:
        replacement = await self.insert(new_fact)
        await self._session.execute(
            update(MemoryFactModel)
            .where(MemoryFactModel.id == old_id)
            .values(status="superseded", superseded_by=replacement.id)
        )
        return replacement

    async def archive(self, fact_id: int) -> None:
        await self._session.execute(
            update(MemoryFactModel)
            .where(MemoryFactModel.id == fact_id)
            .values(status="archived")
        )

    async def touch_recalled(self, fact_ids: list[int]) -> None:
        if fact_ids:
            await self._session.execute(
                update(MemoryFactModel)
                .where(MemoryFactModel.id.in_(fact_ids))
                .values(last_recalled_at=datetime.now(UTC))
            )


def _content_hash(content: str) -> str:
    import hashlib

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _to_fact(model: MemoryFactModel, *, similarity: float | None = None) -> MemoryFact:
    return MemoryFact(
        id=model.id,
        user_id=model.user_id,
        agent_id=model.agent_id,
        scope=model.scope,
        content=model.content,
        keywords=model.keywords,
        embedding=model.embedding,
        embedding_model=model.embedding_model,
        source_session_id=model.source_session_id,
        source_message_ids=model.source_message_ids,
        confidence=model.confidence,
        status=model.status,
        created_at=model.created_at,
        last_recalled_at=model.last_recalled_at,
        similarity=similarity,
    )

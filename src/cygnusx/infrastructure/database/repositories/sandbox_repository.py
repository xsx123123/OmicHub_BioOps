"""沙盒域仓储实现 - SQLAlchemy"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.domain.sandbox.entities import SandboxSession
from cygnusx.domain.sandbox.repositories import ISandboxSessionRepository
from cygnusx.domain.sandbox.value_objects import SandboxStatus
from cygnusx.infrastructure.database.models.sandbox import SandboxSessionModel


class SqlAlchemySandboxSessionRepository(ISandboxSessionRepository):
    """沙盒会话仓储实现"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, session_id: UUID) -> SandboxSession | None:
        model = await self._session.get(SandboxSessionModel, session_id)
        return self._to_entity(model) if model else None

    async def get_active_by_user(self, user_id: UUID) -> SandboxSession | None:
        result = await self._session.execute(
            select(SandboxSessionModel)
            .where(
                SandboxSessionModel.user_id == user_id,
                SandboxSessionModel.status.in_(
                    [SandboxStatus.READY.value, SandboxStatus.IDLE.value]
                ),
            )
            .order_by(desc(SandboxSessionModel.last_activity))
            .limit(1)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_user(self, user_id: UUID) -> list[SandboxSession]:
        result = await self._session.execute(
            select(SandboxSessionModel)
            .where(SandboxSessionModel.user_id == user_id)
            .order_by(desc(SandboxSessionModel.last_activity))
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def save(self, session: SandboxSession) -> SandboxSession:
        model = await self._session.get(SandboxSessionModel, session.id)
        if model is None:
            model = SandboxSessionModel(
                id=session.id,
                user_id=session.user_id,
                container_id=session.container_id,
                container_name=session.container_name,
                status=session.status.value
                if hasattr(session.status, "value")
                else str(session.status),
                language=session.language,
                last_activity=session.last_activity,
                expires_at=session.expires_at,
            )
            self._session.add(model)
        else:
            model.container_id = session.container_id
            model.container_name = session.container_name
            model.status = (
                session.status.value if hasattr(session.status, "value") else str(session.status)
            )
            model.language = session.language
            model.last_activity = session.last_activity
            model.expires_at = session.expires_at
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def update_status(self, session_id: UUID, status: str) -> None:
        model = await self._session.get(SandboxSessionModel, session_id)
        if model is not None:
            model.status = status
            model.last_activity = datetime.now()
            await self._session.flush()

    async def delete(self, session_id: UUID) -> bool:
        model = await self._session.get(SandboxSessionModel, session_id)
        if model is None:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    @staticmethod
    def _to_entity(m: SandboxSessionModel) -> SandboxSession:
        return SandboxSession(
            id=m.id,
            user_id=m.user_id,
            container_id=m.container_id,
            container_name=m.container_name,
            status=SandboxStatus(m.status),
            language=m.language,
            last_activity=m.last_activity or datetime.now(),
            created_at=m.created_at,
            expires_at=m.expires_at,
        )

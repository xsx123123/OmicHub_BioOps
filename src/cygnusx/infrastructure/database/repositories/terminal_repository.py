"""终端域仓储实现 - SQLAlchemy"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.domain.terminal.entities import TerminalSession
from cygnusx.domain.terminal.repositories import ITerminalSessionRepository
from cygnusx.domain.terminal.value_objects import TerminalStatus
from cygnusx.infrastructure.database.models.terminal import TerminalSessionModel


class SqlAlchemyTerminalSessionRepository(ITerminalSessionRepository):
    """终端会话仓储实现"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, session_id: UUID) -> TerminalSession | None:
        model = await self._session.get(TerminalSessionModel, session_id)
        return self._to_entity(model) if model else None

    async def get_by_session_id(self, session_id: str) -> TerminalSession | None:
        result = await self._session.execute(
            select(TerminalSessionModel).where(TerminalSessionModel.session_id == session_id)
        )
        model = result.scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_active_by_user(self, user_id: UUID) -> list[TerminalSession]:
        result = await self._session.execute(
            select(TerminalSessionModel)
            .where(
                TerminalSessionModel.user_id == user_id,
                TerminalSessionModel.status.in_(
                    [TerminalStatus.RUNNING.value, TerminalStatus.IDLE.value]
                ),
            )
            .order_by(desc(TerminalSessionModel.last_activity))
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_all_active(self) -> list[TerminalSession]:
        """管理员：列出所有活跃终端会话。"""
        result = await self._session.execute(
            select(TerminalSessionModel)
            .where(
                TerminalSessionModel.status.in_(
                    [TerminalStatus.RUNNING.value, TerminalStatus.IDLE.value]
                ),
            )
            .order_by(desc(TerminalSessionModel.created_at))
        )
        return [self._to_entity(m) for m in result.scalars().all()]

    async def save(self, session: TerminalSession) -> TerminalSession:
        model = await self._session.get(TerminalSessionModel, session.id)
        if model is None:
            model = TerminalSessionModel(
                id=session.id,
                user_id=session.user_id,
                session_id=session.session_id,
                image_id=session.image_id,
                container_id=session.container_id,
                host_port=session.host_port,
                status=session.status.value
                if hasattr(session.status, "value")
                else str(session.status),
                last_activity=session.last_activity,
                expires_at=session.expires_at,
            )
            self._session.add(model)
        else:
            model.session_id = session.session_id
            model.image_id = session.image_id
            model.container_id = session.container_id
            model.host_port = session.host_port
            model.status = (
                session.status.value if hasattr(session.status, "value") else str(session.status)
            )
            model.last_activity = session.last_activity
            model.expires_at = session.expires_at
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def update_status(self, session_id: UUID, status: str) -> None:
        model = await self._session.get(TerminalSessionModel, session_id)
        if model is not None:
            model.status = status
            model.last_activity = datetime.now(UTC)
            await self._session.flush()

    async def update_last_activity(self, session_id: UUID) -> None:
        model = await self._session.get(TerminalSessionModel, session_id)
        if model is not None:
            model.last_activity = datetime.now(UTC)
            await self._session.flush()

    async def delete(self, session_id: UUID) -> bool:
        model = await self._session.get(TerminalSessionModel, session_id)
        if model is None:
            return False
        await self._session.delete(model)
        await self._session.flush()
        return True

    @staticmethod
    def _to_entity(m: TerminalSessionModel) -> TerminalSession:
        return TerminalSession(
            id=m.id,
            user_id=m.user_id,
            session_id=m.session_id,
            image_id=m.image_id,
            container_id=m.container_id,
            host_port=m.host_port,
            status=TerminalStatus(m.status),
            last_activity=m.last_activity or datetime.now(UTC),
            created_at=m.created_at,
            expires_at=m.expires_at,
        )

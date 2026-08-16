"""沙盒域服务 - 会话状态流转"""

from uuid import UUID

from omichub.domain.sandbox.entities import SandboxSession
from omichub.domain.sandbox.repositories import ISandboxSessionRepository
from omichub.domain.sandbox.value_objects import SandboxStatus


class SandboxDomainService:
    """沙盒域服务"""

    def __init__(self, repo: ISandboxSessionRepository):
        self._repo = repo

    async def create_session(self, session: SandboxSession) -> SandboxSession:
        return await self._repo.save(session)

    async def mark_ready(self, session_id: UUID) -> None:
        await self._repo.update_status(session_id, SandboxStatus.READY.value)

    async def mark_executing(self, session_id: UUID) -> None:
        await self._repo.update_status(session_id, SandboxStatus.EXECUTING.value)

    async def mark_idle(self, session_id: UUID) -> None:
        await self._repo.update_status(session_id, SandboxStatus.IDLE.value)

    async def mark_error(self, session_id: UUID) -> None:
        await self._repo.update_status(session_id, SandboxStatus.ERROR.value)

    async def destroy(self, session_id: UUID) -> bool:
        await self._repo.update_status(session_id, SandboxStatus.DESTROYED.value)
        return await self._repo.delete(session_id)

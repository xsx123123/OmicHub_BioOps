"""终端域服务 - 会话状态流转"""

from uuid import UUID

from omichub.domain.terminal.entities import TerminalSession
from omichub.domain.terminal.repositories import ITerminalSessionRepository
from omichub.domain.terminal.value_objects import TerminalStatus


class TerminalDomainService:
    """终端域服务"""

    def __init__(self, repo: ITerminalSessionRepository):
        self._repo = repo

    async def create_session(self, session: TerminalSession) -> TerminalSession:
        return await self._repo.save(session)

    async def mark_running(self, session_id: UUID) -> None:
        await self._repo.update_status(session_id, TerminalStatus.RUNNING.value)

    async def mark_idle(self, session_id: UUID) -> None:
        await self._repo.update_status(session_id, TerminalStatus.IDLE.value)

    async def mark_stopping(self, session_id: UUID) -> None:
        await self._repo.update_status(session_id, TerminalStatus.STOPPING.value)

    async def destroy(self, session_id: UUID) -> bool:
        await self._repo.update_status(session_id, TerminalStatus.STOPPED.value)
        return await self._repo.delete(session_id)

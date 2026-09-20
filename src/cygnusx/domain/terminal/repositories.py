"""终端域仓储接口"""

from typing import Protocol
from uuid import UUID

from cygnusx.domain.terminal.entities import TerminalSession


class ITerminalSessionRepository(Protocol):
    """终端会话仓储接口"""

    async def get_by_id(self, session_id: UUID) -> TerminalSession | None: ...

    async def get_by_session_id(self, session_id: str) -> TerminalSession | None: ...

    async def list_active_by_user(self, user_id: UUID) -> list[TerminalSession]: ...

    async def save(self, session: TerminalSession) -> TerminalSession: ...

    async def update_status(self, session_id: UUID, status: str) -> None: ...

    async def update_last_activity(self, session_id: UUID) -> None: ...

    async def delete(self, session_id: UUID) -> bool: ...

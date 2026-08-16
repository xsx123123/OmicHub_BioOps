"""沙盒域仓储接口"""

from typing import Protocol
from uuid import UUID

from omichub.domain.sandbox.entities import SandboxSession


class ISandboxSessionRepository(Protocol):
    """沙盒会话仓储接口"""

    async def get_by_id(self, session_id: UUID) -> SandboxSession | None: ...

    async def get_active_by_user(self, user_id: UUID) -> SandboxSession | None: ...

    async def list_by_user(self, user_id: UUID) -> list[SandboxSession]: ...

    async def save(self, session: SandboxSession) -> SandboxSession: ...

    async def update_status(self, session_id: UUID, status: str) -> None: ...

    async def delete(self, session_id: UUID) -> bool: ...

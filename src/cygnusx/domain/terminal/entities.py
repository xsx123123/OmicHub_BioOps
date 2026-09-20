"""终端域实体"""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field

from cygnusx.domain.terminal.value_objects import TerminalStatus


class TerminalSession(BaseModel):
    """终端会话聚合根"""

    id: UUID
    user_id: UUID
    session_id: str = ""  # term_xxxxxxxx
    image_id: str | None = None
    container_id: str | None = None
    host_port: int | None = None
    status: TerminalStatus = TerminalStatus.CREATING
    last_activity: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    expires_at: datetime | None = None

    def is_active(self) -> bool:
        return self.status in (TerminalStatus.RUNNING, TerminalStatus.IDLE)

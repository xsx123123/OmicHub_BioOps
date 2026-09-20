"""任务域仓储接口"""

from typing import Protocol
from uuid import UUID

from sqlalchemy import Row

from cygnusx.domain.task.entities import Task


class ITaskRepository(Protocol):
    """任务仓储接口"""

    async def get_by_id(self, task_id: UUID) -> Task | None: ...

    async def get_by_idempotency_key(self, idempotency_key: str) -> Task | None: ...

    async def count_attempts_by_key_prefix(self, key_prefix: str) -> int: ...

    async def list_by_user(self, user_id: UUID, status: str | None = None) -> list[Task]: ...

    async def save(self, task: Task) -> Task: ...

    async def delete(self, task_id: UUID) -> bool: ...

    async def append_log(self, task_id: UUID, log_entry: dict) -> None: ...

    # ---- 仪表板统计聚合 ----

    async def count_trend_by_day(self, days: int, user_id: UUID | None = None) -> list[Row]: ...

    async def count_by_status(self, user_id: UUID | None = None) -> list[Row]: ...

    async def count_by_flow(self, user_id: UUID | None = None) -> list[Row]: ...

    async def count_active_users_since(self, days: int) -> int: ...

    async def list_recent_failed(
        self, limit: int = 10, user_id: UUID | None = None
    ) -> list[Task]: ...

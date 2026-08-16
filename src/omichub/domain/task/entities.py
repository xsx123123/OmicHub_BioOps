"""任务域实体 - 聚合根"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from omichub.domain.task.value_objects import ExecutionMode, LogLevel, TaskStatus


class TaskLog(BaseModel):
    """任务日志条目"""

    timestamp: datetime = Field(default_factory=datetime.now)
    level: LogLevel = LogLevel.INFO
    message: str
    source: str = ""  # snakemake / celery / system


class Task(BaseModel):
    """任务聚合根 - 统一任务模型"""

    id: UUID
    flow_id: str  # 对应流程 YAML 中 meta.id
    user_id: UUID
    name: str = ""
    status: TaskStatus = TaskStatus.PENDING
    execution_mode: ExecutionMode = ExecutionMode.LOCAL
    parameters: dict[str, Any] = {}  # 参数快照（锁定提交时的值）
    work_dir: str = ""
    result_path: str = ""
    error_message: str = ""
    progress: float = 0.0  # 0.0 ~ 1.0
    sample_count: int = 0  # 提交时由 len(sample_sheet) 落库
    logs: list[TaskLog] = []
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: datetime | None = None
    finished_at: datetime | None = None

    def can_transition_to(self, new_status: TaskStatus) -> bool:
        from omichub.domain.task.value_objects import VALID_TRANSITIONS

        return new_status in VALID_TRANSITIONS.get(self.status, set())

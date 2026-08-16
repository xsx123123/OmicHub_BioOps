"""任务相关 DTO 模型"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import Field

from omichub.application.schemas.base import OmicsHubBaseSchema
from omichub.domain.task.value_objects import ExecutionMode, LogLevel, TaskStatus


class TaskSubmitRequest(OmicsHubBaseSchema):
    """任务提交请求"""

    flow_id: str
    name: str = Field(min_length=1, max_length=128, description="用户提供的分析任务名称")
    parameters: dict[str, Any] = {}
    sample_sheet: list[dict[str, Any]] = []
    comparisons: list[dict[str, Any]] | None = None
    execution_mode: ExecutionMode = ExecutionMode.LOCAL


class TaskLogResponse(OmicsHubBaseSchema):
    """任务日志响应项"""

    timestamp: datetime
    level: str
    message: str
    source: str = ""


class TaskResponse(OmicsHubBaseSchema):
    """任务详情响应"""

    id: UUID
    flow_id: str
    user_id: UUID
    # 所属用户信息：列表接口由服务层按 user_id 回填，供前端按
    # nickname → username 的统一规则展示（无需再拿 UUID 反查）。
    username: str | None = None
    nickname: str | None = None
    name: str
    status: str
    execution_mode: str
    parameters: dict[str, Any]
    work_dir: str
    result_path: str
    error_message: str
    progress: float
    logs: list[TaskLogResponse]
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None


class TaskListResponse(OmicsHubBaseSchema):
    """任务列表响应"""

    items: list[TaskResponse]
    total: int


def task_to_response(task: Any) -> TaskResponse:
    """Task 实体 / ORM → TaskResponse"""
    return TaskResponse(
        id=task.id,
        flow_id=task.flow_id,
        user_id=task.user_id,
        name=task.name,
        status=task.status.value if isinstance(task.status, TaskStatus) else task.status,
        execution_mode=task.execution_mode.value
        if isinstance(task.execution_mode, ExecutionMode)
        else task.execution_mode,
        parameters=task.parameters or {},
        work_dir=task.work_dir,
        result_path=task.result_path,
        error_message=task.error_message,
        progress=task.progress,
        logs=[
            TaskLogResponse(
                timestamp=log.timestamp,
                level=log.level.value if isinstance(log.level, LogLevel) else log.level,
                message=log.message,
                source=log.source,
            )
            for log in task.logs
        ],
        created_at=task.created_at,
        started_at=task.started_at,
        finished_at=task.finished_at,
    )

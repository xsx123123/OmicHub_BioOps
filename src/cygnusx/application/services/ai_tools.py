"""AI Copilot Tool Use 执行器 — submit_task / query_status / list_samples"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ValidationError as PydanticValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.task import TaskSubmitRequest
from cygnusx.application.services.task_service import TaskService
from cygnusx.core.config import get_settings
from cygnusx.domain.ai.value_objects import ToolName
from cygnusx.infrastructure.database.repositories.task_repository import TaskRepositoryImpl


class QueryStatusArgs(BaseModel):
    task_id: str


class ListSamplesArgs(BaseModel):
    pass


class AIToolExecutor:
    """内置工具执行器（Tool Use 协议落地）"""

    def __init__(self, db: AsyncSession, user_id: UUID):
        self._db = db
        self._user_id = user_id

    async def execute(self, tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if tool == ToolName.SUBMIT_TASK.value:
            return await self._submit_task(arguments)
        if tool == ToolName.QUERY_STATUS.value:
            return await self._query_status(arguments)
        if tool == ToolName.LIST_SAMPLES.value:
            return await self._list_samples(arguments)
        return {"success": False, "error": f"未知工具: {tool}"}

    async def _submit_task(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """提交分析任务"""
        try:
            req = TaskSubmitRequest(**arguments)
        except PydanticValidationError as e:
            return {"success": False, "error": f"参数校验失败: {e}"}
        try:
            task_service = TaskService(self._db)
            resp = await task_service.submit(str(self._user_id), req)
            return {
                "success": True,
                "task_id": str(resp.id),
                "status": resp.status,
                "name": resp.name,
            }
        except Exception as e:  # noqa: BLE001
            return {"success": False, "error": str(e)}

    async def _query_status(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """查询任务状态"""
        try:
            args = QueryStatusArgs(**arguments)
            task_id = UUID(str(args.task_id))
        except (PydanticValidationError, ValueError):
            return {"success": False, "error": "无效的 task_id"}

        repo = TaskRepositoryImpl(self._db)
        task = await repo.get_by_id(task_id)
        if task is None or str(task.user_id) != str(self._user_id):
            return {"success": False, "error": "任务不存在或无权访问"}
        return {
            "success": True,
            "task_id": str(task.id),
            "status": task.status.value if hasattr(task.status, "value") else str(task.status),
            "progress": task.progress,
            "error_message": task.error_message,
        }

    async def _list_samples(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """列出用户数据目录下的样本文件"""
        try:
            ListSamplesArgs(**arguments)
        except PydanticValidationError as e:
            return {"success": False, "error": f"参数校验失败: {e}"}
        settings = get_settings()
        user_dir = Path(settings.storage_path) / settings.upload_dir / str(self._user_id)
        samples: list[dict[str, Any]] = []
        if user_dir.exists():
            for entry in sorted(os.listdir(user_dir)):
                full = user_dir / entry
                if full.is_file():
                    stat = full.stat()
                    samples.append({"name": entry, "size_bytes": stat.st_size})
        if not samples:
            samples = [
                {"name": "demo_pbmc.h5ad", "note": "示例数据：10x PBMC"},
                {"name": "demo_tumor.h5ad", "note": "示例数据：肿瘤单细胞"},
            ]
        return {"success": True, "samples": samples}

import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import FileResponse
from sqlalchemy import select

from omichub.api.deps import CurrentUserId, DbSession
from omichub.core.exceptions import NotFoundError
from omichub.infrastructure.database.models.task import TaskModel
from omichub.tools.synteny.schema import SyntenyTaskDTO
from omichub.tools.synteny.service import SyntenyService

prefix = "/synteny"
tags = ["基因组共线性分析"]
router = APIRouter()
service = SyntenyService()


@router.post("/submit", response_model=SyntenyTaskDTO)
async def submit(
    current_user_id: CurrentUserId,
    db: DbSession,
    gff3_text: Annotated[str, Form()],
    blastp_text: Annotated[str, Form()],
    chromosome_filter: Annotated[str | None, Form()] = None,
    project_name: Annotated[str, Form()] = "Synteny",
) -> SyntenyTaskDTO:
    chromosomes = [item.strip() for item in (chromosome_filter or "").split(",") if item.strip()]
    return await service.submit(
        db, current_user_id, gff3_text, blastp_text, chromosomes or None, project_name
    )


@router.get("/tasks/{task_id}", response_model=SyntenyTaskDTO)
async def task(current_user_id: CurrentUserId, db: DbSession, task_id: str) -> SyntenyTaskDTO:
    return await service.get_task(db, current_user_id, task_id)


@router.get("/tasks/{task_id}/download")
async def download(current_user_id: CurrentUserId, db: DbSession, task_id: str) -> FileResponse:
    dto = await service.get_task(db, current_user_id, task_id)
    if dto.status != "completed":
        raise NotFoundError("共线性结果尚未完成")
    try:
        task_uuid = uuid.UUID(task_id)
        user_uuid = uuid.UUID(current_user_id)
    except ValueError as error:
        raise NotFoundError("找不到共线性任务") from error
    result = await db.execute(
        select(TaskModel).where(
            TaskModel.id == task_uuid,
            TaskModel.user_id == user_uuid,
            TaskModel.flow_id == "synteny",
        )
    )
    task_model = result.scalar_one_or_none()
    path = Path(str((task_model.parameters if task_model else {}).get("result_path", "")))
    if not path.exists():
        raise NotFoundError("共线性结果文件不存在")
    return FileResponse(path, media_type="application/json", filename="synteny_result.json")

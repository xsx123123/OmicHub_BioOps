import uuid
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Form
from fastapi.responses import FileResponse
from sqlalchemy import select

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.core.exceptions import NotFoundError
from cygnusx.infrastructure.database.models.task import TaskModel
from cygnusx.tools.gsea.schema import GseaTaskDTO
from cygnusx.tools.gsea.service import GseaService

prefix = "/gsea"
tags = ["GSEA 富集分析"]
router = APIRouter()
service = GseaService()


@router.post("/submit", response_model=GseaTaskDTO)
async def submit(
    current_user_id: CurrentUserId,
    db: DbSession,
    gene_ranking: Annotated[str, Form()],
    species_id: Annotated[str, Form()],
    gene_set: Annotated[str, Form()],
    project_name: Annotated[str, Form()] = "GSEA",
) -> GseaTaskDTO:
    return await service.submit(
        db, current_user_id, gene_ranking, species_id, gene_set, project_name
    )


@router.get("/tasks/{task_id}", response_model=GseaTaskDTO)
async def task(current_user_id: CurrentUserId, db: DbSession, task_id: str) -> GseaTaskDTO:
    return await service.get_task(db, current_user_id, task_id)


@router.get("/tasks/{task_id}/download")
async def download(current_user_id: CurrentUserId, db: DbSession, task_id: str) -> FileResponse:
    dto = await service.get_task(db, current_user_id, task_id)
    if dto.status != "completed":
        raise NotFoundError("GSEA 结果尚未完成")
    try:
        task_uuid = uuid.UUID(task_id)
        user_uuid = uuid.UUID(current_user_id)
    except ValueError as error:
        raise NotFoundError("找不到 GSEA 任务") from error
    result = await db.execute(
        select(TaskModel).where(
            TaskModel.id == task_uuid, TaskModel.user_id == user_uuid, TaskModel.flow_id == "gsea"
        )
    )
    task_model = result.scalar_one_or_none()
    path = Path(str((task_model.parameters if task_model else {}).get("result_path", "")))
    if not path.exists():
        raise NotFoundError("GSEA 结果文件不存在")
    return FileResponse(path, media_type="text/csv", filename="gsea_result.csv")

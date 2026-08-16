"""项目路由 —— 管理用户的分析项目。"""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from omichub.api.deps import CurrentUserId, DbSession
from omichub.application.services.project_service import ProjectService

router = APIRouter()


def get_project_service(db: DbSession) -> ProjectService:
    return ProjectService(db)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


class ProjectCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="项目名称")
    description: str = Field(default="", max_length=2000, description="项目描述（可选）")


@router.get("", summary="列出用户项目")
async def list_projects(
    current_user_id: CurrentUserId,
    service: ProjectServiceDep,
) -> list[dict[str, Any]]:
    """返回当前用户的所有分析项目。首次访问会从磁盘回填历史项目。"""
    from uuid import UUID

    return await service.list_projects(UUID(current_user_id))


@router.get("/count", summary="项目计数")
async def count_projects(
    current_user_id: CurrentUserId,
    service: ProjectServiceDep,
) -> dict[str, int]:
    """返回当前用户的项目数量（供 OverviewStats 等组件使用）。"""
    from uuid import UUID

    return {"count": await service.count_projects(UUID(current_user_id))}


@router.post("", status_code=201, summary="创建项目")
async def create_project(
    current_user_id: CurrentUserId,
    service: ProjectServiceDep,
    req: ProjectCreateRequest,
) -> dict[str, Any]:
    """创建新的分析项目。自动生成路径安全的 slug 并同步创建对应目录。"""
    from uuid import UUID

    try:
        return await service.create_project(
            UUID(current_user_id), req.name, req.description
        )
    except Exception as exc:
        from omichub.core.exceptions import ConflictError, ValidationError

        if isinstance(exc, (ConflictError, ValidationError)):
            raise HTTPException(status_code=400 if isinstance(exc, ValidationError) else 409, detail=str(exc)) from exc
        raise


@router.get("/{project_id}", summary="获取项目详情")
async def get_project(
    current_user_id: CurrentUserId,
    service: ProjectServiceDep,
    project_id: str,
) -> dict[str, Any]:
    """获取单个项目的详细信息。"""
    from uuid import UUID

    try:
        return await service.get_project(UUID(current_user_id), UUID(project_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的项目 ID") from exc
    except Exception as exc:
        from omichub.core.exceptions import NotFoundError

        if isinstance(exc, NotFoundError):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise


@router.delete("/{project_id}", status_code=204, summary="删除项目")
async def delete_project(
    current_user_id: CurrentUserId,
    service: ProjectServiceDep,
    project_id: str,
) -> None:
    """删除项目（仅清 DB 记录，物理文件保留）。"""
    from uuid import UUID

    try:
        await service.delete_project(UUID(current_user_id), UUID(project_id))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="无效的项目 ID") from exc
    except Exception as exc:
        from omichub.core.exceptions import NotFoundError

        if isinstance(exc, NotFoundError):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise

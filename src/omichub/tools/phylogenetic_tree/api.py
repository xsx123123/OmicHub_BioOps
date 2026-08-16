"""系统发育树工具路由。

- POST /phylogenetic-tree/upload    上传序列文件
- POST /phylogenetic-tree/submit    提交树构建任务
- GET  /phylogenetic-tree/tasks/{id}/status
- GET  /phylogenetic-tree/tasks/{id}/result
- DELETE /phylogenetic-tree/tasks/{id}/cancel
- GET  /phylogenetic-tree/download/{id}/{format}
- GET  /phylogenetic-tree/methods   获取支持的方法/预设
- POST /phylogenetic-tree/validate  预校验参数
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import FileResponse

from omichub.api.deps import CurrentUserId, DbSession
from omichub.tools.phylogenetic_tree.config import config_manager
from omichub.tools.phylogenetic_tree.schema import (
    PhyloMethodsResponse,
    PhyloResultDTO,
    PhyloSubmitRequest,
    PhyloTaskResponse,
    PhyloUploadResponse,
    PhyloValidateRequest,
    PhyloValidateResponse,
)
from omichub.tools.phylogenetic_tree.service import phylo_service

prefix = "/phylogenetic-tree"
tags = ["PhylogeneticTree 系统发育树"]

router = APIRouter()


@router.post("/upload", response_model=PhyloUploadResponse, summary="上传序列/Newick 文件")
async def upload_file(
    current_user_id: CurrentUserId,
    file: Annotated[UploadFile, File(description="FASTA/Phylip/NEXUS/Newick 文件")],
) -> PhyloUploadResponse:
    """上传序列文件并返回 file_id，供后续提交任务使用。"""
    return await phylo_service.upload_file(current_user_id, file)


@router.post("/submit", response_model=PhyloTaskResponse, summary="提交系统发育树构建任务")
async def submit_task(
    current_user_id: CurrentUserId,
    db: DbSession,
    request: PhyloSubmitRequest,
) -> PhyloTaskResponse:
    """根据 file_id 与参数投递 Celery 异步任务。"""
    return await phylo_service.submit(current_user_id, request, db)


@router.get(
    "/tasks/{task_id}/status",
    response_model=PhyloTaskResponse,
    summary="查询任务状态与进度",
)
async def get_task_status(
    current_user_id: CurrentUserId,
    task_id: str,
) -> PhyloTaskResponse:
    """轮询任务状态；PROGRESS 时返回 phase/progress/message。"""
    return await phylo_service.get_status(task_id)


@router.get(
    "/tasks/{task_id}/result",
    response_model=PhyloResultDTO,
    summary="获取任务结果",
)
async def get_task_result(
    current_user_id: CurrentUserId,
    task_id: str,
) -> PhyloResultDTO:
    """任务成功后返回 Newick 路径与统计信息。"""
    return await phylo_service.get_result(task_id)


@router.delete(
    "/tasks/{task_id}/cancel",
    response_model=PhyloTaskResponse,
    summary="取消任务",
)
async def cancel_task(
    current_user_id: CurrentUserId,
    task_id: str,
) -> PhyloTaskResponse:
    """取消尚未完成的任务。"""
    return await phylo_service.cancel(task_id)


@router.get(
    "/download/{task_id}/{format}",
    summary="下载结果文件",
)
async def download_result(
    current_user_id: CurrentUserId,
    task_id: str,
    format: str,
) -> FileResponse:
    """下载指定格式的结果文件（newick/nexus/phyloxml/statistics）。"""
    path = phylo_service.get_result_file_path(task_id, format)
    cfg = config_manager.get_config()
    # 从配置查找 MIME
    mime = "application/octet-stream"
    for item in cfg.output.get("available_formats", []):
        if isinstance(item, dict) and item.get("key") == format:
            mime = item.get("mime", mime)
            break
    return FileResponse(path, filename=f"{task_id}_{format}{path.suffix}", media_type=mime)


@router.get("/methods", response_model=PhyloMethodsResponse, summary="获取支持的构建方法")
async def list_methods(
    current_user_id: CurrentUserId,
) -> PhyloMethodsResponse:
    """返回比对工具、树构建方法、进化模型、Bootstrap 类型与预设参数。"""
    return phylo_service.list_methods()


@router.post("/validate", response_model=PhyloValidateResponse, summary="预校验参数组合")
async def validate_params(
    current_user_id: CurrentUserId,
    request: PhyloValidateRequest,
) -> PhyloValidateResponse:
    """提前校验方法/模型/Bootstrap 组合是否合法。"""
    return phylo_service.validate(request)

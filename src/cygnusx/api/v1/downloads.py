"""数据下载路由 — EBI/NCBI 测序数据下载入口。"""

import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.application.schemas.download import DownloadRequest
from cygnusx.application.schemas.download_progress import (
    DownloadProgressResponse,
    RunProgressDTO,
    StageProgressDTO,
)
from cygnusx.application.schemas.task import TaskListResponse, TaskResponse
from cygnusx.application.services.download_service import DownloadService
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import ValidationError
from cygnusx.infrastructure.cache.redis_client import get_redis
from cygnusx.tools.download.config import get_download_config

router = APIRouter()


def get_download_service(db: DbSession) -> DownloadService:
    """获取下载服务实例"""
    return DownloadService(db)


DownloadServiceDep = Annotated[DownloadService, Depends(get_download_service)]


def _ensure_enabled(req: DownloadRequest) -> None:
    """按下载来源检查对应运行时是否启用。"""
    settings = get_settings()
    config = get_download_config()
    if req.source == "direct_link":
        if not (config.features.direct_link or settings.enable_direct_download):
            raise ValidationError("直链与 FTP 下载功能未启用")
        if len(req.links) > config.validation.max_links_per_task:
            raise ValidationError(
                f"单次最多提交 {config.validation.max_links_per_task} 个下载链接"
            )
        return
    if req.source == "cloud_storage":
        if not (config.features.cloud_storage or settings.enable_cloud_storage_download):
            raise ValidationError("云存储下载功能未启用")
        return
    if not (config.features.ebi or settings.enable_ebi_download):
        raise ValidationError("数据下载功能未启用")


@router.post("", response_model=TaskResponse, summary="提交数据下载任务")
async def submit_download(
    current_user_id: CurrentUserId,
    req: DownloadRequest,
    service: DownloadServiceDep,
) -> TaskResponse:
    """提交一个 EBI/NCBI 数据下载任务，返回任务对象（可经 /tasks/{id} 查进度/日志）。"""
    _ensure_enabled(req)
    return await service.submit(current_user_id, req)


@router.get("", response_model=TaskListResponse, summary="数据下载任务列表")
async def list_downloads(
    current_user_id: CurrentUserId,
    service: DownloadServiceDep,
) -> TaskListResponse:
    """列出当前用户的数据下载任务。"""
    return await service.list_downloads(current_user_id)


@router.get(
    "/{task_id}/progress",
    response_model=DownloadProgressResponse,
    summary="获取下载任务逐运行进度",
)
async def get_download_progress(
    task_id: UUID,
    current_user_id: CurrentUserId,
    service: DownloadServiceDep,
) -> DownloadProgressResponse:
    """返回每个 SRR run 的分阶段进度（下载/解压/压缩）。

    数据来源：EBIDownload HTTP Progress API → Celery 轮询解密 → Redis。
    若 Redis 中无数据（任务未运行或 progress API 不可用），返回 source="unavailable"。
    """
    # 校验任务归属
    task_resp = await service.get_task_for_user(task_id, current_user_id)

    redis = get_redis()
    raw = await redis.get(f"download_progress:{task_id}")

    if raw is None:
        return DownloadProgressResponse(
            task_id=str(task_id),
            runs={},
            overall_percent=task_resp.progress * 100,
            source="unavailable",
        )

    runs_data = json.loads(raw)
    runs: dict[str, RunProgressDTO] = {}
    for run_id, rp in runs_data.items():
        runs[run_id] = RunProgressDTO(
            run_id=rp["run_id"],
            stage=rp["stage"],
            overall_percent=rp["overall_percent"],
            download=StageProgressDTO(**rp["download"]),
            extraction=StageProgressDTO(**rp["extraction"]),
            compression=StageProgressDTO(**rp["compression"]),
        )

    overall = sum(r.overall_percent for r in runs.values()) / len(runs) if runs else 0.0

    return DownloadProgressResponse(
        task_id=str(task_id),
        runs=runs,
        overall_percent=overall,
        source="progress_api",
    )

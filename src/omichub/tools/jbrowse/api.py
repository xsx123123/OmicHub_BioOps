"""JBrowse 2 基因组浏览器路由 —— 配置生成 / 文件扫描 / 上传 / 索引管理。

鉴权：所有接口要求登录（CurrentUserId），用户身份取自 JWT；配置热重载需管理员。
用户目录与归属：扫描/上传/索引均以 JWT subject 为 user_id，拒绝 user_id 查询参数伪造。
"""

import asyncio
import contextlib
import os
import shutil
from typing import Annotated

from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import JSONResponse

from omichub.api.deps import CurrentUserId
from omichub.core.exceptions import NotFoundError, ValidationError
from omichub.infrastructure.task_queue.dispatcher import enqueue_task
from omichub.middleware.rbac import AdminRequired
from omichub.tools.jbrowse.config import config_manager
from omichub.tools.jbrowse.schema import (
    AssemblyDetailDTO,
    AssemblyListResponse,
    BatchUploadItemDTO,
    BatchUploadResponse,
    ConfigReloadResponse,
    IndexStatusDTO,
    IndexTaskStatusDTO,
    IndexTaskSubmitDTO,
    PresetTracksResponse,
    ScanResponse,
    UploadResultDTO,
)
from omichub.tools.jbrowse.service import JBrowseService, jbrowse_service
from omichub.tools.jbrowse.tasks import index_file

# 路由元数据：供 omichub.tools.register_tool_routers 自动发现挂载
prefix = "/jbrowse"
tags = ["JBrowse 基因组浏览器"]

router = APIRouter()

# 上传分块大小：8 MiB，兼顾内存与大文件吞吐
_UPLOAD_CHUNK = 8 * 1024 * 1024


def get_jbrowse_service() -> JBrowseService:
    """获取 JBrowse 服务实例（无状态，单例即可）"""
    return jbrowse_service


JBrowseServiceDep = Annotated[JBrowseService, Depends(get_jbrowse_service)]


# ============================================================
# 1. 参考基因组
# ============================================================


@router.get("/assemblies", response_model=AssemblyListResponse, summary="获取所有参考基因组列表")
async def list_assemblies(
    _user: CurrentUserId,
    service: JBrowseServiceDep,
) -> AssemblyListResponse:
    """返回 YAML 中配置的所有参考基因组（含 fasta/fai 存在性）。"""
    assemblies = await service.list_assemblies()
    return AssemblyListResponse(assemblies=assemblies)


@router.get(
    "/assemblies/{assembly_id}",
    response_model=AssemblyDetailDTO,
    summary="获取指定参考基因组详情",
)
async def get_assembly_detail(
    assembly_id: str,
    _user: CurrentUserId,
    service: JBrowseServiceDep,
) -> AssemblyDetailDTO:
    """获取单个参考基因组的详细配置。"""
    return await service.get_assembly_detail(assembly_id)


# ============================================================
# 2. 浏览器配置生成
# ============================================================


@router.get("/config", summary="生成 JBrowse 2 浏览器配置 JSON")
async def generate_config(
    current_user_id: CurrentUserId,
    service: JBrowseServiceDep,
    assembly: Annotated[str, Query(description="参考基因组 ID")],
    tracks: Annotated[list[str] | None, Query(description="用户轨道文件路径列表")] = None,
    region: Annotated[
        str | None, Query(description="初始视图区域，如 Chr1:1000000-2000000")
    ] = None,
) -> JSONResponse:
    """根据 assembly ID 和轨道列表生成完整的 JBrowse 2 配置 JSON。

    前端拿到后写入 blob URL 交给 iframe（JBrowse 2 fetch blob 不需要带 JWT，
    轨道数据则经 nginx /tracks/ 流式读取）。
    """
    config = await service.generate_browser_config(
        assembly_id=assembly,
        user_tracks=tracks,
        region=region,
        user_id=current_user_id,
    )
    return JSONResponse(content=config)


# ============================================================
# 3. 用户目录扫描
# ============================================================


@router.get("/scan", response_model=ScanResponse, summary="扫描用户目录发现可加载文件")
async def scan_user_files(
    current_user_id: CurrentUserId,
    service: JBrowseServiceDep,
) -> ScanResponse:
    """扫描当前用户目录下的 BAM/BigWig/VCF 等文件，返回文件列表及索引状态。"""
    from datetime import datetime

    files = await service.scan_user_directory(current_user_id)
    return ScanResponse(
        user_id=current_user_id,
        scan_time=datetime.utcnow().isoformat(),
        total_files=len(files),
        indexed_count=sum(1 for f in files if f.indexed),
        files=files,
    )


# ============================================================
# 4. 文件上传
# ============================================================


def _sync_save(src_fileobj, dest) -> int:
    """同步落盘：shutil.copyfileobj 从 UploadFile 底层文件对象流式拷贝到 dest。"""
    with open(dest, "wb") as out:
        shutil.copyfileobj(src_fileobj, out, length=_UPLOAD_CHUNK)
    return os.path.getsize(dest)


async def _save_upload(file: UploadFile, dest) -> int:
    """流式保存上传文件到 dest 路径，返回写入字节数。阻塞 I/O 全部在线程中执行。"""
    return await asyncio.to_thread(_sync_save, file.file, dest)


@router.post("/upload", response_model=UploadResultDTO, summary="上传轨道文件")
async def upload_track(
    current_user_id: CurrentUserId,
    service: JBrowseServiceDep,
    file: Annotated[UploadFile, File(description="要上传的文件 (BAM/BigWig/VCF 等)")],
    assembly_id: Annotated[str | None, Query(description="关联的参考基因组 ID")] = None,
    auto_index: Annotated[bool, Query(description="上传后是否自动索引")] = True,
) -> UploadResultDTO:
    """上传文件到用户目录，可选自动触发索引任务。"""
    # UploadFile.size 在部分客户端为 None，落盘后再 stat 取真实大小
    eligibility = service.check_upload_eligibility(file.filename or "", file.size or 0)
    if not eligibility["eligible"]:
        raise ValidationError("文件不符合上传要求: " + "; ".join(eligibility["errors"]))

    upload_dir = config_manager.get_user_upload_dir(current_user_id)
    file_path = upload_dir / (file.filename or "unnamed")

    try:
        await _save_upload(file, file_path)
    finally:
        await file.close()

    size = file_path.stat().st_size
    result = UploadResultDTO(
        filename=file.filename or file_path.name,
        saved_path=str(file_path),
        size=size,
        size_human=JBrowseService._human_readable_size(size),
        user_id=current_user_id,
        assembly_id=assembly_id,
    )

    if auto_index:
        task = enqueue_task(index_file, str(file_path))
        result.index_task_id = task.id
        result.index_status = "queued"

    return result


@router.post("/upload/batch", response_model=BatchUploadResponse, summary="批量上传文件")
async def upload_batch(
    current_user_id: CurrentUserId,
    service: JBrowseServiceDep,
    files: Annotated[list[UploadFile], File(description="批量上传的文件列表")],
    auto_index: Annotated[bool, Query()] = True,
) -> BatchUploadResponse:
    """批量上传多个文件。"""
    upload_dir = config_manager.get_user_upload_dir(current_user_id)
    results: list[BatchUploadItemDTO] = []

    for file in files:
        try:
            eligibility = service.check_upload_eligibility(file.filename or "", file.size or 0)
            if not eligibility["eligible"]:
                results.append(
                    BatchUploadItemDTO(
                        filename=file.filename or "unnamed",
                        success=False,
                        error="; ".join(eligibility["errors"]),
                    )
                )
                await file.close()
                continue

            file_path = upload_dir / (file.filename or "unnamed")
            await _save_upload(file, file_path)
            await file.close()

            item = BatchUploadItemDTO(
                filename=file.filename or file_path.name,
                saved_path=str(file_path),
                success=True,
            )
            if auto_index:
                task = enqueue_task(index_file, str(file_path))
                item.index_task_id = task.id
            results.append(item)
        except Exception as e:
            results.append(
                BatchUploadItemDTO(filename=file.filename or "unnamed", success=False, error=str(e))
            )
            with contextlib.suppress(Exception):
                await file.close()

    return BatchUploadResponse(
        total=len(files),
        success=sum(1 for r in results if r.success),
        failed=sum(1 for r in results if not r.success),
        results=results,
    )


# ============================================================
# 5. 索引管理
# ============================================================


@router.get("/index/check", response_model=IndexStatusDTO, summary="检查文件索引状态")
async def check_index(
    current_user_id: CurrentUserId,
    service: JBrowseServiceDep,
    file_path: Annotated[str, Query(description="文件绝对路径")],
) -> IndexStatusDTO:
    """检查指定文件的索引状态（路径须在数据根目录下）。"""
    status = await service.check_index_status(file_path)
    return IndexStatusDTO(file=file_path, index_status=status)


@router.post("/index/create", response_model=IndexTaskSubmitDTO, summary="创建文件索引")
async def create_index(
    current_user_id: CurrentUserId,
    service: JBrowseServiceDep,
    file_path: Annotated[str, Query(description="需要索引的文件路径")],
) -> IndexTaskSubmitDTO:
    """为文件创建索引（异步任务）。仅允许索引当前用户目录下的文件。"""
    # 写操作归属校验：只能索引自己的文件；参考基因组索引由管理员离线生成
    service.ensure_user_owned(file_path, current_user_id)

    if not await asyncio.to_thread(os.path.exists, file_path):
        raise NotFoundError("文件不存在")

    task = enqueue_task(index_file, file_path)
    return IndexTaskSubmitDTO(
        message="索引任务已提交",
        task_id=task.id,
        file=file_path,
        status="queued",
    )


@router.get(
    "/index/status/{task_id}",
    response_model=IndexTaskStatusDTO,
    summary="查询索引任务状态",
)
async def get_index_status(
    task_id: str,
    _user: CurrentUserId,
) -> IndexTaskStatusDTO:
    """查询 Celery 索引任务状态。"""
    from celery.result import AsyncResult

    result = AsyncResult(task_id)
    ready = result.ready()
    successful = result.successful() if ready else None
    return IndexTaskStatusDTO(
        task_id=task_id,
        status=result.status,
        ready=ready,
        successful=successful,
        result=result.result if ready and successful else None,
        error=str(result.result) if ready and not successful else None,
    )


# ============================================================
# 6. 预设轨道
# ============================================================


@router.get(
    "/preset-tracks/{assembly_id}",
    response_model=PresetTracksResponse,
    summary="获取参考基因组的预设轨道",
)
async def list_preset_tracks(
    assembly_id: str,
    _user: CurrentUserId,
    service: JBrowseServiceDep,
) -> PresetTracksResponse:
    """获取 YAML 中配置的预设轨道。"""
    tracks = await service.list_preset_tracks(assembly_id)
    return PresetTracksResponse(assembly_id=assembly_id, tracks=tracks)


# ============================================================
# 7. 配置热重载（管理员）
# ============================================================


@router.post("/config/reload", response_model=ConfigReloadResponse, summary="热重载 YAML 配置")
async def reload_config(
    _admin: AdminRequired,
) -> ConfigReloadResponse:
    """管理员接口：强制重新加载 jbrowse_config.yaml。"""
    config = config_manager.reload()
    return ConfigReloadResponse(
        message="配置已重载",
        assemblies_count=len(config.assemblies),
        preset_tracks_count=sum(len(v) for v in config.preset_tracks.values()),
        auto_scan_enabled=config.auto_scan.enabled,
    )

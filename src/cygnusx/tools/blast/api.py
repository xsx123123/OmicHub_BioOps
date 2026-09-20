"""BLAST 工具路由。

用户端：
- GET  /databases                    获取可用数据库列表
- POST /submit                       提交 BLAST 查询任务
- GET  /tasks/{task_id}              查询任务状态
- GET  /results/{task_id}            获取任务结果
- GET  /download/{task_id}/{format}  下载结果文件 (xml/text)
- POST /tasks/{task_id}/cancel       取消任务
- GET  /tasks                        获取用户历史任务

管理端：
- POST   /admin/databases                      上传 FASTA 创建数据库
- GET    /admin/databases/{db_id}/build-status 查看构建状态
- POST   /admin/databases/{db_id}/rebuild      重新构建索引
- DELETE /admin/databases/{db_id}              删除数据库
- GET    /admin/tasks                          所有任务监控
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.middleware.rbac import AdminRequired
from cygnusx.tools.blast.events import subscribe_blast_events
from cygnusx.tools.blast.schema import (
    BlastAdminTaskListResponse,
    BlastBuildStatusResponse,
    BlastDatabaseCreateRequest,
    BlastDatabaseDTO,
    BlastDatabaseUploadInitRequest,
    BlastDatabaseUploadInitResponse,
    BlastMethodsResponse,
    BlastResultDTO,
    BlastSubmitRequest,
    BlastTaskListResponse,
    BlastTaskResponse,
)
from cygnusx.tools.blast.service import blast_service

prefix = "/blast"
tags = ["BLAST 序列检索"]

router = APIRouter()


# ------------------------------------------------------------------
# 用户端接口
# ------------------------------------------------------------------


@router.get("/databases", response_model=list[BlastDatabaseDTO], summary="获取可用数据库列表")
async def list_blast_databases(
    current_user_id: CurrentUserId,
    db: DbSession,
    db_type: Annotated[str | None, Query(description="数据库类型过滤：nucl/prot")] = None,
) -> list[BlastDatabaseDTO]:
    """返回当前用户可见且状态为 ready 的 BLAST 数据库列表。"""
    return await blast_service.list_databases(db, current_user_id, db_type)


@router.post("/submit", response_model=BlastTaskResponse, summary="提交 BLAST 查询任务")
async def submit_blast_task(
    current_user_id: CurrentUserId,
    db: DbSession,
    request: BlastSubmitRequest,
) -> BlastTaskResponse:
    """提交 BLAST 查询任务，自动推断 program 并投递 Celery 任务。"""
    return await blast_service.submit(db, current_user_id, request)


@router.get("/tasks/{task_id}", response_model=BlastTaskResponse, summary="查询任务状态")
async def get_blast_task_status(
    current_user_id: CurrentUserId,
    db: DbSession,
    task_id: str,
) -> BlastTaskResponse:
    """返回任务状态、进度百分比及错误信息。"""
    return await blast_service.get_status(db, task_id, current_user_id)


@router.get("/tasks/{task_id}/events", summary="订阅任务状态事件")
async def stream_blast_task_events(
    current_user_id: CurrentUserId,
    db: DbSession,
    task_id: str,
) -> StreamingResponse:
    """通过 SSE 推送 queued/running/completed/failed/cancelled 状态。"""
    initial = await blast_service.get_status(db, task_id, current_user_id)

    async def event_generator() -> AsyncIterator[str]:
        pubsub = await subscribe_blast_events(task_id)
        try:
            initial_payload = initial.model_dump(mode="json")
            yield f"data: {json.dumps(initial_payload, ensure_ascii=False)}\n\n"
            if initial.status in {"completed", "failed", "cancelled"}:
                return

            while True:
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=15.0)
                if message is None:
                    yield ": keep-alive\n\n"
                    continue
                data = message["data"]
                if isinstance(data, bytes):
                    data = data.decode("utf-8")
                yield f"data: {data}\n\n"
                payload = json.loads(data)
                if payload.get("status") in {"completed", "failed", "cancelled"}:
                    return
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/results/{task_id}", response_model=BlastResultDTO, summary="获取任务结果")
async def get_blast_result(
    current_user_id: CurrentUserId,
    db: DbSession,
    task_id: str,
    format: Annotated[str, Query(description="结果格式：json/xml/text/summary")] = "json",
) -> BlastResultDTO:
    """返回 BLAST 结果；format=json 时返回结构化命中列表。"""
    return await blast_service.get_result(db, task_id, current_user_id, format)


@router.get("/download/{task_id}/{format}", summary="下载结果文件")
async def download_blast_result(
    current_user_id: CurrentUserId,
    db: DbSession,
    task_id: str,
    format: str,
) -> FileResponse:
    """下载指定格式的结果文件（xml/text）。"""
    path = await blast_service.get_download_path(db, task_id, current_user_id, format)
    media_types = {
        "xml": "application/xml",
        "json": "application/json",
        "text": "text/plain",
    }
    return FileResponse(
        path,
        filename=f"{task_id}_{format}{path.suffix}",
        media_type=media_types.get(format, "application/octet-stream"),
    )


@router.post("/tasks/{task_id}/cancel", response_model=BlastTaskResponse, summary="取消任务")
async def cancel_blast_task(
    current_user_id: CurrentUserId,
    db: DbSession,
    task_id: str,
) -> BlastTaskResponse:
    """取消 queued 或 running 状态的任务。"""
    return await blast_service.cancel(db, task_id, current_user_id)


@router.get("/tasks", response_model=BlastTaskListResponse, summary="获取用户历史任务")
async def list_user_blast_tasks(
    current_user_id: CurrentUserId,
    db: DbSession,
    status: Annotated[str | None, Query(description="状态过滤")] = None,
    search: Annotated[str | None, Query(max_length=128, description="任务 ID 或查询名称")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> BlastTaskListResponse:
    """分页返回当前用户的 BLAST 任务历史。"""
    return await blast_service.list_user_tasks(
        db, current_user_id, status=status, search=search, page=page, page_size=page_size
    )


@router.get("/methods", response_model=BlastMethodsResponse, summary="获取支持的程序映射")
async def list_blast_methods(
    current_user_id: CurrentUserId,
) -> BlastMethodsResponse:
    """返回 BLAST program 与默认参数。"""
    return blast_service.list_methods()


# ------------------------------------------------------------------
# 管理员端接口
# ------------------------------------------------------------------


@router.get("/admin/databases", response_model=list[BlastDatabaseDTO], summary="获取所有数据库")
async def list_all_blast_databases(
    current_user_id: CurrentUserId,
    db: DbSession,
    _: AdminRequired,
    db_type: Annotated[str | None, Query(description="数据库类型过滤：nucl/prot")] = None,
) -> list[BlastDatabaseDTO]:
    """管理员查看全部数据库（含 pending/building/failed/deprecated）。"""
    return await blast_service.list_all_databases(db, db_type)


@router.post(
    "/admin/database-uploads",
    response_model=BlastDatabaseUploadInitResponse,
    summary="初始化数据库分片上传",
)
async def init_blast_database_upload(
    current_user_id: CurrentUserId,
    _: AdminRequired,
    request: BlastDatabaseUploadInitRequest,
) -> BlastDatabaseUploadInitResponse:
    return await blast_service.init_database_upload(current_user_id, request)


@router.put(
    "/admin/database-uploads/{upload_id}/chunks/{chunk_index}",
    summary="上传数据库文件分片",
)
async def upload_blast_database_chunk(
    current_user_id: CurrentUserId,
    _: AdminRequired,
    upload_id: str,
    chunk_index: int,
    chunk: Annotated[UploadFile, File(description="FASTA 文件分片")],
) -> dict[str, int | str]:
    return await blast_service.save_database_upload_chunk(
        current_user_id, upload_id, chunk_index, chunk
    )


@router.post(
    "/admin/database-uploads/{upload_id}/complete",
    response_model=BlastDatabaseDTO,
    summary="完成数据库分片上传",
)
async def complete_blast_database_upload(
    current_user_id: CurrentUserId,
    db: DbSession,
    _: AdminRequired,
    upload_id: str,
) -> BlastDatabaseDTO:
    return await blast_service.complete_database_upload(db, current_user_id, upload_id)


@router.post("/admin/databases", response_model=BlastDatabaseDTO, summary="创建 BLAST 数据库")
async def create_blast_database(
    current_user_id: CurrentUserId,
    db: DbSession,
    _: AdminRequired,
    name: Annotated[str, Form(description="数据库显示名称")],
    db_key: Annotated[str, Form(description="数据库标识")],
    db_type: Annotated[str, Form(description="数据库类型：nucl/prot")],
    fasta_file: Annotated[UploadFile, File(description="FASTA 源文件")],
    source_species: Annotated[str | None, Form(description="物种")] = None,
    source_version: Annotated[str | None, Form(description="版本")] = None,
    version_group: Annotated[str | None, Form(description="版本族标识")] = None,
    is_public: Annotated[bool, Form(description="是否公开可见")] = True,
) -> BlastDatabaseDTO:
    """管理员上传 FASTA 文件，创建数据库记录并投递 makeblastdb 构建任务。"""
    request = BlastDatabaseCreateRequest(
        name=name,
        db_key=db_key,
        db_type=db_type,  # type: ignore[arg-type]
        source_species=source_species,
        source_version=source_version,
        version_group=version_group,
        is_public=is_public,
    )
    return await blast_service.create_database(db, current_user_id, request, fasta_file)


@router.get(
    "/admin/databases/{db_id}/build-status",
    response_model=BlastBuildStatusResponse,
    summary="查看数据库构建状态",
)
async def get_db_build_status(
    current_user_id: CurrentUserId,
    db: DbSession,
    db_id: str,
    _: AdminRequired,
) -> BlastBuildStatusResponse:
    """返回数据库构建状态、进度与日志。"""
    return await blast_service.get_database_build_status(db, db_id)


@router.post(
    "/admin/databases/{db_id}/rebuild",
    response_model=BlastBuildStatusResponse,
    summary="重新构建数据库索引",
)
async def rebuild_blast_database(
    current_user_id: CurrentUserId,
    db: DbSession,
    db_id: str,
    _: AdminRequired,
) -> BlastBuildStatusResponse:
    """重新运行 makeblastdb。"""
    return await blast_service.rebuild_database(db, db_id)


@router.post(
    "/admin/databases/{db_id}/activate",
    response_model=BlastDatabaseDTO,
    summary="激活数据库版本",
)
async def activate_blast_database(
    current_user_id: CurrentUserId,
    db: DbSession,
    db_id: str,
    _: AdminRequired,
) -> BlastDatabaseDTO:
    """将指定 ready 版本设为当前版本，用于版本回滚。"""
    return await blast_service.activate_database(db, db_id)


@router.delete("/admin/databases/{db_id}", summary="删除数据库")
async def delete_blast_database(
    current_user_id: CurrentUserId,
    db_id: str,
    _: AdminRequired,
    db: DbSession,
    hard_delete: Annotated[bool, Query(description="是否硬删除（默认软删除）")] = False,
) -> dict[str, bool | str]:
    """软删除标记为 deprecated；硬删除会删除文件与数据库记录。"""
    return await blast_service.delete_database(db, db_id, hard_delete)


@router.post(
    "/admin/databases/sync-from-yaml",
    response_model=list[BlastDatabaseDTO],
    summary="从 blast_db.yaml 同步数据库",
)
async def sync_blast_databases_from_yaml(
    current_user_id: CurrentUserId,
    db: DbSession,
    _: AdminRequired,
) -> list[BlastDatabaseDTO]:
    """读取 tool_configs/blast/blast_db.yaml，将新增条目导入数据库并触发构建。"""
    return await blast_service.sync_from_yaml(db, current_user_id)


@router.get("/admin/tasks", response_model=BlastAdminTaskListResponse, summary="所有任务监控")
async def list_all_blast_tasks(
    current_user_id: CurrentUserId,
    db: DbSession,
    _: AdminRequired,
    status: Annotated[str | None, Query(description="状态过滤")] = None,
    user_id: Annotated[str | None, Query(description="用户 ID 过滤")] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 50,
) -> BlastAdminTaskListResponse:
    """管理员查看全平台 BLAST 任务。"""
    return await blast_service.list_all_tasks(
        db, status=status, user_id=user_id, page=page, page_size=page_size
    )


@router.post("/admin/cleanup/old", summary="清理旧 BLAST 任务结果")
async def cleanup_old_blast_tasks(
    current_user_id: CurrentUserId,
    db: DbSession,
    _: AdminRequired,
    days: Annotated[int, Query(ge=1, le=365)] = 7,
) -> dict[str, Any]:
    """清理 N 天前完成的 BLAST 任务结果文件，保留数据库记录。"""
    return await blast_service.cleanup_old_tasks(db, days=days)


@router.post("/admin/cleanup/all", summary="清理所有 BLAST 任务结果")
async def cleanup_all_blast_tasks(
    current_user_id: CurrentUserId,
    db: DbSession,
    _: AdminRequired,
    confirm: Annotated[bool, Query(description="确认清理所有数据")] = False,
) -> dict[str, Any]:
    """清理所有 BLAST 任务结果文件，保留数据库索引和元数据记录。"""
    return await blast_service.cleanup_all_tasks(db, confirm=confirm)


@router.get("/admin/storage-stats", summary="BLAST 存储统计")
async def get_blast_storage_stats(
    current_user_id: CurrentUserId,
    db: DbSession,
    _: AdminRequired,
) -> dict[str, Any]:
    """返回 BLAST 任务数量、状态分布及结果文件存储占用。"""
    return await blast_service.get_storage_stats(db)

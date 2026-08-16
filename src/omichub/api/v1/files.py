"""文件路由 — 列表 / 分块上传 / 配额 / 下载 / 删除 / 目录 / 样本"""

import uuid
from pathlib import Path
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse

from omichub.api.deps import CurrentUserId, DbSession
from omichub.application.schemas.file import (
    DataFileDTO,
    DirectoryCreateRequest,
    DirectoryDTO,
    FileListResponse,
    FilePickerItemDTO,
    MoveFileRequest,
    PresignedDownloadResponse,
    PresignedUploadCompleteRequest,
    PresignedUploadRequest,
    PresignedUploadResponse,
    QuotaResponse,
    SampleCreateRequest,
    SampleDTO,
    SampleListResponse,
    SyncResponse,
    UploadChunkResponse,
    UploadInitRequest,
    UploadInitResponse,
    UploadMergeRequest,
    UploadMergeResponse,
)
from omichub.application.services.file_service import FileService
from omichub.core.exceptions import ValidationError
from omichub.core.config import get_settings
from omichub.infrastructure.config.deployment_config import get_deployment_config
from omichub.infrastructure.config.storage_config import get_storage_config
from omichub.infrastructure.storage import get_path_factory, get_storage_backend

router = APIRouter()

# 聊天文件上传允许/禁止的扩展名
_CHAT_UPLOAD_BLOCKED_SUFFIXES = frozenset(
    {
        ".exe",
        ".bat",
        ".cmd",
        ".com",
        ".scr",
        ".msi",
        ".dll",
        ".sh",
        ".bash",
        ".zsh",
        ".csh",
        ".fish",
        ".ps1",
        ".vbs",
        ".js",
        ".jar",
        ".apk",
        ".app",
        ".dmg",
    }
)
_CHAT_UPLOAD_ALLOWED_SUFFIXES = frozenset(
    {
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".svg",
        ".webp",
        ".bmp",
        ".ico",
        ".pdf",
        ".txt",
        ".md",
        ".doc",
        ".docx",
        ".csv",
        ".tsv",
        ".json",
        ".yaml",
        ".yml",
        ".fastq",
        ".fq",
        ".fasta",
        ".fa",
        ".fna",
        ".faa",
        ".ffn",
        ".bam",
        ".cram",
        ".sam",
        ".vcf",
        ".gff",
        ".gff3",
        ".gtf",
        ".bed",
        ".h5ad",
        ".rds",
        ".gz",
        ".zip",
        ".tar",
        ".bz2",
        ".xz",
        # 系统发育树 / 建树产物（Newick / Nexus 等），供上传后直接可视化
        ".nwk",
        ".newick",
        ".nhx",
        ".nh",
        ".tree",
        ".tre",
        ".trees",
        ".dnd",
        ".nex",
        ".nexus",
        # 建树软件产物（IQ-TREE / BEAST 等：报告 / 树文件 / 一致性树 / bootstrap / 距离矩阵 / 日志）
        ".iqtree",
        ".treefile",
        ".contree",
        ".bionj",
        ".mldist",
        ".ufboot",
        ".log",
        # 多序列比对格式（建树输入）
        ".aln",
        ".phy",
        ".phylip",
        ".sto",
    }
)
_CHAT_UPLOAD_DATA_MANAGEMENT_SUFFIXES = frozenset(
    {
        ".bam",
        ".cram",
        ".h5ad",
        ".rds",
        ".zip",
    }
)


def _validate_chat_upload_filename(filename: str | None) -> None:
    """校验聊天上传文件名：必须带扩展名，禁止可执行文件。"""
    if not filename:
        raise ValidationError("文件名不能为空")
    suffixes = [s.lower() for s in Path(filename).suffixes]
    if not suffixes:
        raise ValidationError("上传文件必须带扩展名")
    for suffix in suffixes:
        if suffix in _CHAT_UPLOAD_BLOCKED_SUFFIXES:
            raise ValidationError(f"禁止上传可执行文件: {suffix}")
    if suffixes[-1] in _CHAT_UPLOAD_DATA_MANAGEMENT_SUFFIXES:
        raise ValidationError(
            "该文件请前往文件管理上传，再在聊天输入框中使用 @ 引用，"
            "避免聊天模型直接解析大体积或二进制数据"
        )
    if suffixes[-1] not in _CHAT_UPLOAD_ALLOWED_SUFFIXES:
        raise ValidationError(f"不支持的文件类型: {suffixes[-1]}")


def get_file_service(db: DbSession) -> FileService:
    """获取文件服务实例（注入 DB 会话）"""
    return FileService(db)


FileServiceDep = Annotated[FileService, Depends(get_file_service)]


@router.get("", response_model=FileListResponse, summary="获取文件列表（含搜索）")
async def list_files(
    current_user_id: CurrentUserId,
    service: FileServiceDep,
    directory: Annotated[str | None, Query(description="按目录过滤，空串=根目录")] = None,
    source: Annotated[str | None, Query(description="按来源过滤: upload/pipeline/blast/enrichment 等")] = None,
    q: Annotated[str | None, Query(max_length=500, description="关键字搜索（递归匹配文件名/路径）")] = None,
    limit: Annotated[int, Query(ge=1, le=200, description="搜索模式下最多返回条数")] = 50,
) -> FileListResponse:
    """获取当前用户的文件列表。

    - 不带 ``q``：按 ``directory`` / ``source`` 过滤当前目录直接子项
    - 带 ``q``：递归搜索匹配的文件（等价于旧 ``/search`` 端点），同时返回目录匹配
    """
    if q is not None and q != "":
        try:
            return await service.search_files(UUID(current_user_id), query=q, limit=limit)
        except PermissionError as exc:
            raise HTTPException(status_code=403, detail="无权限访问该目录") from exc
    return await service.list_files(UUID(current_user_id), directory=directory, source=source)


@router.get(
    "/search",
    response_model=FileListResponse,
    summary="搜索工作区文件",
    deprecated=True,
    description="已废弃：请用 GET /files?q=<关键字> 替代。保留仅为向后兼容。",
)
async def search_files(
    current_user_id: CurrentUserId,
    service: FileServiceDep,
    q: Annotated[str, Query(max_length=500)] = "",
    root: Annotated[str, Query(max_length=500)] = "",
    limit: Annotated[int, Query(ge=1, le=50)] = 50,
) -> FileListResponse:
    """在当前用户根目录递归搜索已索引文件，root 仅保留为前端协议字段。"""
    if root not in ("", ".", "/"):
        raise HTTPException(status_code=403, detail="无权限访问该目录")
    try:
        return await service.search_files(UUID(current_user_id), query=q, limit=limit)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail="无权限访问该目录") from exc


@router.get(
    "/workspace",
    summary="列出工作区文件",
    deprecated=True,
    description="已废弃：MCP/Agent 请直接用 Python 调用 FileService.list_workspace_files。"
    "HTTP 端点保留仅为向后兼容，后续版本可能移除。",
)
async def list_workspace_files(
    current_user_id: CurrentUserId,
    service: FileServiceDep,
    path: Annotated[str | None, Query(max_length=500)] = None,
    pattern: Annotated[str | None, Query(max_length=500)] = None,
) -> dict[str, Any]:
    """列出当前用户工作区目录，供内置 Agent 与外置 MCP 共用。"""
    try:
        return await service.list_workspace_files(
            UUID(current_user_id), path=path, pattern=pattern
        )
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.get(
    "/tree",
    summary="统一文件树",
    deprecated=True,
    description="已废弃：请用 GET /files 加 source 参数按来源分组查询。"
    "HTTP 端点保留仅为向后兼容，后续版本可能移除。",
)
async def file_tree(
    current_user_id: CurrentUserId,
    service: FileServiceDep,
) -> dict[str, Any]:
    """聚合视图：按来源分组返回用户所有文件，供前端渲染统一文件树。"""
    return await service.get_file_tree(UUID(current_user_id))


@router.get("/quota", response_model=QuotaResponse, summary="获取存储配额")
async def get_quota(
    current_user_id: CurrentUserId,
    service: FileServiceDep,
) -> QuotaResponse:
    """获取当前用户存储配额与已用空间"""
    return await service.get_quota(UUID(current_user_id))


@router.get("/storage-info", summary="获取存储与部署模式信息")
async def storage_info() -> dict[str, object]:
    """返回当前部署的存储后端类型与部署模式，供前端决定上传策略。"""
    cfg = get_deployment_config()
    return {
        "deployment_mode": cfg.mode,
        "storage_type": cfg.storage_type,
        "sandbox_mount_strategy": cfg.sandbox_mount_strategy,
        "scratch_volume_enabled": cfg.scratch_volume_enabled,
        "presigned_url_enabled": cfg.presigned_url_enabled,
        "product_recycle_policy": cfg.product_recycle_policy,
        "data_materialization_enabled": cfg.data_materialization_enabled,
        "presigned_upload_threshold_bytes": cfg.presigned_upload_threshold_bytes,
    }


@router.get("/preview", summary="预览文件内容")
async def preview_file(
    current_user_id: CurrentUserId,
    service: FileServiceDep,
    path: Annotated[str, Query(description="相对于用户数据根目录的文件路径")],
    max_lines: Annotated[int, Query(ge=1, le=500, description="最多返回行数")] = 50,
) -> dict[str, Any]:
    """读取用户目录下文本文件的前 N 行（供 MCP Server / AI 助手查看分析结果）。"""
    return await service.preview_by_path(
        UUID(current_user_id), path=path, max_lines=max_lines
    )


@router.post("/sync", response_model=SyncResponse, summary="同步磁盘文件到文件列表")
async def sync_files(
    current_user_id: CurrentUserId,
    service: FileServiceDep,
) -> SyncResponse:
    """对账当前用户目录与 file_records，并重算配额。

    用于手动放入文件、旧任务未登记产物、手工删除物理文件后的页面自愈。
    返回新增、清理和显示名修正统计。
    """
    return await service.sync_user_files(UUID(current_user_id))


@router.get(
    "/{file_id}/presigned-download",
    response_model=PresignedDownloadResponse,
    summary="获取预签名下载 URL（cloud 模式）",
)
async def presigned_download(
    file_id: UUID,
    current_user_id: CurrentUserId,
    service: FileServiceDep,
    expires: Annotated[int, Query(ge=60, le=86400)] = 3600,
) -> PresignedDownloadResponse:
    """为已有文件生成临时直链；本地模式返回 400。"""
    try:
        url = await service.create_presigned_download(
            UUID(current_user_id), file_id, expires=expires
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    return PresignedDownloadResponse(download_url=url)


@router.post(
    "/presigned-upload",
    response_model=PresignedUploadResponse,
    summary="获取预签名上传 URL（cloud 模式）",
)
async def presigned_upload(
    current_user_id: CurrentUserId,
    req: PresignedUploadRequest,
    service: FileServiceDep,
    expires: Annotated[int, Query(ge=60, le=86400)] = 3600,
) -> PresignedUploadResponse:
    """预创建文件记录并返回直传 URL；本地模式返回 400。"""
    try:
        upload_url, file_id, storage_path = await service.create_presigned_upload(
            UUID(current_user_id),
            req.original_name,
            req.directory,
            req.size,
            file_type=req.file_type,
            expires=expires,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc
    return PresignedUploadResponse(
        upload_url=upload_url, file_id=file_id, storage_path=storage_path
    )


@router.post(
    "/{file_id}/presigned-complete",
    response_model=DataFileDTO,
    summary="完成预签名上传（cloud 模式）",
)
async def presigned_upload_complete(
    file_id: UUID,
    current_user_id: CurrentUserId,
    req: PresignedUploadCompleteRequest,
    service: FileServiceDep,
) -> DataFileDTO:
    """客户端直传完成后确认元数据并激活文件记录。"""
    try:
        return await service.complete_presigned_upload(
            UUID(current_user_id), file_id, checksum=req.checksum
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=exc.detail) from exc


# ===== 用户目录 =====
@router.get("/directories", response_model=list[DirectoryDTO], summary="目录列表")
async def list_directories(
    current_user_id: CurrentUserId,
    service: FileServiceDep,
) -> list[DirectoryDTO]:
    """获取当前用户的所有目录（前端组装成树）"""
    return await service.list_directories(UUID(current_user_id))


@router.post("/directories", response_model=DirectoryDTO, summary="创建目录")
async def create_directory(
    current_user_id: CurrentUserId,
    req: DirectoryCreateRequest,
    service: FileServiceDep,
) -> DirectoryDTO:
    """创建用户自定义目录（自动建物理目录）"""
    return await service.create_directory(UUID(current_user_id), req)


@router.delete("/directories", summary="删除目录")
async def delete_directory(
    current_user_id: CurrentUserId,
    service: FileServiceDep,
    path: Annotated[str, Query(description="要删除的目录路径")] = "",
) -> dict[str, Any]:
    """删除目录（含其下文件回退到根目录）"""
    await service.delete_directory(UUID(current_user_id), path)
    return {"deleted": True}


@router.get("/picker", response_model=list[FilePickerItemDTO], summary="文件选择器数据")
async def list_files_for_picker(
    current_user_id: CurrentUserId,
    service: FileServiceDep,
    directory: Annotated[str | None, Query()] = None,
    file_type: Annotated[str | None, Query(description="按文件类型过滤，如 fastq/bam")] = None,
) -> list[FilePickerItemDTO]:
    """供分析文件选择器：返回文件 + 绝对路径"""
    return await service.list_files_for_picker(
        UUID(current_user_id), directory=directory, file_type=file_type
    )


@router.put("/{file_id}/move", response_model=DataFileDTO, summary="移动文件到目录")
async def move_file(
    current_user_id: CurrentUserId,
    file_id: UUID,
    req: MoveFileRequest,
    service: FileServiceDep,
) -> DataFileDTO:
    """移动文件到指定目录（空串 = 根目录）"""
    return await service.move_file(UUID(current_user_id), file_id, req.directory)


@router.post("/upload/init", response_model=UploadInitResponse, summary="初始化分块上传")
async def init_upload(
    current_user_id: CurrentUserId,
    req: UploadInitRequest,
    service: FileServiceDep,
) -> UploadInitResponse:
    """初始化分块上传：配额前置校验 + 秒传/断点续传判定。

    配额超限返回 403。
    """
    return await service.init_upload(UUID(current_user_id), req)


@router.post("/upload/chunk", response_model=UploadChunkResponse, summary="上传分片")
async def upload_chunk(
    current_user_id: CurrentUserId,
    service: FileServiceDep,
    upload_id: UUID = Form(...),  # noqa: B008
    index: int = Form(...),  # noqa: B008
    md5: str = Form(...),  # noqa: B008
    chunk: UploadFile = File(...),  # noqa: B008
) -> UploadChunkResponse:
    """接收单个文件分片，校验 MD5 后落盘并记录传输状态"""
    chunk_bytes = await chunk.read()
    return await service.save_chunk(UUID(current_user_id), upload_id, index, chunk_bytes, md5)


@router.post("/upload/merge", response_model=UploadMergeResponse, summary="合并分片")
async def merge_upload(
    current_user_id: CurrentUserId,
    req: UploadMergeRequest,
    service: FileServiceDep,
) -> UploadMergeResponse:
    """合并全部分片、完整性校验、原子累加配额"""
    return await service.merge_upload(UUID(current_user_id), req.upload_id)


@router.delete("/upload/{upload_id}", summary="取消上传")
async def cancel_upload(
    current_user_id: CurrentUserId,
    upload_id: UUID,
    service: FileServiceDep,
) -> dict[str, Any]:
    """取消上传：删除会话与临时分片"""
    await service.cancel_upload(UUID(current_user_id), upload_id)
    return {"deleted": True}


@router.post("/chat-upload", summary="聊天文件上传（供 AI 多模态/附件）")
async def upload_chat_file(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008 — FastAPI 上传参数标准写法
    session_id: str | None = Form(None),
) -> dict[str, Any]:
    """接收聊天附件，保存到用户隔离目录并返回访问 URL。

    用户身份直接取自 AuthMiddleware 注入的 request.state.user_id，
    避免上传接口重复查询数据库，降低抖动/版本校验带来的失败面。

    可选 session_id（聊天会话唯一 ID）：提供时会作为短标记写入文件名
    （``{file_id}.s{session_id前8位}{suffix}``），便于按会话检索上传文件。
    """
    current_user_id: str = getattr(request.state, "user_id", "") or ""
    if not current_user_id:
        from omichub.core.exceptions import AuthenticationError

        raise AuthenticationError("无法识别当前用户")

    _validate_chat_upload_filename(file.filename)
    factory = get_path_factory()
    upload_dir = factory.chat_uploads_dir(current_user_id)

    suffix = Path(file.filename or "").suffix
    file_id = uuid.uuid4().hex
    session_tag = ""
    if session_id:
        safe_sid = "".join(ch for ch in session_id if ch.isalnum() or ch == "-")
        if safe_sid:
            session_tag = f".s{safe_sid[:8]}"
    filename = f"{file_id}{session_tag}{suffix}"
    dest = upload_dir / filename

    backend = get_storage_backend()
    upload_rel = factory.relative_to_root(upload_dir)
    dest_rel = factory.relative_to_root(dest)
    await backend.ensure_dir(upload_rel)
    body = await file.read()
    await backend.write(dest_rel, body)

    return {
        "id": file_id,
        "name": file.filename or filename,
        "url": f"/api/v1/files/chat-upload/{current_user_id}/{filename}",
        "mime_type": file.content_type or "application/octet-stream",
    }


@router.get("/chat-upload/{user_id}/{filename}", summary="下载聊天附件")
async def download_chat_file(
    request: Request,
    user_id: str,
    filename: str,
) -> FileResponse:
    """下载聊天上传的附件（仅允许访问当前用户自己的聊天文件）。"""
    current_user_id: str = getattr(request.state, "user_id", "") or ""
    if not current_user_id or user_id != current_user_id:
        from omichub.core.exceptions import AuthorizationError

        raise AuthorizationError("无权访问该附件")
    factory = get_path_factory()
    upload_dir = factory.chat_uploads_dir(current_user_id)
    # 防止目录遍历：仅取 basename
    safe_name = Path(filename).name
    path = upload_dir / safe_name

    backend = get_storage_backend()
    rel_path = factory.relative_to_root(path)
    if not await backend.exists(rel_path):
        from omichub.core.exceptions import NotFoundError

        raise NotFoundError("文件不存在")
    local_path = await backend.get_local_path(rel_path)
    return FileResponse(str(local_path), filename=safe_name)


@router.get("/{file_id}/download", summary="下载文件")
async def download_file(
    current_user_id: CurrentUserId,
    file_id: UUID,
    service: FileServiceDep,
) -> FileResponse:
    """下载文件（强制归属校验，越权返回 404）"""
    path = await service.get_file_path(UUID(current_user_id), file_id)
    return FileResponse(path, filename=path.name)


@router.delete("/{file_id}", summary="删除文件")
async def delete_file(
    current_user_id: CurrentUserId,
    file_id: UUID,
    service: FileServiceDep,
) -> dict[str, Any]:
    """删除文件并扣减配额"""
    await service.delete_file(UUID(current_user_id), file_id)
    return {"deleted": True}


# ===== 样本（供流程引擎读取文件路径） =====
@router.get("/samples", response_model=SampleListResponse, summary="获取样本列表")
async def list_samples(
    current_user_id: CurrentUserId,
    service: FileServiceDep,
) -> SampleListResponse:
    return await service.list_samples(UUID(current_user_id))


@router.post("/samples", response_model=SampleDTO, summary="创建样本")
async def create_sample(
    current_user_id: CurrentUserId,
    req: SampleCreateRequest,
    service: FileServiceDep,
) -> SampleDTO:
    """创建样本并关联已上传文件（校验文件归属）"""
    return await service.create_sample(UUID(current_user_id), req)

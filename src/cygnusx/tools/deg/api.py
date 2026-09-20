"""DEG 差异表达分析路由 —— 默认参数 + 示例 + 提交 + 任务查询 + 产物下载。

- GET  /deg/defaults                表单默认值（外置 YAML 热重载）
- GET  /deg/examples                示例输入文本（前端一键填充）
- POST /deg/submit                  multipart 提交，返回已入队 Celery 任务
- GET  /deg/tasks                   当前用户历史任务
- GET  /deg/tasks/{id}              查询状态；完成时返回统计表 + Top 基因 + 产物名单
- GET  /deg/tasks/{id}/artifacts/{name}  下载结果产物（CSV/PNG/PDF/日志）

鉴权：所有接口要求登录（CurrentUserId），user_id 取自 JWT，不信任查询参数。
引擎选择（DESeq2 / edgeR）由 service 按分组重复数解析，见 service._resolve_engine。
"""

from functools import lru_cache
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.tools.deg.schema import (
    DegDefaultsDTO,
    DegTaskDTO,
    DegTaskListResponse,
)
from cygnusx.tools.deg.service import DegService

# 路由元数据：供 cygnusx.tools.register_tool_routers 自动发现挂载
prefix = "/deg"
tags = ["DEG 差异表达分析"]

router = APIRouter()

_MEDIA_TYPES = {
    ".csv": "text/csv; charset=utf-8",
    ".tsv": "text/tab-separated-values; charset=utf-8",
    ".png": "image/png",
    ".pdf": "application/pdf",
    ".log": "text/plain; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


@lru_cache(maxsize=1)
def get_deg_service() -> DegService:
    """获取 DegService 单例（无状态，配置自带 mtime 热重载）。"""
    return DegService()


DegServiceDep = Annotated[DegService, Depends(get_deg_service)]


async def _read_upload(upload: UploadFile, label: str) -> tuple[bytes, str]:
    data = await upload.read()
    filename = upload.filename or ""
    await upload.close()
    if not data:
        from cygnusx.core.exceptions import ValidationError

        raise ValidationError(f"{label}为空文件")
    return data, filename


@router.get("/defaults", response_model=DegDefaultsDTO, summary="获取 DEG 默认参数")
async def get_deg_defaults(
    _user: CurrentUserId,
    service: DegServiceDep,
) -> DegDefaultsDTO:
    """返回外置 YAML 中的默认分析参数，供前端表单初始化。"""
    return service.get_defaults()


@router.get("/examples", summary="获取 DEG 示例输入")
async def get_deg_examples(
    _user: CurrentUserId,
    service: DegServiceDep,
) -> dict[str, str]:
    """返回示例 counts/metadata/pairs/annotation 的 CSV 文本，前端一键填充。"""
    return await service.get_example()


@router.post("/submit", response_model=DegTaskDTO, summary="提交 DEG 分析任务")
async def submit_deg(
    current_user_id: CurrentUserId,
    db: DbSession,
    service: DegServiceDep,
    project_name: Annotated[str, Form(min_length=1, max_length=100, description="项目名称")],
    counts_file: Annotated[UploadFile, File(description="Raw Counts 表达矩阵（首列 GeneID）")],
    metadata_file: Annotated[UploadFile, File(description="样本信息表（Sample, Group）")],
    pairs_file: Annotated[UploadFile, File(description="比较对文件（Treat, Control）")],
    annotation_file: Annotated[
        UploadFile | None, File(description="可选基因注释（首列 ID，可含 Symbol）")
    ] = None,
    method: Annotated[str, Form(description="auto | deseq2 | edger")] = "auto",
    lfc: Annotated[float, Form(ge=0, description="|log2FC| 阈值")] = 1.0,
    pval: Annotated[float, Form(gt=0, le=1, description="Raw P-value 阈值")] = 0.05,
    bcv: Annotated[float, Form(gt=0, description="edgeR 无重复对比 BCV")] = 0.4,
) -> DegTaskDTO:
    """提交 DEG Celery 任务，立即返回任务 ID 与解析出的引擎。"""
    counts_bytes, counts_name = await _read_upload(counts_file, "表达矩阵")
    metadata_bytes, metadata_name = await _read_upload(metadata_file, "样本信息表")
    pairs_bytes, pairs_name = await _read_upload(pairs_file, "比较对文件")
    annotation_bytes: bytes | None = None
    annotation_name: str | None = None
    if annotation_file is not None:
        annotation_bytes, annotation_name = await _read_upload(annotation_file, "注释文件")

    return await service.submit(
        db=db,
        user_id=current_user_id,
        project_name=project_name,
        counts_bytes=counts_bytes,
        counts_filename=counts_name,
        metadata_bytes=metadata_bytes,
        metadata_filename=metadata_name,
        pairs_bytes=pairs_bytes,
        pairs_filename=pairs_name,
        annotation_bytes=annotation_bytes,
        annotation_filename=annotation_name,
        method=method,
        lfc=lfc,
        pval=pval,
        bcv=bcv,
    )


@router.get("/tasks", response_model=DegTaskListResponse, summary="获取当前用户 DEG 历史")
async def list_deg_tasks(
    current_user_id: CurrentUserId,
    db: DbSession,
    service: DegServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> DegTaskListResponse:
    """返回当前用户最近的 DEG 任务；结果按需通过任务详情加载。"""
    return DegTaskListResponse(
        data=await service.list_tasks(db=db, user_id=current_user_id, limit=limit)
    )


@router.get("/tasks/{task_id}", response_model=DegTaskDTO, summary="查询 DEG 分析任务")
async def get_deg_task(
    current_user_id: CurrentUserId,
    db: DbSession,
    task_id: str,
    service: DegServiceDep,
) -> DegTaskDTO:
    """返回任务状态；完成时在 result 中返回统计表、Top 基因与产物名单。"""
    return await service.get_task(db=db, task_id=task_id, user_id=current_user_id)


@router.get("/tasks/{task_id}/artifacts/{filename}", summary="下载 DEG 结果产物")
async def download_deg_artifact(
    current_user_id: CurrentUserId,
    db: DbSession,
    task_id: str,
    filename: str,
    service: DegServiceDep,
) -> FileResponse:
    """下载任务结果目录内的单个产物（DEG CSV / 火山图 / PCA / 日志）。"""
    path, name = await service.get_artifact(
        db=db, task_id=task_id, user_id=current_user_id, filename=filename
    )
    media_type = _MEDIA_TYPES.get(Path(name).suffix.lower(), "application/octet-stream")
    return FileResponse(path, filename=name, media_type=media_type)

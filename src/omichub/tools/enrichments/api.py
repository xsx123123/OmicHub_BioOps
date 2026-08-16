"""富集分析（KEGG / GO）路由 —— 物种列表 + 提交分析。

- GET  /enrichment/species   返回 YAML 中 enabled 物种
- POST /enrichment/submit     multipart 提交，返回已入队 Celery 任务
- GET  /enrichment/tasks      返回当前用户历史任务
- GET  /enrichment/tasks/{id} 查询状态；完成时返回标准结果表
- GET  /enrichment/tasks/{id}/download 下载原始 clusterProfiler CSV

鉴权：所有接口要求登录（CurrentUserId）。结果落到 /data/omichub/users/{user_id}/
enrichments/{project}/{task_id}/，user_id 取自 JWT，不信任查询参数。

物种三字码 / OrgDb / ID 类型由后端按 species_id 从 YAML 权威解析，前端回传的同名
字段仅为展示，不参与容器调用（防篡改）。
"""

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from fastapi.responses import FileResponse

from omichub.api.deps import CurrentUserId, DbSession
from omichub.tools.enrichments.schema import (
    EnrichmentExampleDTO,
    EnrichmentTaskDTO,
    EnrichmentTaskListResponse,
    SpeciesListResponse,
)
from omichub.tools.enrichments.service import EnrichmentService

# 路由元数据：供 omichub.tools.register_tool_routers 自动发现挂载
prefix = "/enrichment"
tags = ["Enrichment 富集分析"]

router = APIRouter()


@lru_cache(maxsize=1)
def get_enrichment_service() -> EnrichmentService:
    """获取 EnrichmentService 单例（无状态，配置自带 mtime 热重载）。"""
    return EnrichmentService()


EnrichmentServiceDep = Annotated[EnrichmentService, Depends(get_enrichment_service)]


@router.get("/species", response_model=SpeciesListResponse, summary="获取可用物种列表")
async def list_species(
    _user: CurrentUserId,
    service: EnrichmentServiceDep,
) -> SpeciesListResponse:
    """返回 YAML 中 enabled=true 的物种（前端下拉数据源）。"""
    species = service.list_species()
    return SpeciesListResponse(data=species)


@router.get("/examples/cop1-hy5-dependent", response_model=EnrichmentExampleDTO, summary="获取 COP1/HY5 富集示例")
async def get_cop1_hy5_example(
    _user: CurrentUserId,
    service: EnrichmentServiceDep,
) -> EnrichmentExampleDTO:
    """返回指定 1576 Gene ID CSV 和对应的真实 R 富集结果。"""
    return await service.get_example()


@router.post("/submit", response_model=EnrichmentTaskDTO, summary="提交富集分析任务")
async def submit_enrichment(
    current_user_id: CurrentUserId,
    db: DbSession,
    service: EnrichmentServiceDep,
    species_id: Annotated[str, Form(description="物种 ID（YAML 中 id）")],
    project_name: Annotated[str, Form(min_length=1, max_length=100, description="用户项目 ID")],
    p_value_cutoff: Annotated[float, Form(gt=0, le=1, description="clusterProfiler p-valueCutoff")] = 0.05,
    q_value_cutoff: Annotated[float, Form(gt=0, le=1, description="clusterProfiler qvalueCutoff")] = 0.1,
    gene_text: Annotated[str | None, Form(description="手动输入的基因 ID 列表，每行一个")] = None,
    gene_file: Annotated[
        UploadFile | None, File(description="仅含 Gene ID 一列的 CSV/TSV 文件")
    ] = None,
) -> EnrichmentTaskDTO:
    """提交 GO / KEGG 富集 Celery 任务，立即返回任务 ID。

    基因列表支持文本（gene_text）或文件（gene_file）二选一；同时提供时以文件为准。
    物种参数由后端按 species_id 从配置解析，容器调用前不使用前端回传的 kegg_code 等。
    """
    file_bytes: bytes | None = None
    filename: str | None = None
    if gene_file is not None:
        file_bytes = await gene_file.read()
        filename = gene_file.filename
        await gene_file.close()
    return await service.submit(
        db=db,
        user_id=current_user_id,
        species_id=species_id,
        gene_text=gene_text,
        gene_file_bytes=file_bytes,
        gene_filename=filename,
        project_name=project_name,
        p_value_cutoff=p_value_cutoff,
        q_value_cutoff=q_value_cutoff,
    )


@router.get("/tasks", response_model=EnrichmentTaskListResponse, summary="获取当前用户富集历史")
async def list_enrichment_tasks(
    current_user_id: CurrentUserId,
    db: DbSession,
    service: EnrichmentServiceDep,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> EnrichmentTaskListResponse:
    """返回当前用户最近的富集任务；结果表按需通过任务详情加载。"""
    return EnrichmentTaskListResponse(
        data=await service.list_tasks(db=db, user_id=current_user_id, limit=limit)
    )


@router.get("/tasks/{task_id}", response_model=EnrichmentTaskDTO, summary="查询富集分析任务")
async def get_enrichment_task(
    current_user_id: CurrentUserId,
    db: DbSession,
    task_id: str,
    service: EnrichmentServiceDep,
) -> EnrichmentTaskDTO:
    """返回任务队列状态；完成时在 result 中返回标准富集结果行。"""
    return await service.get_task(db=db, task_id=task_id, user_id=current_user_id)


@router.get("/tasks/{task_id}/download", summary="下载富集原始 CSV")
async def download_enrichment_result(
    current_user_id: CurrentUserId,
    db: DbSession,
    task_id: str,
    service: EnrichmentServiceDep,
) -> FileResponse:
    """下载 R/clusterProfiler 容器生成的原始标准结果文件。"""
    path, filename = await service.get_result_file(db=db, task_id=task_id, user_id=current_user_id)
    return FileResponse(path, filename=filename, media_type="text/csv; charset=utf-8")

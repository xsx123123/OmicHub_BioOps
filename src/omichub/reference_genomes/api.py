"""参考基因组模块路由 —— 物种 / 版本 / 基因 / 序列 / GO / KEGG / 搜索 / 批量 / 映射 / 重载。

鉴权：
- 查询类端点：Depends CurrentUserId（登录即可）；
- POST /reload：Depends AdminRequired + CurrentUserId（管理员）。

响应：全部同步 def（FastAPI 自动丢线程池），SQLite 阻塞 IO 无碍。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from omichub.api.deps import CurrentUserId
from omichub.core.exceptions import ValidationError
from omichub.middleware.rbac import AdminRequired
from omichub.reference_genomes import service
from omichub.reference_genomes.schema import (
    BatchAnnotationResponse,
    BatchGeneRequest,
    GeneDetailDTO,
    GeneListResponse,
    GoGeneListResponse,
    GoTermListResponse,
    KeggPathwayListResponse,
    MapIdsRequest,
    MapIdsResponse,
    PathwayGeneListResponse,
    ReloadResponse,
    SearchResponse,
    SequenceDTO,
    SpeciesListResponse,
    VersionDetailDTO,
)

# 路由元数据：供 omichub.api.v1.router 自动发现挂载
prefix = "/reference-genomes"
tags = ["参考基因组"]

router = APIRouter()


# ============================================================
# 1. 物种列表
# ============================================================


@router.get("/species", response_model=SpeciesListResponse, summary="物种列表（含版本与文件审计）")
def list_species(
    _user: CurrentUserId,
) -> SpeciesListResponse:
    return service.list_species()


# ============================================================
# 2. 版本详情
# ============================================================


@router.get(
    "/versions/{version_id}",
    response_model=VersionDetailDTO,
    summary="版本详情（染色体 + 基因类型统计 + 文件审计）",
)
def get_version_detail(
    version_id: str,
    _user: CurrentUserId,
) -> VersionDetailDTO:
    return service.get_version_detail(version_id)


# ============================================================
# 3. 基因搜索
# ============================================================


@router.get(
    "/versions/{version_id}/genes",
    response_model=GeneListResponse,
    summary="基因搜索（支持 gene_id / gene_name / annotation / go / kegg / all）",
)
def search_genes(
    version_id: str,
    _user: CurrentUserId,
    field: str = Query(default="all", pattern="^(gene_id|gene_name|annotation|go|kegg|all)$"),
    q: str = Query(default=""),
    chromosome: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> GeneListResponse:
    # q 允许为空 = 浏览模式（分页列出全部基因）；但 go/kegg 反查必须有查询词
    if not q or not q.strip():
        if field in ("go", "kegg"):
            raise ValidationError("go/kegg 反查需要提供 q（GO ID/term 名 或 KO/pathway）")
        return service.search_genes(version_id, field, "", chromosome, page, page_size)
    return service.search_genes(version_id, field, q.strip(), chromosome, page, page_size)


# ============================================================
# 4. 基因详情
# ============================================================


@router.get(
    "/versions/{version_id}/genes/{gene_id}",
    response_model=GeneDetailDTO,
    summary="基因详情（转录本 + GO + KEGG + 序列可用性）",
)
def get_gene_detail(
    version_id: str,
    gene_id: str,
    _user: CurrentUserId,
) -> GeneDetailDTO:
    return service.get_gene_detail(version_id, gene_id)


# ============================================================
# 5. 基因序列
# ============================================================


@router.get(
    "/versions/{version_id}/genes/{gene_id}/sequence",
    summary="基因序列（genomic / cds / protein；json / fasta）",
)
def get_gene_sequence(
    version_id: str,
    gene_id: str,
    _user: CurrentUserId,
    type: str = Query(default="genomic", pattern="^(genomic|cds|protein)$"),
    format: str = Query(default="json", pattern="^(json|fasta)$"),
) -> SequenceDTO:
    # format=fasta 时返回 PlainTextResponse（FastAPI 对 Response 实例直接透传，
    # 不走 response_model 序列化）；json 时返回 SequenceDTO（camelCase alias 输出）
    result = service.get_gene_sequence(version_id, gene_id, type, format)
    if isinstance(result, str):
        return PlainTextResponse(content=result, media_type="text/plain")
    return result


# ============================================================
# 6. 区间序列
# ============================================================


@router.get(
    "/versions/{version_id}/sequence",
    summary="区间序列（上限 1 Mb；json / fasta）",
)
def get_region_sequence(
    version_id: str,
    _user: CurrentUserId,
    chrom: str = Query(...),
    start: int = Query(..., ge=1),
    end: int = Query(..., ge=1),
    strand: str = Query(default="+", pattern="^[+\\-]$"),
    format: str = Query(default="json", pattern="^(json|fasta)$"),
) -> SequenceDTO:
    # 同上：fasta 返回 PlainTextResponse 透传，json 走 SequenceDTO 序列化
    result = service.get_region_sequence(version_id, chrom, start, end, strand, format)
    if isinstance(result, str):
        return PlainTextResponse(content=result, media_type="text/plain")
    return result


# ============================================================
# 7. GO term 列表
# ============================================================


@router.get(
    "/versions/{version_id}/go",
    response_model=GoTermListResponse,
    summary="GO term 列表（按 gene_count 降序）",
)
def list_go_terms(
    version_id: str,
    _user: CurrentUserId,
    q: str = Query(default=""),
    aspect: str = Query(default="", pattern="^([FPC]|)$"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> GoTermListResponse:
    return service.list_go_terms(version_id, q, aspect, page, page_size)


# ============================================================
# 8. KEGG pathway 列表
# ============================================================


@router.get(
    "/versions/{version_id}/kegg/pathways",
    response_model=KeggPathwayListResponse,
    summary="KEGG pathway 列表",
)
def list_kegg_pathways(
    version_id: str,
    _user: CurrentUserId,
    q: str = Query(default=""),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> KeggPathwayListResponse:
    return service.list_kegg_pathways(version_id, q, page, page_size)


# ============================================================
# 9. GO 反查基因
# ============================================================


@router.get(
    "/versions/{version_id}/go/{go_id}/genes",
    response_model=GoGeneListResponse,
    summary="GO term 关联基因列表",
)
def list_go_genes(
    version_id: str,
    go_id: str,
    _user: CurrentUserId,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> GoGeneListResponse:
    return service.list_go_genes(version_id, go_id, page, page_size)


# ============================================================
# 10. KEGG pathway 反查基因
# ============================================================


@router.get(
    "/versions/{version_id}/kegg/pathways/{pathway_id}/genes",
    response_model=PathwayGeneListResponse,
    summary="KEGG pathway 关联基因列表",
)
def list_pathway_genes(
    version_id: str,
    pathway_id: str,
    _user: CurrentUserId,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> PathwayGeneListResponse:
    return service.list_pathway_genes(version_id, pathway_id, page, page_size)


# ============================================================
# 11. 单版本搜索
# ============================================================


@router.get(
    "/versions/{version_id}/search",
    response_model=SearchResponse,
    summary="单版本内搜索（基因 + GO + KEGG）",
)
def search_version(
    version_id: str,
    _user: CurrentUserId,
    q: str = Query(default=""),
    limit: int = Query(default=10, ge=1, le=50),
) -> SearchResponse:
    if not q or not q.strip():
        raise ValidationError("查询参数 q 不能为空")
    return service.search_version(version_id, q.strip(), limit)


# ============================================================
# 12. 全局搜索
# ============================================================


@router.get(
    "/search",
    response_model=SearchResponse,
    summary="跨版本全局搜索（基因 + GO + KEGG + 物种）",
)
def search_global(
    _user: CurrentUserId,
    q: str = Query(default=""),
    species: str | None = Query(default=None),
    limit: int = Query(default=10, ge=1, le=50),
) -> SearchResponse:
    if not q or not q.strip():
        raise ValidationError("查询参数 q 不能为空")
    return service.search_global(q.strip(), species, limit)


# ============================================================
# 13. 批量注释
# ============================================================


@router.post(
    "/versions/{version_id}/genes/batch",
    response_model=BatchAnnotationResponse,
    summary="批量基因注释查询（上限 500 ID）",
)
def batch_gene_annotation(
    version_id: str,
    _user: CurrentUserId,
    body: BatchGeneRequest,
) -> BatchAnnotationResponse:
    return service.batch_gene_annotation(version_id, body.gene_ids)


# ============================================================
# 14. ID 映射
# ============================================================


@router.post(
    "/versions/{version_id}/map-ids",
    response_model=MapIdsResponse,
    summary="跨版本基因 ID 映射",
)
def map_ids(
    version_id: str,
    _user: CurrentUserId,
    body: MapIdsRequest,
) -> MapIdsResponse:
    return service.map_ids(version_id, body.target_version_id, body.ids)


# ============================================================
# 15. 管理员重载配置
# ============================================================


@router.post(
    "/reload",
    response_model=ReloadResponse,
    summary="强制重载 YAML 配置（管理员）",
)
def reload_config(
    _admin: AdminRequired,
    _user: CurrentUserId,
) -> ReloadResponse:
    return service.reload_config()

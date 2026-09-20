"""富集分析（KEGG / GO）Schema —— 物种选项 / 富集结果行 / 提交结果 DTO。

字段命名与前端 `frontend/src/types/enrichment.ts` 对齐：
- SpeciesOption 用 `label`（非方案文档的 display_name），以前端为准；
- 新任务返回标准结果行，前端按 GO / KEGG 分组并分别构建 Plotly 图。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field

from cygnusx.application.schemas.base import CygnusXBaseSchema


class SpeciesOptionDTO(CygnusXBaseSchema):
    """物种下拉选项（前端 SpeciesOption）。

    仅暴露前端渲染所需字段；kegg_rdata / kegg_supported 等离线扩展字段
    留在配置层不外泄，待后续离线 fallback 启用时再加。
    """

    id: str
    label: str
    kegg_code: str
    org_db: str
    id_type: str
    analysis_types: list[str] = []
    default_p_value_cutoff: float = 0.05
    default_q_value_cutoff: float = 0.1


class SpeciesListResponse(CygnusXBaseSchema):
    """GET /enrichment/species 响应包络（前端解 { data: [...] }）。"""

    data: list[SpeciesOptionDTO] = []


class EnrichmentRowDTO(CygnusXBaseSchema):
    """单条富集结果（前端 EnrichmentRow）。

    字段映射自 clusterProfiler GO / KEGG 标准化输出列：
      ID → id, Description → description, GeneRatio → gene_ratio,
      pvalue → pvalue, p.adjust → p_adjust, Count → count。
    """

    id: str
    description: str
    gene_ratio: str
    pvalue: float
    p_adjust: float
    q_value: float = 0.0
    count: int
    source: str = "Unknown"


class EnrichmentResultDTO(CygnusXBaseSchema):
    """完成后的富集分析结果。

    - task_id：UUID 关联 ID（同时是结果目录名 / CSV 导出文件名后缀）。
    - plotly_json：兼容旧任务的历史字段；新页面不消费合并图。
    - table_data：完整富集结果行，前端按 GO / KEGG 分组后分别绘图和展示表格。
    """

    task_id: str
    plotly_json: dict[str, Any] | None = None
    table_data: list[EnrichmentRowDTO] = Field(default_factory=list)


class EnrichmentExampleDTO(CygnusXBaseSchema):
    """可直接载入页面的真实富集示例输入与结果。"""

    id: str
    title: str
    species_id: str
    gene_count: int
    gene_text: str
    p_value_cutoff: float
    q_value_cutoff: float
    result: EnrichmentResultDTO


EnrichmentTaskStatus = Literal["queued", "running", "completed", "failed"]


class EnrichmentTaskDTO(CygnusXBaseSchema):
    """富集 Celery 任务状态；完成时携带前端渲染所需结果。"""

    task_id: str
    status: EnrichmentTaskStatus
    progress: int = 0
    message: str = ""
    error_message: str | None = None
    result: EnrichmentResultDTO | None = None
    project_name: str = ""
    species_id: str = ""
    gene_count: int = 0
    created_at: datetime | None = None
    finished_at: datetime | None = None


class EnrichmentTaskListResponse(CygnusXBaseSchema):
    """当前用户的富集任务历史，按创建时间倒序。"""

    data: list[EnrichmentTaskDTO] = Field(default_factory=list)

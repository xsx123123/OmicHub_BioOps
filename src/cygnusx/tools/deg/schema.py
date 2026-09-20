"""DEG 差异表达分析 Schema —— 提交 / 任务状态 / 结果 DTO。

结果结构：
- statistics：每对比一行的汇总表（对应 R 脚本 All_Contrast_DEG_Statistics.csv）；
- contrasts：每对比的 Top 基因行 + 产物文件名（火山图 / 结果 CSV）；
- artifacts：结果目录内全部可下载文件名（前端经 /tasks/{id}/artifacts/{name} 下载）。

字段命名与前端 `frontend/src/types/deg.ts` 对齐。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field

from cygnusx.application.schemas.base import CygnusXBaseSchema

DegMethodLiteral = Literal["auto", "deseq2", "edger"]
DegEngineLiteral = Literal["deseq2", "edger"]


class DegDefaultsDTO(CygnusXBaseSchema):
    """GET /deg/defaults —— 前端表单默认值与方法选项。"""

    method: DegMethodLiteral = "auto"
    lfc: float = 1.0
    pval: float = 0.05
    bcv: float = 0.4
    min_replicates: int = 2
    max_counts_file_size_mb: int = 200
    max_metadata_file_size_mb: int = 5
    max_pairs_file_size_mb: int = 5
    max_annotation_file_size_mb: int = 50
    min_samples: int = 2
    max_samples: int = 500
    max_contrasts: int = 50
    max_genes: int = 100_000


class DegContrastStatDTO(CygnusXBaseSchema):
    """单个比较对的统计汇总行（All_Contrast_DEG_Statistics.csv 的一行）。"""

    contrast: str                       # {Treat}_vs_{Control}
    control: str
    treat: str
    method: str = ""                    # edgeR 引擎记录 edgeR-QLF / edgeR-NoRep；DESeq2 为空
    dispersion_assumption: str = ""     # edgeR 记录 BCV 假设
    n_control: int = 0
    n_treat: int = 0
    up_regulated: int = 0
    down_regulated: int = 0
    total_deg: int = 0


class DegGeneRowDTO(CygnusXBaseSchema):
    """差异结果表的一行（{Treat}_vs_{Control}_DEG.csv）。

    base_mean（DESeq2）与 log_cpm（edgeR）互斥出现，缺失为 None。
    """

    ensembl: str
    symbol: str = ""
    log2_fc: float = 0.0
    pvalue: float = 1.0
    padj: float | None = None
    base_mean: float | None = None
    log_cpm: float | None = None


class DegContrastResultDTO(CygnusXBaseSchema):
    """单个比较对的结果：Top 基因行 + 产物文件名。"""

    name: str                           # {Treat}_vs_{Control}
    stat: DegContrastStatDTO
    top_genes: list[DegGeneRowDTO] = Field(default_factory=list)
    total_genes: int = 0                # 结果表全量行数（CSV 下载获取全量）
    deg_csv: str = ""                   # {name}_DEG.csv
    volcano_png: str = ""               # {name}_Volcano.png
    volcano_labeled_png: str = ""       # {name}_Volcano_add_gene_id.png


class DegResultDTO(CygnusXBaseSchema):
    """完成后的 DEG 分析结果。"""

    task_id: str
    engine: DegEngineLiteral            # 实际使用的引擎（auto 解析后的结果）
    no_replicate_contrasts: list[str] = Field(default_factory=list)
    statistics: list[DegContrastStatDTO] = Field(default_factory=list)
    contrasts: list[DegContrastResultDTO] = Field(default_factory=list)
    pca_png: str = ""                   # Global_PCA_Combined.png
    artifacts: list[str] = Field(default_factory=list)   # 结果目录可下载文件全名单
    log_file: str = ""                  # deseq2.log / edger.log


DegTaskStatus = Literal["queued", "running", "completed", "failed"]


class DegTaskDTO(CygnusXBaseSchema):
    """DEG Celery 任务状态；完成时携带结果。"""

    task_id: str
    status: str                         # queued | running | completed | failed
    progress: int = 0
    message: str = ""
    error_message: str | None = None
    result: DegResultDTO | None = None
    project_name: str = ""
    method_requested: DegMethodLiteral = "auto"
    engine_resolved: DegEngineLiteral | None = None       # 提交期解析出的引擎
    no_replicate_contrasts: list[str] = Field(default_factory=list)
    sample_count: int = 0
    contrast_count: int = 0
    created_at: datetime | None = None
    finished_at: datetime | None = None


class DegTaskListResponse(CygnusXBaseSchema):
    """当前用户的 DEG 任务历史，按创建时间倒序。"""

    data: list[DegTaskDTO] = Field(default_factory=list)

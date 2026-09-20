"""系统发育树工具 Schema —— 与前端 types/phylo.ts 对齐。"""

from __future__ import annotations

from typing import Any

from pydantic import Field, field_validator

from cygnusx.application.schemas.base import CygnusXBaseSchema


class TreeStatisticsDTO(CygnusXBaseSchema):
    """树统计信息（前端 TreeStatistics）。"""

    sequence_count: int = 0
    total_branches: int = 0
    total_tree_length: float = 0.0
    mean_branch_length: float = 0.0
    tree_height: float = 0.0
    min_bootstrap: float = 0.0
    max_bootstrap: float = 0.0
    avg_bootstrap: float = 0.0
    has_bootstrap_support: bool = False


class PhyloUploadResponse(CygnusXBaseSchema):
    """上传序列/Newick 文件后返回。"""

    file_id: str
    file_path: str
    filename: str
    format: str  # fasta | phylip | nexus | newick
    sequence_count: int | None = None
    sequence_type: str | None = None  # DNA | Protein | unknown
    total_length: int | None = None
    is_aligned: bool | None = None


class PhyloSubmitRequest(CygnusXBaseSchema):
    """提交树构建任务参数。"""

    file_id: str
    project_name: str = Field(min_length=1, max_length=128, description="用户提供的项目名称")
    alignment_tool: str = "mafft"  # mafft | clustalo | muscle5 | prealigned
    alignment_mode: str = "auto"
    tree_method: str = "iqtree"  # nj | upgma | fasttree | iqtree | mrbayes
    substitution_model: str = "auto"
    bootstrap_enabled: bool = True
    bootstrap_type: str = "ultrafast"  # standard | ultrafast
    bootstrap_replicates: int = 1000
    sequence_type: str = "auto"  # auto | dna | protein
    advanced_params: str = ""

    @field_validator("project_name")
    @classmethod
    def require_project_name(cls, value: str) -> str:
        project_name = value.strip()
        if not project_name:
            raise ValueError("项目名称不能为空")
        return project_name


class PhyloTaskResponse(CygnusXBaseSchema):
    """任务状态/进度响应。"""

    task_id: str
    status: str  # PENDING | PROGRESS | SUCCESS | FAILURE | REVOKED
    phase: str | None = None
    progress: float = 0.0
    message: str = ""
    result: dict[str, Any] | None = None


class PhyloResultDTO(CygnusXBaseSchema):
    """任务成功后的结果摘要。"""

    task_id: str
    status: str
    output_files: dict[str, str]
    statistics: TreeStatisticsDTO
    execution_time: float
    phases_completed: list[str]


class PhyloDownloadResponse(CygnusXBaseSchema):
    """下载结果文件响应（实际走 FileResponse，此 DTO 用于文档）。"""

    task_id: str
    format: str
    download_url: str


class PhyloMethodOptionDTO(CygnusXBaseSchema):
    """下拉选项。"""

    key: str
    label: str
    description: str = ""
    supports_bootstrap: bool | None = None


class PhyloMethodsResponse(CygnusXBaseSchema):
    """GET /methods 返回支持的构建方法矩阵。"""

    alignment_tools: list[PhyloMethodOptionDTO] = []
    tree_methods: list[PhyloMethodOptionDTO] = []
    substitution_models: dict[str, list[str]] = {}
    bootstrap_types: list[PhyloMethodOptionDTO] = []
    presets: dict[str, dict[str, Any]] = {}


class PhyloValidateRequest(CygnusXBaseSchema):
    """参数合法性预校验请求。"""

    alignment_tool: str
    tree_method: str
    substitution_model: str
    bootstrap_enabled: bool
    bootstrap_type: str
    bootstrap_replicates: int


class PhyloValidateResponse(CygnusXBaseSchema):
    """参数合法性预校验响应。"""

    valid: bool
    message: str = ""

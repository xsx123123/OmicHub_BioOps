"""BLAST 工具 Schema —— 与前端 types/blast.ts 对齐。"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import Field, field_validator

from omichub.application.schemas.base import OmicsHubBaseSchema

ProgramType = Literal["blastn", "blastp", "blastx", "tblastn", "tblastx"]
DbType = Literal["nucl", "prot"]
TaskStatus = Literal["queued", "running", "completed", "failed", "cancelled", "cleaned"]
BuildStatus = Literal["pending", "building", "ready", "failed", "deprecated"]
ResultFormat = Literal["json", "xml", "text", "summary"]


class BlastDatabaseDTO(OmicsHubBaseSchema):
    """BLAST 数据库元数据 DTO。"""

    id: str
    name: str = Field(min_length=1, max_length=128)
    db_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    db_type: DbType
    source_species: str | None = None
    source_version: str | None = None
    version_group: str
    is_active: bool = False
    file_path: str
    file_size_mb: float = 0.0
    sequence_count: int = 0
    build_status: BuildStatus = "pending"
    is_public: bool = True
    created_at: datetime
    updated_at: datetime | None = None

    @field_validator("id", mode="before")
    @classmethod
    def _uuid_to_str(cls, value: Any) -> str:
        """数据库 UUID 字段兼容字符串输出。"""
        if isinstance(value, uuid.UUID):
            return str(value)
        return value


class BlastDatabaseCreateRequest(OmicsHubBaseSchema):
    """管理员创建数据库请求。"""

    name: str = Field(min_length=1, max_length=128)
    db_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9_]+$")
    db_type: DbType = "nucl"
    source_species: str | None = None
    source_version: str | None = None
    version_group: str | None = Field(default=None, max_length=64, pattern=r"^[a-z0-9_]+$")
    is_public: bool = True


class BlastDatabaseUploadInitRequest(BlastDatabaseCreateRequest):
    """初始化数据库分片上传。"""

    filename: str = Field(min_length=1, max_length=255)
    total_size: int = Field(gt=0)


class BlastDatabaseUploadInitResponse(OmicsHubBaseSchema):
    """数据库分片上传会话。"""

    upload_id: str
    chunk_size_bytes: int
    total_chunks: int


class BlastHspDTO(OmicsHubBaseSchema):
    """单个 HSP 摘要信息。"""

    query_from: int = 0
    query_to: int = 0
    hit_from: int = 0
    hit_to: int = 0
    identity_percent: float = 0.0
    evalue: float = 0.0
    bit_score: float = 0.0


class BlastHspDetailDTO(OmicsHubBaseSchema):
    """单个 HSP 完整信息（含序列对齐）。"""

    hsp_num: int = 0
    bit_score: float = 0.0
    evalue: float = 0.0
    query_from: int = 0
    query_to: int = 0
    hit_from: int = 0
    hit_to: int = 0
    identity: int = 0
    align_length: int = 0
    mismatches: int = 0
    gaps: int = 0
    query_seq: str = ""
    hit_seq: str = ""
    midline: str = ""
    identity_percent: float = 0.0


class BlastHitDTO(OmicsHubBaseSchema):
    """单个 BLAST 命中结果。"""

    # 兼容旧版字段
    query_id: str = ""
    subject_id: str = ""
    identity: float = 0.0
    align_length: int = 0
    mismatches: int = 0
    gap_opens: int = 0
    q_start: int = 0
    q_end: int = 0
    s_start: int = 0
    s_end: int = 0
    evalue: float = 0.0
    bit_score: float = 0.0
    score: int | None = None
    query_seq: str | None = None
    subject_seq: str | None = None
    midline: str | None = None

    # 新增可视化所需字段
    hit_num: int = 0
    hit_id: str = ""
    hit_def: str = ""
    hit_accession: str = ""
    hit_len: int = 0
    identity_percent: float = 0.0
    query_coverage: float = 0.0
    subject_coverage: float = 0.0
    total_score: float = 0.0
    best_hsp: BlastHspDetailDTO | None = None
    hsps: list[BlastHspDTO] = []


class BlastStatisticsDTO(OmicsHubBaseSchema):
    """BLAST 结果统计摘要。"""

    hit_count: int = 0
    top_hit_identity: float | None = None
    top_hit_evalue: float | None = None
    db_name: str = ""
    program: str = ""
    query_title: str = ""


class BlastResultDTO(OmicsHubBaseSchema):
    """BLAST 查询结果响应。"""

    task_id: str
    status: TaskStatus
    hits: list[BlastHitDTO] = []
    statistics: BlastStatisticsDTO
    result_path: str | None = None
    xml_url: str | None = None
    json_url: str | None = None
    text_url: str | None = None
    query_len: int = 0
    program: str = ""
    db_name: str = ""
    query_def: str = ""
    db_display_name: str = ""
    query_params: dict[str, Any] = {}


class BlastTaskResponse(OmicsHubBaseSchema):
    """任务状态/进度响应。"""

    task_id: str
    status: TaskStatus
    progress: int = 0
    message: str = ""
    error_message: str | None = None
    result: BlastResultDTO | None = None
    submitted_at: datetime | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    db_id: str | None = None
    query_sequence: str | None = None
    query_title: str | None = None
    program: ProgramType | None = None
    evalue: float | None = None
    max_target_seqs: int | None = None
    word_size: int | None = None
    gapopen: int | None = None
    gapextend: int | None = None
    result_format: ResultFormat | None = None


class BlastSubmitRequest(OmicsHubBaseSchema):
    """提交 BLAST 查询任务请求。"""

    db_id: str
    project_name: str = Field(min_length=1, max_length=100, description="用户提供的项目名称")
    query_sequence: str | None = None
    query_title: str = Field(default="Untitled Query", max_length=256)
    program: ProgramType | None = None
    evalue: float = Field(default=1e-5, gt=0, le=10)
    max_target_seqs: int = Field(default=10, ge=1, le=100)
    word_size: int | None = Field(default=None, ge=2, le=1000)
    gapopen: int | None = Field(default=None, ge=0, le=1000)
    gapextend: int | None = Field(default=None, ge=0, le=1000)
    result_format: ResultFormat = "json"


class BlastBuildStatusResponse(OmicsHubBaseSchema):
    """数据库构建状态响应。"""

    db_id: str
    build_status: BuildStatus
    progress: int = 0
    sequence_count: int = 0
    file_size_mb: float = 0.0
    build_log: str | None = None


class BlastMethodsResponse(OmicsHubBaseSchema):
    """GET /methods 返回支持的 program 与默认参数。"""

    programs: list[dict[str, Any]] = []
    db_types: list[str] = ["nucl", "prot"]
    defaults: dict[str, Any] = {}


class BlastTaskListItemDTO(OmicsHubBaseSchema):
    """任务列表单项。"""

    task_id: str
    # 所属用户：列表卡片「所属用户」列展示用，由服务层按 user_id 回填。
    user_id: str | None = None
    username: str | None = None
    nickname: str | None = None
    db_id: str
    db_name: str
    program: str
    query_title: str | None = None
    status: TaskStatus
    progress: int = 0
    hit_count: int | None = None
    top_hit_identity: float | None = None
    top_hit_evalue: float | None = None
    submitted_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None


class BlastTaskListResponse(OmicsHubBaseSchema):
    """任务列表分页响应。"""

    items: list[BlastTaskListItemDTO] = []
    total: int = 0
    page: int = 1
    page_size: int = 20


class BlastAdminTaskListResponse(OmicsHubBaseSchema):
    """管理员任务列表分页响应。"""

    items: list[BlastTaskListItemDTO] = []
    total: int = 0
    page: int = 1
    page_size: int = 50

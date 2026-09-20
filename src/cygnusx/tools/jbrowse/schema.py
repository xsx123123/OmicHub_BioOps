"""JBrowse 2 Schema —— 参考基因组 / 扫描文件 / 上传结果 / 索引状态 DTO。

字段命名与 jbrowse_service 返回的 dict 对齐，便于 response_model 直接 model_validate。
"""

from __future__ import annotations

from typing import Any

from pydantic import Field

from cygnusx.application.schemas.base import CygnusXBaseSchema


class AssemblyDataFileDTO(CygnusXBaseSchema):
    """数据库模块数据文件描述（FASTA/GFF/GO/KEGG）。"""

    path: str
    index_path: str | None = None
    db_path: str | None = None
    format: str | None = None
    build_required: bool = False
    build_tool: str | None = None
    build_status: str = "ready"
    size: str | None = None


class AssemblyDTO(CygnusXBaseSchema):
    """参考基因组/数据库版本摘要（不含 FASTA 绝对路径，避免泄漏服务端目录）。"""

    id: str
    name: str
    species: str | None = None
    common_name: str | None = None
    taxonomy_id: str | None = None
    version_id: str | None = None
    version_name: str | None = None
    assembly_name: str | None = None
    category: str | None = None
    icon: str | None = None
    is_default: bool = False
    status: str = "active"
    release_date: str | None = None
    description: str | None = None
    stats: dict[str, Any] = Field(default_factory=dict)
    data_files: dict[str, AssemblyDataFileDTO] = Field(default_factory=dict)
    fasta_exists: bool = False
    fai_exists: bool = False
    aliases: list[str] = Field(default_factory=list)


class AssemblyDetailDTO(AssemblyDTO):
    """参考基因组详情（含绝对路径，供管理员/调试；普通用户一般用不到）。"""

    fasta: str = ""
    fai: str = ""


class AssemblyListResponse(CygnusXBaseSchema):
    assemblies: list[AssemblyDTO] = []


class PresetTrackDTO(CygnusXBaseSchema):
    name: str
    file: str
    type: str
    color: str | None = "#1565C0"
    file_exists: bool = False


class PresetTracksResponse(CygnusXBaseSchema):
    assembly_id: str
    tracks: list[PresetTrackDTO] = []


class ScannedFileDTO(CygnusXBaseSchema):
    """用户目录扫描结果项。"""

    path: str
    name: str
    type: str
    size: int
    size_human: str
    modified: str
    indexed: bool
    index_file: str | None = None
    can_load: bool = False


class ScanResponse(CygnusXBaseSchema):
    user_id: str
    scan_time: str
    total_files: int = 0
    indexed_count: int = 0
    files: list[ScannedFileDTO] = []


class UploadResultDTO(CygnusXBaseSchema):
    """单个文件上传结果。"""

    filename: str
    saved_path: str
    size: int
    size_human: str
    user_id: str
    assembly_id: str | None = None
    index_task_id: str | None = None
    index_status: str | None = None


class BatchUploadItemDTO(CygnusXBaseSchema):
    filename: str
    saved_path: str | None = None
    success: bool
    index_task_id: str | None = None
    error: str | None = None


class BatchUploadResponse(CygnusXBaseSchema):
    total: int = 0
    success: int = 0
    failed: int = 0
    results: list[BatchUploadItemDTO] = []


class IndexStatusDTO(CygnusXBaseSchema):
    """文件索引状态。"""

    file: str
    index_status: dict[str, Any]


class IndexTaskSubmitDTO(CygnusXBaseSchema):
    message: str
    task_id: str
    file: str
    status: str = "queued"


class IndexTaskStatusDTO(CygnusXBaseSchema):
    """Celery 索引任务状态。"""

    task_id: str
    status: str
    ready: bool
    successful: bool | None = None
    result: Any | None = None
    error: str | None = None


class ConfigReloadResponse(CygnusXBaseSchema):
    message: str
    assemblies_count: int = 0
    preset_tracks_count: int = 0
    auto_scan_enabled: bool = False

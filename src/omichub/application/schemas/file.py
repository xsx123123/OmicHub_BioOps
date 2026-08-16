"""Pydantic v2 DTO — 文件管理 / 分块上传 / 配额"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from omichub.domain.file.value_objects import FileType


class DataFileDTO(BaseModel):
    """文件列表项 DTO"""

    id: UUID
    original_name: str
    size: int
    file_type: FileType = FileType.OTHER
    status: str = "active"
    checksum: str = ""
    directory: str = ""
    path: str = ""
    source: str = "upload"
    owner_scope: str = "personal"
    team_id: UUID | None = None
    created_at: datetime
    modified_at: datetime


class DirectorySearchDTO(BaseModel):
    """工作区目录搜索结果。"""

    id: UUID
    path: str
    name: str
    parent_path: str | None = None
    is_system: bool = False


class FileListResponse(BaseModel):
    """文件列表响应"""

    items: list[DataFileDTO] = Field(default_factory=list)
    directories: list[DirectorySearchDTO] = Field(default_factory=list)
    total: int = 0


# ===== 配额 =====
class QuotaResponse(BaseModel):
    """存储配额信息"""

    used: int
    total: int
    percent: float


class SyncResponse(BaseModel):
    """文件同步结果 — 磁盘与文件记录对账统计"""

    added: int = 0
    added_size: int = 0
    removed: int = 0
    removed_size: int = 0
    renamed: int = 0


# ===== 分块上传 =====
class UploadInitRequest(BaseModel):
    """上传初始化请求"""

    file_name: str = Field(..., max_length=500)
    total_size: int = Field(..., ge=0)
    chunk_size: int = Field(..., gt=0)
    total_chunks: int = Field(..., gt=0)
    file_md5: str | None = Field(None, max_length=64)
    # 上传目标目录；默认 "" 会写入 inbox，自定义目录保持相对用户工作区。
    directory: str = Field("", max_length=500)


class UploadInitResponse(BaseModel):
    """上传初始化响应

    - completed=True 且 file_id 非空：秒传命中，无需再传
    - 否则 upload_id 为本次会话 ID，uploaded_chunks 为已传分片（断点续传）
    """

    upload_id: UUID
    completed: bool = False
    file_id: UUID | None = None
    uploaded_chunks: list[dict] = Field(default_factory=list)
    chunk_size: int = 0


class UploadChunkResponse(BaseModel):
    """分片上传响应"""

    upload_id: UUID
    index: int
    accepted: bool = True
    uploaded: int = 0  # 已传分片数


class UploadMergeRequest(BaseModel):
    """合并请求"""

    upload_id: UUID


class UploadMergeResponse(BaseModel):
    """合并响应"""

    file_id: UUID
    original_name: str
    size: int
    checksum: str
    used_storage: int


# ===== 预签名 URL（cloud 模式大文件传输）=====
class PresignedDownloadResponse(BaseModel):
    """预签名下载响应"""

    download_url: str


class PresignedUploadRequest(BaseModel):
    """预签名上传请求"""

    original_name: str = Field(..., max_length=500)
    directory: str = Field("", max_length=500)
    size: int = Field(0, ge=0)
    file_type: str = Field("other", max_length=32)


class PresignedUploadResponse(BaseModel):
    """预签名上传响应"""

    upload_url: str
    file_id: UUID
    storage_path: str


class PresignedUploadCompleteRequest(BaseModel):
    """预签名上传完成请求"""

    checksum: str = Field("", max_length=64)


# ===== 用户目录 =====
class DirectoryCreateRequest(BaseModel):
    """创建目录请求"""

    path: str = Field(..., max_length=500, description="目录相对路径，如 projectA 或 projectA/sub1")


class DirectoryDTO(BaseModel):
    """目录 DTO"""

    id: UUID
    path: str
    name: str
    parent_path: str | None = None
    is_system: bool = False
    created_at: datetime
    modified_at: datetime


class MoveFileRequest(BaseModel):
    """移动文件到目录请求"""

    directory: str = Field("", max_length=500, description="目标目录，空串表示移到根")


class FilePickerItemDTO(BaseModel):
    """文件选择器项（供分析时选文件）"""

    id: UUID
    original_name: str
    size: int
    file_type: FileType = FileType.OTHER
    directory: str = ""
    abs_path: str  # 绝对路径，供流程直接读取


# ===== 样本 =====
class SampleCreateRequest(BaseModel):
    """创建样本请求"""

    name: str = Field(..., max_length=200)
    species: str = Field("", max_length=100)
    tissue: str = Field("", max_length=100)
    description: str = ""
    metadata: dict = Field(default_factory=dict)
    file_ids: list[UUID] = Field(default_factory=list)


class SampleDTO(BaseModel):
    """样本 DTO"""

    id: UUID
    name: str
    species: str
    tissue: str
    description: str
    metadata: dict = Field(default_factory=dict)
    file_ids: list[UUID] = Field(default_factory=list)
    created_at: datetime


class SampleListResponse(BaseModel):
    items: list[SampleDTO] = Field(default_factory=list)
    total: int = 0

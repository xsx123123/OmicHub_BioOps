"""文件域实体 - 聚合根"""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field

from omichub.domain.file.value_objects import FileType, OwnerScope


class DataFile(BaseModel):
    """数据文件"""

    id: UUID
    user_id: UUID | None = None
    path: str
    original_name: str
    size: int
    checksum: str = ""
    file_type: FileType = FileType.OTHER
    status: str = "active"
    directory: str = ""  # 相对 raw/ 子路径，"" = 根
    source: str = "upload"  # 文件来源模块
    owner_scope: str = OwnerScope.PERSONAL.value  # personal / team
    team_id: UUID | None = None  # owner_scope=team 时指向 teams.id
    metadata: dict[str, Any] = {}
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class Directory(BaseModel):
    """用户自定义目录"""

    id: UUID
    user_id: UUID
    path: str  # 完整相对路径 "projectA" / "projectA/sub1"
    name: str  # 末级目录名
    parent_path: str | None = None
    is_system: bool = False  # 系统默认目录，不可删除/重命名
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class ResultArchive(BaseModel):
    """结果归档"""

    id: UUID
    task_id: UUID
    archive_path: str
    size: int
    expires_at: datetime | None = None
    created_at: datetime = Field(default_factory=datetime.now)


class Sample(BaseModel):
    """样本聚合根"""

    id: UUID
    name: str
    user_id: UUID
    species: str = ""
    tissue: str = ""
    description: str = ""
    metadata: dict[str, Any] = {}
    file_ids: list[UUID] = []
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)


class UploadSession(BaseModel):
    """分块上传会话 — 承载断点续传状态"""

    id: UUID
    user_id: UUID
    file_name: str
    total_size: int
    chunk_size: int
    total_chunks: int
    uploaded_chunks: list[dict[str, Any]] = []
    file_md5: str | None = None
    status: str = "pending"  # pending / uploading / merging / completed / failed
    directory: str = ""  # 上传目标目录（相对 raw/ 子路径）
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

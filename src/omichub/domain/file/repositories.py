"""文件域仓储接口

所有方法首参 user_id，查询统一带 WHERE user_id = ?，
在数据访问层彻底杜绝跨租户水平越权。
"""

from typing import Protocol
from uuid import UUID

from omichub.domain.file.entities import DataFile, Directory, ResultArchive, Sample, UploadSession
from omichub.domain.team.value_objects import TeamRole


class IFileRepository(Protocol):
    """文件记录仓储接口"""

    async def get_by_id(self, user_id: UUID, file_id: UUID) -> DataFile | None: ...

    async def get_visible(self, actor_user_id: UUID, file_id: UUID) -> DataFile | None: ...

    async def list_by_user(
        self,
        user_id: UUID,
        *,
        status: str | None = "active",
        order_by: str = "created_at",
        desc: bool = True,
        directory: str | None = None,
    ) -> list[DataFile]: ...

    async def list_visible(
        self,
        actor_user_id: UUID,
        *,
        status: str | None = "active",
        order_by: str = "created_at",
        desc: bool = True,
        directory: str | None = None,
    ) -> list[DataFile]: ...

    async def save(self, file: DataFile) -> DataFile: ...
    async def update_status(self, user_id: UUID, file_id: UUID, status: str) -> bool: ...

    async def delete(self, user_id: UUID, file_id: UUID) -> bool: ...
    async def delete_visible(self, actor_user_id: UUID, file_id: UUID) -> bool: ...

    async def get_team_role(self, team_id: UUID, user_id: UUID) -> TeamRole | None: ...

    async def sum_size(self, user_id: UUID) -> int: ...


class IUploadSessionRepository(Protocol):
    """分块上传会话仓储接口"""

    async def get_by_id(self, user_id: UUID, session_id: UUID) -> UploadSession | None: ...

    async def find_completed(
        self, user_id: UUID, file_name: str, total_size: int
    ) -> UploadSession | None:
        """秒传命中：同名同大小且已 completed"""
        ...

    async def save(self, session: UploadSession) -> UploadSession: ...

    async def add_chunk(
        self, user_id: UUID, session_id: UUID, chunk: dict
    ) -> UploadSession | None: ...

    async def update_status(self, user_id: UUID, session_id: UUID, status: str) -> bool: ...

    async def delete(self, user_id: UUID, session_id: UUID) -> bool: ...


class ISampleRepository(Protocol):
    """样本仓储接口"""

    async def get_by_id(self, user_id: UUID, sample_id: UUID) -> Sample | None: ...

    async def list_by_user(self, user_id: UUID) -> list[Sample]: ...

    async def count_by_user(self, user_id: UUID) -> int: ...

    async def save(self, sample: Sample) -> Sample: ...

    async def delete(self, user_id: UUID, sample_id: UUID) -> bool: ...


class IResultArchiveRepository(Protocol):
    """结果归档仓储接口"""

    async def get_by_task(self, task_id: UUID) -> ResultArchive | None: ...

    async def save(self, archive: ResultArchive) -> ResultArchive: ...

    async def cleanup_expired(self) -> int: ...


class IDirectoryRepository(Protocol):
    """用户目录仓储接口"""

    async def list_by_user(self, user_id: UUID) -> list[Directory]: ...

    async def get_by_path(self, user_id: UUID, path: str) -> Directory | None: ...

    async def save(self, directory: Directory) -> Directory: ...

    async def delete(self, user_id: UUID, path: str) -> bool: ...

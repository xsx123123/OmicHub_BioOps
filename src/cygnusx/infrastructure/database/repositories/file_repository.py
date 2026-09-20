"""文件域仓储 SQLAlchemy 实现 — 强制 user_id 隔离

所有查询带 .where(Model.user_id == user_id)，get_by_id 同时校验归属，
杜绝水平越权访问。
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, delete, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.domain.file.entities import DataFile, Directory, Sample, UploadSession
from cygnusx.domain.file.repositories import (
    IDirectoryRepository,
    IFileRepository,
    ISampleRepository,
    IUploadSessionRepository,
)
from cygnusx.domain.file.value_objects import OwnerScope
from cygnusx.domain.team.value_objects import TeamRole
from cygnusx.infrastructure.database.models.file import (
    DirectoryModel,
    FileRecordModel,
    SampleModel,
    UploadSessionModel,
)
from cygnusx.infrastructure.database.models.team import TeamMemberModel, TeamModel

# 合法排序字段白名单，防注入
_FILE_ORDER_COLUMNS = {
    "created_at": FileRecordModel.created_at,
    "original_name": FileRecordModel.original_name,
    "size": FileRecordModel.size,
    "file_type": FileRecordModel.file_type,
}


# =====================================================================
# 文件记录
# =====================================================================
class FileRepositoryImpl(IFileRepository):
    """文件记录仓储实现"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, user_id: UUID, file_id: UUID) -> DataFile | None:
        stmt = select(FileRecordModel).where(
            FileRecordModel.id == file_id,
            FileRecordModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def get_visible(self, actor_user_id: UUID, file_id: UUID) -> DataFile | None:
        """对 actor_user_id 可见的文件：个人文件且为 owner，或团队空间文件的团队成员。"""
        stmt = select(FileRecordModel).where(
            FileRecordModel.id == file_id,
            or_(
                and_(
                    FileRecordModel.user_id == actor_user_id,
                    FileRecordModel.owner_scope == OwnerScope.PERSONAL.value,
                ),
                and_(
                    FileRecordModel.owner_scope == OwnerScope.TEAM.value,
                    exists().where(
                        TeamMemberModel.team_id == FileRecordModel.team_id,
                        TeamMemberModel.user_id == actor_user_id,
                    ),
                ),
            ),
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_user(
        self,
        user_id: UUID,
        *,
        status: str | None = "active",
        order_by: str = "created_at",
        desc: bool = True,
        directory: str | None = None,
    ) -> list[DataFile]:
        stmt = select(FileRecordModel).where(FileRecordModel.user_id == user_id)
        if status:
            stmt = stmt.where(FileRecordModel.status == status)
        if directory is not None:
            stmt = stmt.where(FileRecordModel.directory == directory)
        col = _FILE_ORDER_COLUMNS.get(order_by, FileRecordModel.created_at)
        stmt = stmt.order_by(col.desc() if desc else col.asc())
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def list_visible(
        self,
        actor_user_id: UUID,
        *,
        status: str | None = "active",
        order_by: str = "created_at",
        desc: bool = True,
        directory: str | None = None,
    ) -> list[DataFile]:
        """聚合 actor_user_id 的个人文件 + 其所属团队的团队文件。"""
        personal = and_(
            FileRecordModel.user_id == actor_user_id,
            FileRecordModel.owner_scope == OwnerScope.PERSONAL.value,
        )
        team = and_(
            FileRecordModel.owner_scope == OwnerScope.TEAM.value,
            exists().where(
                TeamMemberModel.team_id == FileRecordModel.team_id,
                TeamMemberModel.user_id == actor_user_id,
            ),
        )
        stmt = select(FileRecordModel).where(or_(personal, team))
        if status:
            stmt = stmt.where(FileRecordModel.status == status)
        if directory is not None:
            stmt = stmt.where(FileRecordModel.directory == directory)
        col = _FILE_ORDER_COLUMNS.get(order_by, FileRecordModel.created_at)
        stmt = stmt.order_by(col.desc() if desc else col.asc())
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_team_role(self, team_id: UUID, user_id: UUID) -> TeamRole | None:
        # 团队 owner 未必在 team_members 中登记，先查 teams.owner_id
        team = await self._session.get(TeamModel, team_id)
        if team is None:
            return None
        if team.owner_id == user_id:
            return TeamRole.OWNER
        stmt = select(TeamMemberModel.role).where(
            TeamMemberModel.team_id == team_id,
            TeamMemberModel.user_id == user_id,
        )
        role = (await self._session.execute(stmt)).scalar_one_or_none()
        return TeamRole(role) if role else None

    async def save(self, file: DataFile) -> DataFile:
        existing = await self._session.get(FileRecordModel, file.id)
        file_type_value = (
            file.file_type.value if hasattr(file.file_type, "value") else file.file_type
        )
        if existing:
            existing.original_name = file.original_name
            existing.storage_path = file.path
            existing.size = file.size
            existing.checksum = file.checksum
            existing.file_type = file_type_value
            existing.directory = file.directory
            existing.source = file.source or "upload"
            existing.owner_scope = file.owner_scope or OwnerScope.PERSONAL.value
            existing.team_id = file.team_id
            model = existing
        else:
            model = FileRecordModel(
                id=file.id,
                user_id=file.user_id,  # type: ignore[arg-type]
                original_name=file.original_name,
                storage_path=file.path,
                size=file.size,
                checksum=file.checksum,
                file_type=file_type_value,
                status="active",
                directory=file.directory,
                source=file.source or "upload",
                owner_scope=file.owner_scope or OwnerScope.PERSONAL.value,
                team_id=file.team_id,
            )
            self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def update_status(self, user_id: UUID, file_id: UUID, status: str) -> bool:
        stmt = (
            update(FileRecordModel)
            .where(
                FileRecordModel.id == file_id,
                FileRecordModel.user_id == user_id,
            )
            .values(status=status)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0  # type: ignore[union-attr]

    async def delete(self, user_id: UUID, file_id: UUID) -> bool:
        stmt = delete(FileRecordModel).where(
            FileRecordModel.id == file_id,
            FileRecordModel.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0  # type: ignore[union-attr]

    async def delete_visible(self, actor_user_id: UUID, file_id: UUID) -> bool:
        """仅当文件对该用户可见时才删除。"""
        file = await self.get_visible(actor_user_id, file_id)
        if file is None:
            return False
        stmt = delete(FileRecordModel).where(FileRecordModel.id == file_id)
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0  # type: ignore[union-attr]

    async def sum_size(self, user_id: UUID) -> int:
        """统计用户 active 文件总大小（对账/配额校验用）"""
        stmt = select(func.coalesce(func.sum(FileRecordModel.size), 0)).where(
            FileRecordModel.user_id == user_id,
            FileRecordModel.status == "active",
        )
        return int((await self._session.execute(stmt)).scalar_one())

    @staticmethod
    def _to_entity(model: FileRecordModel) -> DataFile:
        from cygnusx.domain.file.value_objects import FileType

        return DataFile(
            id=model.id,
            user_id=model.user_id,  # type: ignore[arg-type]
            path=model.storage_path,
            original_name=model.original_name,
            size=model.size,
            checksum=model.checksum,
            file_type=FileType(model.file_type) if model.file_type else FileType.OTHER,
            status=model.status,
            directory=model.directory or "",
            source=model.source or "upload",
            owner_scope=model.owner_scope or OwnerScope.PERSONAL.value,
            team_id=model.team_id,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


# =====================================================================
# 上传会话
# =====================================================================
class UploadSessionRepositoryImpl(IUploadSessionRepository):
    """分块上传会话仓储实现"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, user_id: UUID, session_id: UUID) -> UploadSession | None:
        stmt = select(UploadSessionModel).where(
            UploadSessionModel.id == session_id,
            UploadSessionModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def find_completed(
        self, user_id: UUID, file_name: str, total_size: int
    ) -> UploadSession | None:
        stmt = (
            select(UploadSessionModel)
            .where(
                UploadSessionModel.user_id == user_id,
                UploadSessionModel.file_name == file_name,
                UploadSessionModel.total_size == total_size,
                UploadSessionModel.status == "completed",
            )
            .order_by(UploadSessionModel.created_at.desc())
            .limit(1)
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def save(self, session: UploadSession) -> UploadSession:
        existing = await self._session.get(UploadSessionModel, session.id)
        if existing:
            existing.file_name = session.file_name
            existing.total_size = session.total_size
            existing.chunk_size = session.chunk_size
            existing.total_chunks = session.total_chunks
            existing.uploaded_chunks = session.uploaded_chunks
            existing.file_md5 = session.file_md5
            existing.status = session.status
            existing.directory = session.directory
            model = existing
        else:
            model = UploadSessionModel(
                id=session.id,
                user_id=session.user_id,
                file_name=session.file_name,
                total_size=session.total_size,
                chunk_size=session.chunk_size,
                total_chunks=session.total_chunks,
                uploaded_chunks=session.uploaded_chunks,
                file_md5=session.file_md5,
                status=session.status,
                directory=session.directory,
            )
            self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def add_chunk(self, user_id: UUID, session_id: UUID, chunk: dict) -> UploadSession | None:
        stmt = select(UploadSessionModel).where(
            UploadSessionModel.id == session_id,
            UploadSessionModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        if model is None:
            return None
        chunks = list(model.uploaded_chunks or [])
        # 幂等：同 index 已存在则替换
        chunks = [c for c in chunks if c.get("index") != chunk.get("index")]
        chunks.append(chunk)
        chunks.sort(key=lambda c: c.get("index", 0))
        model.uploaded_chunks = chunks
        if model.status == "pending":
            model.status = "uploading"
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def update_status(self, user_id: UUID, session_id: UUID, status: str) -> bool:
        stmt = (
            update(UploadSessionModel)
            .where(
                UploadSessionModel.id == session_id,
                UploadSessionModel.user_id == user_id,
            )
            .values(status=status)
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0  # type: ignore[union-attr]

    async def delete(self, user_id: UUID, session_id: UUID) -> bool:
        stmt = delete(UploadSessionModel).where(
            UploadSessionModel.id == session_id,
            UploadSessionModel.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0  # type: ignore[union-attr]

    @staticmethod
    def _to_entity(model: UploadSessionModel) -> UploadSession:
        return UploadSession(
            id=model.id,
            user_id=model.user_id,
            file_name=model.file_name,
            total_size=model.total_size,
            chunk_size=model.chunk_size,
            total_chunks=model.total_chunks,
            uploaded_chunks=list(model.uploaded_chunks or []),
            file_md5=model.file_md5,
            status=model.status,
            directory=model.directory or "",
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


# =====================================================================
# 样本
# =====================================================================
class SampleRepositoryImpl(ISampleRepository):
    """样本仓储实现"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def get_by_id(self, user_id: UUID, sample_id: UUID) -> Sample | None:
        stmt = select(SampleModel).where(
            SampleModel.id == sample_id,
            SampleModel.user_id == user_id,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def list_by_user(self, user_id: UUID) -> list[Sample]:
        stmt = (
            select(SampleModel)
            .where(SampleModel.user_id == user_id)
            .order_by(SampleModel.created_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def count_by_user(self, user_id: UUID) -> int:
        stmt = select(func.count(SampleModel.id)).where(SampleModel.user_id == user_id)
        result = await self._session.execute(stmt)
        return int(result.scalar_one())

    async def save(self, sample: Sample) -> Sample:
        existing = await self._session.get(SampleModel, sample.id)
        if existing:
            existing.name = sample.name
            existing.species = sample.species
            existing.tissue = sample.tissue
            existing.description = sample.description
            existing.meta = sample.metadata
            existing.file_ids = [str(fid) for fid in sample.file_ids]
            model = existing
        else:
            model = SampleModel(
                id=sample.id,
                user_id=sample.user_id,
                name=sample.name,
                species=sample.species,
                tissue=sample.tissue,
                description=sample.description,
                meta=sample.metadata,
                file_ids=[str(fid) for fid in sample.file_ids],
            )
            self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def delete(self, user_id: UUID, sample_id: UUID) -> bool:
        stmt = delete(SampleModel).where(
            SampleModel.id == sample_id,
            SampleModel.user_id == user_id,
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0  # type: ignore[union-attr]

    @staticmethod
    def _to_entity(model: SampleModel) -> Sample:
        return Sample(
            id=model.id,
            user_id=model.user_id,
            name=model.name,
            species=model.species,
            tissue=model.tissue,
            description=model.description,
            metadata=model.meta or {},
            file_ids=model.file_ids or [],
            created_at=model.created_at,
            updated_at=model.updated_at,
        )


# =====================================================================
# 用户目录
# =====================================================================
class DirectoryRepositoryImpl(IDirectoryRepository):
    """用户目录仓储实现"""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def list_by_user(self, user_id: UUID) -> list[Directory]:
        stmt = (
            select(DirectoryModel)
            .where(DirectoryModel.user_id == user_id)
            .order_by(DirectoryModel.path.asc())
        )
        result = await self._session.execute(stmt)
        return [self._to_entity(m) for m in result.scalars().all()]

    async def get_by_path(self, user_id: UUID, path: str) -> Directory | None:
        stmt = select(DirectoryModel).where(
            DirectoryModel.user_id == user_id,
            DirectoryModel.path == path,
        )
        model = (await self._session.execute(stmt)).scalar_one_or_none()
        return self._to_entity(model) if model else None

    async def save(self, directory: Directory) -> Directory:
        existing = await self._session.get(DirectoryModel, directory.id)
        if existing:
            existing.path = directory.path
            existing.name = directory.name
            existing.parent_path = directory.parent_path
            existing.is_system = directory.is_system
            model = existing
        else:
            model = DirectoryModel(
                id=directory.id,
                user_id=directory.user_id,
                path=directory.path,
                name=directory.name,
                parent_path=directory.parent_path,
                is_system=directory.is_system,
            )
            self._session.add(model)
        await self._session.flush()
        await self._session.refresh(model)
        return self._to_entity(model)

    async def delete(self, user_id: UUID, path: str) -> bool:
        stmt = delete(DirectoryModel).where(
            DirectoryModel.user_id == user_id,
            DirectoryModel.path == path,
        )
        result = await self._session.execute(stmt)
        await self._session.flush()
        return result.rowcount > 0  # type: ignore[union-attr]

    @staticmethod
    def _to_entity(model: DirectoryModel) -> Directory:
        return Directory(
            id=model.id,
            user_id=model.user_id,
            path=model.path,
            name=model.name,
            parent_path=model.parent_path,
            is_system=model.is_system,
            created_at=model.created_at,
            updated_at=model.updated_at,
        )

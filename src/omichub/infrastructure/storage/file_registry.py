"""统一文件注册服务 — 所有模块产出文件的唯一注册点。

设计目标：消除各工具/流程各自管理文件路径的混乱局面。任何模块产生输出文件后，
都应调用 FileRegistry.register() 将文件注册到 file_records 表，使其可被统一
浏览、下载、配额计量和生命周期管理。

幂等性：同路径重复注册返回已有记录，不会创建重复条目。
"""

from __future__ import annotations

import fnmatch
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.domain.file.value_objects import FileSource, FileType, LifecycleStatus, OwnerScope
from omichub.infrastructure.database.models.file import FileRecordModel
from omichub.infrastructure.storage import get_storage_backend
from omichub.infrastructure.storage.backend import StorageBackend
from omichub.infrastructure.storage.path_factory import StoragePathFactory, get_path_factory

logger = logging.getLogger(__name__)

_EXTENSION_TYPE_MAP: dict[str, FileType] = {
    ".fq": FileType.FASTQ,
    ".fastq": FileType.FASTQ,
    ".fq.gz": FileType.FASTQ,
    ".fastq.gz": FileType.FASTQ,
    ".bam": FileType.BAM,
    ".cram": FileType.BAM,
    ".vcf": FileType.VCF,
    ".vcf.gz": FileType.VCF,
    ".csv": FileType.COUNT_MATRIX,
    ".tsv": FileType.COUNT_MATRIX,
    ".h5ad": FileType.H5AD,
    ".rds": FileType.RDS,
    ".json": FileType.META,
    ".html": FileType.REPORT,
    ".png": FileType.IMAGE,
    ".jpg": FileType.IMAGE,
    ".jpeg": FileType.IMAGE,
    ".svg": FileType.IMAGE,
    ".pdf": FileType.REPORT,
}


def _detect_file_type(filename: str) -> FileType:
    lower = filename.lower()
    for ext, ftype in _EXTENSION_TYPE_MAP.items():
        if lower.endswith(ext):
            return ftype
    return FileType.OTHER


class FileRegistry:
    """统一文件注册入口。"""

    def __init__(
        self,
        session: AsyncSession,
        path_factory: StoragePathFactory | None = None,
        backend: StorageBackend | None = None,
    ):
        self._session = session
        self._pf = path_factory or get_path_factory()
        self._backend = backend or get_storage_backend()

    async def register(
        self,
        user_id: uuid.UUID,
        path: Path | str,
        *,
        source: FileSource = FileSource.UPLOAD,
        task_id: uuid.UUID | None = None,
        file_type: FileType | None = None,
        display_name: str | None = None,
        directory: str = "",
        cleanup_days: int | None = None,
        owner_scope: OwnerScope = OwnerScope.PERSONAL,
        team_id: uuid.UUID | None = None,
    ) -> FileRecordModel:
        """注册单个文件，返回 FileRecordModel。

        幂等：同 user_id + storage_path 已存在时直接返回已有记录；团队文件额外按 team_id 区分。
        """
        abs_path = Path(path)
        rel_path = self._pf.relative_to_root(abs_path)

        existing = await self._find_by_path(user_id, rel_path, team_id=team_id)
        if existing:
            return existing

        name = display_name or abs_path.name
        detected_type = file_type or _detect_file_type(abs_path.name)
        info = await self._backend.stat(rel_path)
        size = info.get("size", 0) if info else 0

        cleanup_after = None
        if cleanup_days is not None:
            cleanup_after = datetime.now(UTC) + timedelta(days=cleanup_days)

        record = FileRecordModel(
            id=uuid.uuid4(),
            user_id=user_id,
            original_name=name,
            storage_path=rel_path,
            size=size,
            checksum="",
            file_type=detected_type.value if hasattr(detected_type, "value") else str(detected_type),
            status="active",
            directory=directory,
            source=source.value if hasattr(source, "value") else str(source),
            task_id=task_id,
            lifecycle_status=LifecycleStatus.ACTIVE.value,
            cleanup_after=cleanup_after,
            owner_scope=owner_scope.value,
            team_id=team_id,
        )
        self._session.add(record)
        await self._session.flush()
        await self._session.refresh(record)
        logger.info("File registered: user=%s path=%s source=%s", user_id, rel_path, source)
        return record

    async def register_directory(
        self,
        user_id: uuid.UUID,
        directory: Path | str,
        *,
        source: FileSource = FileSource.PIPELINE,
        task_id: uuid.UUID | None = None,
        patterns: list[str] | None = None,
        recursive: bool = True,
        cleanup_days: int | None = None,
        owner_scope: OwnerScope = OwnerScope.PERSONAL,
        team_id: uuid.UUID | None = None,
    ) -> list[FileRecordModel]:
        """批量注册目录下匹配的文件。

        patterns: glob 模式列表（如 ["*.csv", "**/*.html"]），None 表示注册所有文件。
        """
        dir_path = Path(directory)
        dir_rel = self._pf.relative_to_root(dir_path)
        info = await self._backend.stat(dir_rel)
        if info is None or not info.get("is_dir"):
            logger.warning("register_directory: path is not a directory: %s", dir_path)
            return []

        entries = await self._backend.list(dir_rel, recursive=recursive)
        files = [e for e in entries if e["type"] == "file"]
        if patterns:
            files = [
                e
                for e in files
                if any(fnmatch.fnmatch(e["path"], pat) for pat in patterns)
            ]

        records = []
        for entry in sorted(files, key=lambda e: e["path"]):
            abs_path = self._pf.data_root / entry["path"]
            record = await self.register(
                user_id,
                abs_path,
                source=source,
                task_id=task_id,
                cleanup_days=cleanup_days,
                owner_scope=owner_scope,
                team_id=team_id,
            )
            records.append(record)

        logger.info(
            "Directory registered: user=%s dir=%s count=%d source=%s",
            user_id, dir_path, len(records), source,
        )
        return records

    async def get_or_register(
        self,
        user_id: uuid.UUID,
        path: Path | str,
        **kwargs: Any,
    ) -> FileRecordModel:
        """获取已注册记录或注册新文件（register 的别名，强调幂等语义）。"""
        return await self.register(user_id, path, **kwargs)

    async def _find_by_path(
        self, user_id: uuid.UUID, rel_path: str, *, team_id: uuid.UUID | None = None
    ) -> FileRecordModel | None:
        stmt = select(FileRecordModel).where(
            FileRecordModel.user_id == user_id,
            FileRecordModel.storage_path == rel_path,
            FileRecordModel.status != "deleted",
        )
        if team_id is not None:
            stmt = stmt.where(FileRecordModel.team_id == team_id)
        else:
            stmt = stmt.where(FileRecordModel.team_id.is_(None))
        result = await self._session.execute(stmt.limit(1))
        return result.scalars().first()

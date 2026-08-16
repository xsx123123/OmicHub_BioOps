"""用户目录 CRUD 服务 —— 从 FileService 抽出，单独承担目录生命周期管理。

职责：
- 默认目录的幂等初始化（ensure_default_directories）
- 目录列表 / 创建 / 删除
- 删除目录时把该目录下文件的 directory 字段置空回根，避免孤儿记录

物理路径生成统一委托 StoragePathFactory。
"""

from __future__ import annotations

import uuid
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.file import (
    DirectoryCreateRequest,
    DirectoryDTO,
)
from omichub.core.exceptions import (
    AuthorizationError,
    ConflictError,
    NotFoundError,
    ValidationError,
)
from omichub.domain.file.entities import Directory
from omichub.infrastructure.database.repositories import (
    DirectoryRepositoryImpl,
    FileRepositoryImpl,
)
from omichub.infrastructure.storage import get_path_factory, get_storage_backend
from omichub.infrastructure.storage.backend import StorageBackend

# 系统默认目录：用户首次访问时懒初始化，锁定不可删除/重命名。
# 与 file_service.SYSTEM_DIRECTORIES 保持同一来源，避免循环导入故在此重复声明。
SYSTEM_DIRECTORIES: tuple[str, ...] = (
    "inbox",
    "projects",
    "raw_data",
    "workspace",
    "downloads",
    "temp",
)


class DirectoryService:
    """用户目录 CRUD。"""

    def __init__(self, session: AsyncSession, backend: StorageBackend | None = None):
        self._session = session
        self._dirs = DirectoryRepositoryImpl(session)
        self._files = FileRepositoryImpl(session)
        self._factory = get_path_factory()
        self._backend = backend or get_storage_backend()

    # ------------------------------------------------------------------
    # 路径工具
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_directory(directory: str | None) -> str:
        if not directory:
            return ""
        d = directory.strip().strip("/")
        parts = [p for p in d.split("/") if p not in ("", ".", "..")]
        return "/".join(parts)

    async def _ensure_user_system_subdir(self, user_id: UUID, name: str) -> Path:
        """确保用户顶层系统子目录存在。"""
        uid = str(user_id)
        mapping = {
            "inbox": self._factory.inbox_dir(uid),
            "projects": self._factory.projects_dir(uid),
            "raw_data": self._factory.user_root(uid) / "raw_data",
            "workspace": self._factory.workspace_dir(uid),
            "downloads": self._factory.downloads_dir(uid),
            "temp": self._factory.user_root(uid) / "temp",
        }
        d = mapping.get(name) or (self._factory.user_root(uid) / name)
        await self._backend.ensure_dir(self._factory.relative_to_root(d))
        return d

    async def _inbox_subdir(self, user_id: UUID, directory: str) -> Path:
        """用户 inbox/ 下的指定子目录（自动创建）。"""
        normalized = self._normalize_directory(directory)
        if normalized == "inbox":
            normalized = ""
        elif normalized.startswith("inbox/"):
            normalized = normalized.removeprefix("inbox/")
        base = self._factory.inbox_dir(str(user_id))
        target = base / normalized if normalized else base
        await self._backend.ensure_dir(self._factory.relative_to_root(target))
        return target

    # ------------------------------------------------------------------
    # 默认目录初始化
    # ------------------------------------------------------------------
    async def ensure_default_directories(self, user_id: UUID) -> None:
        """幂等创建用户默认目录 inbox/projects/... 及物理目录。"""
        existing = await self._dirs.list_by_user(user_id)
        existing_paths = {d.path for d in existing}
        created_any = False
        for name in SYSTEM_DIRECTORIES:
            if name not in existing_paths:
                directory = Directory(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    path=name,
                    name=name,
                    parent_path=None,
                    is_system=True,
                )
                await self._dirs.save(directory)
                created_any = True
            await self._ensure_user_system_subdir(user_id, name)
        if created_any:
            await self._session.commit()

    # ------------------------------------------------------------------
    # 列表 / 创建 / 删除
    # ------------------------------------------------------------------
    async def list_directories(self, user_id: UUID) -> list[DirectoryDTO]:
        await self.ensure_default_directories(user_id)
        dirs = await self._dirs.list_by_user(user_id)
        return [
            DirectoryDTO(
                id=d.id,
                path=d.path,
                name=d.name,
                parent_path=d.parent_path,
                is_system=d.is_system,
                created_at=d.created_at,
                modified_at=d.updated_at,
            )
            for d in dirs
        ]

    async def create_directory(
        self, user_id: UUID, req: DirectoryCreateRequest
    ) -> DirectoryDTO:
        path = self._normalize_directory(req.path)
        if not path:
            raise ValidationError("目录名不能为空")
        if len(path) > 500:
            raise ValidationError("目录路径过长")
        top = path.split("/")[0]
        if (
            path == top
            and top in SYSTEM_DIRECTORIES
            and not await self._dirs.get_by_path(user_id, top)
        ):
            raise ConflictError(f"系统目录已存在：{path}")
        if await self._dirs.get_by_path(user_id, path) is not None:
            raise ConflictError(f"目录已存在：{path}")
        parts = path.split("/")
        name = parts[-1]
        parent_path = "/".join(parts[:-1]) if len(parts) > 1 else None
        if parent_path and await self._dirs.get_by_path(user_id, parent_path) is None:
            raise NotFoundError(f"父目录不存在：{parent_path}")
        directory = Directory(
            id=uuid.uuid4(),
            user_id=user_id,
            path=path,
            name=name,
            parent_path=parent_path,
        )
        saved = await self._dirs.save(directory)
        await self._inbox_subdir(user_id, path)
        await self._session.commit()
        return DirectoryDTO(
            id=saved.id,
            path=saved.path,
            name=saved.name,
            parent_path=saved.parent_path,
            created_at=saved.created_at,
            modified_at=saved.updated_at,
        )

    async def delete_directory(self, user_id: UUID, path: str) -> bool:
        path = self._normalize_directory(path)
        if not path:
            raise ValidationError("不能删除根目录")
        target = await self._dirs.get_by_path(user_id, path)
        if target is None:
            raise NotFoundError("目录不存在")
        if target.is_system:
            raise AuthorizationError(f"系统目录不可删除：{path}")
        all_dirs = await self._dirs.list_by_user(user_id)
        if any(d.path.startswith(path + "/") for d in all_dirs):
            raise ValidationError("目录下还有子目录，请先删除子目录")
        # 简化策略：连带把该目录下的文件 directory 置空回根，避免孤儿
        files = await self._files.list_by_user(user_id, status="active", directory=path)
        for f in files:
            f.directory = ""
            await self._files.save(f)
        ok = await self._dirs.delete(user_id, path)
        await self._session.commit()
        return ok

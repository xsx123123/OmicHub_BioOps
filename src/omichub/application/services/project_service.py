"""项目应用服务 —— 管理用户的分析项目。

Project 是用户视角的"分析项目"聚合根。每个 Project 对应磁盘上
``users/{user_id}/projects/{slug}/`` 目录，下挂多个 Run。

服务职责：
- 列出 / 计数 / 创建 / 删除项目
- 与 Directory 记录同步（创建 Project 时同步创建 Directory）
- 从磁盘 ``projects/`` 目录回填缺失的 Project 记录（首次访问时懒初始化）
"""

from __future__ import annotations

import uuid
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.core.exceptions import ConflictError, NotFoundError, ValidationError
from omichub.infrastructure.database.models.project import ProjectModel
from omichub.infrastructure.database.repositories import DirectoryRepositoryImpl
from omichub.infrastructure.storage.path_factory import get_path_factory, project_slug


class ProjectService:
    """项目管理服务。"""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._factory = get_path_factory()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    async def list_projects(self, user_id: UUID) -> list[dict]:
        """列出用户的所有项目（先回填磁盘已存在但 DB 缺失的项目）。"""
        await self._backfill_from_disk(user_id)
        stmt = (
            select(ProjectModel)
            .where(ProjectModel.user_id == user_id)
            .order_by(ProjectModel.updated_at.desc())
        )
        result = await self._session.execute(stmt)
        return [
            {
                "id": str(m.id),
                "name": m.name,
                "slug": m.slug,
                "description": m.description,
                "created_at": m.created_at.isoformat() if m.created_at else None,
                "updated_at": m.updated_at.isoformat() if m.updated_at else None,
            }
            for m in result.scalars().all()
        ]

    async def count_projects(self, user_id: UUID) -> int:
        """返回用户项目总数（回填后计数）。"""
        await self._backfill_from_disk(user_id)
        result = await self._session.execute(
            select(func.count()).select_from(ProjectModel).where(ProjectModel.user_id == user_id)
        )
        return result.scalar_one()

    async def get_project(self, user_id: UUID, project_id: UUID) -> dict:
        stmt = select(ProjectModel).where(
            ProjectModel.id == project_id, ProjectModel.user_id == user_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"项目不存在：{project_id}")
        return {
            "id": str(model.id),
            "name": model.name,
            "slug": model.slug,
            "description": model.description,
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "updated_at": model.updated_at.isoformat() if model.updated_at else None,
        }

    # ------------------------------------------------------------------
    # 写操作
    # ------------------------------------------------------------------
    async def create_project(self, user_id: UUID, name: str, description: str = "") -> dict:
        """创建新项目。

        - ``slug`` 由 ``project_slug(name)`` 自动生成，保证路径安全
        - 同步在 ``user_directories`` 登记 ``projects/{slug}`` 目录记录
        """
        name = (name or "").strip()
        if not name:
            raise ValidationError("项目名不能为空")
        if len(name) > 200:
            raise ValidationError("项目名最长 200 字符")

        slug = project_slug(name)
        if not slug:
            raise ValidationError("项目名无法生成合法目录 slug")

        exists = await self._session.execute(
            select(ProjectModel.id).where(
                ProjectModel.user_id == user_id, ProjectModel.slug == slug
            )
        )
        if exists.scalar_one_or_none() is not None:
            raise ConflictError(f"同名项目已存在：{slug}")

        model = ProjectModel(user_id=user_id, name=name, slug=slug, description=description)
        self._session.add(model)

        # 同步创建目录记录
        dirs = DirectoryRepositoryImpl(self._session)
        dir_path = f"projects/{slug}"
        if await dirs.get_by_path(user_id, dir_path) is None:
            from omichub.domain.file.entities import Directory

            await dirs.save(
                Directory(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    path=dir_path,
                    name=slug,
                    parent_path="projects",
                )
            )

        # 预创建物理目录
        self._factory.project_dir(str(user_id), slug).mkdir(parents=True, exist_ok=True)
        (self._factory.project_dir(str(user_id), slug) / "runs").mkdir(exist_ok=True)

        await self._session.commit()
        await self._session.refresh(model)
        return {
            "id": str(model.id),
            "name": model.name,
            "slug": model.slug,
            "description": model.description,
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "updated_at": model.updated_at.isoformat() if model.updated_at else None,
        }

    async def delete_project(self, user_id: UUID, project_id: UUID) -> bool:
        """删除项目（仅删 DB 记录 + 目录记录，不删物理文件，避免误删数据）。"""
        stmt = select(ProjectModel).where(
            ProjectModel.id == project_id, ProjectModel.user_id == user_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"项目不存在：{project_id}")
        await self._session.delete(model)
        # 清理目录记录
        dirs = DirectoryRepositoryImpl(self._session)
        dir_path = f"projects/{model.slug}"
        await dirs.delete(user_id, dir_path)
        await self._session.commit()
        return True

    # ------------------------------------------------------------------
    # 回填：从磁盘 projects/ 目录读取缺失项目，写入 DB
    # ------------------------------------------------------------------
    async def _backfill_from_disk(self, user_id: UUID) -> None:
        """扫描 ``users/{user_id}/projects/`` 下的一级子目录，为缺失的创建 DB 记录。

        幂等：已存在同 slug 的项目跳过。目录名即 slug，显示名暂时等于 slug
        （后续用户可通过 rename 改为可读名）。
        """
        projects_root = self._factory.projects_dir(str(user_id))
        if not projects_root.exists():
            return

        existing = await self._session.execute(
            select(ProjectModel.slug).where(ProjectModel.user_id == user_id)
        )
        existing_slugs = set(existing.scalars().all())

        to_insert: list[ProjectModel] = []
        for entry in projects_root.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            if entry.name in existing_slugs:
                continue
            to_insert.append(
                ProjectModel(
                    user_id=user_id,
                    name=entry.name,
                    slug=entry.name,
                    description="",
                )
            )
        if to_insert:
            self._session.add_all(to_insert)
            await self._session.commit()

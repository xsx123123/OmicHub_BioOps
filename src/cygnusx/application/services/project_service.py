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
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.exceptions import ConflictError, NotFoundError, ValidationError
from cygnusx.infrastructure.database.models.project import ProjectModel
from cygnusx.infrastructure.database.repositories import DirectoryRepositoryImpl
from cygnusx.infrastructure.storage.path_factory import get_path_factory, project_slug


class ProjectService:
    """项目管理服务。"""

    def __init__(self, session: AsyncSession):
        self._session = session
        self._factory = get_path_factory()

    # ------------------------------------------------------------------
    # 查询
    # ------------------------------------------------------------------
    PROJECT_STATUSES = ("active", "completed", "handed_over")

    @staticmethod
    def _to_dict(model: ProjectModel) -> dict:
        return {
            "id": str(model.id),
            "name": model.name,
            "slug": model.slug,
            "description": model.description,
            "customer": model.customer,
            # getattr 兼容测试替身等无 status 属性的投影对象（同 customer 处理）
            "status": getattr(model, "status", None) or "active",
            # WP3 任务 3：项目级设置（当前仅 research_mode）；NULL 透出为 None
            "settings": getattr(model, "settings", None) if isinstance(getattr(model, "settings", None), dict) else None,
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "updated_at": model.updated_at.isoformat() if model.updated_at else None,
        }

    async def list_projects(self, user_id: UUID) -> list[dict]:
        """列出用户的所有项目（先回填磁盘已存在但 DB 缺失的项目）。"""
        await self._backfill_from_disk(user_id)
        stmt = (
            select(ProjectModel)
            .where(ProjectModel.user_id == user_id)
            .order_by(ProjectModel.updated_at.desc())
        )
        result = await self._session.execute(stmt)
        return [self._to_dict(m) for m in result.scalars().all()]

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
        return self._to_dict(model)

    # ------------------------------------------------------------------
    # 写操作
    # ------------------------------------------------------------------
    async def create_project(
        self, user_id: UUID, name: str, description: str = "", customer: str = ""
    ) -> dict:
        """创建新项目。

        - ``slug`` 由 ``project_slug(name)`` 自动生成，保证路径安全
        - 同步在 ``user_directories`` 登记 ``projects/{slug}`` 目录记录
        """
        name = (name or "").strip()
        if not name:
            raise ValidationError("项目名不能为空")
        if len(name) > 200:
            raise ValidationError("项目名最长 200 字符")
        customer = (customer or "").strip()
        if len(customer) > 200:
            raise ValidationError("客户名最长 200 字符")

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

        model = ProjectModel(
            user_id=user_id, name=name, slug=slug, description=description, customer=customer
        )
        self._session.add(model)

        # 同步创建目录记录
        dirs = DirectoryRepositoryImpl(self._session)
        dir_path = f"projects/{slug}"
        if await dirs.get_by_path(user_id, dir_path) is None:
            from cygnusx.domain.file.entities import Directory

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
        return self._to_dict(model)

    async def get_or_create_project_by_name(self, user_id: UUID, name: str) -> dict:
        """按名称复用或创建项目（AgentTeams 聊天 Case 建单场景）。

        聊天式 Case 的项目名由需求文本自动生成；删除 Case 不会删除项目，
        用户用同一需求重新建单时 slug 必然撞上存量项目。此时应复用既有项目
        （每个 Case 仍会在其下创建独立的带时间戳 run 目录），而不是把
        "同名项目已存在"抛给用户。
        """
        slug = project_slug((name or "").strip())
        if slug:
            result = await self._session.execute(
                select(ProjectModel).where(
                    ProjectModel.user_id == user_id, ProjectModel.slug == slug
                )
            )
            model = result.scalar_one_or_none()
            if model is not None:
                return self._to_dict(model)
        return await self.create_project(user_id, name)

    async def update_project_settings(
        self, user_id: UUID, project_id: UUID, settings: dict[str, Any]
    ) -> dict[str, Any]:
        """更新项目级 settings（WP3 任务 3，属主）。

        settings 为整体替换的 JSONB 对象；当前仅约定 research_mode 键，
        若存在必须是 dict（enabled 布尔总开关 + 可选子项），其余键原样保存。
        """
        if not isinstance(settings, dict):
            raise ValidationError("settings 必须是 JSON 对象")
        research_mode = settings.get("research_mode")
        if research_mode is not None and not isinstance(research_mode, dict):
            raise ValidationError("settings.research_mode 必须是 JSON 对象")
        stmt = select(ProjectModel).where(
            ProjectModel.id == project_id, ProjectModel.user_id == user_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"项目不存在：{project_id}")
        model.settings = settings
        await self._session.commit()
        await self._session.refresh(model)
        return self._to_dict(model)

    async def mark_project_status(self, user_id: UUID, project_id: UUID, status: str) -> dict:
        """标记项目状态（属主）；completed/handed_over 触发其下会话工作区休眠打包。

        chat_sessions.project_id 存的是 str(projects.id)（已核实线上数据），
        按字符串等值匹配；打包为后台任务，busy 会话跳过记日志。
        """
        status = (status or "").strip().lower()
        if status not in self.PROJECT_STATUSES:
            raise ValidationError(f"非法项目状态：{status}（允许 {self.PROJECT_STATUSES}）")
        stmt = select(ProjectModel).where(
            ProjectModel.id == project_id, ProjectModel.user_id == user_id
        )
        result = await self._session.execute(stmt)
        model = result.scalar_one_or_none()
        if model is None:
            raise NotFoundError(f"项目不存在：{project_id}")
        model.status = None if status == "active" else status
        await self._session.commit()
        if status in {"completed", "handed_over"}:
            await self._pack_project_sessions(model)
        return self._to_dict(model)

    async def _pack_project_sessions(self, model: ProjectModel) -> None:
        """项目完成/移交后，其下 studio 会话全部后台休眠打包（幂等，busy 跳过）。"""
        import asyncio

        from loguru import logger

        from cygnusx.application.services.workspace_archive_service import pack_session
        from cygnusx.infrastructure.database.models.chat import ChatSessionModel
        from cygnusx.infrastructure.database.session import get_session_factory

        project_id = str(model.id)

        async def _run() -> None:
            packed = 0
            try:
                async with get_session_factory()() as db:
                    result = await db.execute(
                        select(ChatSessionModel).where(
                            ChatSessionModel.project_id == project_id,
                            ChatSessionModel.mode == "studio",
                            ChatSessionModel.status != "deleted",
                        )
                    )
                    sessions = list(result.scalars().all())
                    for session in sessions:
                        try:
                            await pack_session(db, session.session_id, "system", is_admin=True)
                            packed += 1
                        except Exception as exc:  # noqa: BLE001 - busy 等跳过记日志
                            logger.info(
                                "[Archive] 项目 {} 会话 {} 完成触发打包跳过: {}",
                                model.slug,
                                session.session_id[:12],
                                exc,
                            )
            except Exception as exc:  # noqa: BLE001
                logger.warning("[Archive] 项目 {} 会话打包任务失败: {}", model.slug, exc)
            if packed:
                logger.info("[Archive] 项目 {} 完成触发打包 {} 个会话", model.slug, packed)

        # fire-and-forget：API 事务不等待打包完成
        asyncio.create_task(_run())

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

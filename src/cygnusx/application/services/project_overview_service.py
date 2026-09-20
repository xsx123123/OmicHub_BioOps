"""项目总览服务 —— 聚合单个项目下的会话与历史分析运行。

供「按项目浏览历史分析」页面使用：
- 项目元数据（customer 字段由并行开发提供，用 getattr 兜底）
- 该项目下的 chat sessions（按 ``chat_sessions.project_id`` 过滤，时间倒序 + 分页）
- 磁盘 ``projects/{slug}/runs/`` 下的历史分析运行目录扫描
  （AGENTS.md / README.md / environment.json 是否齐备、产物文件数与总大小）

报告（Report）模型暂无 project_id 列，不做关联，避免硬 join。
"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.exceptions import NotFoundError
from cygnusx.infrastructure.database.models.chat import AgentTeamsRoomModel, ChatSessionModel
from cygnusx.infrastructure.database.models.project import ProjectModel
from cygnusx.infrastructure.storage.path_factory import StoragePathFactory, get_path_factory

# 运行目录名约定：{分析名}-{YYYYMMDD-HHMMSS}[-序号]（见 StoragePathFactory.create_project_run_dir）
_RUN_STAMP_RE = re.compile(r"(\d{8})-(\d{6})(?:-\d+)?$")


class ProjectOverviewService:
    """项目总览聚合服务。"""

    def __init__(self, session: AsyncSession, factory: StoragePathFactory | None = None):
        self._session = session
        self._factory = factory or get_path_factory()

    async def get_overview(
        self,
        user_id: UUID,
        project_id: UUID,
        *,
        session_limit: int = 50,
        session_offset: int = 0,
        session_status: str = "active",
    ) -> dict:
        project = await self._load_project(user_id, project_id)
        sessions = await self._list_sessions(
            user_id,
            project_id,
            status=session_status,
            limit=session_limit,
            offset=session_offset,
        )
        runs = await asyncio.to_thread(self._scan_runs, str(user_id), project["slug"])
        return {"project": project, "sessions": sessions, "runs": runs}

    # ------------------------------------------------------------------
    # 项目元数据
    # ------------------------------------------------------------------
    async def _load_project(self, user_id: UUID, project_id: UUID) -> dict:
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
            # customer 列由并行开发加入，模型尚未带该字段时兜底为 None
            "customer": getattr(model, "customer", None),
            "created_at": model.created_at.isoformat() if model.created_at else None,
            "updated_at": model.updated_at.isoformat() if model.updated_at else None,
        }

    # ------------------------------------------------------------------
    # 项目下的聊天会话（chat_sessions）+ 协作室房间（agentteams_rooms）
    # ------------------------------------------------------------------
    @staticmethod
    def _map_room_status(room_status: str) -> str:
        """房间 status 与会话 status 口径对齐：房间目前只有 active，
        其余非删除状态统一视作 archived，deleted 直映 deleted。"""
        if room_status == "active":
            return "active"
        if room_status == "deleted":
            return "deleted"
        return "archived"

    async def _list_sessions(
        self, user_id: UUID, project_id: UUID, *, status: str, limit: int, offset: int
    ) -> dict:
        condition = (
            ChatSessionModel.user_id == str(user_id),
            ChatSessionModel.project_id == str(project_id),
            # 仅列出所请求状态的会话：deleted 为软删回收、system 为 agentteams 计费合成会话
            ChatSessionModel.status == status,
        )
        chat_total = (
            await self._session.execute(
                select(func.count()).select_from(ChatSessionModel).where(*condition)
            )
        ).scalar_one()
        result = await self._session.execute(
            select(ChatSessionModel)
            .where(*condition)
            .order_by(ChatSessionModel.updated_at.desc())
        )
        items = [
            {
                "id": s.session_id,
                "title": s.title,
                "agent_id": s.agent_id,
                "status": s.status,
                "mode": s.mode,
                "message_count": s.message_count,
                "last_message_at": s.last_message_at.isoformat()
                if s.last_message_at
                else None,
                "created_at": s.created_at.isoformat() if s.created_at else None,
                "updated_at": s.updated_at.isoformat() if s.updated_at else None,
                "room_id": None,
                "case_id": None,
            }
            for s in result.scalars().all()
        ]
        room_items = await self._list_room_items(user_id, project_id, status=status)
        items.extend(room_items)
        # 两来源合并后统一按更新时间倒序，再做内存分页（项目维度量级小）
        items.sort(key=lambda item: item["updated_at"] or "", reverse=True)
        total = chat_total + len(room_items)
        return {
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": items[offset : offset + limit],
        }

    async def _list_room_items(
        self, user_id: UUID, project_id: UUID, *, status: str
    ) -> list[dict]:
        """项目下的 agentteams 房间条目（owner 维度），按映射后的 status 参与过滤。"""
        result = await self._session.execute(
            select(AgentTeamsRoomModel)
            .where(
                AgentTeamsRoomModel.owner_id == str(user_id),
                AgentTeamsRoomModel.project_id == str(project_id),
            )
            .order_by(AgentTeamsRoomModel.updated_at.desc())
        )
        items = []
        for room in result.scalars().all():
            mapped_status = self._map_room_status(room.status)
            if mapped_status != status:
                continue
            items.append(
                {
                    "id": room.room_id,
                    "title": room.title,
                    "agent_id": None,
                    "status": mapped_status,
                    "mode": "agentteams",
                    "message_count": 0,
                    "last_message_at": room.updated_at.isoformat()
                    if room.updated_at
                    else None,
                    "created_at": room.created_at.isoformat() if room.created_at else None,
                    "updated_at": room.updated_at.isoformat() if room.updated_at else None,
                    "room_id": room.room_id,
                    "case_id": room.case_id,
                }
            )
        return items

    # ------------------------------------------------------------------
    # 磁盘 runs 目录扫描（同步，经 asyncio.to_thread 调用）
    # ------------------------------------------------------------------
    def _scan_runs(self, user_id: str, project_slug: str) -> list[dict]:
        runs_dir = self._factory.project_dir(user_id, project_slug) / "runs"
        if not runs_dir.is_dir():
            return []
        items = []
        for entry in runs_dir.iterdir():
            if not entry.is_dir() or entry.name.startswith("."):
                continue
            file_count = 0
            total_size = 0
            for file in entry.rglob("*"):
                if file.is_file():
                    file_count += 1
                    total_size += file.stat().st_size
            items.append(
                {
                    "name": entry.name,
                    "timestamp": self._run_timestamp(entry),
                    "has_agents_md": (entry / "AGENTS.md").is_file(),
                    "has_readme": (entry / "README.md").is_file(),
                    "has_environment": (entry / "environment.json").is_file(),
                    "file_count": file_count,
                    "total_size_bytes": total_size,
                }
            )
        # 目录名自带时间戳，按名称倒序即时间倒序
        items.sort(key=lambda item: item["name"], reverse=True)
        return items

    @staticmethod
    def _run_timestamp(entry: Path) -> str:
        """优先解析目录名中的 ``YYYYMMDD-HHMMSS``，失败回退到目录 mtime。"""
        match = _RUN_STAMP_RE.search(entry.name)
        if match:
            try:
                stamp = datetime.strptime(
                    f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S"
                ).replace(tzinfo=UTC)
                return stamp.isoformat()
            except ValueError:
                pass
        return datetime.fromtimestamp(entry.stat().st_mtime, UTC).isoformat()

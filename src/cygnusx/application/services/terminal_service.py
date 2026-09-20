"""终端应用服务 - 会话管理、容器生命周期、超时回收

所有运行时参数从 tool_configs/terminal/terminal_config.yaml 读取（mtime 热重载）。
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.terminal import (
    AdminTerminalSessionDTO,
    CreateTerminalDTO,
    TerminalResourceDTO,
    TerminalRuntimeConfigDTO,
    TerminalRuntimeResourceDTO,
    TerminalSessionDTO,
)
from cygnusx.core.exceptions import BusinessError, NotFoundError
from cygnusx.domain.terminal.entities import TerminalSession
from cygnusx.domain.terminal.services import TerminalDomainService
from cygnusx.domain.terminal.value_objects import TerminalStatus
from cygnusx.infrastructure.database.models.terminal import TerminalSessionModel
from cygnusx.infrastructure.database.repositories.terminal_repository import (
    SqlAlchemyTerminalSessionRepository,
)
from cygnusx.infrastructure.terminal import get_terminal_docker_manager
from cygnusx.infrastructure.terminal.docker_manager import TerminalDockerError
from cygnusx.tools.terminal.config import (
    ResourceConfig,
    TerminalImage,
    get_terminal_config,
    get_terminal_images_config,
)


def _to_dto(s: TerminalSession) -> TerminalSessionDTO:
    cfg = get_terminal_config()
    images_cfg = get_terminal_images_config()
    image = images_cfg.get_image(s.image_id) if s.image_id else images_cfg.get_default_image()
    ws_url = None
    if s.is_active() and s.session_id:
        ws_url = f"/api/v1/terminal/sessions/{s.session_id}/ws"
    return TerminalSessionDTO(
        id=s.id,
        user_id=s.user_id,
        session_id=s.session_id,
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        host_port=s.host_port,
        ws_url=ws_url,
        image_id=image.id if image else s.image_id,
        image_name=image.name if image else None,
        last_activity=s.last_activity,
        created_at=s.created_at,
        expires_at=s.expires_at,
        resources=TerminalResourceDTO(
            memory_mb=cfg.default_resources.memory_mb,
            cpu_cores=cfg.default_resources.cpu_cores,
            pid_limit=cfg.default_resources.pid_limit,
        ),
    )


def _generate_session_id() -> str:
    return "term_" + secrets.token_urlsafe(16)


def _runtime_resource_to_dto(resource: ResourceConfig) -> TerminalRuntimeResourceDTO:
    return TerminalRuntimeResourceDTO(
        memory_mb=resource.memory_mb,
        cpu_cores=resource.cpu_cores,
        pid_limit=resource.pid_limit,
        tmpfs_size_mb=resource.tmpfs_size_mb,
    )


class TerminalService:
    """终端应用服务"""

    def __init__(self, db: AsyncSession):
        self._db = db
        self._repo = SqlAlchemyTerminalSessionRepository(db)
        self._domain = TerminalDomainService(self._repo)
        self._docker = get_terminal_docker_manager()

    @property
    def _cfg(self):
        return get_terminal_config()

    @property
    def _images_cfg(self):
        return get_terminal_images_config()

    def get_enabled_images(self) -> list[TerminalImage]:
        """获取所有启用的终端镜像（前端镜像选择器数据源）。"""
        return self._images_cfg.get_enabled_images()

    def get_runtime_config(self) -> TerminalRuntimeConfigDTO:
        """获取终端运行时配置（mtime 热重载后返回前端用）。"""
        cfg = self._cfg
        return TerminalRuntimeConfigDTO(
            enabled=cfg.enabled,
            default_resources=_runtime_resource_to_dto(cfg.default_resources),
            max_resources=_runtime_resource_to_dto(cfg.max_resources),
        )

    async def list_sessions(self, user_id: UUID) -> list[TerminalSessionDTO]:
        sessions = await self._repo.list_active_by_user(user_id)
        return [_to_dto(s) for s in sessions]

    async def create_session(
        self, user_id: UUID, dto: CreateTerminalDTO | None = None
    ) -> TerminalSessionDTO:
        cfg = self._cfg
        if not cfg.enabled:
            raise BusinessError("终端功能未启用")

        active = await self._repo.list_active_by_user(user_id)
        if len(active) >= cfg.lifecycle.max_sessions_per_user:
            raise BusinessError(
                f"已达最大会话数 ({cfg.lifecycle.max_sessions_per_user})，请先销毁旧会话"
            )

        # 确定镜像（用户指定 -> 默认 -> 第一个启用镜像）
        images_cfg = self._images_cfg
        image = images_cfg.get_image(dto.image_id if dto else None)
        if image is None:
            raise BusinessError("没有可用的终端镜像，请检查 terminal_images.yaml 配置")

        session_id = _generate_session_id()
        session = TerminalSession(
            id=uuid4(),
            user_id=user_id,
            session_id=session_id,
            image_id=image.id,
            status=TerminalStatus.CREATING,
            expires_at=datetime.now(UTC) + timedelta(seconds=cfg.lifecycle.max_session_duration),
        )
        session = await self._domain.create_session(session)

        resources = dto.resources if dto else None
        try:
            container_id, host_port = await self._docker.create_container(
                user_id=str(user_id),
                session_id=session_id,
                image=image,
                registry_prefix=images_cfg.registry_prefix,
                memory_mb=resources.memory_mb if resources else None,
                cpu_cores=resources.cpu_cores if resources else None,
                pid_limit=resources.pid_limit if resources else None,
            )
            session.container_id = container_id
            session.host_port = host_port
            session.status = TerminalStatus.RUNNING
            session = await self._repo.save(session)
        except TerminalDockerError as e:
            session.status = TerminalStatus.ERROR
            await self._repo.save(session)
            raise BusinessError(f"终端不可用：{e}") from e

        logger.info(f"终端会话已创建: {session_id} user={user_id} image={image.id}")
        return _to_dto(session)

    async def get_session(self, user_id: UUID, session_id: str) -> TerminalSessionDTO:
        session = await self._repo.get_by_session_id(session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError("终端会话不存在")
        return _to_dto(session)

    async def delete_session(
        self, user_id: UUID, session_id: str, reason: str = "user_request"
    ) -> bool:
        session = await self._repo.get_by_session_id(session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError("终端会话不存在")

        await self._docker.destroy_container(session.container_id, session.host_port)
        result = await self._domain.destroy(session.id)
        logger.info(f"终端会话已销毁: {session_id} reason={reason}")
        return result

    async def heartbeat(self, session_id: str) -> None:
        session = await self._repo.get_by_session_id(session_id)
        if session and session.is_active():
            await self._repo.update_last_activity(session.id)

    async def get_session_internal(self, session_id: str) -> TerminalSession | None:
        return await self._repo.get_by_session_id(session_id)

    async def list_all_sessions(self, include_stats: bool = False) -> list[AdminTerminalSessionDTO]:
        """管理员：列出所有活跃终端会话。"""
        from cygnusx.infrastructure.database.models.user import UserModel

        sessions = await self._repo.list_all_active()
        user_ids = [s.user_id for s in sessions]
        user_map: dict[UUID, tuple[str, str | None]] = {}
        if user_ids:
            result = await self._db.execute(
                select(UserModel.id, UserModel.username, UserModel.nickname).where(UserModel.id.in_(user_ids))
            )
            user_map = {row.id: (row.username, row.nickname) for row in result.all()}

        cfg = self._cfg
        images_cfg = self._images_cfg
        dtos: list[AdminTerminalSessionDTO] = []
        now = datetime.now(UTC)
        for s in sessions:
            usage_seconds = int((now - (s.created_at or now)).total_seconds())
            container_name = (
                f"cygnusx-term-{str(s.user_id)[:8]}-{s.session_id}" if s.session_id else None
            )
            image = images_cfg.get_image(s.image_id) if s.image_id else None
            stats = None
            if include_stats and s.container_id:
                stats = await self._docker.get_container_stats(s.container_id)
            dtos.append(
                AdminTerminalSessionDTO(
                    id=s.id,
                    user_id=s.user_id,
                    username=(user_map.get(s.user_id) or (None, None))[0],
                    nickname=(user_map.get(s.user_id) or (None, None))[1],
                    session_id=s.session_id,
                    status=s.status.value if hasattr(s.status, "value") else str(s.status),
                    container_id=s.container_id,
                    container_name=container_name,
                    host_port=s.host_port,
                    ws_url=f"/api/v1/terminal/sessions/{s.session_id}/ws" if s.session_id else None,
                    image_id=image.id if image else s.image_id,
                    image_name=image.name if image else None,
                    created_at=s.created_at,
                    last_activity=s.last_activity,
                    expires_at=s.expires_at,
                    usage_seconds=usage_seconds,
                    resources=TerminalResourceDTO(
                        memory_mb=cfg.default_resources.memory_mb,
                        cpu_cores=cfg.default_resources.cpu_cores,
                        pid_limit=cfg.default_resources.pid_limit,
                    ),
                    stats=stats,
                )
            )
        return dtos

    async def admin_delete_session(self, session_id: str, reason: str = "admin_request") -> bool:
        """管理员：强制销毁任意终端会话。"""
        session = await self._repo.get_by_session_id(session_id)
        if session is None:
            raise NotFoundError("终端会话不存在")

        await self._docker.destroy_container(session.container_id, session.host_port)
        result = await self._domain.destroy(session.id)
        logger.info(f"管理员销毁终端会话: {session_id} reason={reason}")
        return result

    async def recycle_expired(self) -> int:
        timeout = self._cfg.lifecycle.idle_timeout
        threshold = datetime.now(UTC) - timedelta(seconds=timeout)

        result = await self._db.execute(
            select(TerminalSessionModel).where(
                TerminalSessionModel.status.in_(
                    [TerminalStatus.RUNNING.value, TerminalStatus.IDLE.value]
                ),
                TerminalSessionModel.last_activity < threshold,
            )
        )
        count = 0
        for model in result.scalars().all():
            await self._docker.destroy_container(model.container_id, model.host_port)
            await self._repo.delete(model.id)
            count += 1
        if count:
            logger.info(f"回收超期终端会话: {count} 个")
        return count

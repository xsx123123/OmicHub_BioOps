"""沙盒应用服务 - 会话管理、代码执行、超时回收"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.sandbox import SandboxSessionDTO
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import BusinessError, NotFoundError
from cygnusx.domain.sandbox.entities import SandboxSession
from cygnusx.domain.sandbox.services import SandboxDomainService
from cygnusx.domain.sandbox.value_objects import SandboxStatus
from cygnusx.infrastructure.database.repositories.sandbox_repository import (
    SqlAlchemySandboxSessionRepository,
)
from cygnusx.infrastructure.sandbox import get_sandbox_pool
from cygnusx.infrastructure.sandbox.pool import SandboxUnavailableError


def _to_dto(s: SandboxSession) -> SandboxSessionDTO:
    return SandboxSessionDTO(
        id=s.id,
        user_id=s.user_id,
        container_id=s.container_id,
        status=s.status.value if hasattr(s.status, "value") else str(s.status),
        language=s.language,
        last_activity=s.last_activity,
        created_at=s.created_at,
        expires_at=s.expires_at,
    )


class SandboxService:
    """沙盒应用服务"""

    def __init__(self, db: AsyncSession):
        self._db = db
        self._repo = SqlAlchemySandboxSessionRepository(db)
        self._domain = SandboxDomainService(self._repo)
        self._settings = get_settings()
        self._pool = get_sandbox_pool()

    async def list_sessions(self, user_id: UUID) -> list[SandboxSessionDTO]:
        sessions = await self._repo.list_by_user(user_id)
        return [_to_dto(s) for s in sessions]

    async def create_session(self, user_id: UUID, language: str = "python") -> SandboxSessionDTO:
        """创建沙盒会话（会话亲和性：复用用户已有活跃会话）"""
        active = await self._repo.get_active_by_user(user_id)
        if active is not None:
            # 会话可能跨 Web 重启复用旧容器。镜像更新或挂载根目录修复后，
            # 必须先验证实际 bind mount；否则数据库中的旧 container_id 会继续
            # 把 root:root 0755 目录带回下一次执行。
            if await self._pool.container_is_usable(active.container_id):
                return _to_dto(active)
            logger.warning(
                "沙盒会话容器不可复用，销毁并重新分配: session={} container={}",
                active.id,
                active.container_id,
            )
            await self._pool.destroy(active.container_id)
            await self._domain.destroy(active.id)

        if not self._settings.sandbox_enabled:
            raise BusinessError("沙盒功能未启用")

        session = SandboxSession(
            id=uuid4(),
            user_id=user_id,
            status=SandboxStatus.CREATING,
            language=language,
            expires_at=datetime.now() + timedelta(seconds=self._settings.sandbox_session_timeout),
        )
        session = await self._domain.create_session(session)

        # 分配容器（warm pool 优先）
        try:
            container_id = await self._pool.get_or_create_container(
                container_name=f"cygnusx-sandbox-{user_id}-{session.id.hex[:8]}"
            )
            session.container_id = container_id
            session.status = SandboxStatus.READY
            session = await self._repo.save(session)
        except SandboxUnavailableError as e:
            session.status = SandboxStatus.ERROR
            await self._repo.save(session)
            raise BusinessError(f"沙盒不可用：{e}") from e

        return _to_dto(session)

    async def get_session(self, user_id: UUID, session_id: UUID) -> SandboxSessionDTO:
        session = await self._repo.get_by_id(session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError("沙盒会话不存在")
        return _to_dto(session)

    async def delete_session(self, user_id: UUID, session_id: UUID) -> bool:
        session = await self._repo.get_by_id(session_id)
        if session is None or session.user_id != user_id:
            raise NotFoundError("沙盒会话不存在")
        await self._pool.destroy(session.container_id)
        return await self._domain.destroy(session_id)

    async def execute_code(
        self,
        user_id: UUID,
        session_id: UUID,
        code: str,
        timeout_sec: int = 0,
        language: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式执行代码"""
        session = await self._repo.get_by_id(session_id)
        if session is None or session.user_id != user_id:
            yield {"type": "error", "detail": "沙盒会话不存在"}
            return
        if not session.container_id:
            yield {"type": "error", "detail": "沙盒容器未就绪"}
            return

        effective_language = language or session.language or "python"
        if effective_language not in {"python", "r", "bash"}:
            yield {"type": "error", "detail": f"不支持的沙盒语言: {effective_language}"}
            return

        await self._domain.mark_executing(session_id)
        try:
            async for event in self._pool.stream_execute(
                session.container_id,
                code,
                timeout_sec=timeout_sec or None,
                language=effective_language,
            ):
                yield event
        except Exception as e:  # noqa: BLE001
            logger.exception(f"沙盒代码执行异常: session={session_id}")
            yield {"type": "error", "detail": f"执行异常：{e}"}
            await self._domain.mark_error(session_id)
            return
        await self._domain.mark_idle(session_id)

    async def recycle_expired(self) -> int:
        """回收超过配置空闲时间的会话（默认 5 分钟）。"""
        timeout = self._settings.sandbox_session_timeout
        threshold = datetime.now() - timedelta(seconds=timeout)
        # 取所有非销毁会话（按用户列表需遍历，这里简单扫描）
        from sqlalchemy import select

        from cygnusx.infrastructure.database.models.sandbox import SandboxSessionModel

        result = await self._db.execute(
            select(SandboxSessionModel).where(
                SandboxSessionModel.status.in_(
                    [
                        SandboxStatus.IDLE.value,
                        SandboxStatus.READY.value,
                        SandboxStatus.PAUSED.value,
                    ]
                ),
                SandboxSessionModel.last_activity < threshold,
            )
        )
        count = 0
        for model in result.scalars().all():
            await self._pool.destroy(model.container_id)
            await self._repo.delete(model.id)
            count += 1
        return count

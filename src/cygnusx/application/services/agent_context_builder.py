"""统一构建 Runtime 所需的 Agent 执行上下文。"""

from __future__ import annotations

import copy
import hashlib
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.config import get_settings
from cygnusx.core.telemetry import get_meter
from cygnusx.domain.execution.agent_context import AgentContext
from cygnusx.infrastructure.database.models.chat import ChatSessionModel

if TYPE_CHECKING:
    from cygnusx.application.services.agent_service import AgentService


_context_meter = get_meter("cygnusx.chat")
_context_build_duration = _context_meter.create_histogram(
    "agent.context.build.duration", unit="ms", description="Agent 上下文装配耗时"
)
_context_cache_access = _context_meter.create_counter(
    "agent.context.cache.access", description="Agent 上下文缓存访问次数"
)


@dataclass
class _CachedAssembly:
    expires_at: float
    assembled: Any


class AgentContextBuilder:
    """集中装配会话、Agent 和运行时标识，并缓存低频 Agent 绑定。"""

    _cache: dict[tuple[str, str, str, str], _CachedAssembly] = {}

    def __init__(self, db: AsyncSession, agent_service: AgentService | None = None) -> None:
        self._db = db
        self._agent_service = agent_service

    async def build(
        self,
        session_id: str,
        agent_id: str,
        *,
        user_message: str | None = None,
        mode: str = "chat",
    ) -> AgentContext | None:
        result = await self._db.execute(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == session_id,
                ChatSessionModel.status == "active",
            )
        )
        session = result.scalar_one_or_none()
        if session is None:
            return None
        return await self.build_for_session(
            session,
            agent_id,
            user_message=user_message,
            mode=mode,
        )

    async def build_for_session(
        self,
        session: ChatSessionModel,
        agent_id: str,
        *,
        user_message: str | None = None,
        mode: str = "chat",
    ) -> AgentContext | None:
        """由已加载会话构建上下文，供 Runtime 避免重复数据库读取。"""
        assembled = await self.assemble(
            agent_id,
            str(session.user_id),
            user_message=user_message,
            mode=mode,
        )
        if assembled is None:
            return None
        return AgentContext(
            session=session,
            assembled=assembled,
            mode=mode,
            execution_path=f"chat_{mode}",
            trace_id=uuid.uuid4().hex,
            run_id=f"agent-chat:{uuid.uuid4().hex}",
        )

    async def assemble(
        self,
        agent_id: str,
        user_id: str,
        *,
        user_message: str | None = None,
        mode: str = "chat",
    ) -> Any | None:
        """缓存并返回与既有 Runtime 兼容的可变 Agent 装配结果。"""
        started = time.perf_counter()
        cache_key = self._cache_key(agent_id, user_id, mode, user_message)
        assembled = self._get_cached(cache_key)
        cache_hit = assembled is not None
        if assembled is None:
            assembled = await self._assemble(agent_id, user_id, user_message)
            if assembled is None:
                return None
            self._cache[cache_key] = _CachedAssembly(
                expires_at=time.monotonic() + get_settings().agent_context_cache_ttl_seconds,
                assembled=self._clone_assembly(assembled),
            )
            assembled = self._clone_assembly(assembled)
        duration_ms = (time.perf_counter() - started) * 1000
        _context_build_duration.record(
            duration_ms,
            {"agent.id": agent_id, "chat.mode": mode, "cache.hit": cache_hit},
        )
        _context_cache_access.add(
            1,
            {"agent.id": agent_id, "chat.mode": mode, "cache.hit": cache_hit},
        )
        return assembled

    async def _assemble(self, agent_id: str, user_id: str, tool_query: str | None) -> Any | None:
        if self._agent_service is None:
            from cygnusx.application.services.agent_service import AgentService

            self._agent_service = AgentService(self._db)
        if tool_query:
            return await self._agent_service.assemble_context(
                agent_id,
                user_id=user_id,
                tool_query=tool_query,
            )
        return await self._agent_service.assemble_context(agent_id, user_id=user_id)

    @classmethod
    def _cache_key(
        cls, agent_id: str, user_id: str, mode: str, user_message: str | None
    ) -> tuple[str, str, str, str]:
        message_hash = hashlib.sha256((user_message or "").encode()).hexdigest()
        return agent_id, user_id, mode, message_hash

    @classmethod
    def _get_cached(cls, key: tuple[str, str, str, str]) -> Any | None:
        cached = cls._cache.get(key)
        if cached is None:
            return None
        if cached.expires_at <= time.monotonic():
            cls._cache.pop(key, None)
            return None
        return cls._clone_assembly(cached.assembled)

    @staticmethod
    def _clone_assembly(assembled: Any) -> Any:
        """隔离每次 Runtime 调用可变的工具与功能配置。"""
        clone = copy.copy(assembled)
        for attribute in ("tools", "features"):
            value = getattr(assembled, attribute, None)
            if value is not None:
                setattr(clone, attribute, copy.deepcopy(value))
        for attribute in ("mcp_servers", "skills"):
            value = getattr(assembled, attribute, None)
            if value is not None:
                setattr(clone, attribute, list(value))
        return clone

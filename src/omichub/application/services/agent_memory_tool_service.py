"""将 AgentMemoryService 暴露为 ToolBridge 后端同步工具。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select

from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.agent_memory_service import AgentMemoryService
from omichub.core.exceptions import BusinessError
from omichub.infrastructure.database.models.chat import ChatSessionModel


class AgentMemoryToolService:
    """记忆工具必须在 builtin 调用上下文中执行，确保用户与会话可追溯。"""

    @staticmethod
    def _service(context: ToolInvocationContext | None) -> AgentMemoryService:
        if context is None:
            raise BusinessError("长期记忆工具需要受控的会话调用上下文")
        return AgentMemoryService(context.db)

    @staticmethod
    def _memory_agent_id(scope: str, context: ToolInvocationContext | None) -> str | None:
        """画像与偏好跨 Agent 共享，项目和摘要按执行 Agent 隔离。"""
        if scope.strip().lower() in {"profile", "preference"}:
            return None
        return context.agent_id if context else None

    @staticmethod
    async def _project_id(context: ToolInvocationContext | None) -> str | None:
        if context is None:
            return None
        session = await context.db.scalar(
            select(ChatSessionModel).where(ChatSessionModel.session_id == context.session_id)
        )
        return session.project_id if session else None

    async def save_memory(
        self,
        *,
        user_id: str,
        content: str,
        scope: str,
        keywords: list[str] | None = None,
        context: ToolInvocationContext | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        result = await self._service(context).save_memory(
            user_id=user_id,
            content=content,
            scope=scope,
            keywords=keywords,
            agent_id=self._memory_agent_id(scope, context),
            project_id=await self._project_id(context),
            source_session=context.session_id if context else None,
        )
        return {
            "success": True,
            "memory_id": result["memory"]["id"],
            "action": result["action"],
            "summary": "已保存跨会话记忆。",
        }

    async def update_memory(
        self,
        *,
        user_id: str,
        memory_id: str,
        content: str,
        keywords: list[str] | None = None,
        context: ToolInvocationContext | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        result = await self._service(context).update_memory(
            user_id=user_id,
            memory_id=memory_id,
            content=content,
            keywords=keywords,
            source_session=context.session_id if context else None,
        )
        return {
            "success": True,
            "memory_id": result["memory"]["id"],
            "action": result["action"],
            "summary": "已更新跨会话记忆。",
        }

    async def forget_memory(
        self,
        *,
        user_id: str,
        memory_id: str,
        context: ToolInvocationContext | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        result = await self._service(context).forget_memory(user_id=user_id, memory_id=memory_id)
        return {"success": True, **result, "summary": "已遗忘指定记忆。"}

    async def search_memory(
        self,
        *,
        user_id: str,
        query: str,
        scope: str | None = None,
        limit: int = 5,
        context: ToolInvocationContext | None = None,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        result = await self._service(context).search_memory(
            user_id=user_id,
            query=query,
            scope=scope,
            limit=limit,
            agent_id=context.agent_id if context else None,
            project_id=await self._project_id(context),
        )
        return {"success": True, **result, "summary": f"找到 {result['count']} 条相关记忆。"}

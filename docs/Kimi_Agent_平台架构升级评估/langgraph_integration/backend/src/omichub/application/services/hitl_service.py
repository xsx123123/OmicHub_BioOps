"""
HITLService
============
HITL（人工在环）管理服务 —— 处理中断请求的人工响应。

职责:
    - 创建 HITLRequest 记录
    - 接收人工响应（确认 / 修改 / 拒绝）
    - 调用 LangGraphRuntimeService 恢复执行
    - 管理 HITL 超时和过期
    - 记录 HITL 历史（审计）

设计:
    - 与 LangGraphRuntimeService 协作（不直接操作 StateGraph）
    - HITLRequest 存储在 PostgreSQL（便于查询和审计）
    - Redis 用于实时通知（推送 SSE 到前端）
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from sqlalchemy import select, insert, update
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.domain.execution.agent_state import AgentState
from omichub.domain.execution.hitl_models import (
    HITLAction,
    HITLHistoryRecord,
    HITLRequest,
    HITLResponse,
    HITLType,
)
from omichub.infrastructure.database.session import async_session_factory
from omichub.infrastructure.cache import redis_client


class HITLService:
    """
    HITL 管理服务

    典型流程:
        1. LangGraph hitl_check 节点触发 interrupt
        2. LangGraphRuntimeService yield hitl_request 事件
        3. 前端收到 SSE → 渲染确认弹窗
        4. 用户操作 → POST /api/v1/agent/hitl/resume
        5. HITLService.handle_response() → 记录响应 → 恢复 LangGraph
    """

    REDIS_CHANNEL_PREFIX = "hitl:notify"

    def __init__(
        self,
        runtime_service: Any,  # LangGraphRuntimeService（避免循环导入）
    ):
        self._runtime = runtime_service

    # ── 核心方法 ──

    async def create_request(
        self,
        thread_id: str,
        session_id: str,
        user_id: int,
        hitl_type: HITLType,
        title: str,
        description: str,
        payload: Dict[str, Any],
        timeout_seconds: int = 300,
    ) -> HITLRequest:
        """
        创建 HITL 请求 —— 当 LangGraph 触发 interrupt 时调用

        Returns:
            HITLRequest 对象
        """
        request = HITLRequest(
            thread_id=thread_id,
            session_id=session_id,
            user_id=user_id,
            hitl_type=hitl_type,
            title=title,
            description=description,
            payload=payload,
            timeout_seconds=timeout_seconds,
        )

        # 存入数据库
        async with async_session_factory() as session:
            await session.execute(
                insert(hitl_requests_table).values(
                    id=request.id,
                    thread_id=request.thread_id,
                    session_id=request.session_id,
                    user_id=request.user_id,
                    hitl_type=request.hitl_type.value,
                    title=request.title,
                    description=request.description,
                    payload=json.dumps(request.payload),
                    status="pending",
                    created_at=request.created_at,
                    timeout_seconds=request.timeout_seconds,
                )
            )
            await session.commit()

        # 发布 Redis 通知（前端 SSE 实时推送）
        await self._publish_notification(request)

        return request

    async def handle_response(
        self,
        request_id: str,
        action: HITLAction,
        human_input: Dict[str, Any],
        user_id: int,
        comment: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        处理人工响应 —— 核心方法

        Args:
            request_id: HITLRequest ID
            action: confirm / modify / reject / defer
            human_input: 人工输入数据（修改后的参数等）
            user_id: 响应用户ID
            comment: 备注

        Returns:
            {"success": bool, "thread_id": str, "message": str}
        """
        # 1. 获取请求
        request = await self._get_request(request_id)
        if not request:
            return {"success": False, "message": "HITL 请求不存在"}

        if request.status != "pending":
            return {"success": False, "message": f"HITL 请求已 {request.status}"}

        if request.is_expired:
            await self._update_status(request_id, "expired")
            return {"success": False, "message": "HITL 请求已超时"}

        # 2. 记录响应
        response = HITLResponse(
            request_id=request_id,
            action=action,
            human_input=human_input,
            comment=comment,
            responded_by=user_id,
        )
        await self._save_response(response)
        await self._update_status(request_id, "responded")

        # 3. 记录历史
        history = HITLHistoryRecord(
            thread_id=request.thread_id,
            session_id=request.session_id,
            user_id=request.user_id,
            hitl_type=request.hitl_type,
            request_payload=request.payload,
            response_action=action,
            response_input=human_input,
            latency_seconds=time.time() - request.created_at,
        )
        await self._save_history(history)

        # 4. 根据 action 处理
        if action == HITLAction.REJECT:
            # 拒绝 → 终止 LangGraph 执行
            return {
                "success": True,
                "thread_id": request.thread_id,
                "message": "操作已取消",
                "action": "reject",
            }

        elif action == HITLAction.DEFER:
            # 稍后处理 → 保存草稿
            return {
                "success": True,
                "thread_id": request.thread_id,
                "message": "已保存为草稿",
                "action": "defer",
            }

        elif action in (HITLAction.CONFIRM, HITLAction.MODIFY):
            # 确认或修改 → 恢复 LangGraph
            resume_input = self._build_resume_input(request, action, human_input)

            # 异步恢复（不阻塞响应）
            asyncio.create_task(
                self._resume_langgraph(request.thread_id, resume_input)
            )

            return {
                "success": True,
                "thread_id": request.thread_id,
                "message": f"已{ '确认' if action == HITLAction.CONFIRM else '修改并' }恢复执行",
                "action": action.value,
            }

        return {"success": False, "message": "未知操作类型"}

    async def get_pending_requests(
        self,
        user_id: int,
        session_id: Optional[str] = None,
    ) -> List[HITLRequest]:
        """获取用户的待处理 HITL 请求"""
        async with async_session_factory() as session:
            query = select(hitl_requests_table).where(
                hitl_requests_table.c.user_id == user_id,
                hitl_requests_table.c.status == "pending",
            )
            if session_id:
                query = query.where(hitl_requests_table.c.session_id == session_id)

            result = await session.execute(query)
            rows = result.mappings().all()

            requests = []
            for row in rows:
                req = self._row_to_request(row)
                # 过滤已过期
                if not req.is_expired:
                    requests.append(req)
                else:
                    # 自动标记过期
                    await self._update_status(req.id, "expired")

            return requests

    async def cancel_request(self, request_id: str, user_id: int) -> bool:
        """取消 HITL 请求（仅限发起用户）"""
        request = await self._get_request(request_id)
        if not request or request.user_id != user_id:
            return False

        if request.status != "pending":
            return False

        await self._update_status(request_id, "cancelled")
        return True

    # ── 内部方法 ──

    async def _get_request(self, request_id: str) -> Optional[HITLRequest]:
        """从数据库获取 HITLRequest"""
        async with async_session_factory() as session:
            result = await session.execute(
                select(hitl_requests_table).where(
                    hitl_requests_table.c.id == request_id
                )
            )
            row = result.mappings().first()
            return self._row_to_request(row) if row else None

    async def _update_status(self, request_id: str, status: str) -> None:
        """更新请求状态"""
        async with async_session_factory() as session:
            await session.execute(
                update(hitl_requests_table)
                .where(hitl_requests_table.c.id == request_id)
                .values(status=status, responded_at=time.time())
            )
            await session.commit()

    async def _save_response(self, response: HITLResponse) -> None:
        """保存响应"""
        async with async_session_factory() as session:
            await session.execute(
                insert(hitl_responses_table).values(
                    id=response.request_id,
                    action=response.action.value,
                    human_input=json.dumps(response.human_input),
                    comment=response.comment,
                    responded_by=response.responded_by,
                    responded_at=response.responded_at,
                )
            )
            await session.commit()

    async def _save_history(self, history: HITLHistoryRecord) -> None:
        """保存历史记录"""
        async with async_session_factory() as session:
            await session.execute(
                insert(hitl_history_table).values(
                    id=history.id,
                    thread_id=history.thread_id,
                    session_id=history.session_id,
                    user_id=history.user_id,
                    hitl_type=history.hitl_type.value,
                    request_payload=json.dumps(history.request_payload),
                    response_action=history.response_action.value,
                    response_input=json.dumps(history.response_input),
                    latency_seconds=history.latency_seconds,
                    created_at=history.created_at,
                )
            )
            await session.commit()

    async def _publish_notification(self, request: HITLRequest) -> None:
        """发布 Redis 通知"""
        try:
            channel = f"{self.REDIS_CHANNEL_PREFIX}:{request.user_id}:{request.session_id}"
            await redis_client.publish(
                channel,
                json.dumps({
                    "type": "hitl_request",
                    "request_id": request.id,
                    "hitl_type": request.hitl_type.value,
                    "title": request.title,
                    "thread_id": request.thread_id,
                }),
            )
        except Exception:
            pass

    def _build_resume_input(
        self,
        request: HITLRequest,
        action: HITLAction,
        human_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """构建 LangGraph 恢复输入"""
        return {
            "action": action.value,
            "hitl_type": request.hitl_type.value,
            "confirmed_params": human_input.get("confirmed_params", {}),
            "modifications": human_input.get("modifications", {}),
            "comment": human_input.get("comment", ""),
            "original_payload": request.payload,
        }

    async def _resume_langgraph(self, thread_id: str, resume_input: Dict[str, Any]) -> None:
        """恢复 LangGraph 执行"""
        if self._runtime:
            async for event in self._runtime.resume_hitl(thread_id, resume_input):
                # 事件由 RuntimeService 处理 SSE 推送
                pass

    def _row_to_request(self, row) -> HITLRequest:
        """数据库行转 HITLRequest"""
        return HITLRequest(
            id=row["id"],
            thread_id=row["thread_id"],
            session_id=row["session_id"],
            user_id=row["user_id"],
            hitl_type=HITLType(row["hitl_type"]),
            title=row["title"],
            description=row["description"],
            payload=json.loads(row["payload"]) if row["payload"] else {},
            status=row["status"],
            created_at=row["created_at"],
            timeout_seconds=row["timeout_seconds"],
            responded_at=row.get("responded_at"),
        )


# ──────────────────────────────
# SQLAlchemy 表定义
# ──────────────────────────────

from sqlalchemy import Table, Column, String, Integer, Float, LargeBinary, MetaData, Index, Text

metadata = MetaData()

hitl_requests_table = Table(
    "hitl_requests",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("thread_id", String(64), nullable=False),
    Column("session_id", String(64), nullable=False),
    Column("user_id", Integer, nullable=False),
    Column("hitl_type", String(32), nullable=False),
    Column("title", String(256), nullable=False),
    Column("description", Text, nullable=False),
    Column("payload", Text, nullable=False),
    Column("status", String(20), nullable=False, default="pending"),
    Column("created_at", Float, nullable=False),
    Column("timeout_seconds", Integer, nullable=False, default=300),
    Column("responded_at", Float, nullable=True),
    Index("idx_hitl_user_pending", "user_id", "status"),
    Index("idx_hitl_thread", "thread_id"),
    Index("idx_hitl_session", "session_id", "created_at"),
)

hitl_responses_table = Table(
    "hitl_responses",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("action", String(20), nullable=False),
    Column("human_input", Text, nullable=False),
    Column("comment", Text, nullable=True),
    Column("responded_by", Integer, nullable=False),
    Column("responded_at", Float, nullable=False),
)

hitl_history_table = Table(
    "hitl_history",
    metadata,
    Column("id", String(32), primary_key=True),
    Column("thread_id", String(64), nullable=False),
    Column("session_id", String(64), nullable=False),
    Column("user_id", Integer, nullable=False),
    Column("hitl_type", String(32), nullable=False),
    Column("request_payload", Text, nullable=False),
    Column("response_action", String(20), nullable=False),
    Column("response_input", Text, nullable=False),
    Column("latency_seconds", Float, nullable=False),
    Column("created_at", Float, nullable=False),
    Index("idx_hithist_user", "user_id", "created_at"),
    Index("idx_hithist_thread", "thread_id"),
)

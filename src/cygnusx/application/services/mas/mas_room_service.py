"""部门房间消息读写、进程内 SSE 广播、run 启停与事件落账。

权威状态账本：mas_room_runs / mas_room_events（LangGraph checkpoint 只作恢复载体）。
消息落库使用独立 AsyncSession（手册红线 5），不与调用方会话共享。
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.database.models.mas_room import (
    MASRoomEventModel,
    MASRoomMessageModel,
    MASRoomRunModel,
)

# 进程内广播 hub：room_id -> set[asyncio.Queue]（单 web 进程多 worker 的广播
# 一致性本阶段不做，TODO：生产多副本时回退 Redis pubsub——手册 Part 5 允许的唯一 Redis 用途）
_ROOM_SUBSCRIBERS: dict[str, set[asyncio.Queue]] = {}

# room_id -> asyncio.Task（活跃 run 任务；单房间单 run）
_ROOM_RUN_TASKS: dict[str, asyncio.Task] = {}


def subscribe_room(room_id: str) -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=256)
    _ROOM_SUBSCRIBERS.setdefault(room_id, set()).add(queue)
    return queue


def unsubscribe_room(room_id: str, queue: asyncio.Queue) -> None:
    subscribers = _ROOM_SUBSCRIBERS.get(room_id)
    if subscribers is not None:
        subscribers.discard(queue)
        if not subscribers:
            _ROOM_SUBSCRIBERS.pop(room_id, None)


async def broadcast_room(room_id: str, event: dict[str, Any]) -> None:
    """向本房间所有订阅者推送事件（绝不抛异常，队列满时丢弃保主流程）。"""
    subscribers = _ROOM_SUBSCRIBERS.get(room_id) or set()
    for queue in list(subscribers):
        try:
            queue.put_nowait(event)
        except asyncio.QueueFull:  # pragma: no cover - 慢消费者丢帧
            continue


def _to_dto(message: MASRoomMessageModel) -> dict[str, Any]:
    return {
        "id": str(message.id),
        "room_id": message.room_id,
        "run_id": message.run_id,
        "agent_id": message.agent_id,
        "role": message.role,
        "content": message.content,
        "metadata": message.meta or {},
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }


class MASRoomService:
    """房间消息应用服务（每实例一个会话，由 API 层注入）。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    # --- 消息层 ---

    async def add_user_message(self, room_id: str, user_id: str, content: str) -> dict[str, Any]:
        """用户发言落库并广播，然后启动/续跑 MAS run（乐观锁：仅无活跃 run 才新建）。"""
        message = MASRoomMessageModel(
            room_id=room_id,
            agent_id=None,
            role="user",
            content=content,
            meta={"user_id": user_id},
        )
        self._db.add(message)
        await self._db.commit()
        await self._db.refresh(message)
        dto = _to_dto(message)
        await broadcast_room(room_id, {"type": "room_message", **dto})
        return dto

    async def add_agent_message(
        self,
        room_id: str,
        *,
        agent_id: str | None,
        role: str,
        content: str,
        run_id: str | None = None,
        meta: dict[str, Any] | None = None,
        broadcast: bool = True,
    ) -> dict[str, Any]:
        """Agent / trace / plan_card 消息落库（MAS 节点调用，独立会话）。"""
        from cygnusx.infrastructure.database.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            message = MASRoomMessageModel(
                room_id=room_id,
                run_id=run_id,
                agent_id=agent_id,
                role=role,
                content=content,
                meta=meta or {},
            )
            session.add(message)
            await session.commit()
            await session.refresh(message)
            dto = _to_dto(message)
        if broadcast:
            await broadcast_room(room_id, {"type": "room_message", **dto})
        return dto

    async def add_assistant_message_with_chunks(
        self,
        room_id: str,
        *,
        agent_id: str,
        content: str,
        run_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Worker turn 最终文本一次性落库（打字机增量已由 SSE 透传，落库存全文）。"""
        return await self.add_agent_message(
            room_id,
            agent_id=agent_id,
            role="assistant",
            content=content,
            run_id=run_id,
            meta=meta,
        )

    async def list_messages(
        self, room_id: str, *, limit: int = 100, before: str | None = None
    ) -> list[dict[str, Any]]:
        """按 created_at 倒序分页拉历史（返回升序，前端直接渲染时间线）。"""
        stmt = select(MASRoomMessageModel).where(MASRoomMessageModel.room_id == room_id)
        if before:
            parsed = _parse_uuid(before)
            if parsed is not None:
                anchor = await self._db.get(MASRoomMessageModel, parsed)
                if anchor is not None and anchor.created_at is not None:
                    stmt = stmt.where(MASRoomMessageModel.created_at < anchor.created_at)
        stmt = stmt.order_by(MASRoomMessageModel.created_at.desc()).limit(limit)
        result = await self._db.execute(stmt)
        items = [_to_dto(m) for m in result.scalars().all()]
        items.reverse()
        return items

    async def list_messages_after(self, room_id: str, *, after_id: str | None = None) -> list[dict[str, Any]]:
        """SSE 轮询兜底：after_id 为前端已见最大 id（uuid 非单调，前端按 id 去重）。"""
        stmt = (
            select(MASRoomMessageModel)
            .where(MASRoomMessageModel.room_id == room_id)
            .order_by(MASRoomMessageModel.created_at.asc())
            .limit(50)
        )
        result = await self._db.execute(stmt)
        return [_to_dto(m) for m in result.scalars().all()]

    # --- run 账本 ---

    async def get_active_run(self, room_id: str) -> MASRoomRunModel | None:
        """查询房间活跃 run（running / awaiting_review）。"""
        stmt = (
            select(MASRoomRunModel)
            .where(
                MASRoomRunModel.room_id == room_id,
                MASRoomRunModel.status.in_(["running", "awaiting_review"]),
            )
            .order_by(MASRoomRunModel.created_at.desc())
            .limit(1)
        )
        result = await self._db.execute(stmt)
        return result.scalars().first()

    async def create_run(self, room_id: str, user_id: str, root_request: str) -> MASRoomRunModel:
        run = MASRoomRunModel(
            run_id=uuid.uuid4().hex[:32],
            room_id=room_id,
            user_id=user_id,
            status="running",
            root_request=root_request,
        )
        self._db.add(run)
        await self._db.commit()
        await self._db.refresh(run)
        return run

    async def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        session: AsyncSession | None = None,
    ) -> None:
        """节点级事件落账本（独立会话；绝不抛异常）。"""
        from cygnusx.infrastructure.database.session import get_session_factory

        factory = get_session_factory()
        async with factory() as db:
            try:
                seq_result = await db.execute(
                    select(func.coalesce(func.max(MASRoomEventModel.sequence), 0)).where(
                        MASRoomEventModel.run_id == run_id
                    )
                )
                seq = int(seq_result.scalar() or 0) + 1
                db.add(
                    MASRoomEventModel(
                        run_id=run_id,
                        sequence=seq,
                        event_type=event_type,
                        payload=payload or {},
                    )
                )
                await db.commit()
            except Exception:  # noqa: BLE001 - 审计事件失败不阻断主流程
                from cygnusx.core.log import get_logger  # noqa: F401

                await db.rollback()

    async def update_run_status(
        self, run_id: str, status: str, *, error: str | None = None
    ) -> None:
        from cygnusx.infrastructure.database.session import get_session_factory

        factory = get_session_factory()
        async with factory() as db:
            run = await db.get(MASRoomRunModel, run_id)
            if run is None:
                return
            run.status = status
            if error:
                run.error = error
            if status in ("finished", "failed"):
                run.finished_at = datetime.now(UTC)
            await db.commit()

    # --- 人工判断点（阶段 3）---

    async def resolve_plan_decision(
        self,
        run_id: str,
        user_id: str,
        action: str,
        *,
        edited_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """人工决议落账本并 resume 图（interrupt 语义对齐 orchestrator 图）。"""
        from langgraph.types import Command

        from cygnusx.infrastructure.database.session import get_session_factory
        from cygnusx.infrastructure.execution.checkpointer import postgres_checkpointer

        await self.update_run_status(run_id, "running")
        await self.append_run_event(
            run_id, "plan_resumed", {"action": action, "user_id": user_id}
        )
        decision = {"action": action}
        if edited_plan:
            decision["edited_plan"] = edited_plan

        task = asyncio.create_task(self._resume_run(run_id, decision))
        _ROOM_RUN_TASKS[_room_of(run_id)] = task
        return {"run_id": run_id, "action": action, "resumed": True}

    async def _resume_run(self, run_id: str, decision: dict[str, Any]) -> None:
        """从 checkpoint 恢复挂起的图并继续执行（Command(resume=...)）。"""
        from cygnusx.application.services.mas.mas_graph import (
            DEFAULT_DEPT_MEMBERS,
            build_mas_graph,
        )
        from langgraph.types import Command
        from cygnusx.application.services.mas.mas_supervisor import build_supervisor_llm
        from cygnusx.domain.execution.mas_state import FINISH_SENTINEL
        from cygnusx.infrastructure.database.session import get_session_factory
        from cygnusx.infrastructure.execution.checkpointer import postgres_checkpointer

        room_id = _room_of(run_id)
        try:
            async def emit(_room_id: str, event: dict[str, Any]) -> None:
                await broadcast_room(room_id, {**event, "run_id": run_id})

            supervisor_llm = await build_supervisor_llm()
            if supervisor_llm is None:
                await self.update_run_status(run_id, "failed", error="无可用 AI Provider")
                await broadcast_room(room_id, {"type": "error", "run_id": run_id})
                return

            async def worker_executor(
                agent_id: str, user_id: str, messages: list, emit_fn, _room: str
            ) -> str:
                from cygnusx.application.services.mas.mas_worker_executor import run_worker_turn

                return await run_worker_turn(agent_id, user_id, messages, emit_fn, room_id)

            async with postgres_checkpointer() as checkpointer:
                graph = build_mas_graph(
                    DEFAULT_DEPT_MEMBERS, supervisor_llm, worker_executor, emit, self,
                    checkpointer=checkpointer,
                )
                await graph.ainvoke(
                    Command(resume=decision),
                    config={"configurable": {"thread_id": run_id}},
                )
            await self.append_run_event(run_id, "run_finished", {"resumed": True})
            await self.update_run_status(run_id, "finished")
            await broadcast_room(room_id, {"type": "done", "run_id": run_id})
        except Exception as exc:  # noqa: BLE001 - resume 失败不落死
            await self.append_run_event(run_id, "run_failed", {"error": str(exc)})
            await self.update_run_status(run_id, "failed", error=str(exc))
            await broadcast_room(room_id, {"type": "error", "run_id": run_id, "content": str(exc)})
        finally:
            _ROOM_RUN_TASKS.pop(room_id, None)

    # --- run 启停（阶段 2 核心）---

    async def start_or_resume_run(
        self,
        room_id: str,
        user_id: str,
        content: str,
        *,
        members: list[dict[str, Any]],
        supervisor_llm: Any,
        worker_executor: Any,
    ) -> dict[str, Any]:
        """POST 发言后启动/续跑 run：乐观锁（仅无活跃 run 才新建），后台任务执行图。"""
        active = await self.get_active_run(room_id)
        if active is not None:
            # 复用活跃 run：把新消息追加进历史（图在下一轮读最新消息）
            return {"run_id": active.run_id, "resumed": True}

        run = await self.create_run(room_id, user_id, content)
        await self.append_run_event(run.run_id, "run_started", {"room_id": room_id})
        await broadcast_room(
            room_id, {"type": "run_started", "run_id": run.run_id, "room_id": room_id}
        )
        task = asyncio.create_task(
            self._execute_run(
                run.run_id,
                room_id,
                user_id,
                content,
                members=members,
                supervisor_llm=supervisor_llm,
                worker_executor=worker_executor,
            )
        )
        _ROOM_RUN_TASKS[room_id] = task
        return {"run_id": run.run_id, "resumed": False}

    async def _execute_run(
        self,
        run_id: str,
        room_id: str,
        user_id: str,
        root_request: str,
        *,
        members: list[dict[str, Any]],
        supervisor_llm: Any,
        worker_executor: Any,
    ) -> None:
        """后台执行 MAS 图：历史由调用方显式传入（红线 4），终态落账本并广播 done。"""
        from cygnusx.application.services.mas.mas_graph import build_mas_graph
        from cygnusx.domain.execution.mas_state import FINISH_SENTINEL
        from cygnusx.infrastructure.database.session import get_session_factory
        from cygnusx.infrastructure.execution.checkpointer import postgres_checkpointer

        try:
            async def emit(_room_id: str, event: dict[str, Any]) -> None:
                await broadcast_room(room_id, {**event, "run_id": run_id})

            factory = get_session_factory()
            async with factory() as session:
                history = await MASRoomService(session).list_messages(room_id, limit=50)
            # 消息角色映射：trace/plan_card 只用于前端渲染，注入模型时转为 system
            #（OpenAI 兼容 API 只接受 system/user/assistant/tool）。
            initial_messages = [
                {
                    "role": (
                        "system"
                        if m["role"] in ("mas_trace", "plan_card")
                        else m["role"]
                    ),
                    "name": m.get("agent_id") or "",
                    "content": m["content"],
                    "metadata": {"user_id": (m.get("metadata") or {}).get("user_id", user_id)},
                }
                for m in history
            ]

            async with postgres_checkpointer() as checkpointer:
                graph = build_mas_graph(
                    members, supervisor_llm, worker_executor, emit, self,
                    checkpointer=checkpointer,
                )
                result = await graph.ainvoke(
                    {
                        "messages": initial_messages,
                        "room_id": room_id,
                        "run_id": run_id,
                        "orchestration_rounds": 0,
                    },
                    config={"configurable": {"thread_id": run_id}},
                )
            # interrupt 挂起：图在 plan_review 暂停，run 进入 awaiting_review
            if result.get("__interrupt__"):
                await self.append_run_event(run_id, "plan_interrupted", {"pending_plan": True})
                await self.update_run_status(run_id, "awaiting_review")
                await broadcast_room(room_id, {"type": "plan_card", "run_id": run_id})
                return
            next_worker = result.get("next_worker") or FINISH_SENTINEL
            await self.append_run_event(
                run_id, "run_finished", {"next_worker": next_worker}
            )
            await self.update_run_status(run_id, "finished")
            await broadcast_room(room_id, {"type": "done", "run_id": run_id})
        except Exception as exc:  # noqa: BLE001 - run 失败不落死
            await self.append_run_event(run_id, "run_failed", {"error": str(exc)})
            await self.update_run_status(run_id, "failed", error=str(exc))
            await broadcast_room(room_id, {"type": "error", "run_id": run_id, "content": str(exc)})
        finally:
            _ROOM_RUN_TASKS.pop(room_id, None)


def _parse_uuid(value: str) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


# run 的房间归属：MVP 单默认房间；多房间时由 mas_room_runs.room_id 查询取代
def _room_of(run_id: str) -> str:
    return "bioinfo-dept"

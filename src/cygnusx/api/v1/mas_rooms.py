"""生物信息部门（MAS 房间）API：消息历史、用户发言、SSE 订阅。

阶段 1 骨架：POST 发言只落库并广播，不启动 MAS run（阶段 2 接入）。
SSE 惯例对齐 api/v1/goals.py（StreamingResponse + data: {...}\n\n + heartbeat）。
"""

import asyncio
import json
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.application.services.mas.mas_room_service import MASRoomService
from cygnusx.application.services.mas.mas_worker_executor import run_worker_turn

router = APIRouter()


async def _worker_executor(
    agent_id: str, user_id: str, messages: list, emit: Any, room_id: str
) -> str:
    """Worker 执行器绑定（run_worker_turn 签名适配）。"""
    return await run_worker_turn(agent_id, user_id, messages, emit, room_id)


def get_room_service(db: DbSession) -> MASRoomService:
    return MASRoomService(db)


RoomServiceDep = Annotated[MASRoomService, Depends(get_room_service)]


@router.get("/{room_id}/messages", summary="拉取房间消息历史")
async def list_messages(
    room_id: str,
    service: RoomServiceDep,
    current_user_id: CurrentUserId,
    limit: int = Query(default=100, ge=1, le=500),
    before: str | None = None,
) -> dict[str, Any]:
    items = await service.list_messages(room_id, limit=limit, before=before)
    return {"room_id": room_id, "messages": items}


@router.post("/{room_id}/messages", summary="发送用户发言")
async def post_message(
    room_id: str,
    body: dict[str, Any],
    service: RoomServiceDep,
    current_user_id: CurrentUserId,
) -> dict[str, Any]:
    content = str(body.get("content") or "").strip()
    if not content:
        from cygnusx.core.exceptions import BusinessError

        raise BusinessError("消息内容不能为空")
    item = await service.add_user_message(room_id, current_user_id, content)
    # 启动/续跑 MAS run（乐观锁：仅无活跃 run 才新建）
    from cygnusx.application.services.mas.mas_supervisor import build_supervisor_llm

    supervisor_llm = await build_supervisor_llm()
    from cygnusx.application.services.mas.mas_graph import DEFAULT_DEPT_MEMBERS

    members = DEFAULT_DEPT_MEMBERS
    run_info = await service.start_or_resume_run(
        room_id,
        current_user_id,
        content,
        members=members,
        supervisor_llm=supervisor_llm,
        worker_executor=_worker_executor,
    )
    return {**item, "run": run_info}


@router.post("/runs/{run_id}/plan-decision", summary="人工判断点决议（approve/reject/edit）")
async def plan_decision(
    run_id: str,
    body: dict[str, Any],
    service: RoomServiceDep,
    current_user_id: CurrentUserId,
) -> dict[str, Any]:
    action = str(body.get("action") or "").strip()
    if action not in ("approve", "reject", "edit"):
        from cygnusx.core.exceptions import BusinessError

        raise BusinessError("action 必须是 approve / reject / edit")
    return await service.resolve_plan_decision(
        run_id, current_user_id, action, edited_plan=body.get("edited_plan")
    )


@router.get("/{room_id}/stream", summary="SSE 订阅房间实时事件")
async def stream_room(
    room_id: str,
    current_user_id: CurrentUserId,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    """SSE：run 内事件 + 本房间新消息（落库即推送）。"""

    from cygnusx.infrastructure.database.session import get_session_factory
    from cygnusx.application.services.mas.mas_room_service import subscribe_room

    async def generate_sse() -> Any:
        queue = subscribe_room(room_id)
        cursor = after
        try:
            while True:
                # DB 轮询兜底（多进程/漏推场景），进程内 Queue 主通道。
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=1.0)
                    cursor = max(cursor, int(item.get("seq") or 0))
                    yield f"data: {json.dumps(item, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    pass
                async with get_session_factory()() as session:
                    page = await MASRoomService(session).list_messages_after(room_id, after=cursor)
                for msg in page:
                    cursor = max(cursor, int(msg.get("seq") or 0))
                    yield f"data: {json.dumps(msg, ensure_ascii=False)}\n\n"
                if not page:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            unsubscribe_room = None
            # 进程内广播退订
            from cygnusx.application.services.mas.mas_room_service import unsubscribe_room as _unsub

            _unsub(room_id, queue)

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

"""任务路由"""

import json
from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import StreamingResponse

from omichub.api.deps import CurrentUserId, DbSession, get_active_user_from_token_payload
from omichub.application.schemas.task import (
    TaskListResponse,
    TaskResponse,
    TaskSubmitRequest,
)
from omichub.application.services.task_service import TaskService
from omichub.core.security import decode_token
from omichub.infrastructure.cache.pubsub import subscribe_arq_progress, subscribe_task_logs
from omichub.infrastructure.database.repositories.task_repository import (
    TaskRepositoryImpl,
)
from omichub.infrastructure.database.session import get_session_factory

router = APIRouter()


def get_task_service(db: DbSession) -> TaskService:
    """获取任务服务实例"""
    return TaskService(db)


TaskServiceDep = Annotated[TaskService, Depends(get_task_service)]


@router.get("", response_model=TaskListResponse, summary="获取任务列表")
async def list_tasks(
    current_user_id: CurrentUserId,
    service: TaskServiceDep,
    status: Annotated[str | None, Query(description="按状态过滤")] = None,
    limit: Annotated[
        int | None, Query(ge=1, le=100, description="最多返回条数（按提交时间倒序的最近 N 条）")
    ] = None,
) -> TaskListResponse:
    """获取当前用户的任务列表"""
    return await service.list_tasks(current_user_id, status=status, limit=limit)


@router.post(
    "",
    response_model=TaskResponse,
    status_code=status.HTTP_201_CREATED,
    summary="提交分析任务",
)
async def submit_task(
    req: TaskSubmitRequest,
    current_user_id: CurrentUserId,
    service: TaskServiceDep,
) -> TaskResponse:
    """提交新的分析任务"""
    return await service.submit(current_user_id, req)


@router.get("/{task_id}", response_model=TaskResponse, summary="获取任务详情")
async def get_task(
    task_id: UUID,
    current_user_id: CurrentUserId,
    service: TaskServiceDep,
) -> TaskResponse:
    """获取指定任务详情"""
    return await service.get_task(task_id, current_user_id)


@router.get("/{task_id}/logs", summary="获取任务日志")
async def get_task_logs(
    task_id: UUID,
    current_user_id: CurrentUserId,
    service: TaskServiceDep,
) -> dict[str, Any]:
    """获取任务执行日志"""
    task = await service.get_task(task_id, current_user_id)
    return {
        "task_id": str(task_id),
        "logs": [log.model_dump() for log in task.logs],
    }


@router.post("/{task_id}/cancel", response_model=TaskResponse, summary="取消任务")
async def cancel_task(
    task_id: UUID,
    current_user_id: CurrentUserId,
    service: TaskServiceDep,
) -> TaskResponse:
    """取消未结束的任务"""
    return await service.cancel_task(task_id, current_user_id)


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT, summary="删除任务")
async def delete_task(
    task_id: UUID,
    current_user_id: CurrentUserId,
    service: TaskServiceDep,
) -> None:
    """删除指定任务（硬删除，同时清理随行的日志等数据）"""
    await service.delete_task(task_id, current_user_id)


@router.get("/{task_id}/dag", summary="获取任务 DAG 可视化")
async def get_task_dag(
    task_id: UUID,
    current_user_id: CurrentUserId,
    service: TaskServiceDep,
) -> dict[str, Any]:
    """生成并返回 Snakemake DAG（SVG 或 DOT 文本）"""
    result = await service.get_task_dag(task_id, current_user_id)
    return result


@router.websocket("/{task_id}/ws", name="task_logs_websocket")
async def task_logs_websocket(websocket: WebSocket, task_id: str) -> None:
    """任务日志 WebSocket 实时推送。

    连接示例：wss://host/api/v1/tasks/{task_id}/ws?token=<JWT>
    """
    token = websocket.query_params.get("token")
    payload = decode_token(token) if token else None
    if payload is None or payload.get("type") != "access":
        await websocket.close(code=1008, reason="Invalid token")
        return

    user = await get_active_user_from_token_payload(payload)
    if user is None:
        await websocket.close(code=1008, reason="User inactive or not found")
        return

    user_id = str(user.id)

    # 校验任务归属
    async with get_session_factory()() as session:
        repo = TaskRepositoryImpl(session)
        task = await repo.get_by_id(UUID(task_id))
        if task is None or str(task.user_id) != user_id:
            await websocket.close(code=1008, reason="Task not found")
            return

    await websocket.accept()
    pubsub = await subscribe_task_logs(task_id)
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except WebSocketDisconnect:
        pass
    finally:
        await pubsub.unsubscribe()
        await pubsub.close()


@router.get("/{task_id}/progress", summary="ARQ 任务进度 SSE")
async def task_progress_sse(
    task_id: str, current_user_id: CurrentUserId
) -> StreamingResponse:
    """ARQ 异步任务进度 Server-Sent Events。

    连接示例：/api/v1/tasks/{task_id}/progress
    """

    async def event_generator() -> AsyncIterator[str]:
        pubsub = await subscribe_arq_progress(task_id)
        try:
            # 先发送一次初始事件
            yield f"data: {json.dumps({'task_id': task_id, 'phase': 'PENDING', 'progress': 0.0, 'message': '等待进度...'}, ensure_ascii=False)}\n\n"
            async for message in pubsub.listen():
                if message["type"] == "message":
                    data = message["data"]
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    yield f"data: {data}\n\n"
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

"""Authenticated control plane for the opt-in persistent Goal runtime."""

from __future__ import annotations

import asyncio
import json
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from fastapi.responses import StreamingResponse

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.application.schemas.goal import (
    GoalAnswerRequest,
    GoalControlRequest,
    GoalEventPage,
    GoalResponse,
    GoalStartRequest,
)
from cygnusx.application.services.goal_service import GoalService
from cygnusx.infrastructure.database.session import get_session_factory

router = APIRouter()


def get_goal_service(db: DbSession) -> GoalService:
    return GoalService(db)


GoalServiceDep = Annotated[GoalService, Depends(get_goal_service)]


def _enqueue_goal_step(goal_id: UUID, cause: str) -> None:
    from cygnusx.infrastructure.celery_app.tasks.goals import run_goal_step

    run_goal_step.delay(str(goal_id), cause)


@router.post("/start", response_model=GoalResponse, status_code=status.HTTP_201_CREATED)
async def start_goal(
    request: GoalStartRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
    service: GoalServiceDep,
) -> GoalResponse:
    goal = await service.create_goal(current_user_id, request)
    await db.commit()
    _enqueue_goal_step(goal.id, "created")
    return goal


@router.get("", response_model=list[GoalResponse])
async def list_goals(
    current_user_id: CurrentUserId,
    service: GoalServiceDep,
    session_id: str | None = Query(default=None, max_length=50),
) -> list[GoalResponse]:
    return await service.list_goals(current_user_id, session_id=session_id)


@router.get("/{goal_id}", response_model=GoalResponse)
async def get_goal(
    goal_id: UUID, current_user_id: CurrentUserId, service: GoalServiceDep
) -> GoalResponse:
    return await service.get_goal(current_user_id, goal_id)


@router.post("/{goal_id}/pause", response_model=GoalResponse)
async def pause_goal(
    goal_id: UUID,
    request: GoalControlRequest,
    current_user_id: CurrentUserId,
    service: GoalServiceDep,
) -> GoalResponse:
    return await service.pause_goal(current_user_id, goal_id, request)


@router.post("/{goal_id}/resume", response_model=GoalResponse)
async def resume_goal(
    goal_id: UUID,
    request: GoalControlRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
    service: GoalServiceDep,
) -> GoalResponse:
    goal = await service.resume_goal(current_user_id, goal_id, request)
    await db.commit()
    _enqueue_goal_step(goal.id, "resumed")
    return goal


@router.post("/{goal_id}/answer", response_model=GoalResponse)
async def answer_goal(
    goal_id: UUID,
    request: GoalAnswerRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
    service: GoalServiceDep,
) -> GoalResponse:
    goal = await service.answer_goal(current_user_id, goal_id, request)
    await db.commit()
    _enqueue_goal_step(goal.id, "user_answered")
    return goal


@router.post("/{goal_id}/cancel", response_model=GoalResponse)
async def cancel_goal(
    goal_id: UUID,
    request: GoalControlRequest,
    current_user_id: CurrentUserId,
    service: GoalServiceDep,
) -> GoalResponse:
    return await service.cancel_goal(current_user_id, goal_id, request)


@router.get("/{goal_id}/events", response_model=GoalEventPage)
async def list_goal_events(
    goal_id: UUID,
    current_user_id: CurrentUserId,
    service: GoalServiceDep,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> GoalEventPage:
    return await service.list_events(current_user_id, goal_id, after=after, limit=limit)


@router.get("/{goal_id}/events/stream")
async def stream_goal_events(
    goal_id: UUID,
    current_user_id: CurrentUserId,
    service: GoalServiceDep,
    after: int = Query(default=0, ge=0),
) -> StreamingResponse:
    await service.get_goal(current_user_id, goal_id)

    async def generate_sse():
        cursor = after
        from cygnusx.infrastructure.cache.goal_pubsub import subscribe_goal_events

        pubsub = await subscribe_goal_events(str(goal_id))
        try:
            while True:
                async with get_session_factory()() as session:
                    page = await GoalService(session).list_events(
                        current_user_id, goal_id, after=cursor, limit=100
                    )
                for event in page.items:
                    cursor = event.sequence
                    yield f"data: {json.dumps(event.model_dump(mode='json'), ensure_ascii=False)}\n\n"
                message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("type") == "message":
                    payload = json.loads(message["data"])
                    if int(payload.get("sequence") or 0) > cursor:
                        cursor = int(payload["sequence"])
                        yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
                elif not page.items:
                    yield ": heartbeat\n\n"
        except asyncio.CancelledError:
            raise
        finally:
            await pubsub.unsubscribe()
            await pubsub.close()

    return StreamingResponse(
        generate_sse(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

"""Authenticated REST endpoints for user schedules."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.application.schemas.schedule import (
    DeliveryResponse,
    OccurrenceResponse,
    ScheduleCreateRequest,
    ScheduleListResponse,
    ScheduleResponse,
    ScheduleUpdateRequest,
)
from cygnusx.application.services.schedule_service import ScheduleService

router = APIRouter()


def get_schedule_service(db: DbSession) -> ScheduleService:
    return ScheduleService(db)


ScheduleServiceDep = Annotated[ScheduleService, Depends(get_schedule_service)]


@router.get("", response_model=ScheduleListResponse, summary="获取当前用户日程")
async def list_schedules(
    current_user_id: CurrentUserId,
    service: ScheduleServiceDep,
    schedule_status: Annotated[str | None, Query(alias="status")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
) -> ScheduleListResponse:
    schedules = await service.list(current_user_id, status=schedule_status, limit=limit)
    return ScheduleListResponse(items=schedules, total=len(schedules))


@router.post("", response_model=ScheduleResponse, status_code=status.HTTP_201_CREATED, summary="创建日程")
async def create_schedule(
    request: ScheduleCreateRequest, current_user_id: CurrentUserId, service: ScheduleServiceDep
) -> ScheduleResponse:
    return await service.create(current_user_id, request)


@router.get("/{schedule_id}", response_model=ScheduleResponse, summary="获取日程详情")
async def get_schedule(
    schedule_id: UUID, current_user_id: CurrentUserId, service: ScheduleServiceDep
) -> ScheduleResponse:
    return await service.get(current_user_id, schedule_id)


@router.patch("/{schedule_id}", response_model=ScheduleResponse, summary="修改日程")
async def update_schedule(
    schedule_id: UUID,
    request: ScheduleUpdateRequest,
    current_user_id: CurrentUserId,
    service: ScheduleServiceDep,
) -> ScheduleResponse:
    return await service.update(current_user_id, schedule_id, request)


@router.post("/{schedule_id}/cancel", response_model=ScheduleResponse, summary="取消日程")
async def cancel_schedule(
    schedule_id: UUID, current_user_id: CurrentUserId, service: ScheduleServiceDep
) -> ScheduleResponse:
    return await service.cancel(current_user_id, schedule_id)


@router.post("/{schedule_id}/complete", response_model=ScheduleResponse, summary="完成日程")
async def complete_schedule(
    schedule_id: UUID, current_user_id: CurrentUserId, service: ScheduleServiceDep
) -> ScheduleResponse:
    return await service.complete_schedule(current_user_id, schedule_id)


@router.get("/{schedule_id}/occurrences", response_model=list[OccurrenceResponse], summary="获取日程实例")
async def list_occurrences(
    schedule_id: UUID, current_user_id: CurrentUserId, service: ScheduleServiceDep
) -> list[OccurrenceResponse]:
    return await service.occurrences(current_user_id, schedule_id)


@router.get("/{schedule_id}/deliveries", response_model=list[DeliveryResponse], summary="获取提醒投递记录")
async def list_deliveries(
    schedule_id: UUID, current_user_id: CurrentUserId, service: ScheduleServiceDep
) -> list[DeliveryResponse]:
    return await service.deliveries(current_user_id, schedule_id)

"""Authenticated actions for delivered reminders."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.application.schemas.schedule import DeliveryResponse, SnoozeRequest
from cygnusx.application.services.schedule_service import ScheduleService

router = APIRouter()


def get_schedule_service(db: DbSession) -> ScheduleService:
    return ScheduleService(db)


ScheduleServiceDep = Annotated[ScheduleService, Depends(get_schedule_service)]


@router.post("/{delivery_id}/snooze", response_model=DeliveryResponse, summary="推迟提醒")
async def snooze_reminder(
    delivery_id: UUID,
    request: SnoozeRequest,
    current_user_id: CurrentUserId,
    service: ScheduleServiceDep,
) -> DeliveryResponse:
    return await service.snooze(current_user_id, delivery_id, request.minutes)


@router.post("/{delivery_id}/complete", response_model=DeliveryResponse, summary="完成提醒")
async def complete_reminder(
    delivery_id: UUID, current_user_id: CurrentUserId, service: ScheduleServiceDep
) -> DeliveryResponse:
    return await service.complete(current_user_id, delivery_id)

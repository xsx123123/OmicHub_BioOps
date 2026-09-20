"""Database-backed schedule scanner and idempotent reminder delivery tasks."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from celery import shared_task
from sqlalchemy import select, update

from cygnusx.core.config import get_settings
from cygnusx.application.services.schedule_service import ScheduleService
from cygnusx.infrastructure.cache.redis_client import get_redis
from cygnusx.infrastructure.database.models.notification import NotificationModel
from cygnusx.infrastructure.database.models.schedule import (
    ReminderDeliveryModel,
    ScheduleModel,
    ScheduleOccurrenceModel,
)
from cygnusx.infrastructure.database.session import get_session_factory

_LEASE_KEY = "cygnusx:schedules:scan:lease"


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.schedules.scan_due_schedules")
def scan_due_schedules() -> dict[str, Any]:
    return asyncio.run(_scan_due_schedules())


async def _scan_due_schedules() -> dict[str, Any]:
    redis = get_redis()
    acquired = await redis.set(_LEASE_KEY, "1", nx=True, ex=60)
    if not acquired:
        return {"status": "skipped", "reason": "lease_held", "fired": 0}
    try:
        settings = get_settings()
        fired = 0
        async with get_session_factory()() as db:
            now = datetime.now(UTC)
            result = await db.execute(
                select(ScheduleModel)
                .where(ScheduleModel.status == "active", ScheduleModel.next_fire_at <= now)
                .order_by(ScheduleModel.next_fire_at)
                .limit(settings.schedule_scan_batch_size)
                .with_for_update(skip_locked=True)
            )
            schedules = list(result.scalars())
            for schedule in schedules:
                occurrence = await db.scalar(
                    select(ScheduleOccurrenceModel)
                    .where(
                        ScheduleOccurrenceModel.schedule_id == schedule.id,
                        ScheduleOccurrenceModel.status == "pending",
                        ScheduleOccurrenceModel.scheduled_at <= now,
                    )
                    .order_by(ScheduleOccurrenceModel.scheduled_at)
                    .with_for_update(skip_locked=True)
                )
                if occurrence is None:
                    if schedule.recurrence_rule:
                        await ScheduleService(db)._ensure_occurrences(schedule)
                        schedule.next_fire_at = await _next_pending_time(db, schedule.id)
                    else:
                        schedule.next_fire_at = None
                    continue
                occurrence.status = "fired"
                occurrence.fired_at = now
                schedule.last_fired_at = now
                if schedule.recurrence_rule:
                    await ScheduleService(db)._ensure_occurrences(schedule)
                schedule.next_fire_at = await _next_pending_time(db, schedule.id)
                if schedule.next_fire_at is None and not schedule.recurrence_rule:
                    schedule.status = "completed"
                schedule.version += 1
                fired += 1
            await db.commit()
        # Delivery rows are persisted at creation time; scan them independently so
        # offsets such as -15 minutes are not delayed until the event start.
        enqueued = await _enqueue_due_deliveries()
        return {"status": "scanned", "fired": fired, "enqueued": enqueued}
    finally:
        await redis.delete(_LEASE_KEY)


async def _next_pending_time(db: Any, schedule_id: UUID) -> datetime | None:
    return await db.scalar(
        select(ScheduleOccurrenceModel.scheduled_at)
        .where(
            ScheduleOccurrenceModel.schedule_id == schedule_id,
            ScheduleOccurrenceModel.status == "pending",
        )
        .order_by(ScheduleOccurrenceModel.scheduled_at)
        .limit(1)
    )


async def _enqueue_due_deliveries() -> int:
    count = 0
    async with get_session_factory()() as db:
        now = datetime.now(UTC)
        result = await db.execute(
            select(ReminderDeliveryModel)
            .where(
                ReminderDeliveryModel.status == "pending",
                ReminderDeliveryModel.due_at <= now,
                (ReminderDeliveryModel.next_retry_at.is_(None) | (ReminderDeliveryModel.next_retry_at <= now)),
            )
            .with_for_update(skip_locked=True)
            .limit(get_settings().schedule_scan_batch_size * 20)
        )
        deliveries = list(result.scalars())
        for delivery in deliveries:
            delivery.status = "sending"
            deliver_reminder.apply_async(args=[str(delivery.id)])
            count += 1
        await db.commit()
    return count


@shared_task(
    bind=True,
    max_retries=0,
    name="cygnusx.infrastructure.celery_app.tasks.schedules.deliver_reminder",
)
def deliver_reminder(self: Any, delivery_id: str) -> dict[str, Any]:
    return asyncio.run(_deliver_reminder(UUID(delivery_id)))


async def _deliver_reminder(delivery_id: UUID) -> dict[str, Any]:
    async with get_session_factory()() as db:
        delivery = await db.get(ReminderDeliveryModel, delivery_id)
        if delivery is None or delivery.status in {"sent", "suppressed"}:
            return {"status": "ignored"}
        schedule = await db.get(ScheduleModel, delivery.schedule_id)
        if schedule is None or schedule.status != "active":
            delivery.status = "suppressed"
            await db.commit()
            return {"status": "suppressed"}
        try:
            notification = NotificationModel(
                title=schedule.title,
                content=schedule.description or schedule.title,
                level="info",
                type="reminder",
                payload={"schedule_id": str(schedule.id), "delivery_id": str(delivery.id)},
                created_by=schedule.user_id,
                is_global=False,
                target_user_id=schedule.user_id,
                read_by=[],
            )
            db.add(notification)
            await db.flush()
            delivery.notification_id = notification.id
            delivery.status = "sent"
            delivery.sent_at = datetime.now(UTC)
            await db.commit()
            await get_redis().publish(
                f"user:{schedule.user_id}:notifications",
                json.dumps({"type": "reminder", "schedule_id": str(schedule.id), "delivery_id": str(delivery.id), "notification_id": str(notification.id)}, ensure_ascii=False),
            )
            return {"status": "sent"}
        except Exception as exc:  # noqa: BLE001
            delivery.attempt_count += 1
            delivery.last_error = str(exc)
            if delivery.attempt_count >= get_settings().schedule_max_delivery_attempts:
                delivery.status = "failed"
            else:
                delivery.status = "pending"
                delivery.next_retry_at = datetime.now(UTC) + timedelta(
                    seconds=60 * (2 ** delivery.attempt_count)
                )
            await db.commit()
            return {"status": delivery.status, "error": str(exc)}


@shared_task(name="cygnusx.infrastructure.celery_app.tasks.schedules.retry_failed_deliveries")
def retry_failed_deliveries() -> dict[str, Any]:
    return asyncio.run(_retry_failed_deliveries())


async def _retry_failed_deliveries() -> dict[str, Any]:
    async with get_session_factory()() as db:
        now = datetime.now(UTC)
        result = await db.execute(
            select(ReminderDeliveryModel.id).where(
                ReminderDeliveryModel.status == "pending",
                ReminderDeliveryModel.next_retry_at <= now,
            )
        )
        ids = [str(item) for item in result.scalars()]
    for delivery_id in ids:
        deliver_reminder.apply_async(args=[delivery_id])
    return {"status": "queued", "count": len(ids)}

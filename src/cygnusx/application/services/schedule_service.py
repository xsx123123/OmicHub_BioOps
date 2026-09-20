"""Domain service for schedules, occurrences, and reminder deliveries."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID
from zoneinfo import ZoneInfo

from dateutil.rrule import rrulestr
from sqlalchemy import Select, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.schedule import ScheduleCreateRequest, ScheduleUpdateRequest
from cygnusx.core.exceptions import NotFoundError, ValidationError
from cygnusx.infrastructure.database.models.schedule import (
    ReminderDeliveryModel,
    ScheduleModel,
    ScheduleOccurrenceModel,
)


class ScheduleService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self, user_id: str, request: ScheduleCreateRequest, *, source: str = "manual"
    ) -> ScheduleModel:
        start_at = self._utc(request.start_at, request.timezone)
        end_at = self._utc(request.end_at, request.timezone) if request.end_at else None
        if end_at and end_at < start_at:
            raise ValidationError("end_at 不能早于 start_at")
        self._validate_rrule(request.recurrence_rule, start_at)
        schedule = ScheduleModel(
            user_id=UUID(user_id), workspace_id=request.workspace_id, team_id=request.team_id,
            title=request.title, description=request.description, timezone=request.timezone,
            start_at=start_at, end_at=end_at,
            duration_seconds=int((end_at - start_at).total_seconds()) if end_at else 0,
            recurrence_rule=request.recurrence_rule, next_fire_at=start_at, source=source,
            metadata_json={**request.metadata_json, "reminder_offsets_minutes": request.reminder_offsets_minutes},
        )
        self._db.add(schedule)
        await self._db.flush()
        await self._ensure_occurrences(schedule)
        return schedule

    async def list(self, user_id: str, *, status: str | None = None, limit: int = 100) -> list[ScheduleModel]:
        query = select(ScheduleModel).where(ScheduleModel.user_id == UUID(user_id))
        if status:
            query = query.where(ScheduleModel.status == status)
        result = await self._db.execute(query.order_by(ScheduleModel.start_at.desc()).limit(limit))
        return list(result.scalars())

    async def get(self, user_id: str, schedule_id: UUID) -> ScheduleModel:
        schedule = await self._db.scalar(
            select(ScheduleModel).where(ScheduleModel.id == schedule_id, ScheduleModel.user_id == UUID(user_id))
        )
        if schedule is None:
            raise NotFoundError("日程不存在")
        return schedule

    async def update(self, user_id: str, schedule_id: UUID, request: ScheduleUpdateRequest) -> ScheduleModel:
        schedule = await self.get(user_id, schedule_id)
        payload = request.model_dump(exclude_unset=True)
        if "status" in payload and payload["status"] not in {"active", "paused", "cancelled", "completed"}:
            raise ValidationError("status 必须是 active、paused、cancelled 或 completed")
        if "start_at" in payload:
            payload["start_at"] = self._utc(payload["start_at"], payload.get("timezone", schedule.timezone))
        if "end_at" in payload and payload["end_at"]:
            payload["end_at"] = self._utc(payload["end_at"], payload.get("timezone", schedule.timezone))
        recurrence_changed = "recurrence_rule" in payload or "start_at" in payload
        offsets = payload.pop("reminder_offsets_minutes", None)
        if "recurrence_rule" in payload:
            self._validate_rrule(payload["recurrence_rule"], payload.get("start_at", schedule.start_at))
        if "end_at" in payload and payload["end_at"] and payload["end_at"] < payload.get("start_at", schedule.start_at):
            raise ValidationError("end_at 不能早于 start_at")
        for name, value in payload.items():
            setattr(schedule, name, value)
        if schedule.status in {"paused", "cancelled", "completed"}:
            schedule.next_fire_at = None
            await self._db.execute(
                update(ReminderDeliveryModel)
                .where(
                    ReminderDeliveryModel.schedule_id == schedule.id,
                    ReminderDeliveryModel.status.in_(["pending", "sending"]),
                )
                .values(status="suppressed")
            )
        elif schedule.status == "active" and schedule.next_fire_at is None:
            await self._ensure_occurrences(schedule)
            schedule.next_fire_at = await self._db.scalar(
                select(ScheduleOccurrenceModel.scheduled_at)
                .where(
                    ScheduleOccurrenceModel.schedule_id == schedule.id,
                    ScheduleOccurrenceModel.status == "pending",
                )
                .order_by(ScheduleOccurrenceModel.scheduled_at)
                .limit(1)
            )
        if offsets is not None:
            schedule.metadata_json = {**schedule.metadata_json, "reminder_offsets_minutes": sorted(set(offsets))}
            recurrence_changed = True
        if recurrence_changed:
            await self._db.execute(
                update(ReminderDeliveryModel)
                .where(ReminderDeliveryModel.schedule_id == schedule.id, ReminderDeliveryModel.status == "pending")
                .values(status="suppressed")
            )
            await self._db.execute(
                update(ScheduleOccurrenceModel)
                .where(ScheduleOccurrenceModel.schedule_id == schedule.id, ScheduleOccurrenceModel.status == "pending")
                .values(status="skipped")
            )
            schedule.next_fire_at = schedule.start_at if schedule.status == "active" else None
            await self._ensure_occurrences(schedule)
        schedule.version += 1
        return schedule

    async def cancel(self, user_id: str, schedule_id: UUID) -> ScheduleModel:
        schedule = await self.get(user_id, schedule_id)
        schedule.status = "cancelled"
        schedule.next_fire_at = None
        schedule.version += 1
        await self._db.execute(
            update(ReminderDeliveryModel)
            .where(ReminderDeliveryModel.schedule_id == schedule.id, ReminderDeliveryModel.status.in_(["pending", "sending"]))
            .values(status="suppressed")
        )
        return schedule

    async def complete_schedule(self, user_id: str, schedule_id: UUID) -> ScheduleModel:
        schedule = await self.get(user_id, schedule_id)
        schedule.status = "completed"
        schedule.next_fire_at = None
        schedule.version += 1
        await self._db.execute(
            update(ReminderDeliveryModel)
            .where(
                ReminderDeliveryModel.schedule_id == schedule.id,
                ReminderDeliveryModel.status.in_(["pending", "sending"]),
            )
            .values(status="suppressed")
        )
        return schedule

    async def occurrences(self, user_id: str, schedule_id: UUID) -> list[ScheduleOccurrenceModel]:
        await self.get(user_id, schedule_id)
        result = await self._db.execute(
            select(ScheduleOccurrenceModel).where(ScheduleOccurrenceModel.schedule_id == schedule_id)
            .order_by(ScheduleOccurrenceModel.scheduled_at)
        )
        return list(result.scalars())

    async def deliveries(self, user_id: str, schedule_id: UUID) -> list[ReminderDeliveryModel]:
        await self.get(user_id, schedule_id)
        result = await self._db.execute(
            select(ReminderDeliveryModel).where(ReminderDeliveryModel.schedule_id == schedule_id)
            .order_by(ReminderDeliveryModel.due_at.desc())
        )
        return list(result.scalars())

    async def snooze(self, user_id: str, delivery_id: UUID, minutes: int) -> ReminderDeliveryModel:
        delivery = await self._owned_delivery(user_id, delivery_id)
        if delivery.status not in {"pending", "sent"}:
            raise ValidationError("当前提醒不可推迟")
        delivery.status = "pending"
        delivery.sent_at = None
        delivery.next_retry_at = None
        delivery.due_at = datetime.now(UTC) + timedelta(minutes=minutes)
        return delivery

    async def complete(self, user_id: str, delivery_id: UUID) -> ReminderDeliveryModel:
        delivery = await self._owned_delivery(user_id, delivery_id)
        occurrence = await self._db.get(ScheduleOccurrenceModel, delivery.occurrence_id)
        if occurrence:
            occurrence.status = "completed"
            occurrence.completed_at = datetime.now(UTC)
        return delivery

    async def _owned_delivery(self, user_id: str, delivery_id: UUID) -> ReminderDeliveryModel:
        delivery = await self._db.scalar(
            select(ReminderDeliveryModel).where(
                ReminderDeliveryModel.id == delivery_id, ReminderDeliveryModel.user_id == UUID(user_id)
            )
        )
        if delivery is None:
            raise NotFoundError("提醒不存在")
        return delivery

    async def _ensure_occurrences(self, schedule: ScheduleModel, *, days: int = 30) -> None:
        if schedule.status != "active":
            return
        until = datetime.now(UTC) + timedelta(days=days)
        existing = set((await self._db.scalars(
            select(ScheduleOccurrenceModel.occurrence_key).where(ScheduleOccurrenceModel.schedule_id == schedule.id)
        )).all())
        times = self._occurrence_times(schedule, until)
        offsets = schedule.metadata_json.get("reminder_offsets_minutes", [0])
        for scheduled_at in times:
            key = scheduled_at.isoformat()
            if key in existing:
                continue
            occurrence = ScheduleOccurrenceModel(
                schedule_id=schedule.id, occurrence_key=key, scheduled_at=scheduled_at,
                status="pending", created_at=datetime.now(UTC),
            )
            self._db.add(occurrence)
            await self._db.flush()
            for offset in offsets:
                self._db.add(ReminderDeliveryModel(
                    schedule_id=schedule.id, occurrence_id=occurrence.id, user_id=schedule.user_id,
                    channel="in_app", reminder_offset_minutes=int(offset),
                    due_at=scheduled_at - timedelta(minutes=int(offset)), status="pending",
                ))

    def _occurrence_times(self, schedule: ScheduleModel, until: datetime) -> list[datetime]:
        if not schedule.recurrence_rule:
            return [schedule.start_at]
        rule = rrulestr(schedule.recurrence_rule, dtstart=schedule.start_at)
        return [self._utc(value, schedule.timezone) for value in rule.between(schedule.start_at, until, inc=True)]

    @staticmethod
    def _validate_rrule(rule: str | None, start_at: datetime) -> None:
        if not rule:
            return
        try:
            rrulestr(rule, dtstart=start_at)
        except (TypeError, ValueError) as exc:
            raise ValidationError("recurrence_rule 必须是有效的 RFC 5545 RRULE") from exc

    @staticmethod
    def _utc(value: datetime, timezone: str) -> datetime:
        if value.tzinfo is None:
            try:
                value = value.replace(tzinfo=ZoneInfo(timezone))
            except Exception as exc:  # noqa: BLE001
                raise ValidationError("timezone 无效") from exc
        return value.astimezone(UTC)

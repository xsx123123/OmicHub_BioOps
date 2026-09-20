"""ToolBridge adapter that derives all ownership from ToolInvocationContext."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo

from cygnusx.application.schemas.schedule import ScheduleCreateRequest, ScheduleUpdateRequest
from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.schedule_service import ScheduleService
from cygnusx.core.exceptions import ValidationError


class ScheduleToolService:
    async def create(
        self,
        *,
        user_id: str,
        title: str,
        start_at: datetime | None = None,
        natural_time: str | None = None,
        timezone: str = "Asia/Shanghai",
        description: str | None = None,
        recurrence_rule: str | None = None,
        reminder_offsets_minutes: list[int] | None = None,
        context: ToolInvocationContext,
    ) -> dict[str, Any]:
        self._require_owner(user_id, context)
        if start_at is None:
            if not natural_time:
                raise ValidationError("必须提供 start_at 或 natural_time")
            start_at = parse_natural_time(natural_time, timezone)
        schedule = await ScheduleService(context.db).create(
            user_id,
            ScheduleCreateRequest(
                title=title, start_at=start_at, timezone=timezone, description=description,
                recurrence_rule=recurrence_rule,
                reminder_offsets_minutes=reminder_offsets_minutes or [0],
                workspace_id=context.extra.get("workspace_id"),
            ),
            source="ai",
        )
        return {"schedule_id": str(schedule.id), "status": schedule.status, "summary": f"已创建日程：{schedule.title}"}

    async def list(self, *, user_id: str, status: str | None = None, context: ToolInvocationContext) -> dict[str, Any]:
        self._require_owner(user_id, context)
        schedules = await ScheduleService(context.db).list(user_id, status=status)
        return {"schedules": [{"id": str(item.id), "title": item.title, "start_at": item.start_at.isoformat(), "status": item.status} for item in schedules], "count": len(schedules)}

    async def update(self, *, user_id: str, schedule_id: str, context: ToolInvocationContext, **changes: Any) -> dict[str, Any]:
        self._require_owner(user_id, context)
        schedule = await ScheduleService(context.db).update(user_id, UUID(schedule_id), ScheduleUpdateRequest(**changes))
        return {"schedule_id": str(schedule.id), "status": schedule.status, "summary": "日程已更新"}

    async def cancel(self, *, user_id: str, schedule_id: str, context: ToolInvocationContext) -> dict[str, Any]:
        self._require_owner(user_id, context)
        schedule = await ScheduleService(context.db).cancel(user_id, UUID(schedule_id))
        return {"schedule_id": str(schedule.id), "status": schedule.status, "summary": "日程已取消"}

    async def complete_schedule(self, *, user_id: str, schedule_id: str, context: ToolInvocationContext) -> dict[str, Any]:
        self._require_owner(user_id, context)
        schedule = await ScheduleService(context.db).complete_schedule(user_id, UUID(schedule_id))
        return {"schedule_id": str(schedule.id), "status": schedule.status, "summary": "日程已完成"}

    async def snooze(self, *, user_id: str, delivery_id: str, minutes: int, context: ToolInvocationContext) -> dict[str, Any]:
        self._require_owner(user_id, context)
        delivery = await ScheduleService(context.db).snooze(user_id, UUID(delivery_id), minutes)
        return {"delivery_id": str(delivery.id), "status": delivery.status, "due_at": delivery.due_at.isoformat()}

    async def complete(self, *, user_id: str, delivery_id: str, context: ToolInvocationContext) -> dict[str, Any]:
        self._require_owner(user_id, context)
        delivery = await ScheduleService(context.db).complete(user_id, UUID(delivery_id))
        return {"delivery_id": str(delivery.id), "status": "completed"}

    @staticmethod
    def _require_owner(user_id: str, context: ToolInvocationContext) -> None:
        if user_id != context.user_id:
            raise ValidationError("user_id 必须与调用上下文一致")


def parse_natural_time(text: str, user_timezone: str = "Asia/Shanghai") -> datetime:
    """Parse common Chinese relative reminder expressions into UTC."""
    try:
        timezone = ZoneInfo(user_timezone)
    except Exception as exc:  # noqa: BLE001
        raise ValidationError("timezone 无效") from exc
    now = datetime.now(timezone).replace(second=0, microsecond=0)
    hours_match = re.search(r"(\d+)\s*小时后", text)
    if hours_match:
        return (now + timedelta(hours=int(hours_match.group(1)))).astimezone(UTC)
    base = now
    if "明天" in text:
        base += timedelta(days=1)
    elif "后天" in text:
        base += timedelta(days=2)
    time_match = re.search(r"(\d{1,2})(?:\s*[:点]\s*(\d{1,2}))?", text)
    if time_match:
        hour = int(time_match.group(1))
        minute = int(time_match.group(2) or 0)
        if ("下午" in text or "晚上" in text) and hour < 12:
            hour += 12
        if hour > 23 or minute > 59:
            raise ValidationError("时间格式无效")
        base = base.replace(hour=hour, minute=minute)
    return base.astimezone(UTC)

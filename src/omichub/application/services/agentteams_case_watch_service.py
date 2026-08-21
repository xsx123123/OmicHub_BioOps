"""将 AgentTeams Case 的关键状态变化可靠回流到聊天会话。"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from omichub.application.services.agentteams_bridge_settings_service import (
    AgentTeamsBridgeSettingsService,
)
from omichub.application.services.agentteams_case_tool_service import agentteams_next_actor
from omichub.application.services.agentteams_service import AgentTeamsService
from omichub.application.services.case_room_projector import CaseRoomProjector
from omichub.application.services.site_settings_service import SiteSettingsService
from omichub.core.config import get_settings
from omichub.infrastructure.cache.chat_case_pubsub import publish_chat_case_event
from omichub.infrastructure.database.models.chat import (
    AgentTeamsCaseCursorModel,
    ChatMessageModel,
    ChatSessionModel,
)

logger = logging.getLogger(__name__)

WATCHED_STATUSES = frozenset(
    {
        "approval_pending",
        "quality_blocked",
        "delivery_ready",
        "execution_failed",
        "cancelled",
        "closed",
    }
)
TERMINAL_STATUSES = frozenset({"closed", "cancelled"})


def _watchable_sessions_query():
    """仅选择实际绑定了 AgentTeams Case 的会话。"""
    return select(ChatSessionModel).where(
        ChatSessionModel.sandbox_meta.is_not(None),
        ChatSessionModel.sandbox_meta.op("?")("agentteams_case_ids"),
    )


class AgentTeamsCaseWatchService:
    """按会话绑定扫描非终态 Case；读取失败不会影响其它会话。"""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def scan(self) -> dict[str, int]:
        settings = get_settings()
        if not (
            settings.agentteams_chat_entry_enabled
            or await SiteSettingsService(self._db).is_agentteams_chat_entry_enabled()
        ):
            return {"scanned": 0, "notified": 0, "failed": 0}

        runtime = await AgentTeamsBridgeSettingsService(self._db, settings).get_runtime_config()
        agentteams = AgentTeamsService(settings, runtime)
        if not agentteams.available:
            return {"scanned": 0, "notified": 0, "failed": 0}

        sessions = list(
            (
                await self._db.scalars(
                    _watchable_sessions_query()
                )
            ).all()
        )
        scanned = notified = failed = 0
        for session in sessions:
            try:
                result = await self._scan_session(session, agentteams)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning("AgentTeams Case watch session failed for %s: %s", session.session_id, exc)
                continue
            scanned += result["scanned"]
            notified += result["notified"]
            failed += result["failed"]
        await self._db.flush()
        return {"scanned": scanned, "notified": notified, "failed": failed}

    async def _scan_session(
        self, session: ChatSessionModel, agentteams: AgentTeamsService
    ) -> dict[str, int]:
        meta = dict(session.sandbox_meta or {})
        case_ids = [item for item in meta.get("agentteams_case_ids", []) if isinstance(item, str)]
        statuses = dict(meta.get("agentteams_case_status") or {})
        migration_mode = get_settings().agentteams_case_cursor_migration_mode
        legacy_notifications = dict(meta.get("agentteams_case_notified", {}) or {})
        legacy_cursors = dict(meta.get("agentteams_case_event_cursor", {}) or {})
        titles = dict(meta.get("agentteams_case_titles") or {})
        failure_counts = dict(meta.get("agentteams_case_watch_failures") or {})
        handoff_notifications = dict(meta.get("agentteams_case_handoff_notifications") or {})
        changed = False
        cursor_mismatches = 0
        scanned = notified = failed = 0

        for case_id in case_ids:
            if statuses.get(case_id) in TERMINAL_STATUSES:
                continue
            scanned += 1
            try:
                case = await agentteams.get_case(case_id, requester_ref=session.user_id)
            except Exception as exc:  # noqa: BLE001
                failed += 1
                failure_count = int(failure_counts.get(case_id) or 0) + 1
                failure_counts[case_id] = failure_count
                changed = True
                logger.warning("AgentTeams Case watch read failed for %s: %s", case_id, exc)
                if failure_count == 3:
                    event = await self._add_sync_failure_notification(
                        session.session_id,
                        case_id,
                        str(titles.get(case_id) or "协作 Case")[:80],
                    )
                    try:
                        await publish_chat_case_event(session.session_id, event)
                    except Exception as publish_exc:  # noqa: BLE001
                        logger.warning(
                            "AgentTeams Case sync warning publish failed for %s: %s",
                            case_id,
                            publish_exc,
                        )
                    notified += 1
                continue
            if int(failure_counts.get(case_id) or 0):
                failure_counts[case_id] = 0
                changed = True
            status = str(case.get("status") or "")
            if not status:
                continue
            cursor_state = await self._get_or_create_cursor_state(
                session.session_id,
                case_id,
                legacy_cursor=(
                    str(legacy_cursors.get(case_id) or "") or None
                    if migration_mode != "new_only"
                    else None
                ),
                legacy_notified_statuses=(
                    legacy_notifications.get(case_id) if migration_mode != "new_only" else None
                ),
            )
            legacy_cursor = str(legacy_cursors.get(case_id) or "") or None
            legacy_statuses = {
                value
                for value in legacy_notifications.get(case_id, [])
                if isinstance(value, str)
            }
            if migration_mode == "dual_write" and (
                (legacy_cursor and legacy_cursor != cursor_state.event_cursor)
                or legacy_statuses != {
                    value for value in cursor_state.notified_statuses if isinstance(value, str)
                }
            ):
                cursor_mismatches += 1
            title = str(case.get("intent") or titles.get(case_id) or "协作 Case")[:80]
            previous = str(statuses.get(case_id) or "")
            statuses[case_id] = status
            titles[case_id] = title
            try:
                events_page = await agentteams.get_case_events(
                    case_id,
                    requester_ref=session.user_id,
                    cursor=(
                        legacy_cursor
                        if migration_mode == "legacy_only"
                        else cursor_state.event_cursor or legacy_cursor
                    ),
                    limit=100,
                )
                events = events_page.get("events") if isinstance(events_page.get("events"), list) else []
                projector = CaseRoomProjector()
                for audit_event in events:
                    for projected in projector.project(
                        audit_event,
                        session_id=session.session_id,
                        flow_id=str(meta.get("flow_id") or ""),
                    ):
                        await publish_chat_case_event(session.session_id, projected)
                    if audit_event.get("event_type") == "room.agent_handoff":
                        handoff_event_id = str(audit_event.get("event_id") or "")
                        if handoff_event_id and handoff_event_id != handoff_notifications.get(case_id):
                            from omichub.infrastructure.celery_app.tasks.agentteams import (
                                respond_to_room_message,
                            )

                            respond_to_room_message.delay(
                                case_id,
                                session.user_id,
                                "系统交接：请 Manager 汇总刚完成的领域 Agent 交接，并说明风险与下一步。",
                            )
                            handoff_notifications[case_id] = handoff_event_id
                            changed = True
                next_cursor = events_page.get("next_cursor")
                last_event_id = str(events[-1].get("event_id") or "") if events else ""
                next_value = ""
                if isinstance(next_cursor, str) and next_cursor:
                    next_value = next_cursor
                elif last_event_id:
                    next_value = last_event_id
                if next_value:
                    if migration_mode != "legacy_only":
                        cursor_state.event_cursor = next_value
                    if migration_mode != "new_only":
                        legacy_cursors[case_id] = next_value
                        changed = True
            except Exception as exc:  # noqa: BLE001
                failed += 1
                logger.warning("AgentTeams Case event projection failed for %s: %s", case_id, exc)
            seen = {
                value for value in cursor_state.notified_statuses if isinstance(value, str)
            }
            if status != previous and status in WATCHED_STATUSES and status not in seen:
                event = await self._add_notification(
                    session.session_id,
                    case_id,
                    title,
                    status,
                    flow_id=str(case.get("flow_id") or ""),
                )
                seen.add(status)
                if migration_mode != "legacy_only":
                    cursor_state.notified_statuses = sorted(seen)
                if migration_mode != "new_only":
                    legacy_notifications[case_id] = sorted(seen)
                    changed = True
                try:
                    await publish_chat_case_event(session.session_id, event)
                except Exception as exc:  # noqa: BLE001
                    logger.warning("AgentTeams Case watch SSE publish failed for %s: %s", case_id, exc)
                notified += 1
            changed = changed or status != previous

        if migration_mode == "new_only":
            removed_notifications = meta.pop("agentteams_case_notified", None)
            removed_cursor = meta.pop("agentteams_case_event_cursor", None)
            changed = bool(removed_notifications is not None or removed_cursor is not None) or changed
        else:
            meta["agentteams_case_notified"] = legacy_notifications
            meta["agentteams_case_event_cursor"] = legacy_cursors
        meta["agentteams_case_cursor_migration"] = {
            "mode": migration_mode,
            "checked_at": datetime.now(UTC).isoformat(),
            "mismatch_count": cursor_mismatches,
        }
        if cursor_mismatches:
            logger.warning(
                "AgentTeams cursor dual-write mismatch: session=%s count=%s",
                session.session_id,
                cursor_mismatches,
            )
        changed = True

        if changed:
            meta["agentteams_case_status"] = statuses
            meta["agentteams_case_titles"] = titles
            meta["agentteams_case_watch_failures"] = failure_counts
            meta["agentteams_case_handoff_notifications"] = handoff_notifications
            session.sandbox_meta = meta
            session.updated_at = datetime.now(UTC)
        return {"scanned": scanned, "notified": notified, "failed": failed}

    async def _get_or_create_cursor_state(
        self,
        session_id: str,
        case_id: str,
        *,
        legacy_cursor: str | None,
        legacy_notified_statuses: object,
    ) -> AgentTeamsCaseCursorModel:
        state = await self._db.scalar(
            select(AgentTeamsCaseCursorModel).where(
                AgentTeamsCaseCursorModel.session_id == session_id,
                AgentTeamsCaseCursorModel.case_id == case_id,
            )
        )
        if state is not None:
            return state
        notified_statuses = (
            sorted({item for item in legacy_notified_statuses if isinstance(item, str)})
            if isinstance(legacy_notified_statuses, list)
            else []
        )
        state = AgentTeamsCaseCursorModel(
            session_id=session_id,
            case_id=case_id,
            event_cursor=legacy_cursor,
            notified_statuses=notified_statuses,
        )
        self._db.add(state)
        return state

    async def _add_notification(
        self,
        session_id: str,
        case_id: str,
        title: str,
        status: str,
        *,
        flow_id: str = "",
    ) -> dict[str, str]:
        next_actor = agentteams_next_actor(status)
        message_id = str(uuid.uuid4())
        case_url = f"/agent-teams/cases/{case_id}"
        completion_kind = "analysis_execution" if flow_id else "plan_delivery"
        if status == "closed":
            completion_label = "分析执行完成" if completion_kind == "analysis_execution" else "方案交付完成"
            content = (
                f"协作 Case「{title}」{completion_label}，"
                "交付清单与产物入口已在协作室中保留。"
            )
            next_actor = "无需处理（已完成）"
        else:
            content = (
                f"协作 Case「{title}」已进入「{status}」，"
                f"下一步请由 {next_actor} 处理。"
            )
        self._db.add(
            ChatMessageModel(
                id=uuid.uuid4(),
                message_id=message_id,
                session_id=session_id,
                role="system",
                content=content,
                content_type="text",
                status="complete",
                metadata_json={
                    "type": "agentteams_case",
                    "phase": "status_changed",
                    "case_id": case_id,
                    "title": title,
                    "status": status,
                    "next_actor": next_actor,
                    "completion_kind": completion_kind if status == "closed" else None,
                    "case_url": case_url,
                    "session_id": session_id,
                    "message_id": message_id,
                },
            )
        )
        session = await self._db.scalar(
            select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
        )
        if session is not None:
            session.message_count += 1
            session.last_message_at = datetime.now(UTC)
            session.updated_at = datetime.now(UTC)
        return {
            "type": "agentteams_case",
            "phase": "status_changed",
            "case_id": case_id,
            "title": title,
            "status": status,
            "next_actor": next_actor,
            "completion_kind": completion_kind if status == "closed" else "",
            "case_url": case_url,
            "session_id": session_id,
            "message_id": message_id,
        }

    async def _add_sync_failure_notification(
        self,
        session_id: str,
        case_id: str,
        title: str,
    ) -> dict[str, Any]:
        message_id = str(uuid.uuid4())
        content = (
            f"协作 Case「{title}」已连续 3 次同步失败。"
            "Bridge 可能暂时不可用，系统会继续自动重试；当前任务状态以 OmicHub 为准。"
        )
        self._db.add(
            ChatMessageModel(
                id=uuid.uuid4(),
                message_id=message_id,
                session_id=session_id,
                role="system",
                content=content,
                content_type="text",
                status="complete",
                metadata_json={
                    "type": "room_speech",
                    "phase": "agentteams_sync_warning",
                    "case_id": case_id,
                    "session_id": session_id,
                    "message_id": message_id,
                },
            )
        )
        session = await self._db.scalar(
            select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
        )
        if session is not None:
            session.message_count += 1
            session.last_message_at = datetime.now(UTC)
            session.updated_at = datetime.now(UTC)
        return {
            "type": "room_speech",
            "content": content,
            "sender": {
                "agent_id": "agent-general",
                "name": "星尘 AI",
                "avatar": "✨",
                "color": "#4f8ef7",
                "role": "manager",
            },
            "round": 0,
            "session_id": session_id,
            "message_id": message_id,
            "case_id": case_id,
        }

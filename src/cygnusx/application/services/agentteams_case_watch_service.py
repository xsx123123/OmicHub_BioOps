"""将 AgentTeams Case 的关键状态变化可靠回流到聊天会话。"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

from cygnusx.application.services.agentteams_bridge_settings_service import (
    AgentTeamsBridgeSettingsService,
)
from cygnusx.application.services.agentteams_case_tool_service import agentteams_next_actor
from cygnusx.application.services.agentteams_quality_gate_service import (
    AgentTeamsQualityGateService,
)
from cygnusx.application.services.agentteams_service import (
    CASE_LEVEL_WORK_ITEM_ID,
    AgentTeamsService,
)
from cygnusx.application.services.case_room_projector import CaseRoomProjector
from cygnusx.application.services.site_settings_service import SiteSettingsService
from cygnusx.core.config import get_settings
from cygnusx.infrastructure.cache.chat_case_pubsub import publish_chat_case_event
from cygnusx.infrastructure.database.models.chat import (
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
    """按会话绑定扫描非终态 Case；读取失败不会影响其它会话。

    每个 tick 通过 ``refresh_case`` 触发 Bridge reconcile：case 状态推进、
    ``omic_task.stalled`` 与 planning/execution 超时看门狗都由 reconcile 驱动。
    若只做纯读取（``get_case``），用户不打开 Case 视图时看门狗永远不触发
    （E2E-1 曾观测卡死 17min+ 未终止，根因即此）。
    """

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
        delivery_gates = dict(meta.get("agentteams_case_delivery_gate") or {})
        changed = False
        cursor_mismatches = 0
        scanned = notified = failed = 0

        for case_id in case_ids:
            if statuses.get(case_id) in TERMINAL_STATUSES:
                continue
            scanned += 1
            try:
                # refresh_case 内部即 Bridge reconcile（幂等，设计供轮询器反复调用），
                # 让 stall/timeout 看门狗不依赖用户打开 Case 视图也能触发。
                case = await agentteams.refresh_case(case_id, requester_ref=session.user_id)
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
            gate_reason = ""
            if status == "delivery_ready" and status != previous:
                # 交付门（quality.light_gate）：文件可打开性 + 引用完整性轻量校验。
                # 判定不通过转到既有 quality_blocked 路径（不发明新状态），
                # 结构化原因随通知与 Bridge 审计事件留痕；通过才放行交付通知。
                gate = await self._run_delivery_gate(agentteams, session, case_id, delivery_gates)
                if gate and gate.get("decision") == "BLOCKED":
                    status = "quality_blocked"
                    statuses[case_id] = status
                    gate_reason = str((gate.get("audit_event") or {}).get("reason") or "")
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
                            from cygnusx.infrastructure.celery_app.tasks.agentteams import (
                                respond_to_room_message,
                            )

                            respond_to_room_message.delay(
                                case_id,
                                session.user_id,
                                "系统交接：请生物信息部门经理汇总刚完成的领域 Agent 交接，并说明风险与下一步。",
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
                    status_reason=gate_reason,
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
            meta["agentteams_case_delivery_gate"] = delivery_gates
            session.sandbox_meta = meta
            session.updated_at = datetime.now(UTC)
        return {"scanned": scanned, "notified": notified, "failed": failed}

    async def _run_delivery_gate(
        self,
        agentteams: AgentTeamsService,
        session: ChatSessionModel,
        case_id: str,
        delivery_gates: dict[str, Any],
    ) -> dict[str, Any] | None:
        """delivery_ready 交付门：物化交付产物后跑 evaluate_report_delivery 轻量校验。

        判定按 case 缓存（同一 delivery_ready 只评一次，避免每个 tick 重复物化并
        重复投影 Bridge 审计事件）；门判定本身与审计事件都是结构化留痕，
        物化/投影失败返回 None 放行既有通知路径，不阻断 watch 主流程。
        """
        cached = delivery_gates.get(case_id)
        if isinstance(cached, dict) and cached.get("status") == "delivery_ready":
            gate = cached.get("gate")
            return gate if isinstance(gate, dict) else None
        try:
            materialized = await agentteams.materialize_case_delivery(
                case_id, session.user_id, self._db
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("AgentTeams delivery gate materialize failed for %s: %s", case_id, exc)
            return None
        deliverables = [
            {"path": path, "kind": Path(path).suffix.lstrip(".").lower()}
            for path in materialized.get("files") or []
        ]
        gate = AgentTeamsQualityGateService().evaluate_report_delivery(deliverables)
        try:
            await agentteams.post_case_evidence(
                case_id,
                work_item_id=CASE_LEVEL_WORK_ITEM_ID,
                event_type=str(gate["audit_event"]["event_type"]),
                summary=f"交付门判定 {gate['decision']}：{gate['audit_event']['reason']}",
                payload={**gate["audit_event"], "checks": gate["checks"][:100]},
            )
        except Exception as exc:  # noqa: BLE001 - 审计事件投影失败不影响门判定
            logger.warning(
                "AgentTeams delivery gate evidence projection failed for %s: %s", case_id, exc
            )
        delivery_gates[case_id] = {"status": "delivery_ready", "gate": gate}
        if gate["decision"] == "BLOCKED":
            logger.warning(
                "AgentTeams delivery gate BLOCKED for %s: %s",
                case_id,
                gate["audit_event"]["reason"],
            )
        return gate

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
        status_reason: str = "",
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
            if status_reason:
                content += f"原因：{status_reason[:200]}"
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
                    "status_reason": status_reason or None,
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
            "Bridge 可能暂时不可用，系统会继续自动重试；当前任务状态以 CygnusX 为准。"
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

"""Consume Bridge Case SSE events and project them into bound chat sessions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from cygnusx.application.services.agentteams_bridge_settings_service import (
    AgentTeamsBridgeSettingsService,
)
from cygnusx.application.services.agentteams_service import AgentTeamsService
from cygnusx.application.services.case_room_projector import CaseRoomProjector
from cygnusx.core.config import get_settings
from cygnusx.infrastructure.cache.chat_case_pubsub import publish_chat_case_event
from cygnusx.infrastructure.database.models.chat import (
    AgentTeamsCaseCursorModel,
    ChatSessionModel,
)

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset({"closed", "cancelled"})


class AgentTeamsCaseEventConsumerService:
    """Maintain one bounded Bridge SSE connection for one chat-bound Case."""

    def __init__(self, db: Any) -> None:
        self._db = db

    async def consume(
        self,
        session_id: str,
        case_id: str,
        *,
        watch_seconds: int,
        agentteams: AgentTeamsService | None = None,
    ) -> dict[str, int]:
        session = await self._db.scalar(
            select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
        )
        if session is None:
            return {"events": 0, "projected": 0, "skipped": 1}
        meta = dict(session.sandbox_meta or {})
        migration_mode = get_settings().agentteams_case_cursor_migration_mode
        case_ids = {item for item in meta.get("agentteams_case_ids", []) if isinstance(item, str)}
        statuses = dict(meta.get("agentteams_case_status") or {})
        if case_id not in case_ids or statuses.get(case_id) in TERMINAL_STATUSES:
            return {"events": 0, "projected": 0, "skipped": 1}

        client = agentteams or await self._build_agentteams()
        if not client.available:
            return {"events": 0, "projected": 0, "skipped": 1}
        legacy_cursors = dict(meta.get("agentteams_case_event_cursor", {}) or {})
        cursor_state = await self._get_or_create_cursor(
            session_id,
            case_id,
            legacy_cursor=(
                str(legacy_cursors.get(case_id) or "") or None
                if migration_mode != "new_only"
                else None
            ),
        )
        projector = CaseRoomProjector()
        event_count = projected_count = 0

        async for audit_event in client.stream_case_events(
            case_id,
            requester_ref=session.user_id,
            cursor=(
                str(legacy_cursors.get(case_id) or "") or None
                if migration_mode == "legacy_only"
                else cursor_state.event_cursor or str(legacy_cursors.get(case_id) or "") or None
            ),
            watch_seconds=watch_seconds,
        ):
            event_count += 1
            for projected in projector.project(
                audit_event,
                session_id=session_id,
                flow_id=str(meta.get("flow_id") or ""),
            ):
                await publish_chat_case_event(session_id, projected)
                projected_count += 1
            event_id = str(audit_event.get("event_id") or "")
            if event_id:
                if migration_mode != "legacy_only":
                    cursor_state.event_cursor = event_id
                if migration_mode != "new_only":
                    legacy_cursors[case_id] = event_id
            if self._apply_case_state(meta, case_id, audit_event):
                session.sandbox_meta = meta
                session.updated_at = datetime.now(UTC)
            if migration_mode == "new_only":
                meta.pop("agentteams_case_event_cursor", None)
            else:
                meta["agentteams_case_event_cursor"] = legacy_cursors
            meta["agentteams_case_cursor_migration"] = {
                "mode": migration_mode,
                "checked_at": datetime.now(UTC).isoformat(),
                "mismatch_count": 0,
            }
            session.sandbox_meta = meta
            await self._db.commit()

        return {"events": event_count, "projected": projected_count, "skipped": 0}

    async def _build_agentteams(self) -> AgentTeamsService:
        settings = get_settings()
        runtime = await AgentTeamsBridgeSettingsService(self._db, settings).get_runtime_config()
        return AgentTeamsService(settings, runtime)

    async def _get_or_create_cursor(
        self, session_id: str, case_id: str, *, legacy_cursor: str | None = None
    ) -> AgentTeamsCaseCursorModel:
        state = await self._db.scalar(
            select(AgentTeamsCaseCursorModel).where(
                AgentTeamsCaseCursorModel.session_id == session_id,
                AgentTeamsCaseCursorModel.case_id == case_id,
            )
        )
        if state is not None:
            return state
        state = AgentTeamsCaseCursorModel(
            session_id=session_id,
            case_id=case_id,
            event_cursor=legacy_cursor,
            notified_statuses=[],
        )
        self._db.add(state)
        return state

    @staticmethod
    def _apply_case_state(meta: dict[str, Any], case_id: str, event: dict[str, Any]) -> bool:
        if str(event.get("event_type") or "") != "case.state_changed":
            return False
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        status = str(payload.get("status") or "")
        if not status:
            return False
        statuses = dict(meta.get("agentteams_case_status") or {})
        if statuses.get(case_id) == status:
            return False
        statuses[case_id] = status
        meta["agentteams_case_status"] = statuses
        return True

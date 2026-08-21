"""按 case_id 拉取全量业务事件链（统一审计总线查询入口，Part 3.4）。

聚合两条 Bridge 事件流：Case 自身事件流 +（已立项绑定时）房间命名空间
事件流（``room-<room_id>``，含立项确认卡与立项前澄清）。事件按
``recorded_at`` 排序输出统一结构，关联字段（causation_event_id /
answer_to_event_id / correlation_id）经 ``agentteams_audit_events``
的同口径提取，供"5 分钟定位"取证与 CLI 工具消费。

两条入口：

- ``get_case_audit_chain``：用户态，经 Bridge requester 校验与房间 owner
  校验，供 API 端点使用；
- ``get_case_audit_chain_ops``：运维态（manager 身份直连，无 requester
  校验），供 scripts/fetch_case_audit_chain.py 等取证工具使用。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.services.agentteams_audit_events import (
    classify_event_type,
    event_stream_sort_key,
    extract_correlation,
    redact_confirm_token,
)
from omichub.application.services.agentteams_service import (
    AgentTeamsService,
    room_namespace_case_id,
)
from omichub.core.exceptions import BusinessError
from omichub.infrastructure.database.models.chat import AgentTeamsRoomModel

# 依据: 上游契约 — 与 API 默认一致（src/omichub/api/v1/agentteams.py:896 max_events Query 默认 5000、上限 20000）
_DEFAULT_MAX_EVENTS = 5_000
# 依据: 实测 E2E-2 — events 端点分页契约每页上限 100（limit>100 钳制，evidence/e2e-2026-08-21/E2E-2）
_PAGE_LIMIT = 100

# 事件页拉取器：(stream_case_id, cursor, limit) -> {"events": [...], "next_cursor": ...}
_EventPageFetcher = Callable[[str, str | None, int], Awaitable[dict[str, Any]]]


class AgentTeamsAuditChainService:
    def __init__(self, db: AsyncSession, *, agentteams: AgentTeamsService) -> None:
        self._db = db
        self._agentteams = agentteams

    async def get_case_audit_chain(
        self,
        case_id: str,
        requester_ref: str,
        *,
        max_events: int = _DEFAULT_MAX_EVENTS,
    ) -> dict[str, Any]:
        """用户态事件链：Case 与房间流都做归属校验（Bridge requester 口径）。"""

        async def fetch(stream_id: str, cursor: str | None, limit: int) -> dict[str, Any]:
            return await self._agentteams.get_case_events(
                stream_id, requester_ref, cursor=cursor, limit=limit
            )

        room = await self._find_bound_room(case_id, owner_id=requester_ref)
        return await self._build_chain(case_id, room=room, fetch=fetch, max_events=max_events)

    async def get_case_audit_chain_ops(
        self,
        case_id: str,
        *,
        max_events: int = _DEFAULT_MAX_EVENTS,
    ) -> dict[str, Any]:
        """运维态事件链：manager 身份直连 Bridge，不做 requester 归属校验。"""

        async def fetch(stream_id: str, cursor: str | None, limit: int) -> dict[str, Any]:
            params: dict[str, Any] = {"limit": limit}
            if cursor:
                params["cursor"] = cursor
            return await self._agentteams._request(  # noqa: SLF001 - 与 export_agentteams_evidence.py 同一运维口径
                f"/v1/cases/{stream_id}/events", params=params
            )

        room = await self._find_bound_room(case_id, owner_id=None)
        return await self._build_chain(case_id, room=room, fetch=fetch, max_events=max_events)

    async def _find_bound_room(
        self, case_id: str, *, owner_id: str | None
    ) -> AgentTeamsRoomModel | None:
        statement = select(AgentTeamsRoomModel).where(AgentTeamsRoomModel.case_id == case_id)
        if owner_id is not None:
            statement = statement.where(AgentTeamsRoomModel.owner_id == owner_id)
        result = await self._db.execute(statement)
        return result.scalars().first()

    async def _build_chain(
        self,
        case_id: str,
        *,
        room: AgentTeamsRoomModel | None,
        fetch: _EventPageFetcher,
        max_events: int,
    ) -> dict[str, Any]:
        max_events = max(1, max_events)
        collected: list[tuple[str, dict[str, Any]]] = []
        collected.extend(("case", event) for event in await self._fetch_all(case_id, fetch, max_events))
        remaining = max_events - len(collected)
        if room is not None and remaining > 0:
            stream_id = room_namespace_case_id(room.room_id)
            try:
                room_events = await self._fetch_all(stream_id, fetch, remaining)
            except BusinessError as exc:
                # 房间命名空间流不存在（尚未落任何房间级事件）时不阻断 Case 链输出。
                logger.bind(room_id=room.room_id).warning(
                    "AgentTeams audit chain room stream unavailable: {}", exc
                )
                room_events = []
            collected.extend(("room", event) for event in room_events)

        # 跨流去重（同一 event_id 只保留先读到的一条），排序口径与房间视图
        # 归并共用 event_stream_sort_key：(recorded_at, event_id)。
        seen: set[str] = set()
        merged: list[tuple[str, dict[str, Any]]] = []
        for source, event in collected:
            event_id = str(event.get("event_id") or "")
            if event_id and event_id in seen:
                continue
            if event_id:
                seen.add(event_id)
            merged.append((source, event))
        merged.sort(key=lambda item: event_stream_sort_key(item[1]))

        events = [self._project_event(source, event) for source, event in merged]
        broken_links = _find_broken_links(events)
        return {
            "case_id": case_id,
            "room_id": room.room_id if room is not None else None,
            "event_count": len(events),
            "broken_link_count": len(broken_links),
            "broken_links": broken_links,
            "generated_at": datetime.now(UTC).isoformat(),
            "events": events,
        }

    @staticmethod
    async def _fetch_all(
        stream_id: str, fetch: _EventPageFetcher, max_events: int
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        cursor: str | None = None
        while len(events) < max_events:
            page = await fetch(stream_id, cursor, min(_PAGE_LIMIT, max_events - len(events)))
            items = [item for item in page.get("events", []) if isinstance(item, dict)]
            events.extend(items)
            cursor = page.get("next_cursor") or None
            if not cursor or not items:
                break
        return events

    @staticmethod
    def _project_event(source: str, event: dict[str, Any]) -> dict[str, Any]:
        # B3：审计链是取证出口，confirm_token 一律脱敏（pending 卡也不例外——
        # 取证视图不需要也不应携带可消费令牌）。redact 返回拷贝，不改原事件。
        event = redact_confirm_token(event)
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        inner = payload.get("payload")
        return {
            "event_id": str(event.get("event_id") or ""),
            "recorded_at": str(event.get("recorded_at") or ""),
            "case_id": str(event.get("case_id") or ""),
            "actor": str(event.get("actor") or ""),
            "event_type": str(event.get("event_type") or ""),
            "source": source,
            "event_class": classify_event_type(str(event.get("event_type") or "")),
            "summary": str(payload.get("summary") or ""),
            "correlation": extract_correlation(payload),
            "payload": inner if isinstance(inner, dict) else payload,
        }


def _find_broken_links(events: list[dict[str, Any]]) -> list[dict[str, str]]:
    """关联字段指向不在本链内的事件（跨流引用缺失即取证断点）。"""
    known_ids = {event["event_id"] for event in events if event["event_id"]}
    broken: list[dict[str, str]] = []
    for event in events:
        for field in ("causation_event_id", "answer_to_event_id"):
            target = event["correlation"].get(field)
            if target and target not in known_ids:
                broken.append(
                    {"event_id": event["event_id"], "field": field, "target_event_id": target}
                )
    return broken


__all__ = ["AgentTeamsAuditChainService"]

"""统一审计总线（Part 3.4）测试：audit-chain 聚合查询、关联字段写入、事件分级口径。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from omichub.application.services.agent_consultation_service import (
    AgentConsultationService,
    ConsultationEnvelope,
)
from omichub.application.services.agentteams_audit_chain_service import (
    AgentTeamsAuditChainService,
)
from omichub.application.services.agentteams_audit_events import (
    OPERATIONAL_EVENT_TYPES,
    classify_event_type,
    extract_correlation,
)
from omichub.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)
from omichub.application.services.agentteams_room_response_service import (
    AgentTeamsRoomResponseService,
)
from omichub.application.services.agentteams_room_service import (
    AgentTeamsRoomService,
    build_room_proposal,
)
from omichub.application.services.agentteams_service import room_namespace_case_id
from omichub.infrastructure.database.models.chat import AgentTeamsRoomModel

_STATUS_LINES = {
    key: [key]
    for key in (
        "recruited",
        "queued",
        "running",
        "reviewing",
        "succeeded",
        "failed",
        "awaiting_input",
    )
}


def _agent_config(agent_id: str, *, planner_eligible: bool = False) -> dict:
    return {
        "agent_id": agent_id,
        "name": agent_id,
        "features": {
            "internal_case_role": agent_id,
            "agentteams": {
                "category": "expert",
                "recruitable": True,
                "planner_eligible": planner_eligible,
                "execution_modes": ["readonly_consultation"],
            },
            "persona": {"status_lines": _STATUS_LINES},
        },
    }


def _manager_agent_config() -> dict:
    return {
        "agent_id": "agentteams-manager",
        "name": "生物信息部门经理",
        "features": {
            "internal_case_role": "bioops-manager",
            "agentteams": {
                "category": "manager",
                "recruitable": False,
                "planner_eligible": True,
                "execution_modes": ["readonly_consultation"],
            },
            "persona": {"status_lines": _STATUS_LINES},
        },
    }


class FakeAbilityCatalog:
    def __init__(self, agent_ids: set[str]) -> None:
        self._agent_ids = agent_ids

    def all(self) -> dict[str, dict]:
        return {agent_id: {} for agent_id in self._agent_ids}


def _registry(*agent_ids: str, with_manager: bool = True) -> AgentTeamsCapabilityRegistry:
    configs = [_agent_config(agent_id) for agent_id in agent_ids]
    catalog_ids = set(agent_ids)
    if with_manager:
        configs.append(_manager_agent_config())
        catalog_ids.add("agentteams-manager")
    return AgentTeamsCapabilityRegistry(
        ability_catalog=FakeAbilityCatalog(catalog_ids),
        agent_configs=configs,
    )


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}

    async def set(self, *args, **kwargs):
        if args and not kwargs.get("nx"):
            self.store[str(args[0])] = args[1] if len(args) > 1 else "1"
        return True

    async def get(self, key):
        return self.store.get(str(key))

    async def eval(self, *args):
        return 1


def make_room(**overrides) -> AgentTeamsRoomModel:
    values = {
        "room_id": uuid4().hex,
        "owner_id": "user-a",
        "title": "协作室会话",
        "status": "active",
        "origin": "manual",
        "case_id": None,
        "matrix_room_id": "!room:test",
        "proposal": None,
    }
    values.update(overrides)
    return AgentTeamsRoomModel(**values)


class _FakeResult:
    def __init__(self, row) -> None:
        self._row = row
        self.rowcount = 1  # 立项确认的原子消费 UPDATE 判定依据

    def scalars(self):
        return self

    def first(self):
        return self._row


def make_db(room: AgentTeamsRoomModel | None = None) -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()  # Session.add 是同步方法
    db.execute = AsyncMock(return_value=_FakeResult(room))
    return db


def _event(
    event_id: str,
    event_type: str,
    recorded_at: str,
    *,
    case_id: str = "bioops_1",
    actor: str = "bioops-manager",
    inner: dict | None = None,
) -> dict:
    return {
        "event_id": event_id,
        "recorded_at": recorded_at,
        "case_id": case_id,
        "actor": actor,
        "event_type": event_type,
        "payload": {"summary": event_type, "payload": inner or {}},
    }


def _user_message_event(content: str, event_id: str = "evt-msg-1") -> dict:
    return {
        "event_id": event_id,
        "event_type": "room.user_message",
        "payload": {"summary": content[:80], "payload": {"actor": "user-a", "content": content}},
    }


def _clarify_card_event(origin_content: str, round_no: int, event_id: str) -> dict:
    return {
        "event_id": event_id,
        "event_type": "room.ask_user",
        "payload": {
            "summary": "请确认数据来源",
            "payload": {
                "content": "需要你先确认数据来源，再启动执行。",
                "role": "bioops-manager",
                "questions": [{"question": "请确认数据来源：", "options": ["上传文件"]}],
                "clarify_kind": "execution_object",
                "round": round_no,
                "origin_content": origin_content,
            },
        },
    }


def _response_service(agentteams: SimpleNamespace) -> AgentTeamsRoomResponseService:
    return AgentTeamsRoomResponseService(
        make_db(),
        agentteams=agentteams,
        registry=_registry("agent-general"),
        redis_getter=FakeRedis,
    )


def _room_agentteams(events: list[dict] | None = None) -> SimpleNamespace:
    case = {
        "case_id": "room-stub",
        "intent": "协作室房间会话",
        "status": "received",
        "requester_ref": "user-a",
        "work_items": [],
    }
    return SimpleNamespace(
        available=True,
        get_case=AsyncMock(return_value=case),
        get_case_events=AsyncMock(return_value={"events": events or [], "next_cursor": None}),
        post_case_evidence=AsyncMock(return_value={"event_id": "evt-new"}),
        create_case=AsyncMock(return_value={"case_id": "bioops_new1"}),
        bind_case_room=AsyncMock(return_value={"room_id": "!room:test"}),
        start_chat_planning=AsyncMock(return_value=None),
    )


# ---------------------------------------------------------------------------
# 事件分级口径
# ---------------------------------------------------------------------------


def test_operational_event_types_match_bridge_contract() -> None:
    """与 Bridge audit.py 的 OPERATIONAL_EVENT_TYPES 同一份清单（改动需同步）。"""
    assert frozenset(
        {"worker.inbox_polled", "worker.heartbeat", "room.typing"}
    ) == OPERATIONAL_EVENT_TYPES
    for event_type in OPERATIONAL_EVENT_TYPES:
        assert classify_event_type(event_type) == "operational"


def test_classify_event_type_defaults_to_business() -> None:
    """白名单兜底：未显式列入 operational 的一律 business（含高频保留类）。"""
    for event_type in (
        "room.user_message",
        "room.agent_message",
        "room.proposal_confirm",
        "case.created",
        "approval.resolved",
        "room.response_timing",
        "room.agent_stream",
        "something.unknown",
    ):
        assert classify_event_type(event_type) == "business"


def test_extract_correlation_reads_inner_payload_first() -> None:
    payload = {
        "summary": "s",
        "payload": {"causation_event_id": "evt-a", "answer_to_event_id": "evt-b"},
    }
    assert extract_correlation(payload) == {
        "causation_event_id": "evt-a",
        "answer_to_event_id": "evt-b",
    }
    # 老事件没有关联字段 → 空 dict，不影响查询。
    assert extract_correlation({"summary": "s", "payload": {}}) == {}
    # 兼容直写在外层的事件。
    assert extract_correlation({"correlation_id": "trace-1"}) == {"correlation_id": "trace-1"}


# ---------------------------------------------------------------------------
# audit-chain 聚合查询
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_audit_chain_merges_case_and_room_streams_in_order() -> None:
    room = make_room(case_id="bioops_1")
    db = make_db(room)
    room_stream_id = room_namespace_case_id(room.room_id)
    case_events = [
        _event("evt-c2", "case.created", "2026-08-20T10:02:00+00:00"),
        _event(
            "evt-c3",
            "room.agent_message",
            "2026-08-20T10:03:00+00:00",
            inner={"causation_event_id": "evt-r2"},
        ),
    ]
    room_events = [
        _event(
            "evt-r1",
            "room.user_message",
            "2026-08-20T10:00:00+00:00",
            case_id=room_stream_id,
            actor="omichub-user-x",
        ),
        _event(
            "evt-r2",
            "room.proposal_confirm",
            "2026-08-20T10:01:00+00:00",
            case_id=room_stream_id,
            inner={"causation_event_id": "evt-r1"},
        ),
    ]

    async def get_case_events(stream_id, requester_ref, *, cursor=None, limit=100):
        assert requester_ref == "user-a"
        return {
            "events": case_events if stream_id == "bioops_1" else room_events,
            "next_cursor": None,
        }

    agentteams = SimpleNamespace(get_case_events=AsyncMock(side_effect=get_case_events))
    chain = await AgentTeamsAuditChainService(db, agentteams=agentteams).get_case_audit_chain(
        "bioops_1", "user-a"
    )

    assert chain["case_id"] == "bioops_1"
    assert chain["room_id"] == room.room_id
    assert chain["event_count"] == 4
    assert [event["event_id"] for event in chain["events"]] == [
        "evt-r1",
        "evt-r2",
        "evt-c2",
        "evt-c3",
    ]
    sources = {event["event_id"]: event["source"] for event in chain["events"]}
    assert sources["evt-r1"] == sources["evt-r2"] == "room"
    assert sources["evt-c2"] == sources["evt-c3"] == "case"
    # 跨流关联字段完整提取：立项卡 → 用户发言，Manager 回复 → 立项卡。
    by_id = {event["event_id"]: event for event in chain["events"]}
    assert by_id["evt-r2"]["correlation"] == {"causation_event_id": "evt-r1"}
    assert by_id["evt-c3"]["correlation"] == {"causation_event_id": "evt-r2"}
    # 全链引用闭合，无断链。
    assert chain["broken_links"] == []
    assert chain["broken_link_count"] == 0
    # 统一结构字段齐全。
    for event in chain["events"]:
        assert set(event) >= {
            "event_id",
            "recorded_at",
            "case_id",
            "actor",
            "event_type",
            "source",
            "event_class",
            "summary",
            "correlation",
            "payload",
        }
        assert event["event_class"] == "business"


@pytest.mark.asyncio
async def test_audit_chain_paginates_until_stream_end() -> None:
    db = make_db(None)
    pages = {
        None: {
            "events": [_event(f"evt-{index}", "case.note", f"2026-08-20T10:{index:02d}:00+00:00") for index in range(3)],
            "next_cursor": "evt-2",
        },
        "evt-2": {
            "events": [_event("evt-3", "case.closed", "2026-08-20T10:03:00+00:00")],
            "next_cursor": None,
        },
    }

    async def get_case_events(stream_id, requester_ref, *, cursor=None, limit=100):
        return pages[cursor]

    agentteams = SimpleNamespace(get_case_events=AsyncMock(side_effect=get_case_events))
    chain = await AgentTeamsAuditChainService(db, agentteams=agentteams).get_case_audit_chain(
        "bioops_1", "user-a"
    )

    assert chain["room_id"] is None
    assert chain["event_count"] == 4
    assert [event["event_id"] for event in chain["events"]] == [
        "evt-0",
        "evt-1",
        "evt-2",
        "evt-3",
    ]


@pytest.mark.asyncio
async def test_audit_chain_flags_broken_links() -> None:
    db = make_db(None)
    events = [
        _event("evt-a", "room.user_message", "2026-08-20T10:00:00+00:00"),
        _event(
            "evt-b",
            "room.agent_message",
            "2026-08-20T10:01:00+00:00",
            inner={"causation_event_id": "evt-missing"},
        ),
    ]
    agentteams = SimpleNamespace(
        get_case_events=AsyncMock(return_value={"events": events, "next_cursor": None})
    )
    chain = await AgentTeamsAuditChainService(db, agentteams=agentteams).get_case_audit_chain(
        "bioops_1", "user-a"
    )

    assert chain["broken_link_count"] == 1
    assert chain["broken_links"] == [
        {"event_id": "evt-b", "field": "causation_event_id", "target_event_id": "evt-missing"}
    ]


@pytest.mark.asyncio
async def test_audit_chain_consultation_parse_failed_link_closed() -> None:
    """手册阶段 2 修复 3 验收：consultation.parse_failed 经 causation_event_id
    挂到触发的 room.user_message，audit-chain 不出现断链。"""
    db = make_db(None)
    events = [
        _event("evt-u1", "room.user_message", "2026-08-20T10:00:00+00:00"),
        _event(
            "evt-p1",
            "consultation.parse_failed",
            "2026-08-20T10:01:00+00:00",
            inner={
                "causation_event_id": "evt-u1",
                "reason": "invalid_consultation_envelope",
            },
        ),
    ]
    agentteams = SimpleNamespace(
        get_case_events=AsyncMock(return_value={"events": events, "next_cursor": None})
    )
    chain = await AgentTeamsAuditChainService(db, agentteams=agentteams).get_case_audit_chain(
        "bioops_1", "user-a"
    )

    by_id = {event["event_id"]: event for event in chain["events"]}
    assert by_id["evt-p1"]["correlation"] == {"causation_event_id": "evt-u1"}
    assert chain["broken_links"] == []
    assert chain["broken_link_count"] == 0


@pytest.mark.asyncio
async def test_audit_chain_marks_operational_events() -> None:
    """operational 事件若出现在历史流中，输出显式标记 event_class（不再静默混入）。"""
    db = make_db(None)
    events = [
        _event("evt-hb", "worker.heartbeat", "2026-08-20T10:00:00+00:00"),
        _event("evt-msg", "room.user_message", "2026-08-20T10:01:00+00:00"),
    ]
    agentteams = SimpleNamespace(
        get_case_events=AsyncMock(return_value={"events": events, "next_cursor": None})
    )
    chain = await AgentTeamsAuditChainService(db, agentteams=agentteams).get_case_audit_chain(
        "bioops_1", "user-a"
    )

    classes = {event["event_id"]: event["event_class"] for event in chain["events"]}
    assert classes == {"evt-hb": "operational", "evt-msg": "business"}


@pytest.mark.asyncio
async def test_audit_chain_ops_path_uses_manager_identity() -> None:
    """运维态入口：manager 身份直连 Bridge 事件端点，不做 requester 校验。"""
    room = make_room(case_id="bioops_1")
    db = make_db(room)

    async def _request(path, *, method="GET", **kwargs):
        assert method == "GET"
        events = (
            [_event("evt-c1", "case.created", "2026-08-20T10:00:00+00:00")]
            if path == "/v1/cases/bioops_1/events"
            else []
        )
        return {"events": events, "next_cursor": None}

    agentteams = SimpleNamespace(_request=AsyncMock(side_effect=_request))
    chain = await AgentTeamsAuditChainService(db, agentteams=agentteams).get_case_audit_chain_ops(
        "bioops_1"
    )

    assert chain["event_count"] == 1
    assert chain["room_id"] == room.room_id
    assert agentteams._request.await_count == 2  # Case 流 + 房间命名空间流
    paths = [call.args[0] for call in agentteams._request.await_args_list]
    assert f"/v1/cases/{room_namespace_case_id(room.room_id)}/events" in paths


# ---------------------------------------------------------------------------
# correlation 链字段写入
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clarify_answer_carries_answer_to_event_id(monkeypatch) -> None:
    """澄清答复事件必须带 answer_to_event_id 指回澄清卡事件。"""
    reply = "【澄清回复】\n1. 请确认数据来源：我去上传文件"
    events = [
        _user_message_event("帮我做差异分析", event_id="evt-msg-0"),
        _clarify_card_event("帮我做差异分析", 1, event_id="evt-clarify-1"),
        _user_message_event(reply),
    ]
    agentteams = _room_agentteams(events=events)
    monkeypatch.setattr(
        AgentConsultationService,
        "run_consultation",
        AsyncMock(return_value=ConsultationEnvelope(conclusion="好的。")),
    )

    result = await _response_service(agentteams).respond("bioops_1", "user-a", reply)

    assert result["status"] == "asked"
    answer_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.ask_user_answered"
    )
    assert answer_call.kwargs["payload"]["answer_to_event_id"] == "evt-clarify-1"
    # 第二轮澄清卡携带 causation_event_id 指回当前用户发言。
    clarify_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.ask_user"
    )
    assert clarify_call.kwargs["payload"]["causation_event_id"] == "evt-msg-1"


@pytest.mark.asyncio
async def test_direct_agent_reply_carries_causation_event_id(monkeypatch) -> None:
    """点名领域 Agent 的答复事件带 causation_event_id 指回用户发言。"""
    events = [_user_message_event("@agent-general 这个样本质控怎么看？")]
    agentteams = _room_agentteams(events=events)
    monkeypatch.setattr(
        AgentConsultationService,
        "run_consultation",
        AsyncMock(return_value=ConsultationEnvelope(conclusion="从质控指标看……")),
    )

    result = await _response_service(agentteams).respond(
        "bioops_1", "user-a", "@agent-general 这个样本质控怎么看？", target_agent_id="agent-general"
    )

    assert result == {"status": "direct_responded"}
    reply_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.agent_message"
    )
    assert reply_call.kwargs["payload"]["causation_event_id"] == "evt-msg-1"
    assert reply_call.kwargs["payload"]["direct_mention"] is True


@pytest.mark.asyncio
async def test_proposal_card_event_id_roundtrip_to_case_bound(monkeypatch) -> None:
    """立项卡事件 id 回写房间 proposal；确认后 room.case_bound 以 answer_to_event_id 指回。"""
    room = make_room()
    content = "运行分析 matrix.csv 并生成图表"
    agentteams = _room_agentteams(events=[_user_message_event(content)])
    # 立项卡落事件后 Bridge 回执 event_id。
    agentteams.post_case_evidence = AsyncMock(return_value={"event_id": "evt-card-1"})
    monkeypatch.setattr(
        AgentConsultationService,
        "run_consultation",
        AsyncMock(return_value=ConsultationEnvelope(conclusion="不应走到会诊")),
    )

    result = await _response_service(agentteams).respond_room(room, "user-a", content)

    assert result == {"status": "proposal_pending"}
    assert room.proposal is not None
    assert room.proposal["card_event_id"] == "evt-card-1"

    db = make_db()
    room_service = AgentTeamsRoomService(db, agentteams)
    confirm = await room_service.confirm_proposal(
        room, "user-a", confirm_token=room.proposal["token"], decision="confirm"
    )

    assert confirm["status"] == "confirmed"
    bound_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.case_bound"
    )
    assert bound_call.kwargs["payload"]["answer_to_event_id"] == "evt-card-1"


@pytest.mark.asyncio
async def test_proposal_cancel_carries_answer_to_event_id() -> None:
    """取消立项卡的事件同样以 answer_to_event_id 指回卡片（老卡片为 None）。"""
    proposal = build_room_proposal(
        proposal_kind="new_case",
        content="运行分析 matrix.csv 并生成图表",
        route_decision={},
        context_refs=[],
        source_case_id=None,
    )
    proposal["card_event_id"] = "evt-card-9"
    room = make_room(proposal=proposal)
    agentteams = _room_agentteams()
    service = AgentTeamsRoomService(make_db(), agentteams)

    result = await service.confirm_proposal(
        room, "user-a", confirm_token=proposal["token"], decision="cancel"
    )

    assert result == {"status": "cancelled"}
    cancel_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.proposal_cancelled"
    )
    assert cancel_call.kwargs["payload"]["answer_to_event_id"] == "evt-card-9"


# ---------------------------------------------------------------------------
# B3：审计链（取证出口）confirm_token 无条件脱敏（手册阶段 0 修复 3）
# ---------------------------------------------------------------------------


def test_audit_chain_project_event_redacts_confirm_token_unconditionally() -> None:
    """取证出口不设 pending 例外：即使 token 仍存活也一律置 None。"""
    card = _event(
        "evt-card-1",
        "room.proposal_confirm",
        "2026-08-20T10:01:00+00:00",
        inner={"proposal_id": "p-1", "confirm_token": "live-secret-token"},
    )

    projected = AgentTeamsAuditChainService._project_event("room_stream", card)

    assert projected["payload"]["confirm_token"] is None
    # 脱敏返回拷贝，不改原事件。
    assert card["payload"]["payload"]["confirm_token"] == "live-secret-token"


def test_audit_chain_project_event_keeps_non_card_payload_untouched() -> None:
    message = _event(
        "evt-msg-1",
        "room.agent_message",
        "2026-08-20T10:02:00+00:00",
        inner={"content": "你好"},
    )

    projected = AgentTeamsAuditChainService._project_event("room_stream", message)

    assert projected["payload"] == {"content": "你好"}


# ---------------------------------------------------------------------------
# A2：房间视图与 audit-chain 同一排序口径（复审清单 A2 验收）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_room_view_and_audit_chain_share_order_for_same_events() -> None:
    """同一批事件（含跨流同刻 tie）：房间视图与 audit-chain 输出顺序一致。"""
    room = make_room(case_id="bioops_1")
    db = make_db(room)
    room_stream_id = room_namespace_case_id(room.room_id)
    same_ts = "2026-08-20T10:00:00+00:00"
    streams = {
        room_stream_id: [
            _event("evt-n-b", "room.user_message", same_ts, case_id=room_stream_id),
            _event("evt-n-d", "room.proposal_confirm", same_ts, case_id=room_stream_id),
            _event("evt-n-f", "room.case_bound", "2026-08-20T10:02:00+00:00", case_id=room_stream_id),
        ],
        "bioops_1": [
            _event("evt-c-a", "case.created", same_ts),
            _event("evt-c-c", "case.plan_frozen", same_ts),
            _event("evt-c-e", "case.state_changed", "2026-08-20T10:01:00+00:00"),
        ],
    }

    async def get_case_events(stream_id, requester_ref, *, cursor=None, limit=100):
        events = streams.get(stream_id, [])
        start = 0
        if cursor:
            ids = [str(event.get("event_id")) for event in events]
            start = ids.index(cursor) + 1 if cursor in ids else 0
        page = events[start : start + limit]
        next_cursor = (
            str(page[-1]["event_id"]) if page and start + limit < len(events) else None
        )
        return {"events": page, "next_cursor": next_cursor}

    agentteams = SimpleNamespace(get_case_events=AsyncMock(side_effect=get_case_events))

    chain = await AgentTeamsAuditChainService(db, agentteams=agentteams).get_case_audit_chain(
        "bioops_1", "user-a"
    )
    page = await AgentTeamsRoomService(make_db(), agentteams).get_room_events(
        room, "user-a", limit=100
    )

    chain_ids = [event["event_id"] for event in chain["events"]]
    room_ids = [event["event_id"] for event in page["events"]]
    # (recorded_at, event_id) 单一口径：同刻按 event_id 字符串序。
    assert chain_ids == room_ids == [
        "evt-c-a",
        "evt-c-c",
        "evt-n-b",
        "evt-n-d",
        "evt-c-e",
        "evt-n-f",
    ]

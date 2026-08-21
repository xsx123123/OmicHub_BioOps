"""协作室房间（会话-工单解耦 Part 2）主后端测试。

覆盖：房间 CRUD / 未立项房间纯咨询全程无 Case / execute → 立项确认卡 →
确认后建 Case 绑定 / 确认幂等与失败回滚 / 房间级事件聚合重放 /
Case 终态后继续对话与"继续/新建"分支。
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from omichub.application.services import agentteams_room_service as room_service_module
from omichub.application.services import agentteams_service as agentteams_service_module
from omichub.application.services.agent_consultation_service import (
    AgentConsultationService,
    ConsultationEnvelope,
)
from omichub.application.services.agentteams_audit_events import event_stream_sort_key
from omichub.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)
from omichub.application.services.agentteams_room_response_service import (
    AgentTeamsRoomResponseService,
)
from omichub.application.services.agentteams_room_service import (
    AgentTeamsRoomService,
    build_room_proposal,
    proposal_project_name,
)
from omichub.application.services.agentteams_service import (
    AgentTeamsService,
    room_namespace_case_id,
)
from omichub.core.config import Settings
from omichub.core.exceptions import AuthorizationError, BusinessError
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


def _registry() -> AgentTeamsCapabilityRegistry:
    return AgentTeamsCapabilityRegistry(
        ability_catalog=FakeAbilityCatalog({"agentteams-manager"}),
        agent_configs=[_manager_agent_config()],
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


def make_db() -> AsyncMock:
    db = AsyncMock()
    db.add = MagicMock()  # Session.add 是同步方法
    db.execute = AsyncMock(return_value=SimpleNamespace(rowcount=1))
    return db


def _user_message_event(content: str, event_id: str = "evt-msg-1") -> dict:
    return {
        "event_id": event_id,
        "event_type": "room.user_message",
        "payload": {"summary": content, "payload": {"actor": "user-a", "content": content}},
    }


def make_agentteams(
    *,
    case_status: str = "received",
    events: list[dict] | None = None,
) -> SimpleNamespace:
    case = {
        "case_id": "room-stub",
        "intent": "协作室房间会话",
        "status": case_status,
        "requester_ref": "user-a",
        "work_items": [],
    }
    return SimpleNamespace(
        available=True,
        get_case=AsyncMock(return_value=case),
        get_case_events=AsyncMock(return_value={"events": events or [], "next_cursor": None}),
        post_case_evidence=AsyncMock(return_value={"event_id": "evt-new"}),
        create_case=AsyncMock(return_value={"case_id": "bioops_new1"}),
        create_room_namespace=AsyncMock(return_value={"case_id": "room-stub"}),
        provision_case_room=AsyncMock(
            return_value={"room_id": "!room:test", "element_room_url": "http://element.test/!room:test"}
        ),
        bind_case_room=AsyncMock(return_value={"room_id": "!room:test"}),
        start_chat_planning=AsyncMock(return_value=None),
        post_room_message=AsyncMock(return_value={"event_id": "evt-msg"}),
    )


def make_response_service(agentteams: SimpleNamespace) -> AgentTeamsRoomResponseService:
    return AgentTeamsRoomResponseService(
        make_db(),
        agentteams=agentteams,
        registry=_registry(),
        redis_getter=FakeRedis,
    )


# ---------------------------------------------------------------------------
# 房间 CRUD
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_room_persists_row_and_namespace() -> None:
    db = make_db()
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(db, agentteams)

    room = await service.create_room(owner_id="user-a", title="scRNA 讨论")

    assert room.room_id
    assert room.title == "scRNA 讨论"
    assert room.case_id is None
    assert room.matrix_room_id == "!room:test"
    db.add.assert_called_once()
    agentteams.create_room_namespace.assert_awaited_once()
    assert agentteams.create_room_namespace.await_args.kwargs["room_id"] == room.room_id
    # Matrix 建房挂在房间命名空间记录下（room.created 证据落房间级事件流）。
    agentteams.provision_case_room.assert_awaited_once_with(
        room_namespace_case_id(room.room_id), requester_ref="user-a"
    )


@pytest.mark.asyncio
async def test_create_room_requires_bridge() -> None:
    agentteams = make_agentteams()
    agentteams.available = False
    service = AgentTeamsRoomService(make_db(), agentteams)

    with pytest.raises(BusinessError):
        await service.create_room(owner_id="user-a")


@pytest.mark.asyncio
async def test_get_room_enforces_ownership() -> None:
    room = make_room(owner_id="user-a")
    db = make_db()
    db.scalar = AsyncMock(return_value=room)
    service = AgentTeamsRoomService(db, make_agentteams())

    assert (await service.get_room(room.room_id, "user-a")) is room
    with pytest.raises(AuthorizationError):
        await service.get_room(room.room_id, "user-b")


# ---------------------------------------------------------------------------
# 未立项房间：纯咨询 / 澄清 / 立项确认卡，全程无 Case
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unbound_room_chat_never_creates_case(monkeypatch: pytest.MonkeyPatch) -> None:
    room = make_room()
    agentteams = make_agentteams(events=[_user_message_event("scRNA-seq 的整合方法有哪些")])
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="常用方法有 Harmony、scVI 等。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await make_response_service(agentteams).respond_room(
        room, "user-a", "scRNA-seq 的整合方法有哪些"
    )

    assert result == {"status": "responded"}
    agentteams.create_case.assert_not_called()
    agentteams.create_case.assert_not_awaited()
    agentteams.start_chat_planning.assert_not_called()
    # Manager 回复落在房间命名空间流（room-<room_id>），而非任何 Case。
    reply_calls = [
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.agent_message"
    ]
    assert len(reply_calls) == 1
    assert reply_calls[0].args[0] == room_namespace_case_id(room.room_id)


@pytest.mark.asyncio
async def test_unbound_room_clarify_stays_in_room_dimension(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room = make_room()
    agentteams = make_agentteams(events=[_user_message_event("帮我分析这些样本")])
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="不应走到会诊"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await make_response_service(agentteams).respond_room(room, "user-a", "帮我分析这些样本")

    assert result == {"status": "asked"}
    agentteams.create_case.assert_not_called()
    run.assert_not_called()
    clarify_calls = [
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.ask_user"
    ]
    assert len(clarify_calls) == 1
    assert clarify_calls[0].args[0] == room_namespace_case_id(room.room_id)


@pytest.mark.asyncio
async def test_unbound_room_execute_emits_proposal_card_without_case(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room = make_room()
    content = "运行分析 matrix.csv 并生成图表"
    agentteams = make_agentteams(events=[_user_message_event(content)])
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="不应走到会诊"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await make_response_service(agentteams).respond_room(room, "user-a", content)

    assert result == {"status": "proposal_pending"}
    agentteams.create_case.assert_not_called()
    agentteams.start_chat_planning.assert_not_called()
    run.assert_not_called()
    proposal_calls = [
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.proposal_confirm"
    ]
    assert len(proposal_calls) == 1
    call = proposal_calls[0]
    assert call.args[0] == room_namespace_case_id(room.room_id)
    payload = call.kwargs["payload"]
    assert payload["proposal_kind"] == "new_case"
    assert payload["objective"] == content
    assert payload["options"] == ["confirm", "modify", "cancel"]
    assert payload["confirm_token"]
    # 立项卡已持久化到房间行（pending，待 confirm-proposal 消费）。
    assert room.proposal is not None
    assert room.proposal["status"] == "pending"
    assert room.proposal["token"] == payload["confirm_token"]


# ---------------------------------------------------------------------------
# 立项确认：建 Case 绑定 / 幂等 / 失败回滚
# ---------------------------------------------------------------------------


def _pending_room(**overrides) -> AgentTeamsRoomModel:
    proposal = build_room_proposal(
        proposal_kind="new_case",
        content="运行分析 matrix.csv 并生成图表",
        route_decision={},
        context_refs=[{"kind": "file", "id": "file-1", "location": "inbox/matrix.csv"}],
        source_case_id=None,
    )
    return make_room(proposal=proposal, **overrides)


@pytest.mark.asyncio
async def test_confirm_proposal_creates_case_and_binds_room() -> None:
    room = _pending_room()
    db = make_db()
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(db, agentteams)

    result = await service.confirm_proposal(
        room, "user-a", confirm_token=room.proposal["token"], decision="confirm"
    )

    assert result["status"] == "confirmed"
    assert result["case_id"] == "bioops_new1"
    assert room.case_id == "bioops_new1"
    agentteams.create_case.assert_awaited_once()
    assert agentteams.create_case.await_args.kwargs["flow_id"] is None
    agentteams.bind_case_room.assert_awaited_once_with(
        "bioops_new1",
        room_id=room.room_id,
        matrix_room_id="!room:test",
        requester_ref="user-a",
    )
    bound_events = [
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.case_bound"
    ]
    assert len(bound_events) == 1
    assert bound_events[0].args[0] == room_namespace_case_id(room.room_id)
    assert room.proposal["status"] == "consumed"


@pytest.mark.asyncio
async def test_confirm_proposal_idempotent_when_already_bound() -> None:
    room = _pending_room(case_id="bioops_existing")
    db = make_db()
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(db, agentteams)

    result = await service.confirm_proposal(
        room, "user-a", confirm_token=room.proposal["token"], decision="confirm"
    )

    assert result == {
        "status": "already_bound",
        "case_id": "bioops_existing",
        "idempotent_replay": True,
    }
    agentteams.create_case.assert_not_called()
    db.execute.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_proposal_rejects_consumed_token() -> None:
    room = _pending_room()
    db = make_db()
    # 原子消费未命中：token 已被并发请求消费。
    db.execute = AsyncMock(return_value=SimpleNamespace(rowcount=0))
    service = AgentTeamsRoomService(db, make_agentteams())

    with pytest.raises(BusinessError, match="令牌无效或已使用"):
        await service.confirm_proposal(
            room, "user-a", confirm_token=room.proposal["token"], decision="confirm"
        )


@pytest.mark.asyncio
async def test_confirm_proposal_rejects_wrong_token() -> None:
    room = _pending_room()
    service = AgentTeamsRoomService(make_db(), make_agentteams())

    with pytest.raises(BusinessError, match="令牌无效或已使用"):
        await service.confirm_proposal(
            room, "user-a", confirm_token="x" * 24, decision="confirm"
        )


@pytest.mark.asyncio
async def test_confirm_proposal_failure_rolls_back_to_pending() -> None:
    room = _pending_room()
    db = make_db()
    agentteams = make_agentteams()
    agentteams.create_case = AsyncMock(side_effect=BusinessError("Agent 协作中心暂时不可用"))
    service = AgentTeamsRoomService(db, agentteams)

    with pytest.raises(BusinessError):
        await service.confirm_proposal(
            room, "user-a", confirm_token=room.proposal["token"], decision="confirm"
        )

    # 建单失败可重试：提案回滚 pending，房间保持未绑定。
    assert room.proposal["status"] == "pending"
    assert room.case_id is None
    agentteams.bind_case_room.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_proposal_cancel_closes_card() -> None:
    room = _pending_room()
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(make_db(), agentteams)

    result = await service.confirm_proposal(
        room, "user-a", confirm_token=room.proposal["token"], decision="cancel"
    )

    assert result == {"status": "cancelled"}
    assert room.proposal["status"] == "cancelled"
    assert room.case_id is None
    agentteams.create_case.assert_not_called()
    cancel_events = [
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.proposal_cancelled"
    ]
    assert len(cancel_events) == 1


# ---------------------------------------------------------------------------
# 房间级事件聚合（确认前刷新重放 / 绑定后聚合）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_room_events_unbound_replays_namespace_history() -> None:
    room = make_room()
    agentteams = make_agentteams()
    agentteams.get_case_events = AsyncMock(
        return_value={
            "events": [
                {"event_id": "e1", "recorded_at": "2026-08-20T01:00:00+00:00"},
                {"event_id": "e2", "recorded_at": "2026-08-20T01:01:00+00:00"},
            ],
            "next_cursor": None,
        }
    )
    service = AgentTeamsRoomService(make_db(), agentteams)

    page = await service.get_room_events(room, "user-a")

    assert [event["event_id"] for event in page["events"]] == ["e1", "e2"]
    assert page["case_id"] is None
    # E2E-9：本页保留数 < limit → 流已耗尽，游标必须收敛为 None。
    assert page["next_cursor"] is None
    # 未绑定房间只有命名空间一条流。
    assert agentteams.get_case_events.await_count == 1
    assert agentteams.get_case_events.await_args.args[0] == room_namespace_case_id(room.room_id)


@pytest.mark.asyncio
async def test_room_events_bound_merges_case_stream_by_recorded_at() -> None:
    room = make_room(case_id="bioops_case1")
    agentteams = make_agentteams()
    pages = {
        room_namespace_case_id(room.room_id): {
            "events": [
                {"event_id": "ns-1", "recorded_at": "2026-08-20T01:00:00+00:00"},
                {"event_id": "ns-2", "recorded_at": "2026-08-20T01:03:00+00:00"},
            ],
            "next_cursor": None,
        },
        "bioops_case1": {
            "events": [
                {"event_id": "case-1", "recorded_at": "2026-08-20T01:02:00+00:00"},
            ],
            "next_cursor": None,
        },
    }
    agentteams.get_case_events = AsyncMock(side_effect=lambda case_id, *a, **kw: pages[case_id])
    service = AgentTeamsRoomService(make_db(), agentteams)

    page = await service.get_room_events(room, "user-a")

    assert [event["event_id"] for event in page["events"]] == ["ns-1", "case-1", "ns-2"]
    assert page["case_id"] == "bioops_case1"
    # 归并后保留数（3）< limit（100）→ 两流均耗尽，游标清空。
    assert page["next_cursor"] is None


# ---------------------------------------------------------------------------
# Case 终态后：继续对话 + "继续/新建"选择卡
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminal_case_new_execute_emits_followup_choice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    room = make_room(case_id="bioops_done1")
    content = "运行分析 result.csv 并生成图表"
    agentteams = make_agentteams(case_status="closed", events=[_user_message_event(content)])
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="不应走到会诊"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await make_response_service(agentteams).respond_room(room, "user-a", content)

    assert result == {"status": "proposal_pending"}
    run.assert_not_called()
    agentteams.create_case.assert_not_called()
    proposal_calls = [
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.proposal_confirm"
    ]
    assert len(proposal_calls) == 1
    payload = proposal_calls[0].kwargs["payload"]
    assert payload["proposal_kind"] == "followup"
    assert payload["options"] == ["continue", "new", "cancel"]
    assert payload["source_case_id"] == "bioops_done1"


@pytest.mark.asyncio
async def test_terminal_case_chat_still_replies(monkeypatch: pytest.MonkeyPatch) -> None:
    room = make_room(case_id="bioops_done1")
    agentteams = make_agentteams(
        case_status="closed", events=[_user_message_event("这个结果说明了什么")]
    )
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="说明分组间差异显著。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await make_response_service(agentteams).respond_room(room, "user-a", "这个结果说明了什么")

    assert result == {"status": "responded"}
    proposal_calls = [
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.proposal_confirm"
    ]
    assert proposal_calls == []


@pytest.mark.asyncio
async def test_followup_confirm_continue_carries_source_case_id() -> None:
    proposal = build_room_proposal(
        proposal_kind="followup",
        content="运行分析 result.csv 并生成图表",
        route_decision={},
        context_refs=[],
        source_case_id="bioops_done1",
    )
    room = make_room(proposal=proposal)
    db = make_db()
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(db, agentteams)

    result = await service.confirm_proposal(
        room,
        "user-a",
        confirm_token=proposal["token"],
        decision="confirm",
        followup_mode="continue",
    )

    assert result["status"] == "confirmed"
    assert result["source_case_id"] == "bioops_done1"
    assert agentteams.create_case.await_args.kwargs["source_case_id"] == "bioops_done1"


@pytest.mark.asyncio
async def test_followup_confirm_new_drops_source_case_id() -> None:
    proposal = build_room_proposal(
        proposal_kind="followup",
        content="运行分析 result.csv 并生成图表",
        route_decision={},
        context_refs=[],
        source_case_id="bioops_done1",
    )
    room = make_room(proposal=proposal)
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(make_db(), agentteams)

    result = await service.confirm_proposal(
        room,
        "user-a",
        confirm_token=proposal["token"],
        decision="confirm",
        followup_mode="new",
    )

    assert result["source_case_id"] is None
    assert agentteams.create_case.await_args.kwargs["source_case_id"] is None


# ---------------------------------------------------------------------------
# 房间消息路由（未立项 → 命名空间流；已绑定 → Case 流）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_post_room_message_routes_by_binding() -> None:
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(make_db(), agentteams)

    unbound = make_room()
    await service.post_room_message(unbound, "user-a", "你好")
    assert agentteams.post_room_message.await_args.args[0] == room_namespace_case_id(
        unbound.room_id
    )

    bound = make_room(case_id="bioops_case9")
    await service.post_room_message(bound, "user-a", "进度如何")
    assert agentteams.post_room_message.await_args.args[0] == "bioops_case9"


# ---------------------------------------------------------------------------
# B1：confirm_token 写入后即全出口脱敏 / owner 免 token 确认（复审清单 B1）
# ---------------------------------------------------------------------------


def _proposal_card_event(token: str, event_id: str = "evt-card-1") -> dict:
    return {
        "event_id": event_id,
        "recorded_at": "2026-08-20T01:00:00+00:00",
        "event_type": "room.proposal_confirm",
        "payload": {
            "summary": "立项确认卡",
            "payload": {"proposal_id": "p-1", "confirm_token": token},
        },
    }


@pytest.mark.asyncio
async def test_room_events_redact_confirm_token_for_pending_card() -> None:
    """pending 卡同样脱敏：token 只存房间行 DB 字段，不再经事件流分发。"""
    room = _pending_room()
    token = room.proposal["token"]
    agentteams = make_agentteams(events=[_proposal_card_event(token)])
    service = AgentTeamsRoomService(make_db(), agentteams)

    page = await service.get_room_events(room, "user-a")

    card = next(event for event in page["events"] if event["event_id"] == "evt-card-1")
    assert card["payload"]["payload"]["confirm_token"] is None
    # 脱敏是出口拷贝，不动 DB 侧存活 token。
    assert room.proposal["token"] == token


@pytest.mark.asyncio
async def test_room_events_redact_confirm_token_once_not_pending() -> None:
    room = _pending_room()
    token = room.proposal["token"]
    room.proposal = {**room.proposal, "status": "confirmed"}
    agentteams = make_agentteams(events=[_proposal_card_event(token)])
    service = AgentTeamsRoomService(make_db(), agentteams)

    page = await service.get_room_events(room, "user-a")

    card = next(event for event in page["events"] if event["event_id"] == "evt-card-1")
    assert card["payload"]["payload"]["confirm_token"] is None


@pytest.mark.asyncio
async def test_room_events_sse_path_redacts_confirm_token() -> None:
    """SSE 出口与分页同路径脱敏：pending 卡 token 不出现在聚合事件流中。"""
    room = _pending_room()
    token = room.proposal["token"]
    agentteams = make_agentteams(events=[_proposal_card_event(token)])
    service = AgentTeamsRoomService(make_db(), agentteams)

    streamed = []
    async for event in service.stream_room_events(room, "user-a", watch_seconds=1):
        streamed.append(event)
        break  # 拉到第一批即足够验证出口脱敏

    card = next(event for event in streamed if event["event_id"] == "evt-card-1")
    assert card["payload"]["payload"]["confirm_token"] is None


@pytest.mark.asyncio
async def test_confirm_proposal_without_token_succeeds_for_owner() -> None:
    """B1：owner 不带 token 即可确认（owner 校验 + pending 状态原子消费）。"""
    room = _pending_room()
    db = make_db()
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(db, agentteams)

    result = await service.confirm_proposal(room, "user-a", decision="confirm")

    assert result["status"] == "confirmed"
    assert room.case_id == "bioops_new1"
    agentteams.create_case.assert_awaited_once()
    # 无 token 消费时原子 UPDATE 不带 token 谓词（仅 status=pending 抢占）。
    stmt = db.execute.await_args.args[0]
    assert str(stmt.compile()).count("proposal ->>") == 1


@pytest.mark.asyncio
async def test_confirm_proposal_without_token_rejected_when_not_pending() -> None:
    room = _pending_room()
    room.proposal = {**room.proposal, "status": "consumed"}
    service = AgentTeamsRoomService(make_db(), make_agentteams())

    with pytest.raises(BusinessError, match="令牌无效或已使用"):
        await service.confirm_proposal(room, "user-a", decision="confirm")


@pytest.mark.asyncio
async def test_confirm_proposal_without_token_idempotent_replay() -> None:
    """重复确认幂等：已绑定房间直接返回既有绑定，不重复建 Case。"""
    room = _pending_room(case_id="bioops_existing")
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(make_db(), agentteams)

    result = await service.confirm_proposal(room, "user-a", decision="confirm")

    assert result["status"] == "already_bound"
    assert result["idempotent_replay"] is True
    agentteams.create_case.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_proposal_double_confirm_creates_single_case() -> None:
    """重复确认（先成功后重试）全程只创建一个 Case（任务书 Part 0.2 补验）。"""
    room = _pending_room()
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(make_db(), agentteams)

    first = await service.confirm_proposal(room, "user-a", decision="confirm")
    second = await service.confirm_proposal(room, "user-a", decision="confirm")

    assert first["status"] == "confirmed"
    assert second["status"] == "already_bound"
    assert second["case_id"] == first["case_id"]
    agentteams.create_case.assert_awaited_once()


@pytest.mark.asyncio
async def test_confirm_proposal_concurrent_loser_returns_idempotent_result() -> None:
    """并发双确认：原子更新落败方刷新后发现已被绑定，幂等返回首次结果。"""
    room = _pending_room()
    db = make_db()
    db.execute = AsyncMock(return_value=SimpleNamespace(rowcount=0))

    async def _winner_committed(instance: AgentTeamsRoomModel) -> None:
        instance.case_id = "bioops_winner"

    db.refresh = AsyncMock(side_effect=_winner_committed)
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(db, agentteams)

    result = await service.confirm_proposal(room, "user-a", decision="confirm")

    assert result["status"] == "already_bound"
    assert result["case_id"] == "bioops_winner"
    assert result["idempotent_replay"] is True
    agentteams.create_case.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_proposal_rejects_non_owner() -> None:
    room = _pending_room()  # owner_id == "user-a"
    service = AgentTeamsRoomService(make_db(), make_agentteams())

    with pytest.raises(AuthorizationError, match="只有房间所有者"):
        await service.confirm_proposal(
            room, "user-b", confirm_token=room.proposal["token"], decision="confirm"
        )


@pytest.mark.asyncio
async def test_confirm_proposal_wrong_token_emits_reject_audit_event() -> None:
    room = _pending_room()
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(make_db(), agentteams)

    with pytest.raises(BusinessError, match="令牌无效或已使用"):
        await service.confirm_proposal(
            room, "user-a", confirm_token="x" * 24, decision="confirm"
        )

    rejected = [
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.proposal_confirm_rejected"
    ]
    assert len(rejected) == 1
    assert rejected[0].kwargs["payload"]["actor"] == "user-a"


# ---------------------------------------------------------------------------
# A1：立项 Case 接入与旧直建路径一致的交付物化链路（复审清单 A1）
# ---------------------------------------------------------------------------

_OWNER_UUID = "12345678-1234-5678-1234-567812345678"
_PROJECT_ID = "99999999-9999-4999-8999-999999999999"


class _RecordingProjectService:
    """get_or_create_project_by_name 探针：记录调用并返回固定项目。"""

    calls: list[tuple[str, str]] = []

    def __init__(self, db) -> None:
        pass

    async def get_or_create_project_by_name(self, user_id, name):
        type(self).calls.append((str(user_id), name))
        return {"id": _PROJECT_ID, "name": name, "slug": "recording-project"}


class _FailingProjectService:
    """不应被触达：走到按名建项目即失败。"""

    def __init__(self, db) -> None:
        pass

    async def get_or_create_project_by_name(self, user_id, name):
        raise AssertionError("不应走到按名建项目")


def _owner_pending_room(**overrides) -> AgentTeamsRoomModel:
    proposal = build_room_proposal(
        proposal_kind="new_case",
        content="运行分析 matrix.csv 并生成图表",
        route_decision={},
        context_refs=[{"kind": "file", "id": "file-1", "location": "inbox/matrix.csv"}],
        source_case_id=None,
    )
    return make_room(owner_id=_OWNER_UUID, proposal=proposal, **overrides)


def test_proposal_project_name_matches_legacy_naming() -> None:
    """与旧直建路径前端 buildCaseProjectName 同口径：需求前 30 字符、剥非法字符。"""
    assert proposal_project_name("运行分析 matrix.csv 并生成图表", "房间") == (
        "运行分析 matrix.csv 并生成图表"
    )
    assert proposal_project_name('a/b\\c:d*e?f"g<h>i|j', "房间") == "abcdefghij"
    assert proposal_project_name("  ", "scRNA 讨论") == "scRNA 讨论"
    assert proposal_project_name("", "") == "agentteams-case"
    assert len(proposal_project_name("很" * 60, "房间")) == 30


@pytest.mark.asyncio
async def test_confirmed_case_resolves_project_via_get_or_create(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """立项确认 → 按 objective 摘要 get-or-create 项目，project_id 传入 create_case。"""
    _RecordingProjectService.calls = []
    monkeypatch.setattr(room_service_module, "ProjectService", _RecordingProjectService)
    room = _owner_pending_room()
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(make_db(), agentteams)

    result = await service.confirm_proposal(room, _OWNER_UUID, decision="confirm")

    assert result["status"] == "confirmed"
    kwargs = agentteams.create_case.await_args.kwargs
    assert kwargs["project_id"] == _PROJECT_ID
    # 项目名与旧路径 buildCaseProjectName 口径一致（需求文本摘要）。
    assert kwargs["project_name"] == "运行分析 matrix.csv 并生成图表"
    assert _RecordingProjectService.calls == [
        (_OWNER_UUID, "运行分析 matrix.csv 并生成图表")
    ]


@pytest.mark.asyncio
async def test_confirmed_case_reuses_project_ref_in_context_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """立项卡上下文已带 kind=project 引用时直接复用，不再按名建项目。"""
    monkeypatch.setattr(room_service_module, "ProjectService", _FailingProjectService)
    proposal = build_room_proposal(
        proposal_kind="new_case",
        content="继续分析",
        route_decision={},
        context_refs=[
            {"kind": "project", "id": _PROJECT_ID, "meta": {"project_name": "既有项目"}}
        ],
        source_case_id=None,
    )
    room = make_room(owner_id=_OWNER_UUID, proposal=proposal)
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(make_db(), agentteams)

    await service.confirm_proposal(room, _OWNER_UUID, decision="confirm")

    kwargs = agentteams.create_case.await_args.kwargs
    assert kwargs["project_id"] == _PROJECT_ID
    assert kwargs["project_name"] == "既有项目"


@pytest.mark.asyncio
async def test_followup_continue_inherits_source_case_project(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """followup 关联上一 Case：继承源 Case 的项目归属（新 run 目录仍独立创建）。"""
    monkeypatch.setattr(room_service_module, "ProjectService", _FailingProjectService)
    proposal = build_room_proposal(
        proposal_kind="followup",
        content="基于上次结果再画一张图",
        route_decision={},
        context_refs=[],
        source_case_id="bioops_done1",
    )
    room = make_room(owner_id=_OWNER_UUID, proposal=proposal)
    agentteams = make_agentteams()
    agentteams.get_case = AsyncMock(
        return_value={
            "case_id": "bioops_done1",
            "context_refs": [
                {
                    "kind": "project",
                    "id": _PROJECT_ID,
                    "location": "projects/mouse/runs/agentteams-case-20260820-010000",
                    "meta": {
                        "project_name": "小鼠项目",
                        "run_path": "projects/mouse/runs/agentteams-case-20260820-010000",
                    },
                }
            ],
        }
    )
    service = AgentTeamsRoomService(make_db(), agentteams)

    result = await service.confirm_proposal(
        room, _OWNER_UUID, decision="confirm", followup_mode="continue"
    )

    assert result["source_case_id"] == "bioops_done1"
    kwargs = agentteams.create_case.await_args.kwargs
    assert kwargs["project_id"] == _PROJECT_ID
    assert kwargs["project_name"] == "小鼠项目"


@pytest.mark.asyncio
async def test_confirmed_room_case_satisfies_materialization_precondition(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """mock 层级断言物化前置条件：房间立项 Case 经真实 AgentTeamsService.create_case
    后，context_refs 携带 kind=project 且 run_path 含 /runs/ 的 run_ref——正是
    _materialize_case_delivery 提前 return 的判定条件（agentteams_service.py）。"""
    monkeypatch.setattr(room_service_module, "ProjectService", _RecordingProjectService)
    _RecordingProjectService.calls = []

    async def fake_get_project(self, user_id, project_id):
        return {"name": "运行分析 matrix.csv 并生成图表", "id": str(project_id)}

    class _FakeFactory:
        def __init__(self, root) -> None:
            self._root = root

        def user_root(self, user_id):
            return self._root

        def create_project_run_dir(self, user_id, project_name, analysis_name):
            run_dir = (
                self._root / "projects" / "recording-project" / "runs"
                / f"{analysis_name}-20260821-000000"
            )
            run_dir.mkdir(parents=True, exist_ok=True)
            return run_dir

    monkeypatch.setattr(agentteams_service_module.ProjectService, "get_project", fake_get_project)
    monkeypatch.setattr(
        agentteams_service_module, "get_path_factory", lambda: _FakeFactory(tmp_path)
    )
    monkeypatch.setattr(
        agentteams_service_module, "ensure_directory_chain", AsyncMock(return_value=None)
    )

    captured: dict[str, Any] = {}

    async def fake_request(path, **kwargs):
        captured.update(kwargs)
        return {"case_id": "bioops_new1", "requester_ref": _OWNER_UUID}

    real_agentteams = AgentTeamsService(
        Settings(
            agentteams_bridge_enabled=True,
            agentteams_bridge_url="http://bridge.test",
            agentteams_bridge_manager_token="manager-token",
        )
    )
    monkeypatch.setattr(real_agentteams, "_request", fake_request)
    monkeypatch.setattr(real_agentteams, "bind_case_room", AsyncMock(return_value={}))
    monkeypatch.setattr(real_agentteams, "post_case_evidence", AsyncMock(return_value={}))

    room = _owner_pending_room()
    service = AgentTeamsRoomService(make_db(), real_agentteams)

    result = await service.confirm_proposal(room, _OWNER_UUID, decision="confirm")

    assert result["status"] == "confirmed"
    payload = captured["json"]
    assert payload["project_ref"] == {"kind": "project", "id": _PROJECT_ID}
    run_refs = [
        ref
        for ref in payload["context_refs"]
        if ref.get("kind") == "project" and "/runs/" in str(ref.get("meta", {}).get("run_path", ""))
    ]
    assert len(run_refs) == 1
    assert run_refs[0]["meta"]["run_path"].startswith("projects/")


# ---------------------------------------------------------------------------
# A2：复合游标双流归并——截断到 limit + 游标按保留集重算 + 统一 tie-break
# ---------------------------------------------------------------------------


def _stream_event(event_id: str, recorded_at: str) -> dict:
    return {"event_id": event_id, "recorded_at": recorded_at}


def _paged_agentteams(streams: dict[str, list[dict]]) -> SimpleNamespace:
    """按 Bridge 语义（cursor=该 id 之后、每页最多 limit 条）服务的假事件流。"""

    async def get_case_events(case_id, requester_ref, *, cursor=None, limit=100):
        events = streams.get(case_id, [])
        start = 0
        if cursor:
            ids = [str(event.get("event_id")) for event in events]
            assert cursor in ids, f"游标 {cursor} 不在流 {case_id} 中（丢事件）"
            start = ids.index(cursor) + 1
        page = events[start : start + limit]
        next_cursor = (
            str(page[-1]["event_id"]) if page and start + limit < len(events) else None
        )
        return {"events": page, "next_cursor": next_cursor}

    agentteams = make_agentteams()
    agentteams.get_case_events = AsyncMock(side_effect=get_case_events)
    return agentteams


async def _drain_room_events(service, room, *, limit) -> list[str]:
    """翻页遍历房间事件流，返回全程 event_id 序列。"""
    seen: list[str] = []
    cursor = None
    while True:
        page = await service.get_room_events(room, "user-a", cursor=cursor, limit=limit)
        events = page["events"]
        assert len(events) <= limit, "单页事件数不能超过 limit（A2 截断）"
        if not events:
            break
        seen.extend(str(event["event_id"]) for event in events)
        next_cursor = page.get("next_cursor") or ""
        if next_cursor == (cursor or ""):
            break
        cursor = next_cursor
    return seen


@pytest.mark.asyncio
async def test_room_events_truncates_merged_page_and_recomputes_cursor() -> None:
    """两流各取 limit 条归并后截断到 limit；游标按截断后保留的各流最后一条重算。"""
    room = make_room(case_id="bioops_case1")
    ns_id = room_namespace_case_id(room.room_id)
    agentteams = _paged_agentteams(
        {
            ns_id: [
                _stream_event("ns-1", "2026-08-20T10:00:00+00:00"),
                _stream_event("ns-3", "2026-08-20T10:02:00+00:00"),
            ],
            "bioops_case1": [
                _stream_event("case-2", "2026-08-20T10:01:00+00:00"),
                _stream_event("case-4", "2026-08-20T10:03:00+00:00"),
            ],
        }
    )
    service = AgentTeamsRoomService(make_db(), agentteams)

    page = await service.get_room_events(room, "user-a", limit=2)

    assert [event["event_id"] for event in page["events"]] == ["ns-1", "case-2"]
    # 游标不是"各流取页的最后一条"（ns-3/case-4 被截掉，不能进游标）。
    assert page["next_cursor"] == "ns:ns-1|case:case-2"

    page2 = await service.get_room_events(
        room, "user-a", cursor=page["next_cursor"], limit=2
    )
    assert [event["event_id"] for event in page2["events"]] == ["ns-3", "case-4"]
    assert page2["next_cursor"] == "ns:ns-3|case:case-4"

    page3 = await service.get_room_events(
        room, "user-a", cursor=page2["next_cursor"], limit=2
    )
    assert page3["events"] == []
    # E2E-9：空页必须清空游标，调用方据此判停（此前 next_cursor 永不清空）。
    assert page3["next_cursor"] is None


@pytest.mark.asyncio
async def test_room_events_cross_stream_same_timestamp_pagination_no_loss_no_dup() -> None:
    """一页内两流均有同刻事件：翻页遍历全程不重不漏，tie-break 按 event_id。"""
    room = make_room(case_id="bioops_case1")
    ns_id = room_namespace_case_id(room.room_id)
    same_ts = "2026-08-20T10:00:00+00:00"
    agentteams = _paged_agentteams(
        {
            ns_id: [_stream_event("n-b", same_ts), _stream_event("n-d", same_ts)],
            "bioops_case1": [_stream_event("c-a", same_ts), _stream_event("c-c", same_ts)],
        }
    )
    service = AgentTeamsRoomService(make_db(), agentteams)

    seen = await _drain_room_events(service, room, limit=2)

    # (recorded_at, event_id) 口径：同刻按 event_id 字符串序，与 audit-chain 一致。
    assert seen == ["c-a", "c-c", "n-b", "n-d"]
    assert len(seen) == len(set(seen))


@pytest.mark.asyncio
async def test_room_events_order_matches_shared_sort_key() -> None:
    """房间归并的排序键与共享口径 event_stream_sort_key 完全一致。"""
    room = make_room(case_id="bioops_case1")
    ns_id = room_namespace_case_id(room.room_id)
    events = [
        _stream_event("evt-z", "2026-08-20T10:00:00+00:00"),
        _stream_event("evt-a", "2026-08-20T10:00:00+00:00"),
        _stream_event("evt-m", "2026-08-19T23:59:59+00:00"),
    ]
    agentteams = _paged_agentteams({ns_id: events[:2], "bioops_case1": events[2:]})
    service = AgentTeamsRoomService(make_db(), agentteams)

    page = await service.get_room_events(room, "user-a", limit=100)

    assert [event["event_id"] for event in page["events"]] == [
        event["event_id"] for event in sorted(events, key=event_stream_sort_key)
    ] == ["evt-m", "evt-a", "evt-z"]


# ---------------------------------------------------------------------------
# BUG-E2E-01：Matrix 建房回写二次 flush 后 updated_at 被 expire，必须 refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_room_refreshes_after_matrix_writeback() -> None:
    """Matrix 建房成功路径：二次 flush（UPDATE）使 onupdate=func.now() 的
    updated_at 进入 expired/unloaded 态，端点 _room_payload 在 async 上下文
    同步读列会触发懒加载 IO（MissingGreenlet → 500）。修复后必须显式 refresh。"""
    db = make_db()
    agentteams = make_agentteams()
    service = AgentTeamsRoomService(db, agentteams)

    room = await service.create_room(owner_id="user-a", title="x")

    assert room.matrix_room_id == "!room:test"
    # 插入 + matrix_room_id 回写共两次 flush；回写后必须 refresh 重新加载所有列。
    assert db.flush.await_count == 2
    db.refresh.assert_awaited_once_with(room)


@pytest.mark.asyncio
async def test_create_room_without_matrix_writeback_does_not_refresh() -> None:
    """Matrix 不可用（纯 INSERT）时 updated_at 经 RETURNING 已加载，无需 refresh。"""
    db = make_db()
    agentteams = make_agentteams()
    agentteams.provision_case_room = AsyncMock(return_value=None)
    service = AgentTeamsRoomService(db, agentteams)

    room = await service.create_room(owner_id="user-a")

    assert room.matrix_room_id is None
    assert db.flush.await_count == 1
    db.refresh.assert_not_awaited()


# ---------------------------------------------------------------------------
# E2E-9：游标分页终止性——末页后 next_cursor 收敛为 None，全程不重不漏
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_room_events_pagination_terminates_at_end_of_stream() -> None:
    """20 条事件按 limit=7 翻页（7+7+6）：末页 next_cursor 必须为 None，
    且不允许出现「空页 + 非空游标」的死循环页。"""
    room = make_room()
    ns_id = room_namespace_case_id(room.room_id)
    events = [
        _stream_event(f"e{index:02d}", f"2026-08-20T10:{index:02d}:00+00:00")
        for index in range(20)
    ]
    agentteams = _paged_agentteams({ns_id: events})
    service = AgentTeamsRoomService(make_db(), agentteams)

    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        page = await service.get_room_events(room, "user-a", cursor=cursor, limit=7)
        pages += 1
        assert len(page["events"]) <= 7
        seen.extend(str(event["event_id"]) for event in page["events"])
        if page["next_cursor"] is None:
            break
        assert page["events"], "空页不得携带非空 next_cursor（E2E-9 死循环回归）"
        cursor = page["next_cursor"]
        assert pages < 10, "翻页未在末页终止"

    assert pages == 3  # 7 + 7 + 6
    assert seen == [f"e{index:02d}" for index in range(20)]  # 不重不漏
    assert len(seen) == len(set(seen))


@pytest.mark.asyncio
async def test_room_events_full_boundary_page_terminates_on_next_empty_page() -> None:
    """末页恰好满页（kept == limit）时允许再拉一页空页，但空页游标必须为 None。"""
    room = make_room()
    ns_id = room_namespace_case_id(room.room_id)
    events = [
        _stream_event(f"e{index}", f"2026-08-20T10:0{index}:00+00:00") for index in range(4)
    ]
    agentteams = _paged_agentteams({ns_id: events})
    service = AgentTeamsRoomService(make_db(), agentteams)

    page1 = await service.get_room_events(room, "user-a", limit=4)
    assert len(page1["events"]) == 4
    # 满页无法判断是否还有后续，游标继续推进。
    assert page1["next_cursor"] == "ns:e3|case:"

    page2 = await service.get_room_events(room, "user-a", cursor=page1["next_cursor"], limit=4)
    assert page2["events"] == []
    assert page2["next_cursor"] is None


# ---------------------------------------------------------------------------
# E2E-2：events 端点 limit 超上界钳制到 100（不对用户报 422）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_room_events_endpoint_clamps_limit_above_100(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """limit=101/200 不再被 Query(le=100) 422 抹平：端点钳制到 100 交给 Service，
    调用方凭 next_cursor 续拉（Bridge 自身的硬上限校验保留，不在本层）。"""
    from omichub.api.v1 import agentteams as agentteams_api

    captured: dict[str, Any] = {}

    class FakeRooms:
        def __init__(self, db: Any, service: Any) -> None: ...

        async def get_room(self, room_id: str, user_id: str) -> Any:
            return make_room(room_id=room_id, owner_id=user_id)

        async def get_room_events(
            self, room: Any, user_id: str, *, cursor: str | None, limit: int
        ) -> dict:
            captured["limit"] = limit
            return {"room_id": room.room_id, "events": [], "next_cursor": None}

    monkeypatch.setattr(agentteams_api, "AgentTeamsRoomService", FakeRooms)

    for requested in (1, 100, 101, 200):
        result = await agentteams_api.get_room_events(
            "room-1",
            current_user_id="user-a",
            service=SimpleNamespace(),
            db=AsyncMock(),
            cursor=None,
            limit=requested,
        )
        assert result["events"] == []
        assert captured["limit"] == min(requested, 100)

"""房间 Manager 响应回路测试：锁去重、终态跳过、LLM 失败容错、manager agent 选法。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from omichub.application.services.agent_consultation_service import (
    AgentConsultationService,
    ConsultationEnvelope,
)
from omichub.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)
from omichub.application.services.agentteams_room_response_service import (
    ROOM_RESPONSE_LOCK_KEY_PREFIX,
    AgentTeamsRoomResponseService,
)

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


class FakeAbilityCatalog:
    def __init__(self, agent_ids: set[str]) -> None:
        self._agent_ids = agent_ids

    def all(self) -> dict[str, dict]:
        return {agent_id: {} for agent_id in self._agent_ids}


def _registry(*agent_ids: str, planner_ids: set[str] | None = None) -> AgentTeamsCapabilityRegistry:
    planners = planner_ids or set()
    return AgentTeamsCapabilityRegistry(
        ability_catalog=FakeAbilityCatalog(set(agent_ids)),
        agent_configs=[
            _agent_config(agent_id, planner_eligible=agent_id in planners)
            for agent_id in agent_ids
        ],
    )


class FakeRedis:
    def __init__(self, acquired: bool = True) -> None:
        self.acquired = acquired
        self.set_calls: list[tuple[object, ...]] = []
        self.release_calls: list[tuple[object, ...]] = []

    async def set(self, *args, **kwargs):
        self.set_calls.append((*args, kwargs))
        return self.acquired

    async def eval(self, *args):
        self.release_calls.append(args)
        return 1


def _service(
    *,
    agentteams: SimpleNamespace,
    registry: AgentTeamsCapabilityRegistry,
    redis: FakeRedis,
) -> AgentTeamsRoomResponseService:
    return AgentTeamsRoomResponseService(
        SimpleNamespace(),
        agentteams=agentteams,
        registry=registry,
        redis_getter=lambda: redis,
    )


def _agentteams(
    *,
    status: str = "executing",
    events: list[dict] | None = None,
    case_overrides: dict | None = None,
) -> SimpleNamespace:
    case = {"case_id": "bioops_1", "intent": "RNA-seq 差异分析", "status": status}
    case.update(case_overrides or {})
    return SimpleNamespace(
        get_case=AsyncMock(return_value=case),
        get_case_events=AsyncMock(return_value={"events": events or [], "next_cursor": None}),
        post_case_evidence=AsyncMock(return_value={"event_id": "evt-reply"}),
        start_chat_planning=AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_respond_records_manager_reply_evidence(monkeypatch) -> None:
    events = [
        {
            "event_type": "room.user_message",
            "payload": {"summary": "旧问题", "payload": {"actor": "user-a", "content": "旧问题"}},
        },
        {
            "event_type": "room.user_message",
            "payload": {
                "summary": "质控过了吗？",
                "payload": {"actor": "user-a", "content": "质控过了吗？"},
            },
        },
    ]
    agentteams = _agentteams(events=events)
    redis = FakeRedis()
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="质控已通过，可以交付。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-general"),
        redis=redis,
    ).respond("bioops_1", "user-a", "质控过了吗？")

    assert result == {"status": "responded"}
    assert run.await_args.kwargs["agent_id"] == "agent-general"
    assert run.await_args.kwargs["capability"] == "interpretation"
    assert "质控过了吗？" in run.await_args.kwargs["question"]
    assert "RNA-seq 差异分析" in run.await_args.kwargs["question"]
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert event_types == ["room.typing", "room.agent_message", "room.typing"]
    typing_payloads = [
        call.kwargs["payload"]
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.typing"
    ]
    assert typing_payloads == [{"typing": True}, {"typing": False}]
    reply_call = agentteams.post_case_evidence.await_args_list[1]
    assert reply_call.kwargs["work_item_id"] == "case"
    assert reply_call.kwargs["payload"]["content"] == "质控已通过，可以交付。"
    assert reply_call.kwargs["payload"]["agent_id"] == "agent-general"
    assert reply_call.kwargs["payload"]["role"] == "bioops-manager"
    assert len(redis.release_calls) == 1


@pytest.mark.asyncio
async def test_respond_skipped_when_lock_held() -> None:
    agentteams = _agentteams()
    redis = FakeRedis(acquired=False)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=redis
    ).respond("bioops_1", "user-a", "hello")

    assert result == {"status": "skipped_locked"}
    agentteams.get_case.assert_not_awaited()
    agentteams.post_case_evidence.assert_not_awaited()
    assert redis.release_calls == []


def test_build_question_keeps_task_message_when_newer_room_message_exists() -> None:
    events = [
        {
            "event_type": "room.user_message",
            "payload": {
                "summary": "帮我做系统发育树",
                "payload": {
                    "content": "帮我做系统发育树",
                    "context_refs": [
                        {
                            "kind": "file",
                            "id": "tree-1",
                            "location": "workspace/chat-uploads/example.treefile",
                        }
                    ],
                },
            },
        },
        {
            "event_type": "room.user_message",
            "payload": {"summary": "这是更新的问题", "payload": {"content": "这是更新的问题"}},
        },
    ]

    question = AgentTeamsRoomResponseService._build_question(
        {"intent": "介绍 Manager", "status": "planning_running"},
        events,
        "帮我做系统发育树",
    )

    assert "请求人最新发言：帮我做系统发育树" in question
    assert "workspace/chat-uploads/example.treefile" in question
    assert "必须以‘请求人最新发言’为唯一当前问题" in question


def test_build_question_applies_global_manager_preferences_without_skipping_gates() -> None:
    question = AgentTeamsRoomResponseService._build_question(
        {"intent": "数据质控", "status": "planning_running"},
        [],
        "继续处理",
        {
            "managerName": "小 O",
            "communicationStyle": "concise",
            "autonomy": "autonomous",
            "language": "en-US",
        },
    )

    assert "称呼自己为「小 O」" in question
    assert "沟通语言为English" in question
    assert "极简高效" in question
    assert "自主模式" in question
    assert "真实计算、写入、费用、提交和审批仍必须遵守系统安全闸门" in question


@pytest.mark.asyncio
async def test_respond_also_answers_for_terminal_case(monkeypatch) -> None:
    """终态 Case（已取消/已关闭）发言仍应得到 Manager 只读回复。"""
    agentteams = _agentteams(status="closed")
    run = AsyncMock(
        return_value=SimpleNamespace(conclusion="这个 Case 已关闭，但可以继续解答问题")
    )
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", "还在吗")

    assert result == {"status": "responded"}
    run.assert_awaited_once()


@pytest.mark.asyncio
async def test_respond_llm_failure_only_logs_and_releases_lock(monkeypatch) -> None:
    agentteams = _agentteams()
    redis = FakeRedis()
    monkeypatch.setattr(
        AgentConsultationService,
        "run_consultation",
        AsyncMock(side_effect=RuntimeError("LLM 不可用")),
    )

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=redis
    ).respond("bioops_1", "user-a", "hello")

    assert result == {"status": "failed"}
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert event_types == ["room.typing", "room.typing"]
    typing_payloads = [
        call.kwargs["payload"] for call in agentteams.post_case_evidence.await_args_list
    ]
    assert typing_payloads == [{"typing": True}, {"typing": False}]
    assert len(redis.release_calls) == 1


@pytest.mark.asyncio
async def test_respond_skipped_without_manager_agent(monkeypatch) -> None:
    agentteams = _agentteams()
    run = AsyncMock()
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-rnaseq"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", "hello")

    assert result == {"status": "skipped_no_manager"}
    run.assert_not_awaited()


@pytest.mark.asyncio
async def test_manager_agent_falls_back_to_planner_eligible(monkeypatch) -> None:
    agentteams = _agentteams()
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="好的。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-rnaseq", "agent-code", planner_ids={"agent-code"}),
        redis=FakeRedis(),
    ).respond("bioops_1", "user-a", "hello")

    assert result == {"status": "responded"}
    assert run.await_args.kwargs["agent_id"] == "agent-code"


def test_lock_key_namespaced_per_case() -> None:
    assert ROOM_RESPONSE_LOCK_KEY_PREFIX == "agentteams:room-response:lock:"


_EXECUTION_EVENTS = [
    {
        "event_type": "room.user_message",
        "payload": {
            "summary": "对这个 treefile 进行可视化并解释",
            "payload": {
                "actor": "user-a",
                "content": "对这个 treefile 进行可视化并解释",
                "context_refs": [
                    {
                        "kind": "file",
                        "id": "tree-1",
                        "location": "workspace/chat-uploads/example.treefile",
                    }
                ],
            },
        },
    }
]


@pytest.mark.asyncio
async def test_execution_intent_starts_chat_planning_and_still_responds(monkeypatch) -> None:
    """执行意图 + received + 无 flow + 无 plan-01 → 触发规划，Manager 回复照常。"""
    agentteams = _agentteams(status="received", events=_EXECUTION_EVENTS)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="已为你启动可视化流水线。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", "对这个 treefile 进行可视化并解释")

    assert result == {"status": "responded"}
    agentteams.start_chat_planning.assert_awaited_once()
    trigger = agentteams.start_chat_planning.await_args.kwargs
    assert trigger["case_id"] == "bioops_1"
    assert trigger["requester_ref"] == "user-a"
    assert "对这个 treefile 进行可视化并解释" in trigger["objective"]
    assert "work_items" in trigger["objective"]
    assert trigger["context_refs"] == [
        {"kind": "file", "id": "tree-1", "location": "workspace/chat-uploads/example.treefile"}
    ]
    question = run.await_args.kwargs["question"]
    # 触发后 prompt 中的 Case 状态应反映已推进的 planning_running
    assert "Case 当前状态：planning_running" in question
    # autonomous 模式下无需人工确认，旧版教育话术已移除
    assert "计划冻结后会在房间内请求你确认" not in question
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert event_types == ["room.typing", "room.agent_message", "room.typing"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("content", "status", "case_overrides"),
    [
        # 非执行意图
        ("你好", "received", {}),
        # 有 flow_id 的 Case 走人工审批链路，绝不自动触发
        ("对这个 treefile 进行可视化并解释", "received", {"flow_id": "rna_seq"}),
        # 状态非 received
        ("对这个 treefile 进行可视化并解释", "planning_running", {}),
        # 已有 plan-01 工作项
        (
            "对这个 treefile 进行可视化并解释",
            "received",
            {"work_items": [{"work_item_id": "plan-01"}]},
        ),
    ],
)
async def test_execution_intent_not_triggered_when_gates_fail(
    monkeypatch, content: str, status: str, case_overrides: dict
) -> None:
    agentteams = _agentteams(status=status, events=_EXECUTION_EVENTS, case_overrides=case_overrides)
    monkeypatch.setattr(
        AgentConsultationService,
        "run_consultation",
        AsyncMock(return_value=ConsultationEnvelope(conclusion="好的。")),
    )

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", content)

    assert result == {"status": "responded"}
    agentteams.start_chat_planning.assert_not_awaited()


@pytest.mark.asyncio
async def test_execution_trigger_failure_does_not_break_manager_reply(monkeypatch) -> None:
    agentteams = _agentteams(status="received", events=_EXECUTION_EVENTS)
    agentteams.start_chat_planning = AsyncMock(side_effect=RuntimeError("bridge down"))
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="稍后为你处理。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", "对这个 treefile 进行可视化并解释")

    assert result == {"status": "responded"}
    assert "计划冻结后会在房间内请求你确认" not in run.await_args.kwargs["question"]


def test_celery_task_delegates_to_async_impl(monkeypatch) -> None:
    import omichub.infrastructure.celery_app.tasks.agentteams as task_module

    calls: list[tuple[str, str, str]] = []

    async def fake_impl(case_id: str, requester_ref: str, content: str) -> dict[str, str]:
        calls.append((case_id, requester_ref, content))
        return {"status": "responded"}

    monkeypatch.setattr(task_module, "_respond_to_room_message", fake_impl)

    result = task_module.respond_to_room_message("bioops_1", "user-a", "hello")

    assert result == {"status": "responded"}
    assert calls == [("bioops_1", "user-a", "hello")]

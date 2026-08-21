"""房间 Manager 响应回路测试：锁去重、终态跳过、LLM 失败容错、manager agent 选法。"""

from __future__ import annotations

import asyncio
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
from omichub.application.services.agentteams_service import room_namespace_case_id
from omichub.core.config import get_settings
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
    """协作室 Manager 独立人格（recruitable=false 的内部 planner 角色）。"""
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


def _registry(
    *agent_ids: str,
    planner_ids: set[str] | None = None,
    with_manager: bool = False,
) -> AgentTeamsCapabilityRegistry:
    planners = planner_ids or set()
    configs = [
        _agent_config(agent_id, planner_eligible=agent_id in planners)
        for agent_id in agent_ids
    ]
    catalog_ids = set(agent_ids)
    if with_manager:
        configs.append(_manager_agent_config())
        catalog_ids.add("agentteams-manager")
    return AgentTeamsCapabilityRegistry(
        ability_catalog=FakeAbilityCatalog(catalog_ids),
        agent_configs=configs,
    )


class FakeRedis:
    def __init__(self, acquired: bool = True) -> None:
        self.acquired = acquired
        self.set_calls: list[tuple[object, ...]] = []
        self.release_calls: list[tuple[object, ...]] = []
        self.store: dict[str, object] = {}

    async def set(self, *args, **kwargs):
        self.set_calls.append((*args, kwargs))
        # 幂等标记（无 nx 的 set）落进内存字典，供 get 读取；锁的 nx 占位不入字典。
        if args and not kwargs.get("nx"):
            self.store[str(args[0])] = args[1] if len(args) > 1 else "1"
        return self.acquired

    async def get(self, key):
        return self.store.get(str(key))

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
        registry=_registry("agent-general", with_manager=True),
        redis=redis,
    ).respond("bioops_1", "user-a", "质控过了吗？")

    assert result == {"status": "responded"}
    assert run.await_args.kwargs["agent_id"] == "agentteams-manager"
    assert run.await_args.kwargs["capability"] == "interpretation"
    assert "质控过了吗？" in run.await_args.kwargs["question"]
    assert "RNA-seq 差异分析" in run.await_args.kwargs["question"]
    # 称呼注入来自 manager agent YAML 的 display_name（bioops-manager 角色标签）。
    assert "称呼自己为「生物信息部门经理」" in run.await_args.kwargs["question"]
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
    assert reply_call.kwargs["payload"]["agent_id"] == "agentteams-manager"
    assert reply_call.kwargs["payload"]["role"] == "bioops-manager"
    assert len(redis.release_calls) == 1


@pytest.mark.asyncio
async def test_respond_passes_trigger_event_id_to_consultation(monkeypatch) -> None:
    """手册阶段 2 修复 3：触发发言的 event_id 透传进 run_consultation（causation_event_id）。"""
    events = [
        {
            "event_id": "evt-msg-9",
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
        registry=_registry("agent-general", with_manager=True),
        redis=redis,
    ).respond("bioops_1", "user-a", "质控过了吗？")

    assert result == {"status": "responded"}
    assert run.await_args.kwargs["causation_event_id"] == "evt-msg-9"


@pytest.mark.asyncio
async def test_respond_is_idempotent_per_user_message(monkeypatch) -> None:
    """同一条 room.user_message（按 event_id 定位）只应得到一次 Manager 回复：
    任务重试 / broker 重投递 / 双通道重复调度时第二次直接跳过。"""
    events = [
        {
            "event_id": "evt-msg-1",
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
    service = _service(agentteams=agentteams, registry=_registry("agent-general"), redis=redis)

    first = await service.respond("bioops_1", "user-a", "质控过了吗？")
    second = await service.respond("bioops_1", "user-a", "质控过了吗？")

    assert first == {"status": "responded"}
    assert second == {"status": "skipped_duplicate"}
    assert run.await_count == 1
    replies = [
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.agent_message"
    ]
    assert len(replies) == 1


@pytest.mark.asyncio
async def test_respond_failure_does_not_arm_dedup(monkeypatch) -> None:
    """响应失败时不落幂等标记，后续重试仍可正常回复。"""
    events = [
        {
            "event_id": "evt-msg-1",
            "event_type": "room.user_message",
            "payload": {
                "summary": "质控过了吗？",
                "payload": {"actor": "user-a", "content": "质控过了吗？"},
            },
        },
    ]
    agentteams = _agentteams(events=events)
    redis = FakeRedis()
    run = AsyncMock(side_effect=RuntimeError("LLM 不可用"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)
    service = _service(agentteams=agentteams, registry=_registry("agent-general"), redis=redis)

    first = await service.respond("bioops_1", "user-a", "质控过了吗？")
    assert first == {"status": "failed"}

    run.side_effect = None
    run.return_value = ConsultationEnvelope(conclusion="质控已通过，可以交付。")
    second = await service.respond("bioops_1", "user-a", "质控过了吗？")

    assert second == {"status": "responded"}
    assert run.await_count == 2


@pytest.mark.asyncio
async def test_flow_manager_reply_exposes_persisted_handoff_failure(monkeypatch) -> None:
    agentteams = _agentteams(
        events=[
            _user_message_event("请开始单细胞分析"),
            {
                "event_type": "case.handoff_failed",
                "payload": {"reason": "agent-scrna-upstream 凭证未配置"},
            },
        ],
        case_overrides={"flow_id": "scrna"},
    )
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="我会先整理分析步骤。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-general"),
        redis=FakeRedis(),
    ).respond("bioops_1", "user-a", "请开始单细胞分析")

    assert result == {"status": "responded"}
    reply_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.agent_message"
    )
    assert "agent-scrna-upstream 凭证未配置" in reply_call.kwargs["payload"]["content"]
    assert "方案咨询" in reply_call.kwargs["payload"]["content"]


@pytest.mark.asyncio
async def test_flow_manager_reply_cannot_claim_handoff_before_started(monkeypatch) -> None:
    agentteams = _agentteams(
        events=[_user_message_event("请开始单细胞分析")],
        case_overrides={"flow_id": "scrna"},
    )
    run = AsyncMock(
        return_value=ConsultationEnvelope(
            conclusion="已交接给专项 Agent，任务已派发并已开始分析。"
        )
    )
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    await _service(
        agentteams=agentteams,
        registry=_registry("agent-general"),
        redis=FakeRedis(),
    ).respond("bioops_1", "user-a", "请开始单细胞分析")

    reply_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.agent_message"
    )
    content = reply_call.kwargs["payload"]["content"]
    assert "已交接" not in content
    assert "已派发" not in content
    assert "已开始分析" not in content
    assert "待确认交接" in content


@pytest.mark.asyncio
async def test_respond_projects_reasoning_and_text_deltas_before_final_reply(monkeypatch) -> None:
    agentteams = _agentteams(events=[_user_message_event("请说明这个结果")])

    async def run_consultation(_service, **kwargs):
        projector = kwargs["on_event"]
        await projector({"type": "worker_reasoning_delta", "content": "先核对输入。"})
        await projector({"type": "worker_text_delta", "content": "结果已核对。"})
        return ConsultationEnvelope(
            conclusion="结果已核对。",
            recommendations=["可继续进行下游分析。"],
            risks=["样本量较小时需谨慎解释。"],
        )

    monkeypatch.setattr(AgentConsultationService, "run_consultation", run_consultation)

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-general", with_manager=True),
        redis=FakeRedis(),
    ).respond("bioops_1", "user-a", "请说明这个结果")

    assert result == {"status": "responded"}
    calls = agentteams.post_case_evidence.await_args_list
    event_types = [call.kwargs["event_type"] for call in calls]
    assert event_types == ["room.typing", "room.agent_stream", "room.agent_stream", "room.agent_message", "room.typing"]
    stream_calls = [call for call in calls if call.kwargs["event_type"] == "room.agent_stream"]
    assert [call.kwargs["payload"]["channel"] for call in stream_calls] == ["reasoning", "content"]
    assert stream_calls[0].kwargs["payload"]["delta"] == "先核对输入。"
    assert stream_calls[1].kwargs["payload"]["delta"] == "结果已核对。"
    final_payload = next(call.kwargs["payload"] for call in calls if call.kwargs["event_type"] == "room.agent_message")
    assert final_payload["stream_id"] == stream_calls[0].kwargs["payload"]["stream_id"]
    assert final_payload["manager_report"] == {
        "conclusion": "结果已核对。",
        "recommendations": ["可继续进行下游分析。"],
        "evidence_refs": [],
        "risks": ["样本量较小时需谨慎解释。"],
        "hard_gate": None,
        "proposed_submission": None,
    }


@pytest.mark.asyncio
async def test_readonly_file_request_routes_to_tool_execution_without_planning(monkeypatch) -> None:
    events = [
        _user_message_event("读取 result.csv 并判断是否为空"),
    ]
    agentteams = _agentteams(
        status="received",
        events=events,
        case_overrides={
            "work_items": [],
        },
    )
    run = AsyncMock(
        return_value=ConsultationEnvelope(
            conclusion="已读取 result.csv，文件包含 3 行数据，未发现空内容。",
            evidence_refs=["file:result.csv"],
        )
    )
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-general"),
        redis=FakeRedis(),
    ).respond("bioops_1", "user-a", "读取 result.csv 并判断是否为空")

    assert result == {"status": "responded"}
    agentteams.start_chat_planning.assert_not_awaited()
    run.assert_awaited_once()
    assert run.await_args.kwargs["requested_tools"] == ["workspace_read", "readonly_review"]
    assert run.await_args.kwargs["execution_mode"] == "readonly_consultation"
    assert run.await_args.kwargs["on_event"] is not None
    route = next(
        call for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.route_decision"
    )
    assert route.kwargs["payload"]["execution_path"] == "agentteams_tool_execution"
    reply = next(
        call for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.agent_message"
    )
    assert reply.kwargs["payload"]["tool_result_refs"] == ["file:result.csv"]
    assert reply.kwargs["payload"]["stream_id"]
    assert reply.kwargs["payload"]["manager_report"]["conclusion"] == "已读取 result.csv，文件包含 3 行数据，未发现空内容。"


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
        agentteams=agentteams, registry=_registry("agent-general", with_manager=True), redis=redis
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
    # 降级必须写 room.manager_persona_fallback 审计事件（原因/首选/目标/case_id）。
    audit = next(
        call for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.manager_persona_fallback"
    )
    assert audit.kwargs["work_item_id"] == "case"
    payload = audit.kwargs["payload"]
    assert payload["preferred_agent_id"] == "agentteams-manager"
    assert payload["target_agent_id"] == "agent-code"
    assert payload["case_id"] == "bioops_1"
    assert payload["reason"]


@pytest.mark.asyncio
async def test_manager_persona_fallback_to_general_keeps_manager_voice(monkeypatch) -> None:
    """首选 Manager agent 不可用 → 降级 agent-general：话术/展示名不变 + 审计事件。"""
    agentteams = _agentteams(events=[_user_message_event("你的职责是什么")])
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="我负责接单、协调与交付。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-general", planner_ids={"agent-general"}),
        redis=FakeRedis(),
    ).respond("bioops_1", "user-a", "你的职责是什么")

    assert result == {"status": "responded"}
    assert run.await_args.kwargs["agent_id"] == "agent-general"
    question = run.await_args.kwargs["question"]
    # Manager 话术层继续生效，称呼注入不降级为通用助手。
    assert "扮演 Manager" in question
    assert "称呼自己为「生物信息部门经理」" in question
    audit = next(
        call for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.manager_persona_fallback"
    )
    assert audit.kwargs["payload"]["preferred_agent_id"] == "agentteams-manager"
    assert audit.kwargs["payload"]["target_agent_id"] == "agent-general"
    assert audit.kwargs["payload"]["case_id"] == "bioops_1"
    reply = next(
        call for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.agent_message"
    )
    # 房间展示身份不变：role 仍是 bioops-manager。
    assert reply.kwargs["payload"]["role"] == "bioops-manager"


@pytest.mark.asyncio
async def test_manager_agent_id_config_failure_is_not_silent(monkeypatch) -> None:
    """配置加载失败必须显式报错（响应失败 + 日志），禁止静默回退到任何 agent。"""
    import omichub.application.services.agentteams_room_response_service as room_module

    def broken_settings():
        raise RuntimeError("agentteams.manager_agent_id 配置加载失败")

    monkeypatch.setattr(room_module, "get_settings", broken_settings)
    agentteams = _agentteams(events=[_user_message_event("hello")])
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="不应到达"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-general", planner_ids={"agent-general"}),
        redis=FakeRedis(),
    ).respond("bioops_1", "user-a", "hello")

    assert result == {"status": "failed"}
    run.assert_not_awaited()
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert "room.agent_message" not in event_types
    assert "room.manager_persona_fallback" not in event_types


def test_manager_agent_id_setting_rejects_blank() -> None:
    from pydantic import ValidationError

    from omichub.core.config import Settings

    with pytest.raises(ValidationError):
        Settings(agentteams_manager_agent_id="  ")


def test_build_question_display_name_prefers_agent_yaml_over_platform_default() -> None:
    question = AgentTeamsRoomResponseService._build_question(
        {"intent": "数据质控", "status": "planning_running"},
        [],
        "继续处理",
        {},
        manager_display_name="生物信息部门经理",
    )
    assert "称呼自己为「生物信息部门经理」" in question

    fallback_question = AgentTeamsRoomResponseService._build_question(
        {"intent": "数据质控", "status": "planning_running"},
        [],
        "继续处理",
        {},
    )
    assert "称呼自己为「生物信息部门经理」" in fallback_question


def test_lock_key_namespaced_per_case() -> None:
    assert ROOM_RESPONSE_LOCK_KEY_PREFIX == "agentteams:room-response:lock:"


@pytest.mark.asyncio
async def test_respond_posts_ask_user_card_when_manager_requests_clarification(monkeypatch) -> None:
    """Manager 信封携带 ask_user 问题时落 room.ask_user 事件，而非纯文本回复。"""
    agentteams = _agentteams(status="received")
    run = AsyncMock(
        return_value=ConsultationEnvelope(
            conclusion="启动规划前需要你确认几个关键信息。",
            ask_user=[
                {
                    "question": "输入数据是计数矩阵还是 FASTQ？",
                    "options": ["已有计数矩阵", "从 FASTQ 开始"],
                },
                {"question": "物种与参考基因组版本？", "options": []},
            ],
        )
    )
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    # 注意：消息文本不得含执行动词，否则会先命中 clarify 中间态而不走 LLM 会诊。
    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general", with_manager=True), redis=FakeRedis()
    ).respond("bioops_1", "user-a", "想确认一下这个 Case 的分组设置")

    assert result == {"status": "asked"}
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert event_types == ["room.typing", "room.ask_user", "room.typing"]
    ask_call = agentteams.post_case_evidence.await_args_list[1]
    assert ask_call.kwargs["work_item_id"] == "case"
    assert ask_call.kwargs["payload"]["content"] == "启动规划前需要你确认几个关键信息。"
    assert ask_call.kwargs["payload"]["role"] == "bioops-manager"
    assert ask_call.kwargs["payload"]["questions"] == [
        {"question": "输入数据是计数矩阵还是 FASTQ？", "options": ["已有计数矩阵", "从 FASTQ 开始"]},
        {"question": "物种与参考基因组版本？", "options": []},
    ]
    assert ask_call.kwargs["payload"]["manager_report"]["conclusion"] == "启动规划前需要你确认几个关键信息。"


def test_build_question_instructs_structured_ask_user() -> None:
    question = AgentTeamsRoomResponseService._build_question(
        {"intent": "RNA-seq 数据分析", "status": "received"},
        [],
        "rna-seq 数据分析",
    )

    assert "ask_user" in question
    assert "禁止只在 conclusion 正文里罗列编号问题" in question


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
async def test_execution_intent_starts_chat_planning_without_duplicate_manager_reply(monkeypatch) -> None:
    """执行意图进入领域规划后，不再让 Manager 追加重复澄清。"""
    agentteams = _agentteams(status="received", events=_EXECUTION_EVENTS)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="已为你启动可视化流水线。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", "对这个 treefile 进行可视化并解释")

    assert result == {"status": "planning_started"}
    agentteams.start_chat_planning.assert_awaited_once()
    trigger = agentteams.start_chat_planning.await_args.kwargs
    assert trigger["case_id"] == "bioops_1"
    assert trigger["requester_ref"] == "user-a"
    assert "对这个 treefile 进行可视化并解释" in trigger["objective"]
    assert "work_items" in trigger["objective"]
    assert trigger["context_refs"] == [
        {"kind": "file", "id": "tree-1", "location": "workspace/chat-uploads/example.treefile"}
    ]
    run.assert_not_awaited()
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert event_types == ["room.route_decision"]
    route_call = agentteams.post_case_evidence.await_args_list[0]
    assert route_call.kwargs["work_item_id"] == "case"
    decision = route_call.kwargs["payload"]
    # “treefile 可视化”走通用 Overdrive 路径，由 Manager 自动选择，不要求用户选 Agent。
    assert decision["path"] == "overdrive"
    assert decision["flow_id"] is None
    assert decision["confidence"] == "high"
    assert "options" not in decision


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
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert "room.route_decision" not in event_types


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


# ---- O6 阶段 2：clarify 中间态（执行动词成立但无作用对象）----


def _user_message_event(content: str, context_refs: list[dict] | None = None) -> dict:
    inner: dict = {"actor": "user-a", "content": content}
    if context_refs:
        inner["context_refs"] = context_refs
    return {
        "event_type": "room.user_message",
        "payload": {"summary": content[:80], "payload": inner},
    }


def _clarify_card_event(origin_content: str, round_no: int) -> dict:
    return {
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


def test_unstarted_flow_handoff_language_is_gated() -> None:
    reply = "我已交接给专项 Agent，任务已派发并已开始分析。"

    guarded = AgentTeamsRoomResponseService._gate_unstarted_handoff_language(reply)

    assert "已交接" not in guarded
    assert "已派发" not in guarded
    assert "已开始分析" not in guarded
    assert "待确认交接" in guarded


def test_handoff_failure_reason_is_read_from_persisted_event() -> None:
    reason = AgentTeamsRoomResponseService._handoff_failure_reason(
        [
            {"event_type": "room.user_message", "payload": {}},
            {
                "event_type": "case.handoff_failed",
                "payload": {"reason": "agent-scrna-upstream 凭证未配置"},
            },
        ]
    )

    assert reason == "agent-scrna-upstream 凭证未配置"


@pytest.mark.asyncio
async def test_clarify_intent_emits_option_card_without_route_decision(monkeypatch) -> None:
    """“帮我做差异分析”（无附件）→ 选项式澄清卡；不触发规划、不推 route_decision、不跑 LLM。"""
    events = [_user_message_event("帮我做差异分析")]
    agentteams = _agentteams(status="received", events=events)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="好的。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", "帮我做差异分析")

    assert result == {"status": "asked"}
    run.assert_not_awaited()
    agentteams.start_chat_planning.assert_not_awaited()
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert event_types == ["room.ask_user"]
    payload = agentteams.post_case_evidence.await_args_list[0].kwargs["payload"]
    assert payload["clarify_kind"] == "execution_object"
    assert payload["round"] == 1
    assert payload["origin_content"] == "帮我做差异分析"
    assert "差异分析" in payload["questions"][0]["question"]
    assert len(payload["questions"][0]["options"]) >= 3


@pytest.mark.asyncio
async def test_clarify_reply_with_object_auto_starts_execution(monkeypatch) -> None:
    """澄清回复补全作用对象（文件名）→ 自动转 execute，沿用原始请求拼接执行目标。"""
    reply = "【澄清回复】\n1. 请确认数据来源：使用工作区已有数据 genes.xlsx"
    events = [
        _user_message_event("帮我做差异分析"),
        _clarify_card_event("帮我做差异分析", 1),
        _user_message_event(reply),
    ]
    agentteams = _agentteams(status="received", events=events)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="已为你启动差异分析流水线。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", reply)

    assert result == {"status": "planning_started"}
    agentteams.start_chat_planning.assert_awaited_once()
    run.assert_not_awaited()
    trigger = agentteams.start_chat_planning.await_args.kwargs
    assert "帮我做差异分析" in trigger["objective"]
    assert "genes.xlsx" in trigger["objective"]
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    # 自动转 execute 后按既有链路外显路由决策卡
    assert "room.route_decision" in event_types
    assert "room.ask_user" not in event_types
    answer_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.ask_user_answered"
    )
    assert answer_call.kwargs["payload"]["answer"] == reply
    assert answer_call.kwargs["payload"]["round"] == 1


@pytest.mark.asyncio
async def test_clarify_answer_is_recorded_before_second_round(monkeypatch) -> None:
    """没有作用对象的澄清回复也要进入 Case 的已收集答案清单。"""
    reply = "【澄清回复】\n1. 请确认数据来源：我去上传文件"
    events = [
        _user_message_event("帮我做差异分析"),
        _clarify_card_event("帮我做差异分析", 1),
        _user_message_event(reply),
    ]
    agentteams = _agentteams(status="received", events=events)
    monkeypatch.setattr(
        AgentConsultationService,
        "run_consultation",
        AsyncMock(return_value=ConsultationEnvelope(conclusion="好的。")),
    )

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", reply)

    assert result == {"status": "asked"}
    answer_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.ask_user_answered"
    )
    assert answer_call.kwargs["payload"]["question"] == "请确认数据来源："
    assert answer_call.kwargs["payload"]["answer"] == reply


@pytest.mark.asyncio
async def test_clarify_reply_without_object_advances_to_round_two(monkeypatch) -> None:
    """结构化答复仍未给出对象 → 发出第 2 轮澄清卡。"""
    reply = "【澄清回复】\n1. 请确认数据来源：使用工作区已有数据（请回复文件名或路径）"
    events = [
        _user_message_event("帮我做差异分析"),
        _clarify_card_event("帮我做差异分析", 1),
        _user_message_event(reply),
    ]
    agentteams = _agentteams(status="received", events=events)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="好的。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", reply)

    assert result == {"status": "asked"}
    run.assert_not_awaited()
    agentteams.start_chat_planning.assert_not_awaited()
    ask_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.ask_user"
    )
    payload = ask_call.kwargs["payload"]
    assert payload["round"] == 2


@pytest.mark.asyncio
async def test_clarify_exhausted_after_two_rounds_degrades_to_chat(monkeypatch) -> None:
    """2 轮追问后仍无对象 → 降级纯对话，Manager 说明原因，不触发规划。"""
    content = "再帮我汇总一下吧"
    events = [
        _user_message_event("帮我做差异分析"),
        _clarify_card_event("帮我做差异分析", 1),
        _user_message_event("【澄清回复】\n1. 请确认数据来源：使用工作区已有数据"),
        _clarify_card_event("帮我做差异分析", 2),
        _user_message_event(content),
    ]
    agentteams = _agentteams(status="received", events=events)
    run = AsyncMock(
        return_value=ConsultationEnvelope(conclusion="缺少输入数据，暂时无法直接执行。")
    )
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", content)

    assert result == {"status": "responded"}
    agentteams.start_chat_planning.assert_not_awaited()
    question = run.await_args.kwargs["question"]
    assert "暂时无法直接执行" in question
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert "room.route_decision" not in event_types
    assert "room.ask_user" not in event_types


@pytest.mark.asyncio
async def test_clarify_opt_out_reply_falls_back_to_chat(monkeypatch) -> None:
    """用户在澄清中选择“先不执行”→ 纯对话，不再追问。"""
    reply = "【澄清回复】\n1. 请确认数据来源：先不执行，继续讨论方案"
    events = [
        _user_message_event("帮我做差异分析"),
        _clarify_card_event("帮我做差异分析", 1),
        _user_message_event(reply),
    ]
    agentteams = _agentteams(status="received", events=events)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="好的，先讨论方案。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", reply)

    assert result == {"status": "responded"}
    run.assert_awaited_once()
    agentteams.start_chat_planning.assert_not_awaited()
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert "room.ask_user" not in event_types
    assert "room.route_decision" not in event_types


@pytest.mark.asyncio
async def test_non_execution_ask_user_card_does_not_arm_pending_clarify(monkeypatch) -> None:
    """Manager LLM 产出的普通澄清卡（无 clarify_kind 标记）不计入执行对象追问：
    其后的纯文件名回复不应被误判为补全对象而触发执行。"""
    reply = "result.csv"
    events = [
        _user_message_event("想确认一下分组"),
        {
            "event_type": "room.ask_user",
            "payload": {
                "summary": "输入数据是计数矩阵还是 FASTQ？",
                "payload": {
                    "content": "需要确认。",
                    "role": "bioops-manager",
                    "questions": [{"question": "输入数据是计数矩阵还是 FASTQ？", "options": []}],
                },
            },
        },
        _user_message_event(reply),
    ]
    agentteams = _agentteams(status="received", events=events)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="收到。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", reply)

    assert result == {"status": "responded"}
    agentteams.start_chat_planning.assert_not_awaited()


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


class _ReadFailRedis(FakeRedis):
    async def get(self, key):
        raise RuntimeError("redis unavailable")


@pytest.mark.asyncio
async def test_dedup_read_failure_is_audited_and_reply_keeps_causation(monkeypatch) -> None:
    events = [
        {
            "event_id": "evt-msg-1",
            "event_type": "room.user_message",
            "payload": {
                "summary": "质控过了吗？",
                "payload": {"actor": "user-a", "content": "质控过了吗？"},
            },
        },
    ]
    agentteams = _agentteams(events=events)
    monkeypatch.setattr(
        AgentConsultationService,
        "run_consultation",
        AsyncMock(return_value=ConsultationEnvelope(conclusion="质控已通过。")),
    )

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-general"),
        redis=_ReadFailRedis(),
    ).respond("bioops_1", "user-a", "质控过了吗？")

    assert result == {"status": "responded"}
    evidence = agentteams.post_case_evidence.await_args_list
    degraded = next(call for call in evidence if call.kwargs["event_type"] == "room.dedup_degraded")
    reply = next(call for call in evidence if call.kwargs["event_type"] == "room.agent_message")
    assert degraded.kwargs["payload"]["causation_event_id"] == "evt-msg-1"
    assert reply.kwargs["payload"]["causation_event_id"] == "evt-msg-1"


@pytest.mark.asyncio
async def test_execution_clarify_answer_links_back_to_ask_event(monkeypatch) -> None:
    reply = "【澄清回复】\n使用已选文件"
    clarify = _clarify_card_event("帮我做差异分析", 1)
    clarify["event_id"] = "evt-ask-1"
    answered = _user_message_event(
        reply,
        context_refs=[{"kind": "file", "id": "file-1", "location": "counts.csv"}],
    )
    answered["event_id"] = "evt-msg-2"
    events = [_user_message_event("帮我做差异分析"), clarify, answered]
    agentteams = _agentteams(status="received", events=events)
    monkeypatch.setattr(
        AgentConsultationService,
        "run_consultation",
        AsyncMock(return_value=ConsultationEnvelope(conclusion="收到。")),
    )

    await _service(
        agentteams=agentteams,
        registry=_registry("agent-general"),
        redis=FakeRedis(),
    ).respond("bioops_1", "user-a", reply)

    answer_event = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.ask_user_answered"
    )
    assert answer_event.kwargs["payload"]["answer_to_event_id"] == "evt-ask-1"
    assert answer_event.kwargs["payload"]["answer_status"] == "collected"


# ---------------------------------------------------------------------------
# A3：@直答失败/超时/目标不可用 → Manager 降级接管（Part 2.7，禁止静默）
# ---------------------------------------------------------------------------


def _direct_message_events(content: str = "这个样本的质控怎么看？") -> list[dict]:
    return [
        {
            "event_id": "evt-msg-direct",
            "event_type": "room.user_message",
            "payload": {
                "summary": content,
                "payload": {"actor": "user-a", "content": content},
            },
        }
    ]


def _room(**overrides) -> AgentTeamsRoomModel:
    values = {
        "room_id": "roomdirect1",
        "owner_id": "user-a",
        "title": "协作室会话",
        "status": "active",
        "origin": "manual",
        "case_id": None,
        "matrix_room_id": None,
        "proposal": None,
    }
    values.update(overrides)
    return AgentTeamsRoomModel(**values)


def _evidence_calls(agentteams: SimpleNamespace, event_type: str) -> list:
    return [
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == event_type
    ]


@pytest.mark.asyncio
async def test_direct_mention_failure_falls_back_to_manager_with_audit(monkeypatch) -> None:
    """已立项 Case 路径（旧 respond）：直答报错 → 降级消息 + room.agent_timeout
    + Manager 主回路正式回复，且降级消息先于正式回复。"""
    events = _direct_message_events()
    agentteams = _agentteams(events=events)
    redis = FakeRedis()

    async def run(self, **kwargs):
        if kwargs["agent_id"] == "agent-scrna":
            raise RuntimeError("worker llm down")
        return ConsultationEnvelope(conclusion="Manager 已接管，先给出初步判断。")

    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-scrna", with_manager=True),
        redis=redis,
    ).respond("bioops_1", "user-a", "这个样本的质控怎么看？", target_agent_id="agent-scrna")

    assert result == {"status": "responded"}
    event_types = [
        call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list
    ]
    assert event_types == [
        "room.agent_message",
        "room.agent_timeout",
        "room.typing",
        "room.agent_message",
        "room.typing",
    ]
    fallback = _evidence_calls(agentteams, "room.agent_message")[0]
    assert fallback.kwargs["payload"]["direct_fallback"] is True
    assert "暂时无法响应" in fallback.kwargs["payload"]["content"]
    assert fallback.kwargs["payload"]["target_agent_id"] == "agent-scrna"
    assert fallback.kwargs["payload"]["causation_event_id"] == "evt-msg-direct"
    timeout = _evidence_calls(agentteams, "room.agent_timeout")[0]
    assert timeout.kwargs["payload"]["target_agent_id"] == "agent-scrna"
    assert "RuntimeError" in timeout.kwargs["payload"]["reason"]
    assert timeout.kwargs["payload"]["causation_event_id"] == "evt-msg-direct"
    reply = _evidence_calls(agentteams, "room.agent_message")[1]
    assert reply.kwargs["payload"]["content"] == "Manager 已接管，先给出初步判断。"
    assert reply.kwargs["payload"]["role"] == "bioops-manager"


@pytest.mark.asyncio
async def test_direct_mention_timeout_falls_back_to_manager_on_unbound_room(
    monkeypatch,
) -> None:
    """未立项房间路径（respond_room）：直答超过 agentteams_direct_timeout_seconds
    与报错同口径降级，消息与审计落在房间命名空间流（room-<id>）。"""
    settings = get_settings()
    monkeypatch.setattr(settings, "agentteams_direct_timeout_seconds", 0.05)
    events = _direct_message_events()
    agentteams = _agentteams(events=events)
    redis = FakeRedis()

    async def run(self, **kwargs):
        if kwargs["agent_id"] == "agent-scrna":
            await asyncio.sleep(5)
            return ConsultationEnvelope(conclusion="不应到达的迟到回复")
        return ConsultationEnvelope(conclusion="Manager 超时接管回复。")

    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)
    room = _room()

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-scrna", with_manager=True),
        redis=redis,
    ).respond_room(room, "user-a", "这个样本的质控怎么看？", target_agent_id="agent-scrna")

    assert result == {"status": "responded"}
    namespace = room_namespace_case_id(room.room_id)
    timeout = _evidence_calls(agentteams, "room.agent_timeout")[0]
    assert timeout.args[0] == namespace
    assert timeout.kwargs["payload"]["reason"].startswith("timeout_after_")
    assert timeout.kwargs["payload"]["target_agent_id"] == "agent-scrna"
    messages = _evidence_calls(agentteams, "room.agent_message")
    assert [call.args[0] for call in messages] == [namespace, namespace]
    assert messages[0].kwargs["payload"]["direct_fallback"] is True
    assert messages[1].kwargs["payload"]["content"] == "Manager 超时接管回复。"


@pytest.mark.asyncio
async def test_direct_mention_unavailable_agent_also_falls_back(monkeypatch) -> None:
    """目标 agent 不在会诊注册表（direct_agent_unavailable）同样降级，禁止静默。"""
    events = _direct_message_events()
    agentteams = _agentteams(events=events)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="Manager 代答。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-scrna", with_manager=True),
        redis=FakeRedis(),
    ).respond("bioops_1", "user-a", "这个样本的质控怎么看？", target_agent_id="agent-ghost")

    assert result == {"status": "responded"}
    timeout = _evidence_calls(agentteams, "room.agent_timeout")[0]
    assert timeout.kwargs["payload"]["reason"] == "agent_not_in_consultation_registry"
    assert timeout.kwargs["payload"]["target_agent_id"] == "agent-ghost"
    # 只对 Manager 跑了一次会诊，从未调用不存在的 agent-ghost。
    assert run.await_count == 1
    assert run.await_args.kwargs["agent_id"] == "agentteams-manager"


@pytest.mark.asyncio
async def test_direct_mention_success_has_no_fallback(monkeypatch) -> None:
    """正常直答路径不回归：bound Case 房间直答成功时无降级消息、无超时审计。"""
    events = _direct_message_events()
    agentteams = _agentteams(events=events)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="领域直答：质控已通过。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)
    room = _room(case_id="bioops_1")

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-scrna", with_manager=True),
        redis=FakeRedis(),
    ).respond_room(room, "user-a", "这个样本的质控怎么看？", target_agent_id="agent-scrna")

    assert result == {"status": "direct_responded"}
    assert run.await_count == 1
    assert run.await_args.kwargs["agent_id"] == "agent-scrna"
    assert _evidence_calls(agentteams, "room.agent_timeout") == []
    messages = _evidence_calls(agentteams, "room.agent_message")
    assert len(messages) == 1
    assert messages[0].kwargs["payload"]["direct_mention"] is True
    assert messages[0].kwargs["payload"]["content"] == "领域直答：质控已通过。"

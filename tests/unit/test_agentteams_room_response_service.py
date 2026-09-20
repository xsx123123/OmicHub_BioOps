"""房间 Manager 响应回路测试：锁去重、终态跳过、LLM 失败容错、manager agent 选法。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cygnusx.application.services.agent_consultation_service import (
    AgentConsultationService,
    ConsultationEnvelope,
)
from cygnusx.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)
from cygnusx.application.services.agentteams_room_response_service import (
    ROOM_RESPONSE_LOCK_KEY_PREFIX,
    AgentTeamsRoomResponseService,
    _sanitize_manager_reply,
    _visible_manager_risks,
)
from cygnusx.application.services.agentteams_service import room_namespace_case_id
from cygnusx.application.services.flow_registry import FlowRegistry
from cygnusx.core.config import get_settings
from cygnusx.infrastructure.database.models.chat import AgentTeamsRoomModel

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


def test_internal_capability_risk_boilerplate_is_removed_from_reply() -> None:
    reply = (
        "这是正常的分析说明。\n\n风险\n"
        "本轮未获准调用能力目录类只读工具，本回复仅描述部门经理的固定职责边界，"
        "未枚举平台各 Agent 的实时能力清单；具体领域能力以平台能力目录实况为准。"
    )

    assert _sanitize_manager_reply(reply) == "这是正常的分析说明。"


def test_real_manager_risks_are_preserved() -> None:
    risks = ["样本量较小，统计效能有限", "未获准调用能力目录类只读工具：内部元数据"]

    assert _visible_manager_risks(risks) == ["样本量较小，统计效能有限"]


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
    def __init__(
        self, agent_ids: set[str], *, chat_entry_false: set[str] | None = None
    ) -> None:
        self._agent_ids = agent_ids
        self._chat_entry_false = chat_entry_false or set()

    def all(self) -> dict[str, dict]:
        return {
            agent_id: {"chat_entry": False} if agent_id in self._chat_entry_false else {}
            for agent_id in self._agent_ids
        }


def _registry(
    *agent_ids: str,
    planner_ids: set[str] | None = None,
    with_manager: bool = False,
    chat_entry_false: set[str] | None = None,
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
        ability_catalog=FakeAbilityCatalog(catalog_ids, chat_entry_false=chat_entry_false),
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
    flow_registry: FlowRegistry | None = None,
) -> AgentTeamsRoomResponseService:
    return AgentTeamsRoomResponseService(
        SimpleNamespace(),
        agentteams=agentteams,
        registry=registry,
        redis_getter=lambda: redis,
        flow_registry=flow_registry,
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


# ---- P0-1：领域路由可命中的最小注册表 fixture ----


def _write_flow(flows_dir, flow_id: str, actor: str, bridge_workflow: str, hints: str) -> None:
    (flows_dir / f"{flow_id}.yaml").write_text(
        f"""flow:
  id: {flow_id}
  version: 1.0.0
  display_name: {flow_id} 流程
  domain: {flow_id}
  actor: {actor}
  runtime_image: analysis-core
  bridge_workflow: {bridge_workflow}
  trigger_hints: [{hints}]
artifacts:
  - {{key: result, type: table}}
stages:
  - key: run
    title: Run
    executors:
      - {{key: run, queue: general, resource_profile: standard, outputs: [result], retry_policy: bounded}}
delivery: {{quality_gate: true, outputs: [result]}}
""",
        encoding="utf-8",
    )


def _flow_registries(tmp_path) -> tuple[FlowRegistry, AgentTeamsCapabilityRegistry]:
    """路由可命中的最小注册表：rnaseq(actor=agent-rnaseq, hints RNA-seq/差异分析)。"""
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    shared_dir = flows_dir / "_shared"
    shared_dir.mkdir()
    (shared_dir / "policies.yaml").write_text(
        "retry_policies:\n  bounded: {max_attempts: 1}\napproval_templates: {}\n",
        encoding="utf-8",
    )
    (shared_dir / "resources.yaml").write_text(
        "standard: {cpu: 1, memory_gb: 1, temp_disk_gb: 1, queue: general, max_project_concurrency: 1}\n",
        encoding="utf-8",
    )
    (shared_dir / "artifact_types.yaml").write_text(
        "table: {format: tsv, media_types: [text/tab-separated-values], max_size_gb: 1, retention_days: 1}\n",
        encoding="utf-8",
    )
    _write_flow(flows_dir, "rnaseq", "agent-rnaseq", "rna_seq", "RNA-seq, 差异分析")
    flow_registry = FlowRegistry.from_directory(flows_dir)
    capabilities = AgentTeamsCapabilityRegistry(
        flow_registry,
        FakeAbilityCatalog({"agent-rnaseq", "agent-general"}),
        [
            _agent_config("agent-rnaseq", planner_eligible=True),
            _agent_config("agent-general", planner_eligible=True),
        ],
    )
    return flow_registry, capabilities


def _route_clarify_card_event(origin_content: str, round_no: int) -> dict:
    return {
        "event_type": "room.ask_user",
        "payload": {
            "summary": "请确认分析类型",
            "payload": {
                "content": "需要你先确认分析类型，再启动执行。",
                "role": "bioops-manager",
                "questions": [{"question": "请确认分析类型：", "options": ["rnaseq 流程"]}],
                "clarify_kind": "route_domain",
                "round": round_no,
                "origin_content": origin_content,
            },
        },
    }


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
    assert "代表「生物信息部门经理」履行生物信息部门经理职责" in question
    assert "称呼自己为「生物信息部门经理」" in question
    assert "禁止以英文 Manager、协作室 Manager 或系统 Manager 自称" in question
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
    import cygnusx.application.services.agentteams_room_response_service as room_module

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

    from cygnusx.core.config import Settings

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
    assert "只能自称「生物信息部门经理」或「我」" in question
    assert "禁止以英文 Manager、协作室 Manager 或系统 Manager 自称" in question

    fallback_question = AgentTeamsRoomResponseService._build_question(
        {"intent": "数据质控", "status": "planning_running"},
        [],
        "继续处理",
        {},
    )
    assert "称呼自己为「生物信息部门经理」" in fallback_question
    assert "只能自称「生物信息部门经理」或「我」" in fallback_question


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


def test_manager_question_can_be_forced_into_multi_expert_summary() -> None:
    question = AgentTeamsRoomResponseService._build_question(
        {"intent": "", "status": "received"},
        [
            {
                "event_type": "room.agent_message",
                "payload": {
                    "payload": {
                        "agent_id": "agent-scrna",
                        "content": "单细胞分析师负责上游分析和 RDS 交接。",
                    }
                },
            },
            {
                "event_type": "room.agent_message",
                "payload": {
                    "payload": {
                        "agent_id": "agent-viz",
                        "content": "可视化助手负责出版级图表和下游展示。",
                    }
                },
            },
        ],
        "@单细胞分析师 @可视化助手 你们两个可以搭配干活吗",
        system_note=(
            "请先阅读最近动态中各领域 Agent 的真实回复，明确标注各自姓名并用一段简洁内容汇总；"
        ),
    )

    assert "agent-scrna：单细胞分析师负责上游分析和 RDS 交接。" in question
    assert "agent-viz：可视化助手负责出版级图表和下游展示。" in question
    assert "请先阅读最近动态中各领域 Agent 的真实回复" in question
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
async def test_execution_intent_without_route_hit_emits_domain_clarify(monkeypatch, tmp_path) -> None:
    """P0-1：路由无命中禁止静默直达兜底 planner——先落领域澄清卡，不触发规划。"""
    flow_registry, _capabilities = _flow_registries(tmp_path)
    agentteams = _agentteams(status="received", events=_EXECUTION_EVENTS)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="不应走到会诊"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-general"),
        redis=FakeRedis(),
        flow_registry=flow_registry,
    ).respond("bioops_1", "user-a", "对这个 treefile 进行可视化并解释")

    assert result == {"status": "asked"}
    agentteams.start_chat_planning.assert_not_awaited()
    run.assert_not_awaited()
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert event_types == ["room.ask_user"]
    payload = agentteams.post_case_evidence.await_args_list[0].kwargs["payload"]
    assert payload["clarify_kind"] == "route_domain"
    assert payload["round"] == 1
    assert payload["origin_content"] == "对这个 treefile 进行可视化并解释"
    options = payload["questions"][0]["options"]
    assert "rnaseq 流程" in options
    assert options[-1] == "以上都不是，先和生物信息部门经理讨论方案"


@pytest.mark.asyncio
async def test_execution_intent_with_route_hit_starts_planning_without_duplicate_manager_reply(
    monkeypatch, tmp_path
) -> None:
    """执行意图命中领域路由后按路由 planner 启动规划，Manager 不追加重复澄清。"""
    flow_registry, capabilities = _flow_registries(tmp_path)
    content = "对这些样本做差异分析"
    events = [
        _user_message_event(
            content,
            context_refs=[
                {"kind": "file", "id": "m-1", "location": "workspace/chat-uploads/matrix.csv"}
            ],
        )
    ]
    agentteams = _agentteams(status="received", events=events)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="不应走到会诊"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=capabilities, redis=FakeRedis(), flow_registry=flow_registry
    ).respond("bioops_1", "user-a", content)

    assert result == {"status": "planning_started"}
    agentteams.start_chat_planning.assert_awaited_once()
    trigger = agentteams.start_chat_planning.await_args.kwargs
    assert trigger["case_id"] == "bioops_1"
    assert trigger["requester_ref"] == "user-a"
    assert trigger["target_agent_id"] == "agent-rnaseq"
    assert content in trigger["objective"]
    run.assert_not_awaited()
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert event_types == ["room.route_decision"]
    decision = agentteams.post_case_evidence.await_args_list[0].kwargs["payload"]
    assert decision["path"] == "bridge_workflow"
    assert decision["flow_id"] == "rnaseq"
    assert decision["lead_planner"] == "agent-rnaseq"


@pytest.mark.asyncio
async def test_route_clarify_reply_with_domain_starts_planning(monkeypatch, tmp_path) -> None:
    """领域澄清答复与原始请求拼接后重跑路由：命中即按路由 planner 启动规划。"""
    flow_registry, capabilities = _flow_registries(tmp_path)
    reply = "【澄清回复】\n1. 请确认分析类型：rnaseq 流程"
    events = [
        _user_message_event("帮我跑一下这个数据"),
        _route_clarify_card_event("帮我跑一下这个数据", 1),
        _user_message_event(reply),
    ]
    agentteams = _agentteams(status="received", events=events)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="不应走到会诊"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=capabilities, redis=FakeRedis(), flow_registry=flow_registry
    ).respond("bioops_1", "user-a", reply)

    assert result == {"status": "planning_started"}
    agentteams.start_chat_planning.assert_awaited_once()
    trigger = agentteams.start_chat_planning.await_args.kwargs
    assert trigger["target_agent_id"] == "agent-rnaseq"
    assert "帮我跑一下这个数据" in trigger["objective"]
    run.assert_not_awaited()
    answer_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.ask_user_answered"
    )
    assert answer_call.kwargs["payload"]["clarify_kind"] == "route_domain"


@pytest.mark.asyncio
async def test_route_clarify_exhausted_degrades_to_manager_consultation(monkeypatch, tmp_path) -> None:
    """追问轮次耗尽仍无命中 → 降级 Manager 会诊对话，绝不静默派发兜底 planner。"""
    flow_registry, capabilities = _flow_registries(tmp_path)
    content = "把这个 matrix.csv 跑一下"
    ref = {"kind": "file", "id": "m-1", "location": "workspace/chat-uploads/matrix.csv"}
    events = [
        _user_message_event(content, context_refs=[ref]),
        _route_clarify_card_event(content, 1),
        _user_message_event("【澄清回复】\n1. 请确认分析类型：随便跑跑"),
        _route_clarify_card_event(content, 2),
        _user_message_event(content, context_refs=[ref]),
    ]
    agentteams = _agentteams(status="received", events=events)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="可以先讨论分析方案。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=capabilities, redis=FakeRedis(), flow_registry=flow_registry
    ).respond("bioops_1", "user-a", content)

    assert result == {"status": "responded"}
    agentteams.start_chat_planning.assert_not_awaited()
    run.assert_awaited_once()
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert "room.ask_user" not in event_types
    assert "room.route_decision" not in event_types


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
async def test_execution_trigger_failure_does_not_break_manager_reply(monkeypatch, tmp_path) -> None:
    flow_registry, capabilities = _flow_registries(tmp_path)
    content = "对这些样本做差异分析"
    events = [
        _user_message_event(
            content,
            context_refs=[
                {"kind": "file", "id": "m-1", "location": "workspace/chat-uploads/matrix.csv"}
            ],
        )
    ]
    agentteams = _agentteams(status="received", events=events)
    agentteams.start_chat_planning = AsyncMock(side_effect=RuntimeError("bridge down"))
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="稍后为你处理。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=capabilities, redis=FakeRedis(), flow_registry=flow_registry
    ).respond("bioops_1", "user-a", content)

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
    """“帮我做差异分析”（无附件）→ 数据来源澄清卡；不触发规划、不推 route_decision、不跑 LLM。"""
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
    assert payload["questions"][0]["options"] == []
    assert "上传文件或填写工作区路径" in payload["questions"][0]["question"]


@pytest.mark.asyncio
async def test_rnaseq_workflow_consultation_does_not_ask_for_data(monkeypatch) -> None:
    """询问 RNA-seq 分析流程属于咨询，不应弹出数据来源澄清卡。"""
    content = "rna-seq分析要如何进行呀"
    events = [_user_message_event(content)]
    agentteams = _agentteams(status="received", events=events)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="可以先从实验设计开始讨论。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams, registry=_registry("agent-general"), redis=FakeRedis()
    ).respond("bioops_1", "user-a", content)

    assert result == {"status": "responded"}
    run.assert_awaited_once()
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert "room.ask_user" not in event_types


@pytest.mark.asyncio
async def test_clarify_reply_with_object_auto_starts_execution(monkeypatch, tmp_path) -> None:
    """澄清回复补全作用对象（文件名）→ 自动转 execute，沿用原始请求拼接执行目标。"""
    flow_registry, capabilities = _flow_registries(tmp_path)
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
        agentteams=agentteams, registry=capabilities, redis=FakeRedis(), flow_registry=flow_registry
    ).respond("bioops_1", "user-a", reply)

    assert result == {"status": "planning_started"}
    agentteams.start_chat_planning.assert_awaited_once()
    run.assert_not_awaited()
    trigger = agentteams.start_chat_planning.await_args.kwargs
    # 原始请求命中 rnaseq 路由（“差异分析” hint），按路由 planner 派发。
    assert trigger["target_agent_id"] == "agent-rnaseq"
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


def test_ask_reply_answer_text_strips_nested_question() -> None:
    """结构化答复只取每行最后一个「：」之后的答案文本，剥离嵌套的问题原文。"""
    content = (
        "【澄清回复】\n"
        "1. 数据来源（任选其一）：填写工作区文件名/路径，例如 raw/genes.xlsx：先讨论方案（暂不执行）"
    )

    assert (
        AgentTeamsRoomResponseService._ask_reply_answer_text(content)
        == "先讨论方案（暂不执行）"
    )
    assert AgentTeamsRoomResponseService._ask_reply_answer_text("随便聊聊") is None


@pytest.mark.asyncio
async def test_clarify_opt_out_without_pending_card_falls_back_to_chat(monkeypatch) -> None:
    """pending 卡检测失效（事件流取不到历史卡）时，结构化 opt-out 答复也必须
    终止追问：答复里嵌套的问题原文含“执行”动词，不得再被判成执行意图。"""
    reply = (
        "【澄清回复】\n"
        "1. 收到你的执行请求「帮我做差异分析」。如需立即执行，请上传文件或填写工作区路径；"
        "也可以先讨论分析方案。：先讨论方案（暂不执行）"
    )
    events = [_user_message_event("帮我做差异分析"), _user_message_event(reply)]
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
async def test_clarify_card_origin_stays_original_request_not_nested_reply(monkeypatch) -> None:
    """继续追问时卡片引用的执行请求必须保持原始请求，不得递归嵌套上一轮答复。"""
    reply = (
        "【澄清回复】\n"
        "1. 收到你的执行请求「帮我做差异分析」。如需立即执行，请上传文件或填写工作区路径；"
        "也可以先讨论分析方案。：使用工作区已有数据（请回复文件名或路径）"
    )
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
    ask_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.ask_user"
    )
    payload = ask_call.kwargs["payload"]
    assert payload["round"] == 2
    assert payload["origin_content"] == "帮我做差异分析"
    assert "【澄清回复】" not in payload["origin_content"]
    assert "【澄清回复】" not in payload["questions"][0]["question"]


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
    import cygnusx.infrastructure.celery_app.tasks.agentteams as task_module

    calls: list[tuple[str, str, str]] = []

    async def fake_impl(case_id: str, requester_ref: str, content: str) -> dict[str, str]:
        calls.append((case_id, requester_ref, content))
        return {"status": "responded"}

    monkeypatch.setattr(task_module, "_respond_to_room_message", fake_impl)

    result = task_module.respond_to_room_message("bioops_1", "user-a", "hello")

    assert result == {"status": "responded"}
    assert calls == [("bioops_1", "user-a", "hello")]


def test_celery_task_passes_model_override(monkeypatch) -> None:
    import cygnusx.infrastructure.celery_app.tasks.agentteams as task_module

    model_id = "11111111-1111-1111-1111-111111111111"
    captured: list[object] = []

    async def fake_impl(case_id, requester_ref, content, dispatch=None, model_id=None):
        captured.append(model_id)
        return {"status": "responded"}

    monkeypatch.setattr(task_module, "_respond_to_room_message", fake_impl)

    result = task_module.respond_to_room_message("bioops_1", "user-a", "hello", None, model_id)

    assert result == {"status": "responded"}
    assert captured == [task_module.uuid.UUID(model_id)]


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
        "room.typing",
        "room.typing",
        "room.agent_message",
        "room.agent_timeout",
        "room.typing",
        "room.agent_message",
        "room.typing",
    ]
    # 前两条 typing 是领域 Agent 直答的开/结束，携带响应者身份。
    expert_typing = _evidence_calls(agentteams, "room.typing")[:2]
    assert [call.kwargs["payload"]["typing"] for call in expert_typing] == [True, False]
    assert all(call.kwargs["payload"]["agent_id"] == "agent-scrna" for call in expert_typing)
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


@pytest.mark.asyncio
async def test_direct_mention_emits_typing_events_with_agent_identity(monkeypatch) -> None:
    """直答路径必须落 room.typing(True/False) 且携带响应者身份，
    前端据此显示「<领域 Agent> 正在输入」而不是一律显示经理。"""
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
    typing_calls = _evidence_calls(agentteams, "room.typing")
    assert len(typing_calls) == 2
    assert [call.kwargs["payload"]["typing"] for call in typing_calls] == [True, False]
    for call in typing_calls:
        assert call.kwargs["payload"]["agent_id"] == "agent-scrna"
        assert call.kwargs["payload"]["agent_name"] == "agent-scrna"


@pytest.mark.asyncio
async def test_direct_mention_failure_still_clears_typing(monkeypatch) -> None:
    """直答报错降级时 typing 也必须复位，避免指示器残留（TTL 之外的硬复位）。"""
    events = _direct_message_events()
    agentteams = _agentteams(events=events)

    async def run(self, **kwargs):
        if kwargs["agent_id"] == "agent-scrna":
            raise RuntimeError("worker llm down")
        return ConsultationEnvelope(conclusion="Manager 已接管，先给出初步判断。")

    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)
    room = _room(case_id="bioops_1")

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-scrna", with_manager=True),
        redis=FakeRedis(),
    ).respond_room(room, "user-a", "这个样本的质控怎么看？", target_agent_id="agent-scrna")

    assert result == {"status": "responded"}
    # 前两条 typing 属于直答的领域 Agent（True→False 硬复位）；其后是 Manager 接管主回路的 typing。
    typing_calls = _evidence_calls(agentteams, "room.typing")
    assert [call.kwargs["payload"]["typing"] for call in typing_calls[:2]] == [True, False]
    assert all(call.kwargs["payload"]["agent_id"] == "agent-scrna" for call in typing_calls[:2])


@pytest.mark.asyncio
async def test_multi_direct_mentions_are_summarized_by_manager_before_execution_gate(
    monkeypatch,
) -> None:
    """多专家都完成只读直答后，必须先由 Manager 汇总而不是追问执行对象。"""
    content = "@单细胞分析师 @可视化助手 你们两个可以搭配干活吗"
    events = _direct_message_events(content)
    agentteams = _agentteams(events=events)
    event_counter = 0

    async def post_case_evidence(case_id, **kwargs):
        nonlocal event_counter
        if kwargs["event_type"] == "room.agent_message":
            payload = kwargs.get("payload") or {}
            if payload.get("role") == "worker":
                event_counter += 1
                events.append(
                    {
                        "event_id": f"evt-worker-{event_counter}",
                        "event_type": "room.agent_message",
                        "payload": {
                            "summary": payload.get("content", "")[:200],
                            "payload": payload,
                        },
                    }
                )
        return {"event_id": f"evt-evidence-{event_counter}"}

    agentteams.post_case_evidence = AsyncMock(side_effect=post_case_evidence)
    consultation_calls: list[dict] = []

    async def run(self, **kwargs):
        consultation_calls.append(kwargs)
        if kwargs["agent_id"] == "agent-scrna":
            return ConsultationEnvelope(conclusion="单细胞分析师：负责上游质控与细胞注释。")
        if kwargs["agent_id"] == "agent-viz":
            return ConsultationEnvelope(conclusion="可视化助手：负责图表设计与结果呈现。")
        return ConsultationEnvelope(
            conclusion=(
                "收到你的执行请求「@单细胞分析师 @可视化助手 你们两个可以搭配干活吗」。"
                "如需立即执行，请上传文件或填写工作区路径；也可以先讨论分析方案。"
            )
        )

    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)

    result = await _service(
        agentteams=agentteams,
        registry=_registry("agent-scrna", "agent-viz", with_manager=True),
        redis=FakeRedis(),
    ).respond(
        "bioops_1",
        "user-a",
        content,
        target_agent_ids=["agent-scrna", "agent-viz"],
    )

    assert result == {"status": "responded"}
    assert [call["agent_id"] for call in consultation_calls] == [
        "agent-scrna",
        "agent-viz",
        "agentteams-manager",
    ]
    message_calls = _evidence_calls(agentteams, "room.agent_message")
    assert [call.kwargs["payload"]["role"] for call in message_calls] == [
        "worker",
        "worker",
        "bioops-manager",
    ]
    manager_question = consultation_calls[-1]["question"]
    assert "单细胞分析师：负责上游质控与细胞注释。" in manager_question
    assert "可视化助手：负责图表设计与结果呈现。" in manager_question
    assert "请先阅读最近动态中各领域 Agent 的真实回复" in manager_question
    manager_reply = message_calls[-1].kwargs["payload"]["content"]
    assert "两位专家已完成初步协作判断" in manager_reply
    assert "单细胞分析师：负责上游质控与细胞注释。" in manager_reply
    assert "可视化助手：负责图表设计与结果呈现。" in manager_reply
    assert "是否需要进行实际的数据分析？如果需要" in manager_reply
    assert "收到你的执行请求" not in manager_reply
    assert _evidence_calls(agentteams, "room.ask_user") == []


@pytest.mark.asyncio
async def test_direct_mention_success_arms_dedup(monkeypatch) -> None:
    """@直答成功后应落幂等标记，任务重试/轮询时同一消息不再重复直答。"""
    events = _direct_message_events()
    agentteams = _agentteams(events=events)
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="领域直答：质控已通过。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)
    redis = FakeRedis()
    room = _room(case_id="bioops_1")
    service = _service(
        agentteams=agentteams,
        registry=_registry("agent-scrna", with_manager=True),
        redis=redis,
    )

    first = await service.respond_room(room, "user-a", "这个样本的质控怎么看？", target_agent_id="agent-scrna")
    second = await service.respond_room(room, "user-a", "这个样本的质控怎么看？", target_agent_id="agent-scrna")

    assert first == {"status": "direct_responded"}
    assert second == {"status": "skipped_duplicate"}
    assert run.await_count == 1
    messages = _evidence_calls(agentteams, "room.agent_message")
    assert len(messages) == 1
    assert messages[0].kwargs["payload"]["direct_mention"] is True
    """纯咨询分支（A1）：不注入 Case 状态/研究设计，不含接单阶段引导与结构化 ask_user 指令。"""
    question = AgentTeamsRoomResponseService._build_question(
        {"intent": "", "status": "received"},
        [],
        "你们平台能做哪些分析？",
        consultation=True,
    )

    assert "纯咨询/闲聊" in question
    assert "ask_user 字段必须留空数组" in question
    assert "Case 当前状态" not in question
    assert "已提取研究设计" not in question
    assert "规划、确认、执行和产物交付中的哪个阶段" not in question
    assert "ask_user 字段输出结构化" not in question


def test_build_question_default_keeps_intake_guidance() -> None:
    """默认分支不回归（A1）：仍注入 Case 状态、研究设计与结构化 ask_user 澄清协议。"""
    question = AgentTeamsRoomResponseService._build_question(
        {"intent": "RNA-seq 数据分析", "status": "received"},
        [],
        "rna-seq 数据分析",
    )

    assert "Case 当前状态：received" in question
    assert "已提取研究设计" in question
    assert "ask_user 字段输出结构化" in question


def test_is_consultation_reply_requires_empty_case_intent() -> None:
    """Case 已提取研究目标时不算纯咨询：接单语境的选项式追问卡片必须保留。"""
    service = _service(
        agentteams=_agentteams(),
        registry=_registry("agent-general", with_manager=True),
        redis=FakeRedis(),
    )
    case_with_intent = {"intent": "RNA-seq 差异分析", "status": "received"}
    case_no_intent = {"intent": "", "status": "received"}

    assert (
        service._is_consultation_reply(case_with_intent, [], "想确认一下这个 Case 的分组设置", "none")
        is False
    )
    assert (
        service._is_consultation_reply(case_no_intent, [], "想确认一下这个 Case 的分组设置", "none")
        is True
    )
    # 已有 flow 或已开始规划时不可能是纯咨询。
    assert (
        service._is_consultation_reply(
            {"intent": "", "status": "received", "flow_id": "rna_seq"}, [], "你好", "none"
        )
        is False
    )
    assert (
        service._is_consultation_reply(case_no_intent, [], "你好", "started") is False
    )


# --- M2：L4 房间读取面记忆注入 ---

_MEMORY_BLOCK = "<user_memory>\n## 用户记忆\n- 结果图都用英文标注\n</user_memory>"


def test_build_question_injects_memory_context_when_provided() -> None:
    """M2 注入：记忆块进入 Manager 问题装配，且位于最新发言之前。"""
    question = AgentTeamsRoomResponseService._build_question(
        {"intent": "RNA-seq 数据分析", "status": "received"},
        [],
        "帮我做差异分析",
        memory_context=_MEMORY_BLOCK,
    )

    assert "<user_memory>" in question
    assert "结果图都用英文标注" in question
    assert question.index("<user_memory>") < question.rindex("请求人最新发言")


def test_build_question_without_memory_context_has_no_user_memory() -> None:
    """专家直答/会诊子 Agent 等未传 memory_context 的调用方零注入（V5）。"""
    question = AgentTeamsRoomResponseService._build_question(
        {"intent": "受控只读工具执行", "status": "tool_execute"},
        [],
        "读一下结果文件",
    )

    assert "<user_memory>" not in question


@pytest.mark.asyncio
async def test_memory_context_empty_when_v2_off(monkeypatch) -> None:
    """v2 off 时行为与接入前完全一致：不装配、不触碰记忆服务。"""
    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_room_response_service.get_settings",
        lambda: SimpleNamespace(memory_v2_enabled=False),
    )

    class _ForbiddenMemoryService:
        def __init__(self, *args, **kwargs) -> None:
            raise AssertionError("v2 off 不应装配记忆服务")

    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.AgentMemoryService",
        _ForbiddenMemoryService,
    )
    service = _service(
        agentteams=SimpleNamespace(),
        registry=_registry("agent-general", with_manager=True),
        redis=FakeRedis(),
    )

    result = await service._build_memory_context(
        requester_ref="user-1", agent_id="agentteams-manager", current_message="你好"
    )

    assert result == ""


@pytest.mark.asyncio
async def test_memory_context_uses_shared_plus_manager_partition(monkeypatch) -> None:
    """v2 开启时按 requester + manager agent 分区装配，结果原样透传。"""
    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_room_response_service.get_settings",
        lambda: SimpleNamespace(memory_v2_enabled=True),
    )
    captured: dict = {}

    class _FakeMemoryService:
        def __init__(self, _db) -> None:
            pass

        async def build_prompt_context_v2(
            self, user_id, agent_id, current_message, *, project_id=None
        ) -> str:
            captured.update(user_id=user_id, agent_id=agent_id, message=current_message)
            return _MEMORY_BLOCK

    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.AgentMemoryService",
        _FakeMemoryService,
    )
    service = _service(
        agentteams=SimpleNamespace(),
        registry=_registry("agent-general", with_manager=True),
        redis=FakeRedis(),
    )

    result = await service._build_memory_context(
        requester_ref="user-1", agent_id="agentteams-manager", current_message="提个需求"
    )

    assert result == _MEMORY_BLOCK
    assert captured == {
        "user_id": "user-1",
        "agent_id": "agentteams-manager",
        "message": "提个需求",
    }


@pytest.mark.asyncio
async def test_memory_context_failure_does_not_break_room_reply(monkeypatch) -> None:
    """记忆装配异常降级为空注入，不得阻断房间回复主流程。"""
    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_room_response_service.get_settings",
        lambda: SimpleNamespace(memory_v2_enabled=True),
    )

    class _BrokenMemoryService:
        def __init__(self, _db) -> None:
            pass

        async def build_prompt_context_v2(self, *args, **kwargs) -> str:
            raise RuntimeError("memory backend down")

    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.AgentMemoryService",
        _BrokenMemoryService,
    )
    service = _service(
        agentteams=SimpleNamespace(),
        registry=_registry("agent-general", with_manager=True),
        redis=FakeRedis(),
    )

    result = await service._build_memory_context(
        requester_ref="user-1", agent_id="agentteams-manager", current_message="你好"
    )

    assert result == ""


@pytest.mark.asyncio
async def test_memory_context_excludes_other_agent_partitions(monkeypatch) -> None:
    """M2+M1 装配点贯通证据：注入含共享偏好与 Manager 分区事实，不含其他 agent 分区。"""
    from datetime import UTC, datetime

    from cygnusx.application.services.agent_memory_service import AgentMemoryService

    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_room_response_service.get_settings",
        lambda: SimpleNamespace(memory_v2_enabled=True),
    )
    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.get_settings",
        lambda: SimpleNamespace(
            memory_v2_enabled=True,
            memory_fact_time_decay_lambda=0.02,
            agent_memory_embedding_model="text-embedding-3-small",
        ),
    )
    monkeypatch.setattr(
        AgentMemoryService, "_embed", AsyncMock(return_value=[1.0, 0.0, 0.0])
    )

    def _fact(fact_id: int, agent_id: str, scope: str, content: str) -> SimpleNamespace:
        return SimpleNamespace(
            id=fact_id, agent_id=agent_id, scope=scope, content=content,
            similarity=0.9, created_at=datetime.now(UTC),
        )

    partitions = {
        "": [_fact(1, "", "preference", "结果图都用英文标注")],
        "agentteams-manager": [_fact(2, "agentteams-manager", "summary", "manager 分区摘要")],
        "agent-scrna": [_fact(3, "agent-scrna", "project", "scrna 分区项目事实")],
    }
    store_calls: list[str] = []

    class _FakeStore:
        def __init__(self, _db) -> None:
            pass

        async def search(self, user_id, agent_id, query_vector, limit=10):
            store_calls.append(agent_id)
            return list(partitions.get(agent_id, []))[:limit]

    monkeypatch.setattr(
        "cygnusx.application.services.agent_memory_service.PostgresFactStore", _FakeStore
    )

    blocks = [
        SimpleNamespace(id=1, agent_id="", block_name="preferences", content="偏好块：英文标注"),
        SimpleNamespace(id=2, agent_id="agent-scrna", block_name="current_focus", content="不应出现"),
    ]

    class _FakeScalars:
        def __init__(self, rows: list) -> None:
            self._rows = rows

        def all(self) -> list:
            # 模拟 DB 分区过滤：只返回共享层 + 当前 agent 分区的块
            return [
                row for row in self._rows if row.agent_id in {"", "agentteams-manager"}
            ]

    db = AsyncMock()
    db.scalars = AsyncMock(return_value=_FakeScalars(blocks))
    service = AgentTeamsRoomResponseService(
        db,
        agentteams=SimpleNamespace(),
        registry=_registry("agent-general", with_manager=True),
        redis_getter=lambda: FakeRedis(),
    )

    content = await service._build_memory_context(
        requester_ref="user-1", agent_id="agentteams-manager", current_message="帮我画图"
    )

    assert content.startswith("<user_memory>")
    assert "结果图都用英文标注" in content
    assert "偏好块：英文标注" in content
    assert "manager 分区摘要" in content
    assert "scrna 分区项目事实" not in content
    assert "不应出现" not in content
    assert store_calls == ["", "agentteams-manager"]


def test_room_message_history_injects_other_agent_reply_without_current_message(monkeypatch) -> None:
    monkeypatch.setattr(
        "cygnusx.application.services.agentteams_room_response_service.get_settings",
        lambda: SimpleNamespace(
            room_context_message_limit=20,
            room_context_max_chars=16_000,
            room_context_include_thinking=False,
        ),
    )
    history = AgentTeamsRoomResponseService._room_message_history(
        [
            {
                "event_type": "room.user_message",
                "payload": {"payload": {"content": "请代码助手回答"}},
            },
            {
                "event_type": "room.agent_message",
                "payload": {
                    "payload": {"agent_id": "agent-code", "content": "代码助手的真实回复"}
                },
            },
            {
                "event_type": "room.user_message",
                "payload": {"payload": {"content": "重复代码助手刚刚的回复"}},
            },
        ],
        current_content="重复代码助手刚刚的回复",
    )

    assert "agent-code：代码助手的真实回复" in history
    assert "重复代码助手刚刚的回复" not in history
    assert "thinking" not in history.lower()


# ---- 纯咨询分诊（CHAT → 领域专家直答）----


def _chat_question_events(content: str) -> list[dict]:
    return [
        {
            "event_id": "evt-chat-1",
            "event_type": "room.user_message",
            "recorded_at": "2026-08-26T12:40:00+00:00",
            "payload": {"summary": content, "payload": {"actor": "user-a", "content": content}},
        }
    ]


@pytest.mark.asyncio
async def test_consultation_triage_routes_chat_question_to_specialist(monkeypatch) -> None:
    """纯咨询问题命中分诊：落 room.route_transition 事件并由领域专家直答。"""
    content = "rna-seq 的原理是什么呀"
    agentteams = _agentteams(events=_chat_question_events(content))
    redis = FakeRedis()
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="RNA-seq 的核心原理是……"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)
    service = _service(
        agentteams=agentteams,
        registry=_registry("agent-rnaseq", "agent-general", with_manager=True),
        redis=redis,
    )
    triage = AsyncMock(
        return_value={"agent_id": "agent-rnaseq", "reason": "RNA-seq 原理属转录组领域", "confidence": 0.92}
    )
    monkeypatch.setattr(service, "_triage_consultation_agent", triage)

    result = await service.respond("bioops_1", "user-a", content)

    assert result == {"status": "triage_responded"}
    # 只有领域专家被会诊，Manager 不再重复作答。
    assert run.await_count == 1
    assert run.await_args.kwargs["agent_id"] == "agent-rnaseq"
    assert "分诊" in run.await_args.kwargs["question"]
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert "room.route_transition" in event_types
    transition_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.route_transition"
    )
    assert transition_call.kwargs["payload"]["target_agent_id"] == "agent-rnaseq"
    assert transition_call.kwargs["payload"]["trigger"] == "consultation_triage"
    assert transition_call.kwargs["payload"]["causation_event_id"] == "evt-chat-1"
    reply_call = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.agent_message"
    )
    assert reply_call.kwargs["payload"]["agent_id"] == "agent-rnaseq"
    assert reply_call.kwargs["payload"]["routed_by"] == "manager_triage"
    assert reply_call.kwargs["payload"]["direct_mention"] is False


@pytest.mark.asyncio
async def test_consultation_triage_miss_keeps_manager_reply(monkeypatch) -> None:
    """分诊未命中（返回 None）：维持 Manager 主回路回答，不落分诊事件。"""
    content = "rna-seq 的原理是什么呀"
    agentteams = _agentteams(events=_chat_question_events(content))
    redis = FakeRedis()
    run = AsyncMock(return_value=ConsultationEnvelope(conclusion="经理直接回答。"))
    monkeypatch.setattr(AgentConsultationService, "run_consultation", run)
    service = _service(
        agentteams=agentteams,
        registry=_registry("agent-rnaseq", "agent-general", with_manager=True),
        redis=redis,
    )
    monkeypatch.setattr(service, "_triage_consultation_agent", AsyncMock(return_value=None))

    result = await service.respond("bioops_1", "user-a", content)

    assert result == {"status": "responded"}
    assert run.await_args.kwargs["agent_id"] == "agentteams-manager"
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert "room.route_transition" not in event_types


@pytest.mark.asyncio
async def test_consultation_triage_direct_failure_degrades_to_manager(monkeypatch) -> None:
    """分诊命中但专家直答失败：按 A3 口径落可见降级，随后 Manager 接管回复。"""
    content = "rna-seq 的原理是什么呀"
    agentteams = _agentteams(events=_chat_question_events(content))
    redis = FakeRedis()

    async def _run_consultation(self, **kwargs):
        if kwargs.get("agent_id") == "agent-rnaseq":
            raise RuntimeError("specialist boom")
        return ConsultationEnvelope(conclusion="经理兜底回答。")

    monkeypatch.setattr(AgentConsultationService, "run_consultation", _run_consultation)
    service = _service(
        agentteams=agentteams,
        registry=_registry("agent-rnaseq", "agent-general", with_manager=True),
        redis=redis,
    )
    monkeypatch.setattr(
        service,
        "_triage_consultation_agent",
        AsyncMock(return_value={"agent_id": "agent-rnaseq", "reason": "领域问题", "confidence": 0.9}),
    )

    result = await service.respond("bioops_1", "user-a", content)

    assert result == {"status": "responded"}
    event_types = [call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list]
    assert "room.route_transition" in event_types
    assert "room.agent_timeout" in event_types
    fallback = next(
        call
        for call in agentteams.post_case_evidence.await_args_list
        if call.kwargs["event_type"] == "room.agent_message"
        and call.kwargs["payload"].get("direct_fallback")
    )
    assert fallback.kwargs["payload"]["target_agent_id"] == "agent-rnaseq"
    # Manager 最终答复仍存在。
    assert any(
        call.kwargs["event_type"] == "room.agent_message"
        and call.kwargs["payload"].get("content") == "经理兜底回答。"
        for call in agentteams.post_case_evidence.await_args_list
    )


class _FakeRouteProvider:
    def __init__(self, text: str) -> None:
        self._text = text

    async def chat_stream(self, **_kwargs):
        yield SimpleNamespace(type="text", content=self._text)


def _triage_service() -> AgentTeamsRoomResponseService:
    return _service(
        agentteams=_agentteams(),
        registry=_registry("agent-rnaseq", "agent-general", with_manager=True),
        redis=FakeRedis(),
    )


def _patch_triage_runtime(monkeypatch, service, route_text: str) -> None:
    catalog = [
        {
            "agent_id": "agent-rnaseq",
            "name": "RNA-seq 专家",
            "description": "bulk RNA-seq 差异表达分析",
            "category": "analysis",
        },
        {
            "agent_id": "agent-general",
            "name": "通用助手",
            "description": "通用问答",
            "category": "general",
        },
    ]
    monkeypatch.setattr(service._registry, "room_consultation_catalog", lambda: catalog)
    from cygnusx.application.services.agent_service import AgentService

    monkeypatch.setattr(
        AgentService,
        "assemble_context",
        AsyncMock(return_value=SimpleNamespace(model_config=SimpleNamespace())),
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.ai_provider.openai_compatible.provider_manager",
        _FakeRouteProvider(route_text),
    )


@pytest.mark.asyncio
async def test_triage_consultation_agent_parses_llm_decision(monkeypatch) -> None:
    service = _triage_service()
    _patch_triage_runtime(
        monkeypatch,
        service,
        '{"agent_id": "agent-rnaseq", "reason": "RNA-seq 原理属转录组领域", "confidence": 0.92}',
    )

    decision = await service._triage_consultation_agent(
        "rna-seq 的原理是什么呀", manager_agent_id="agentteams-manager", model_id=None, user_id="user-a"
    )

    assert decision == {
        "agent_id": "agent-rnaseq",
        "reason": "RNA-seq 原理属转录组领域",
        "confidence": 0.92,
    }


@pytest.mark.asyncio
async def test_triage_consultation_agent_rejects_low_confidence_and_manager(monkeypatch) -> None:
    service = _triage_service()
    _patch_triage_runtime(
        monkeypatch, service, '{"agent_id": "agent-rnaseq", "reason": "拿不准", "confidence": 0.4}'
    )
    assert (
        await service._triage_consultation_agent(
            "随便聊聊", manager_agent_id="agentteams-manager", model_id=None, user_id="user-a"
        )
        is None
    )

    _patch_triage_runtime(
        monkeypatch,
        service,
        '{"agent_id": "agentteams-manager", "reason": "通用问题", "confidence": 0.99}',
    )
    assert (
        await service._triage_consultation_agent(
            "平台怎么用", manager_agent_id="agentteams-manager", model_id=None, user_id="user-a"
        )
        is None
    )

    _patch_triage_runtime(
        monkeypatch, service, '{"agent_id": "agent-unknown", "reason": "幻觉候选", "confidence": 0.99}'
    )
    assert (
        await service._triage_consultation_agent(
            "rna-seq 的原理是什么呀",
            manager_agent_id="agentteams-manager",
            model_id=None,
            user_id="user-a",
        )
        is None
    )


@pytest.mark.asyncio
async def test_triage_consultation_agent_failure_returns_none(monkeypatch) -> None:
    """模型调用异常静默回落：分诊不得阻断 Manager 主回路。"""
    service = _triage_service()
    monkeypatch.setattr(
        service._registry,
        "room_consultation_catalog",
        lambda: [{"agent_id": "agent-rnaseq", "name": "RNA-seq 专家"}],
    )
    from cygnusx.application.services.agent_service import AgentService

    monkeypatch.setattr(
        AgentService,
        "assemble_context",
        AsyncMock(side_effect=RuntimeError("model config unavailable")),
    )

    assert (
        await service._triage_consultation_agent(
            "rna-seq 的原理是什么呀",
            manager_agent_id="agentteams-manager",
            model_id=None,
            user_id="user-a",
        )
        is None
    )


@pytest.mark.asyncio
async def test_triage_candidates_include_internal_staff_without_chat_entry(monkeypatch) -> None:
    """chat_entry:false 的内部员工（如 agent-data）仍是房间分诊候选。

    chat_entry 只约束 chat 侧对外路由入口；协作室内被 @ 或分诊直答不受其限制。
    使用真实注册表（不 mock room_consultation_catalog）验证候选合成链路。
    """
    service = _service(
        agentteams=_agentteams(),
        registry=_registry(
            "agent-rnaseq",
            "agent-data",
            with_manager=True,
            chat_entry_false={"agent-data"},
        ),
        redis=FakeRedis(),
    )
    # agent-data 不进 chat 侧对外路由目录，但进房间会诊目录
    assert "agent-data" not in {
        entry["agent_id"] for entry in service._registry.chat_router_catalog()
    }
    assert "agent-data" in {
        entry["agent_id"] for entry in service._registry.room_consultation_catalog()
    }

    from cygnusx.application.services.agent_service import AgentService

    monkeypatch.setattr(
        AgentService,
        "assemble_context",
        AsyncMock(return_value=SimpleNamespace(model_config=SimpleNamespace())),
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.ai_provider.openai_compatible.provider_manager",
        _FakeRouteProvider(
            '{"agent_id": "agent-data", "reason": "数据管理属数据管理员职责", "confidence": 0.9}'
        ),
    )

    decision = await service._triage_consultation_agent(
        "这个项目的数据管理要如何进行",
        manager_agent_id="agentteams-manager",
        model_id=None,
        user_id="user-a",
    )

    assert decision is not None
    assert decision["agent_id"] == "agent-data"

"""路由决策卡（O1）测试：决策载荷构建 + 房间回路 room.route_decision 事件外显。"""

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
from omichub.application.services.agentteams_intent_router import infer_intent_route
from omichub.application.services.agentteams_room_response_service import (
    AgentTeamsRoomResponseService,
)
from omichub.application.services.agentteams_route_decision import (
    build_route_decision,
    summarize_route_decision,
)
from omichub.application.services.flow_registry import FlowRegistry


class _Abilities:
    def __init__(self, agent_ids: set[str]) -> None:
        self._agent_ids = agent_ids

    def all(self) -> dict[str, dict]:
        return {agent_id: {} for agent_id in self._agent_ids}


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


def _agent(agent_id: str) -> dict:
    return {
        "agent_id": agent_id,
        "name": agent_id,
        "features": {
            "internal_case_role": agent_id,
            "agentteams": {
                "category": "expert",
                "recruitable": True,
                "planner_eligible": True,
                "execution_modes": ["readonly_consultation"],
            },
            "persona": {"status_lines": _STATUS_LINES},
        },
    }


def _write_flow(
    flows_dir, flow_id: str, actor: str, bridge_workflow: str, hints: str, *, stages: str = ""
) -> None:
    default_stages = (
        "  - key: run\n"
        "    title: Run\n"
        "    executors:\n"
        "      - {key: run, queue: general, resource_profile: standard, outputs: [result], retry_policy: bounded}\n"
    )
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
{stages or default_stages}delivery: {{quality_gate: true, outputs: [result]}}
""",
        encoding="utf-8",
    )


def _shared(flows_dir) -> None:
    shared_dir = flows_dir / "_shared"
    shared_dir.mkdir(parents=True)
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


def _build_registries(tmp_path):
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    _shared(flows_dir)
    _write_flow(flows_dir, "rnaseq", "agent-rnaseq", "rna_seq", "RNA-seq, bulk RNA, 差异分析")
    _write_flow(flows_dir, "atacseq", "agent-atacseq", "atac_seq", "ATAC-seq, peak calling")
    flow_registry = FlowRegistry.from_directory(flows_dir)
    capabilities = AgentTeamsCapabilityRegistry(
        flow_registry,
        _Abilities({"agent-rnaseq", "agent-atacseq", "agent-general"}),
        [_agent("agent-rnaseq"), _agent("agent-atacseq"), _agent("agent-general")],
    )
    return flow_registry, capabilities


def test_rnaseq_request_yields_high_confidence_bridge_decision(tmp_path) -> None:
    flow_registry, capabilities = _build_registries(tmp_path)

    decision = build_route_decision(
        "帮我进行rna-seq分析", flow_registry=flow_registry, capability_registry=capabilities
    )

    assert decision is not None
    assert decision["path"] == "bridge_workflow"
    assert decision["flow_id"] == "rnaseq"
    assert decision["flow_label"] == "rnaseq 流程"
    assert decision["lead_planner"] == "agent-rnaseq"
    assert decision["matched_hints"] == ["RNA-seq"]
    assert decision["planner_scores"]["agent-rnaseq"] == 1
    assert decision["estimated_stages"] == [{"key": "run", "title": "Run"}]
    assert decision["participants"] == ["agent-rnaseq"]
    assert decision["confidence"] == "high"
    assert "options" not in decision


def test_vague_request_yields_ambiguous_overdrive_decision_with_options(tmp_path) -> None:
    flow_registry, capabilities = _build_registries(tmp_path)

    decision = build_route_decision(
        "帮我分析这个数据", flow_registry=flow_registry, capability_registry=capabilities
    )

    assert decision is not None
    assert decision["path"] == "overdrive"
    assert decision["flow_id"] is None
    assert decision["confidence"] == "ambiguous"
    assert [stage["key"] for stage in decision["estimated_stages"]] == [
        "planning",
        "execution",
        "delivery",
    ]
    option_flows = [option["flow_id"] for option in decision["options"]]
    assert option_flows == ["atacseq", "rnaseq", None]
    assert decision["options"][-1]["lead_planner"] == decision["lead_planner"]


def test_tied_flow_scores_yield_ambiguous_decision(tmp_path) -> None:
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    _shared(flows_dir)
    _write_flow(flows_dir, "flowa", "agent-rnaseq", "flow_a", "组学分析")
    _write_flow(flows_dir, "flowb", "agent-atacseq", "flow_b", "组学分析")
    flow_registry = FlowRegistry.from_directory(flows_dir)
    capabilities = AgentTeamsCapabilityRegistry(
        flow_registry,
        _Abilities({"agent-rnaseq", "agent-atacseq"}),
        [_agent("agent-rnaseq"), _agent("agent-atacseq")],
    )

    decision = build_route_decision(
        "帮我做组学分析", flow_registry=flow_registry, capability_registry=capabilities
    )

    assert decision is not None
    assert decision["confidence"] == "ambiguous"
    # 平分保持字典序在前者胜出（与 infer_intent_route 一致），卡片仍给出全部候选。
    assert decision["flow_id"] == "flowa"
    assert [option["flow_id"] for option in decision["options"]] == ["flowa", "flowb", None]


def test_blank_text_returns_none(tmp_path) -> None:
    flow_registry, capabilities = _build_registries(tmp_path)
    assert (
        build_route_decision("   ", flow_registry=flow_registry, capability_registry=capabilities)
        is None
    )


def test_summarize_route_decision() -> None:
    flow_registry, capabilities = None, None  # 摘要函数不依赖 registry
    assert flow_registry is None and capabilities is None
    high = {
        "flow_label": "bulk RNA-seq 差异分析",
        "lead_planner": "agent-rnaseq",
        "estimated_stages": [{"key": "run", "title": "Run"}],
        "confidence": "high",
    }
    assert (
        summarize_route_decision(high)
        == "已选择「bulk RNA-seq 差异分析」 · 规划者 agent-rnaseq · 预计 1 个阶段"
    )
    ambiguous = {**high, "confidence": "ambiguous"}
    assert "请点选裁决" in summarize_route_decision(ambiguous)


def test_fallback_route_decision_is_explicitly_auditable(tmp_path) -> None:
    flow_registry, capabilities = _build_registries(tmp_path)

    decision = build_route_decision(
        "帮我处理这个数据",
        flow_registry=flow_registry,
        capability_registry=capabilities,
        fallback_lead_planner="agent-code",
    )

    assert decision is not None
    assert decision["lead_planner"] == "agent-code"
    assert decision["fallback"] is True
    assert "未识别到领域专家" in decision["flow_label"]
    assert decision["options"][-1]["lead_planner"] == "agent-code"


def test_resolved_scrna_route_drives_display_target(tmp_path) -> None:
    flow_registry, capabilities = _build_registries(tmp_path)
    # Extend the fixture with a scrna flow and planner so this test exercises
    # the same route result that dispatch receives.
    _write_flow(flow_registry.flows_dir, "scrna", "agent-scrna", "scrna", "单细胞")
    flow_registry = FlowRegistry.from_directory(flow_registry.flows_dir)
    capabilities = AgentTeamsCapabilityRegistry(
        flow_registry,
        _Abilities({"agent-rnaseq", "agent-atacseq", "agent-scrna", "agent-general"}),
        [_agent("agent-rnaseq"), _agent("agent-atacseq"), _agent("agent-scrna"), _agent("agent-general")],
    )
    route = infer_intent_route(
        "请用单细胞流程分析 Cell Ranger 结果",
        flow_registry=flow_registry,
        capability_registry=capabilities,
    )

    decision = build_route_decision(
        "请用单细胞流程分析 Cell Ranger 结果",
        flow_registry=flow_registry,
        capability_registry=capabilities,
        resolved_route=route,
    )

    assert route is not None
    assert route.lead_planner == "agent-scrna"
    assert decision["lead_planner"] == route.lead_planner


class _FakeRedis:
    async def set(self, *args, **kwargs):
        return True

    async def eval(self, *args):
        return 1


def _room_agentteams(events: list[dict]) -> SimpleNamespace:
    return SimpleNamespace(
        get_case=AsyncMock(
            return_value={"case_id": "bioops_1", "intent": "rna-seq", "status": "received"}
        ),
        get_case_events=AsyncMock(return_value={"events": events, "next_cursor": None}),
        post_case_evidence=AsyncMock(return_value={"event_id": "evt"}),
        start_chat_planning=AsyncMock(return_value=None),
    )


@pytest.mark.asyncio
async def test_execution_intent_emits_route_decision_event(monkeypatch, tmp_path) -> None:
    """验收口径：发送“帮我进行rna-seq分析”+ FASTQ 附件 → 房间出现路由决策卡事件。"""
    flow_registry, capabilities = _build_registries(tmp_path)
    events = [
        {
            "event_type": "room.user_message",
            "payload": {
                "summary": "帮我进行rna-seq分析",
                "payload": {
                    "actor": "user-a",
                    "content": "帮我进行rna-seq分析",
                    "context_refs": [
                        {
                            "kind": "file",
                            "id": "fastq-1",
                            "location": "workspace/chat-uploads/sample_R1.fastq",
                        }
                    ],
                },
            },
        }
    ]
    agentteams = _room_agentteams(events)
    monkeypatch.setattr(
        AgentConsultationService,
        "run_consultation",
        AsyncMock(return_value=ConsultationEnvelope(conclusion="已为你启动分析。")),
    )

    result = await AgentTeamsRoomResponseService(
        SimpleNamespace(),
        agentteams=agentteams,
        registry=capabilities,
        redis_getter=_FakeRedis,
        flow_registry=flow_registry,
    ).respond("bioops_1", "user-a", "帮我进行rna-seq分析")

    assert result == {"status": "planning_started"}
    agentteams.start_chat_planning.assert_awaited_once()
    route_call = agentteams.post_case_evidence.await_args_list[0]
    assert route_call.kwargs["event_type"] == "room.route_decision"
    assert route_call.kwargs["work_item_id"] == "case"
    decision = route_call.kwargs["payload"]
    assert decision["path"] == "bridge_workflow"
    assert decision["flow_id"] == "rnaseq"
    assert decision["lead_planner"] == "agent-rnaseq"
    assert decision["confidence"] == "high"
    assert agentteams.start_chat_planning.await_args.kwargs["target_agent_id"] == "agent-rnaseq"
    assert decision["audit"]["display_lead_planner"] == "agent-rnaseq"
    assert decision["audit"]["actual_plan_target"] == "agent-rnaseq"
    assert decision["audit"]["level"] == "INFO"
    # 规划接手后仅落路由决策，不再由 Manager 追加一轮重复回复。
    event_types = [
        call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list
    ]
    assert event_types == ["room.route_decision"]


@pytest.mark.asyncio
async def test_fallback_route_emits_audited_code_planner(tmp_path) -> None:
    flow_registry, capabilities = _build_registries(tmp_path)
    agentteams = SimpleNamespace(post_case_evidence=AsyncMock())
    service = AgentTeamsRoomResponseService(
        SimpleNamespace(),
        agentteams=agentteams,
        registry=capabilities,
        redis_getter=lambda: None,
        flow_registry=flow_registry,
    )

    await service._emit_route_decision("case-1", "帮我处理这个数据")

    payload = agentteams.post_case_evidence.await_args.kwargs["payload"]
    assert payload["fallback"] is True
    assert payload["audit"]["actual_plan_target"] == "agent-code"
    assert payload["audit"]["level"] == "INFO"
    assert "回退通用代码助手" in payload["flow_label"]


@pytest.mark.asyncio
async def test_consultation_message_emits_no_route_decision(monkeypatch, tmp_path) -> None:
    """验收口径：无附件纯咨询消息不出现路由决策卡。"""
    flow_registry, capabilities = _build_registries(tmp_path)
    events = [
        {
            "event_type": "room.user_message",
            "payload": {
                "summary": "什么是RNA-seq",
                "payload": {"actor": "user-a", "content": "什么是RNA-seq"},
            },
        }
    ]
    agentteams = _room_agentteams(events)
    monkeypatch.setattr(
        AgentConsultationService,
        "run_consultation",
        AsyncMock(return_value=ConsultationEnvelope(conclusion="RNA-seq 是转录组测序技术。")),
    )

    result = await AgentTeamsRoomResponseService(
        SimpleNamespace(),
        agentteams=agentteams,
        registry=capabilities,
        redis_getter=_FakeRedis,
        flow_registry=flow_registry,
    ).respond("bioops_1", "user-a", "什么是RNA-seq")

    assert result == {"status": "responded"}
    agentteams.start_chat_planning.assert_not_awaited()
    event_types = [
        call.kwargs["event_type"] for call in agentteams.post_case_evidence.await_args_list
    ]
    assert "room.route_decision" not in event_types

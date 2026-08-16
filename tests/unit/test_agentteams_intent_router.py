"""AgentTeams 聊天意图路由测试:关键词命中推到对应流程分析师,未命中回退。"""

from __future__ import annotations

import pytest

from omichub.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)
from omichub.application.services.agentteams_intent_router import infer_intent_route
from omichub.application.services.flow_registry import FlowRegistry


class _Abilities:
    def all(self):
        return {"agent-code": {}, "agent-rnaseq": {}, "agent-atacseq": {}}


def _features(role: str) -> dict:
    return {
        "internal_case_role": role,
        "agentteams": {
            "category": "expert",
            "recruitable": True,
            "planner_eligible": True,
            "execution_modes": ["readonly_consultation"],
            "max_parallel_work_items": 1,
            "case_mode_excluded_tool_packs": ["subagents"],
            "handoff_in_case_mode": False,
            "work_item_timeout_sec": 300,
        },
        "persona": {
            "status_lines": {
                "recruited": ["ready"],
                "queued": ["queued"],
                "running": ["running"],
                "reviewing": ["reviewing"],
                "succeeded": ["done"],
                "failed": ["failed"],
                "awaiting_input": ["waiting"],
            }
        },
    }


def _agent(agent_id: str) -> dict:
    return {"agent_id": agent_id, "name": agent_id, "features": _features(agent_id)}


def _write_flow(flows_dir, flow_id: str, actor: str, bridge_workflow: str, hints: str) -> None:
    (flows_dir / f"{flow_id}.yaml").write_text(
        f"""flow:
  id: {flow_id}
  version: 1.0.0
  display_name: {flow_id}
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


def _build_registry(tmp_path, *, with_atacseq_agent: bool = True):
    flows_dir = tmp_path / "flows"
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
    _write_flow(flows_dir, "rnaseq", "agent-rnaseq", "rna_seq", "RNA-seq, bulk RNA, 差异分析, RNAFlow")
    _write_flow(
        flows_dir, "atacseq", "agent-atacseq", "atac_seq", "ATAC-seq, 染色质开放性, peak calling"
    )
    flow_registry = FlowRegistry.from_directory(flows_dir)
    agents = [_agent("agent-code"), _agent("agent-rnaseq")]
    if with_atacseq_agent:
        agents.append(_agent("agent-atacseq"))
    capabilities = AgentTeamsCapabilityRegistry(flow_registry, _Abilities(), agents)
    return flow_registry, capabilities


@pytest.mark.parametrize(
    "text",
    [
        "帮我分析一批rna-seq数据",
        "RNASEQ 定量后做差异表达",
        "我有一批 bulk RNA 数据想做差异分析",
        "小鼠脑组织转录组测序数据怎么分析",
        "用 RNAFlow 跑一下这个项目",
    ],
)
def test_rnaseq_intent_routes_to_rnaseq_analyst(tmp_path, text: str) -> None:
    flow_registry, capabilities = _build_registry(tmp_path)
    route = infer_intent_route(text, flow_registry=flow_registry, capability_registry=capabilities)
    assert route is not None
    assert route.flow_id == "rna_seq"
    assert route.lead_planner == "agent-rnaseq"


@pytest.mark.parametrize(
    "text",
    [
        "帮我做 ATAC-seq 的 peak calling",
        "atacseq 数据质控",
        "染色质可及性分析",
    ],
)
def test_atacseq_intent_routes_to_atacseq_analyst(tmp_path, text: str) -> None:
    flow_registry, capabilities = _build_registry(tmp_path)
    route = infer_intent_route(text, flow_registry=flow_registry, capability_registry=capabilities)
    assert route is not None
    assert route.flow_id == "atac_seq"
    assert route.lead_planner == "agent-atacseq"


def test_unrecognized_intent_returns_none(tmp_path) -> None:
    flow_registry, capabilities = _build_registry(tmp_path)
    assert (
        infer_intent_route(
            "帮我订一个披萨", flow_registry=flow_registry, capability_registry=capabilities
        )
        is None
    )


def test_blank_intent_returns_none(tmp_path) -> None:
    flow_registry, capabilities = _build_registry(tmp_path)
    assert infer_intent_route("  ", flow_registry=flow_registry, capability_registry=capabilities) is None


def test_flow_without_active_agent_is_skipped(tmp_path) -> None:
    flow_registry, capabilities = _build_registry(tmp_path, with_atacseq_agent=False)
    assert (
        infer_intent_route(
            "帮我做 ATAC-seq 的 peak calling",
            flow_registry=flow_registry,
            capability_registry=capabilities,
        )
        is None
    )

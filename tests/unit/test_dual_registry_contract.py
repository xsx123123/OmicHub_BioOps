"""双注册表统一(Part 3.3)契约测试。

断言 chat 侧 LLM 路由与房间关键词路由共用 ``AgentTeamsCapabilityRegistry``
同一快照:候选集、能力描述、流程目录同源;trigger_hints 路由目标必须落在
注册表已登记 Agent 内,未登记目标降级统一 fallback。
"""

from __future__ import annotations

import pytest

from omichub.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)
from omichub.application.services.agentteams_intent_router import (
    explain_intent_route,
    infer_intent_route,
)
from omichub.application.services.flow_registry import FlowRegistry


class _Abilities:
    """agent_ability.yaml  stub:agent_id -> 能力条目。"""

    def __init__(self, entries: dict[str, dict] | None = None) -> None:
        self._entries = entries or {}

    def all(self) -> dict[str, dict]:
        return {agent_id: dict(value) for agent_id, value in self._entries.items()}


class _Domains:
    """domains/*.yaml stub:无派生别名、无路由提示。"""

    def __init__(self, flow_aliases: dict[str, tuple[str, ...]] | None = None) -> None:
        self._flow_aliases = flow_aliases or {}

    def router_notes_for(self, agent_id: str, domain: str | None = None) -> str:
        return ""

    def derived_flow_aliases(self) -> dict[str, tuple[str, ...]]:
        return dict(self._flow_aliases)


def _features(role: str, *, router: bool = False) -> dict:
    return {
        "internal_case_role": role,
        "router": router,
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


def _agent(agent_id: str, *, router: bool = False, name: str | None = None) -> dict:
    return {
        "agent_id": agent_id,
        "name": name or agent_id,
        "category": "general" if "general" in agent_id else "analysis",
        "features": _features(agent_id, router=router),
    }


def _write_shared(flows_dir) -> None:
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


def _build_registry(
    tmp_path,
    *,
    flows: list[tuple[str, str, str, str]] | None = None,
    agents: list[dict] | None = None,
    abilities: _Abilities | None = None,
    domains: _Domains | None = None,
):
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    _write_shared(flows_dir)
    for flow_id, actor, bridge_workflow, hints in flows or [
        ("rnaseq", "agent-rnaseq", "rna_seq", "RNA-seq, bulk RNA, 差异分析"),
        ("atacseq", "agent-atacseq", "atac_seq", "ATAC-seq, 染色质开放性"),
    ]:
        _write_flow(flows_dir, flow_id, actor, bridge_workflow, hints)
    flow_registry = FlowRegistry.from_directory(flows_dir)
    capabilities = AgentTeamsCapabilityRegistry(
        flow_registry,
        abilities or _Abilities(),
        agents
        if agents is not None
        else [_agent("agent-general"), _agent("agent-rnaseq"), _agent("agent-atacseq")],
        domain_registry=domains or _Domains(),
    )
    return flow_registry, capabilities


@pytest.mark.unit
def test_chat_and_room_routing_share_snapshot_candidates(tmp_path) -> None:
    """同一快照:房间关键词路由的每个 flow 路由目标都在 chat 候选目录内。"""
    flow_registry, capabilities = _build_registry(tmp_path)
    snapshot = capabilities.snapshot()

    chat_ids = {entry["agent_id"] for entry in snapshot["chat_router_catalog"]}
    registered = set(snapshot["registered_agent_ids"])
    assert chat_ids == {"agent-general", "agent-rnaseq", "agent-atacseq"}

    for flow_id in flow_registry.flows:
        planner = capabilities.agent_for_flow(flow_id)
        assert planner is not None
        assert planner in registered, f"{flow_id} 路由目标 {planner} 未登记"
        assert planner in chat_ids, f"{flow_id} 路由目标 {planner} 不在 chat 候选集"

    route = infer_intent_route(
        "帮我分析一批 RNA-seq 数据",
        flow_registry=flow_registry,
        capability_registry=capabilities,
        domain_registry=_Domains(),
    )
    assert route is not None
    assert route.lead_planner == capabilities.agent_for_flow("rnaseq")
    assert route.lead_planner in chat_ids


@pytest.mark.unit
def test_flow_catalog_in_snapshot_matches_room_router_source(tmp_path) -> None:
    """chat prompt 注入的 flow 目录与房间关键词路由读取的是同一 FlowRegistry。"""
    flow_registry, capabilities = _build_registry(tmp_path)
    snapshot = capabilities.snapshot()

    flow_catalog = {item["flow_id"]: item for item in snapshot["flow_router_catalog"]}
    assert sorted(flow_catalog) == sorted(flow_registry.flows)
    for flow_id, registered in flow_registry.flows.items():
        meta = registered.definition.flow
        assert flow_catalog[flow_id]["bridge_workflow"] == meta.bridge_workflow
        assert flow_catalog[flow_id]["trigger_hints"] == list(meta.trigger_hints)


@pytest.mark.unit
def test_unregistered_flow_actor_degrades_to_registered_fallback(tmp_path) -> None:
    """flow actor 未登记时,房间路由落到注册表内 fallback(agent-general),ghost 不进任何候选。"""
    flow_registry, capabilities = _build_registry(
        tmp_path,
        flows=[("ghostflow", "agent-ghost", "ghost_wf", "幽灵流程")],
        agents=[_agent("agent-general"), _agent("agent-rnaseq")],
    )
    snapshot = capabilities.snapshot()
    chat_ids = {entry["agent_id"] for entry in snapshot["chat_router_catalog"]}
    registered = set(snapshot["registered_agent_ids"])

    assert "agent-ghost" not in chat_ids
    assert "agent-ghost" not in registered

    planner = capabilities.agent_for_flow("ghostflow")
    assert planner == "agent-general"  # 统一 fallback,且已登记
    assert planner in chat_ids

    explanation = explain_intent_route(
        "帮我跑一下幽灵流程",
        flow_registry=flow_registry,
        capability_registry=capabilities,
        domain_registry=_Domains(),
    )
    assert explanation.winner is not None
    assert explanation.winner.lead_planner == "agent-general"
    assert explanation.blocked == ()


@pytest.mark.unit
def test_flow_without_any_registered_agent_blocked(tmp_path) -> None:
    """fallback 链穷尽时命中流程进 blocked(统一 fallback 由调用方兜底),不产生未登记路由。"""
    flow_registry, capabilities = _build_registry(
        tmp_path,
        flows=[("ghostflow", "agent-ghost", "ghost_wf", "幽灵流程")],
        agents=[_agent("agent-code")],  # 无 agent-general/agent-omics 可兜底
    )
    assert capabilities.agent_for_flow("ghostflow") is None

    explanation = explain_intent_route(
        "帮我跑一下幽灵流程",
        flow_registry=flow_registry,
        capability_registry=capabilities,
        domain_registry=_Domains(),
    )
    assert explanation.winner is None
    assert [item.flow_id for item in explanation.blocked] == ["ghostflow"]
    assert (
        infer_intent_route(
            "帮我跑一下幽灵流程",
            flow_registry=flow_registry,
            capability_registry=capabilities,
            domain_registry=_Domains(),
        )
        is None
    )


@pytest.mark.unit
def test_domain_alias_targeting_unknown_flow_ignored(tmp_path) -> None:
    """domains routing.flow_aliases 指向未登记 flow 时被忽略,不影响已登记流程路由。"""
    flow_registry, capabilities = _build_registry(tmp_path)
    domains = _Domains(flow_aliases={"ghostflow": ("幽灵关键词",)})
    explanation = explain_intent_route(
        "帮我看看幽灵关键词和 RNA-seq",
        flow_registry=flow_registry,
        capability_registry=capabilities,
        domain_registry=domains,
    )
    assert explanation.winner is not None
    assert explanation.winner.flow_id == "rnaseq"


@pytest.mark.unit
def test_chat_catalog_filters_router_and_chat_entry_false(tmp_path) -> None:
    """chat 候选过滤:features.router 与能力目录 chat_entry=false 均不进目录。"""
    _, capabilities = _build_registry(
        tmp_path,
        agents=[
            _agent("agent-general"),
            _agent("agent-rnaseq", name="RNA-seq 分析师"),
            _agent("agent-router", router=True),
            _agent("agent-atacseq"),
        ],
        abilities=_Abilities(
            {
                "agent-rnaseq": {
                    "summary": "Bulk RNA-seq 专家",
                    "capabilities": ["差异表达"],
                    "chat_entry": True,
                },
                "agent-atacseq": {"summary": "内部角色", "chat_entry": False},
            }
        ),
    )
    catalog = {entry["agent_id"]: entry for entry in capabilities.snapshot()["chat_router_catalog"]}

    assert set(catalog) == {"agent-general", "agent-rnaseq"}
    entry = catalog["agent-rnaseq"]
    assert entry["description"] == "Bulk RNA-seq 专家"  # 能力描述来自 agent_ability.yaml
    assert entry["capabilities"] == ["差异表达"]
    assert entry["name"] == "RNA-seq 分析师"
    for key in (
        "category",
        "chat_entry",
        "not_suitable_for",
        "handoff_when",
        "preferred_inputs",
        "routing_hints",
        "capability_tags",
        "routing_notes",
        "avatar",
        "color",
    ):
        assert key in entry


@pytest.mark.unit
def test_snapshot_is_single_cached_source_for_both_routes(tmp_path) -> None:
    """TTL 内 snapshot() 返回同一缓存对象:两路由消费同一份数据,无第二份清单。"""
    _, capabilities = _build_registry(tmp_path)
    first = capabilities.snapshot()
    second = capabilities.snapshot()
    assert first is second
    assert "chat_router_catalog" in first
    assert "flow_router_catalog" in first


@pytest.mark.unit
def test_real_yaml_flow_trigger_hints_targets_all_registered() -> None:
    """真实 data/ai/*.yaml 对账:每个 flow 的 trigger_hints 路由目标都在注册表与 chat 候选内。"""
    capabilities = AgentTeamsCapabilityRegistry()
    snapshot = capabilities.snapshot()
    flow_registry = capabilities._flows()

    chat_ids = {entry["agent_id"] for entry in snapshot["chat_router_catalog"]}
    registered = set(snapshot["registered_agent_ids"])
    assert flow_registry.flows, "flows 目录不应为空"
    for flow_id in flow_registry.flows:
        planner = capabilities.agent_for_flow(flow_id)
        assert planner is not None, f"flow={flow_id} 无可用路由目标"
        assert planner in registered, f"flow={flow_id} 路由目标 {planner} 未登记"
        assert planner in chat_ids, f"flow={flow_id} 路由目标 {planner} 不在 chat 候选集"

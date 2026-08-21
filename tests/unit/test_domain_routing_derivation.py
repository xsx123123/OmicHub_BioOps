"""阶段 3 配置化收敛测试:O4 关键词派生注册 + O7 fallback 链与"等待资源"外显。

验收口径:
- 新增一个 domain yaml(不改任何 .py),意图路由与 Planner 评分同时生效;
- 停用某 agent 后任务自动落到 fallback 实例,全链不可用时路由决策卡提示等待资源。
"""

from __future__ import annotations

from omichub.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)
from omichub.application.services.agentteams_intent_router import infer_intent_route
from omichub.application.services.agentteams_route_decision import build_route_decision
from omichub.application.services.domain_registry import DomainRegistry
from omichub.application.services.flow_registry import FlowRegistry
from omichub.application.services.overdrive_planning_service import (
    OverdrivePlanningService,
    get_domain_hints,
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


class _Abilities:
    def __init__(self, agent_ids: set[str]) -> None:
        self._agent_ids = agent_ids

    def all(self) -> dict[str, dict]:
        return {agent_id: {} for agent_id in self._agent_ids}


def _agent(
    agent_id: str, *, is_active: bool = True, fallbacks: list[str] | None = None
) -> dict:
    agentteams: dict = {
        "category": "expert",
        "recruitable": True,
        "planner_eligible": True,
        "execution_modes": ["readonly_consultation"],
    }
    if fallbacks:
        agentteams["fallback_agents"] = fallbacks
    config = {
        "agent_id": agent_id,
        "name": agent_id,
        "features": {
            "internal_case_role": agent_id,
            "agentteams": agentteams,
            "persona": {"status_lines": _STATUS_LINES},
        },
    }
    if not is_active:
        config["is_active"] = False
    return config


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


def _write_flow(flows_dir, flow_id: str, actor: str, hints: str) -> None:
    (flows_dir / f"{flow_id}.yaml").write_text(
        f"""flow:
  id: {flow_id}
  version: 1.0.0
  display_name: {flow_id} 流程
  domain: {flow_id}
  actor: {actor}
  runtime_image: analysis-core
  bridge_workflow: {flow_id}_wf
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


def _write_domain(
    domains_dir,
    domain: str,
    markers: list[str],
    *,
    planner_agent: str | None = None,
    flow_aliases: list[str] | None = None,
) -> None:
    routing_lines = ""
    if planner_agent or flow_aliases:
        routing_lines = "routing:\n"
        if planner_agent:
            routing_lines += f"  planner_agent: {planner_agent}\n"
        if flow_aliases:
            routing_lines += f"  flow_aliases: [{', '.join(flow_aliases)}]\n"
    (domains_dir / f"{domain}.yaml").write_text(
        f"""domain: {domain}
version: 1
display_name: {domain}
match:
  domain_markers: [{', '.join(markers)}]
{routing_lines}""",
        encoding="utf-8",
    )


# ---------------------------------------------------------------- O4 派生注册


def test_new_domain_yaml_drives_planner_scoring_without_code_change(tmp_path) -> None:
    """新增 domain yaml(不改 .py)后,Planner 评分表派生出该域关键词。"""
    domains_dir = tmp_path / "domains"
    domains_dir.mkdir()
    _write_domain(domains_dir, "fab", ["晶圆良率", "wafer"], planner_agent="agent-fab")
    registry = DomainRegistry(domains_dir)

    hints = get_domain_hints(registry)

    assert "晶圆良率" in hints["agent-fab"]
    catalog = [
        {"agent_id": "agent-fab", "is_active": True, "features": {}},
        {"agent_id": "agent-general", "is_active": True, "features": {}},
    ]
    decision = OverdrivePlanningService.select_lead_planner(
        "帮我看看这批晶圆良率数据", catalog, domain_registry=registry
    )
    assert decision["lead_planner_agent_id"] == "agent-fab"
    assert "晶圆良率" in decision["matched_capabilities"]


def test_new_domain_yaml_drives_intent_routing_without_code_change(tmp_path) -> None:
    """domain yaml 的 routing.flow_aliases 派生为意图路由别名,无需改 .py。"""
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    _write_shared(flows_dir)
    _write_flow(flows_dir, "fabreport", "agent-fab", "FabReport")
    domains_dir = tmp_path / "domains"
    domains_dir.mkdir()
    _write_domain(
        domains_dir, "fab", ["晶圆良率"], planner_agent="agent-fab", flow_aliases=["fabreport"]
    )
    flow_registry = FlowRegistry.from_directory(flows_dir)
    domain_registry = DomainRegistry(domains_dir)
    capabilities = AgentTeamsCapabilityRegistry(flow_registry, _Abilities({"agent-fab"}), [_agent("agent-fab")])

    route = infer_intent_route(
        "帮我汇总这个月晶圆良率",
        flow_registry=flow_registry,
        capability_registry=capabilities,
        domain_registry=domain_registry,
    )

    assert route is not None
    assert route.flow_id == "fabreport_wf"
    assert route.lead_planner == "agent-fab"
    # 没有 domain 派生别名时同一文本不命中(trigger_hints 只有 FabReport)。
    empty_domains = tmp_path / "empty_domains"
    empty_domains.mkdir()
    assert (
        infer_intent_route(
            "帮我汇总这个月晶圆良率",
            flow_registry=flow_registry,
            capability_registry=capabilities,
            domain_registry=DomainRegistry(empty_domains),
        )
        is None
    )


def test_legacy_hardcoded_tables_remain_fallback(tmp_path) -> None:
    """迁移期兼容:registry 未派生的 agent 仍由遗留硬编码表兜底。"""
    empty_domains = tmp_path / "domains"
    empty_domains.mkdir()
    hints = get_domain_hints(DomainRegistry(empty_domains))
    assert "转录组" in hints["agent-rnaseq"]


# ---------------------------------------------------------------- O7 fallback 链


def test_resolve_agent_falls_back_to_first_available_instance() -> None:
    agents = [
        _agent("agent-qc", fallbacks=["agent-qc-backup"]),
        _agent("agent-qc-backup"),
    ]
    registry = AgentTeamsCapabilityRegistry(None, _Abilities(set()), agents)
    assert registry.resolve_agent("agent-qc") == "agent-qc"
    assert registry.resolve_agent_chain("agent-qc") == ("agent-qc", "agent-qc-backup")

    degraded = AgentTeamsCapabilityRegistry(
        None,
        _Abilities(set()),
        [_agent("agent-qc", is_active=False, fallbacks=["agent-qc-backup"]), _agent("agent-qc-backup")],
    )
    assert degraded.resolve_agent("agent-qc") == "agent-qc-backup"
    # 别名身份同样走 fallback 链。
    assert degraded.resolve_agent("quality-auditor") == "agent-qc-backup"

    exhausted = AgentTeamsCapabilityRegistry(
        None,
        _Abilities(set()),
        [
            _agent("agent-qc", is_active=False, fallbacks=["agent-qc-backup"]),
            _agent("agent-qc-backup", is_active=False),
        ],
    )
    assert exhausted.resolve_agent("agent-qc") is None


def test_flow_actor_uses_declared_fallback_before_legacy_general(tmp_path) -> None:
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    _write_shared(flows_dir)
    _write_flow(flows_dir, "rnaseq", "agent-rnaseq", "RNA-seq")
    flow_registry = FlowRegistry.from_directory(flows_dir)
    agents = [
        _agent("agent-rnaseq", is_active=False, fallbacks=["agent-omics-cover"]),
        _agent("agent-omics-cover"),
        _agent("agent-general"),
    ]
    registry = AgentTeamsCapabilityRegistry(
        flow_registry, _Abilities({"agent-omics-cover", "agent-general"}), agents
    )

    # 声明的 fallback 优先于历史兜底 agent-general。
    assert registry.agent_for_flow("rnaseq") == "agent-omics-cover"


def test_route_decision_marks_waiting_when_fallback_chain_exhausted(tmp_path) -> None:
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    _write_shared(flows_dir)
    _write_flow(flows_dir, "rnaseq", "agent-rnaseq", "RNA-seq")
    flow_registry = FlowRegistry.from_directory(flows_dir)
    capabilities = AgentTeamsCapabilityRegistry(
        flow_registry,
        _Abilities(set()),
        [_agent("agent-rnaseq", is_active=False)],
    )

    decision = build_route_decision(
        "帮我进行rna-seq分析", flow_registry=flow_registry, capability_registry=capabilities
    )

    assert decision is not None
    assert decision["flow_id"] is None  # 无可用 Agent,流程不进入候选
    assert decision["resource_status"] == "waiting"
    assert "等待资源" in decision["resource_notice"]
    assert "rnaseq" in decision["resource_notice"]
    waiting_options = [
        option for option in decision["options"] if option.get("resource_status") == "waiting"
    ]
    assert [option["flow_id"] for option in waiting_options] == ["rnaseq"]


def test_route_decision_marks_degraded_when_actor_resolved_via_fallback(tmp_path) -> None:
    flows_dir = tmp_path / "flows"
    flows_dir.mkdir()
    _write_shared(flows_dir)
    _write_flow(flows_dir, "rnaseq", "agent-rnaseq", "RNA-seq")
    flow_registry = FlowRegistry.from_directory(flows_dir)
    capabilities = AgentTeamsCapabilityRegistry(
        flow_registry,
        _Abilities({"agent-general"}),
        [_agent("agent-rnaseq", is_active=False), _agent("agent-general")],
    )

    decision = build_route_decision(
        "帮我进行rna-seq分析", flow_registry=flow_registry, capability_registry=capabilities
    )

    assert decision is not None
    assert decision["path"] == "bridge_workflow"
    assert decision["lead_planner"] == "agent-general"
    assert decision["resource_status"] == "degraded"
    assert "agent-rnaseq" in decision["resource_notice"]

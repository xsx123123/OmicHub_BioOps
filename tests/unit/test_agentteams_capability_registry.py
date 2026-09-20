from __future__ import annotations

from pathlib import Path

import yaml

from cygnusx.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)
from cygnusx.application.services.flow_registry import FlowRegistry
from cygnusx.infrastructure.config.agent_loader import load_agent_configs


class _Abilities:
    def all(self):
        return {"agent-code": {}, "agent-qc": {}}

    def render_detail(self, agent_id: str) -> str:
        return f"### {agent_id}\n能力：代码实现"


def _features(role: str, *, recruitable: bool = True) -> dict:
    return {
        "internal_case_role": role,
        "agentteams": {
            "category": "expert" if recruitable else "router",
            "recruitable": recruitable,
            "planner_eligible": False,
            "execution_modes": ["readonly_consultation"] if recruitable else [],
            "max_parallel_work_items": 1 if recruitable else 0,
            "case_mode_excluded_tool_packs": ["subagents"],
            "handoff_in_case_mode": False,
            "work_item_timeout_sec": 300 if recruitable else 0,
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


def test_registry_discovers_flow_roles_and_worker_profiles(tmp_path) -> None:
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
    (flows_dir / "test_general.yaml").write_text(
        """flow:
  id: test_general
  version: 1.0.0
  display_name: Test General
  domain: general
  actor: agent-code
  runtime_image: analysis-core
  bridge_workflow: test_general
artifacts:
  - {key: result, type: table}
stages:
  - key: transform
    title: Transform
    executors:
      - {key: transform, queue: general, resource_profile: standard, outputs: [result], retry_policy: bounded}
delivery: {quality_gate: true, outputs: [result]}
""",
        encoding="utf-8",
    )
    registry = AgentTeamsCapabilityRegistry(
        FlowRegistry.from_directory(flows_dir),
        _Abilities(),
        [
            {
                "agent_id": "agent-code",
                "name": "Code",
                "features": _features("agent-code"),
            },
            {
                "agent_id": "agent-qc",
                "name": "QC",
                "features": _features("agent-qc"),
            },
            {
                "agent_id": "agent-disabled",
                "is_active": False,
                "features": _features("disabled"),
            },
        ],
    )

    assert registry.allowed_flow_ids() == {"test_general"}
    assert registry.role_agent_map() == {"agent-code": "agent-code", "agent-qc": "agent-qc"}
    assert registry.role_alias_map() == {"quality-auditor": "agent-qc"}
    assert registry.consultation_agents() == {"agent-code", "agent-qc"}
    assert registry.flow_agent_map() == {"test_general": "agent-code"}
    assert registry.flow_quality_gate_map() == {"test_general": True}
    assert registry.agent_for_flow("test_general") == "agent-code"
    assert registry.worker_profile("agent-code").capability == "planning_advice"


def test_router_catalog_carries_configured_persona_summary(tmp_path) -> None:
    registry = AgentTeamsCapabilityRegistry(
        FlowRegistry.from_directory(tmp_path),
        _Abilities(),
        [
            {
                "agent_id": "agent-code",
                "name": "Code",
                "description": "Code",
                "category": "code",
                "features": {
                    **_features("agent-code"),
                    "persona": {
                        "archetype": "务实的工程师",
                        "traits": ["严谨", "可复现"],
                        "working_style": "先复现再修改",
                        "status_lines": _features("agent-code")["persona"]["status_lines"],
                    },
                },
            }
        ],
    )

    entry = registry.chat_router_catalog()[0]
    assert entry["persona"]["archetype"] == "务实的工程师"
    assert entry["persona"]["traits"] == ["严谨", "可复现"]
    assert "status_lines" not in entry["persona"]


def test_router_catalog_carries_compact_role_scope(tmp_path) -> None:
    registry = AgentTeamsCapabilityRegistry(
        FlowRegistry.from_directory(tmp_path),
        _Abilities(),
        [
            {
                "agent_id": "agent-viz",
                "name": "Visualization",
                "category": "visualization",
                "features": {
                    **_features("agent-viz"),
                    "default_role": "生成出版级图形",
                    "capability_scope": ["统计图表", "火山图"],
                },
            }
        ],
    )

    entry = registry.chat_router_catalog()[0]
    assert entry["default_role"] == "生成出版级图形"
    assert entry["capability_scope"] == ["统计图表", "火山图"]


def test_capability_detail_context_carries_selected_agent_persona(tmp_path) -> None:
    features = _features("agent-code")
    features["persona"].update(
        {
            "archetype": "务实的工程师",
            "traits": ["严谨", "可复现"],
            "working_style": "先复现再修改",
        }
    )
    registry = AgentTeamsCapabilityRegistry(
        FlowRegistry.from_directory(tmp_path),
        _Abilities(),
        [{"agent_id": "agent-code", "features": features}],
    )

    detail = registry.capability_detail_context(["agent-code"])
    assert "Persona：" in detail
    assert "角色原型：务实的工程师" in detail
    assert "稳定特质：严谨、可复现" in detail


def test_registry_rejects_flow_without_active_actor(tmp_path) -> None:
    registry = AgentTeamsCapabilityRegistry(FlowRegistry.from_directory(tmp_path), _Abilities(), [])
    assert registry.agent_for_flow("missing") is None


def test_registry_falls_back_to_general_agent_when_flow_actor_is_missing(tmp_path) -> None:
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
    (flows_dir / "fallback.yaml").write_text(
        """flow:
  id: fallback
  version: 1.0.0
  display_name: Fallback
  domain: general
  actor: agent-missing
  runtime_image: analysis-core
  bridge_workflow: fallback
artifacts: [{key: result, type: table}]
stages:
  - key: run
    title: Run
    executors: [{key: run, queue: general, resource_profile: standard, outputs: [result], retry_policy: bounded}]
delivery: {quality_gate: true, outputs: [result]}
""",
        encoding="utf-8",
    )
    registry = AgentTeamsCapabilityRegistry(
        FlowRegistry.from_directory(flows_dir),
        _Abilities(),
        [{"agent_id": "agent-general", "features": _features("agent-general")}],
    )

    assert registry.agent_for_flow("fallback") == "agent-general"


def test_registry_covers_fifteen_recruitable_experts() -> None:
    registry = AgentTeamsCapabilityRegistry(agent_configs=load_agent_configs())

    role_map = registry.role_agent_map()
    capabilities = registry.agent_capabilities()

    # 15 个可招募专家 + 1 个不可招募的协作室 Manager（bioops-manager）。
    assert len(role_map) == 16
    assert sum(item["recruitable"] for item in capabilities.values()) == 15
    # agent-router 与 shania 是路由/人设型 agent，不参与 Case 执行。
    assert "agent-router" not in role_map
    assert "shania" not in role_map
    # Manager 人格分层：独立 agent，显式不可招募、保持 planner 入口能力，
    # 不进可招募会诊集合，但可作为内部会诊对象（房间 Manager 回路）。
    manager = capabilities["bioops-manager"]
    assert manager["agent_id"] == "agentteams-manager"
    assert manager["recruitable"] is False
    assert manager["planner_eligible"] is True
    assert "agentteams-manager" not in registry.consultation_agents()
    assert "agentteams-manager" in registry.internal_consultation_agents()
    assert registry.role_alias_map() == {
        "data-steward": "agent-data",
        "quality-auditor": "agent-qc",
        "delivery-reporter": "agent-delivery",
    }
    assert registry.resolve_agent("data-steward") == "agent-data"
    assert registry.resolve_agent("agent-scrna-integration") == "agent-scrna-integration"


def test_registry_rejects_incomplete_agentteams_declaration(tmp_path) -> None:
    registry = AgentTeamsCapabilityRegistry(
        FlowRegistry.from_directory(tmp_path),
        _Abilities(),
        [{"agent_id": "agent-broken", "features": {"internal_case_role": "agent-broken"}}],
    )

    try:
        registry.role_agent_map()
    except ValueError as exc:
        assert "features.agentteams" in str(exc)
    else:
        raise AssertionError("incomplete AgentTeams declarations must fail fast")


def test_agentteams_team_manifest_contains_all_recruitable_experts() -> None:
    registry = AgentTeamsCapabilityRegistry(agent_configs=load_agent_configs())
    manifest = yaml.safe_load(
        Path("integrations/agentteams/teams/bioops-delivery.yaml").read_text(encoding="utf-8")
    )
    worker_ids = {worker["identity"] for worker in manifest["workers"]}
    recruitable_ids = {
        agent_id
        for agent_id, capability in registry.agent_capabilities().items()
        if capability["recruitable"]
    }

    assert len(recruitable_ids) == 15
    assert worker_ids == recruitable_ids | {"workflow-operator"}


def test_room_consultation_catalog_includes_internal_staff_without_chat_entry(tmp_path) -> None:
    """chat_entry:false 的内部员工不进 chat 侧对外路由目录，但仍是房间会诊候选。"""

    class _ChatEntryAbilities:
        def all(self):
            return {
                "agent-code": {"summary": "代码实现"},
                "agent-data": {"summary": "数据预检", "chat_entry": False},
            }

        def render_detail(self, agent_id: str) -> str:
            return ""

    registry = AgentTeamsCapabilityRegistry(
        FlowRegistry.from_directory(tmp_path),
        _ChatEntryAbilities(),
        [
            {"agent_id": "agent-code", "name": "Code", "features": _features("agent-code")},
            {"agent_id": "agent-data", "name": "数据管理员", "features": _features("agent-data")},
        ],
    )

    chat_ids = {entry["agent_id"] for entry in registry.chat_router_catalog()}
    room_entries = {entry["agent_id"]: entry for entry in registry.room_consultation_catalog()}
    assert "agent-data" not in chat_ids
    assert set(room_entries) == {"agent-code", "agent-data"}
    assert room_entries["agent-data"]["chat_entry"] is False
    assert room_entries["agent-data"]["name"] == "数据管理员"
    assert room_entries["agent-data"]["description"] == "数据预检"

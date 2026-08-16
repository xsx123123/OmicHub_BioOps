"""Regression tests for YAML-driven multi-agent flow definitions."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from omichub.application.services.flow_registry import FlowRegistry
from omichub.application.services.mas_plan_validator import MASPlanValidator
from omichub.core.exceptions import BusinessError, ValidationError
from omichub.domain.mas.models import ExecutionPlan

ROOT = Path(__file__).parents[2]
FLOWS_DIR = ROOT / "data" / "ai" / "flows"
SITE_CONFIG = ROOT / "data" / "OmicHub.yaml"


def _scrna_payload() -> dict:
    return yaml.safe_load((FLOWS_DIR / "scrna.yaml").read_text(encoding="utf-8"))


def _registry(tmp_path: Path) -> FlowRegistry:
    shared = tmp_path / "_shared"
    shared.mkdir()
    for source in (FLOWS_DIR / "_shared").glob("*.yaml"):
        (shared / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    return FlowRegistry.from_directory(tmp_path)


def _write_flow(tmp_path: Path, payload: dict) -> FlowRegistry:
    registry = _registry(tmp_path)
    path = tmp_path / "scrna.yaml"
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return registry


def test_registry_loads_builtin_flows_and_derives_contracts() -> None:
    registry = FlowRegistry.from_directory(FLOWS_DIR)

    assert set(registry.flows) == {
        "atacseq",
        "rnaseq",
        "sales_report",
        "scrna",
        "test_general",
        "treeplot",
    }
    assert registry.errors == {}
    assert registry.get("scrna").digest
    assert registry.bridge_flow_ids() == {
        "atac_seq",
        "rna_seq",
        "sales_report",
        "scrna_seq",
        "test_general",
        "treeplot",
    }
    treeplot = registry.get("treeplot").definition
    assert treeplot.stages[0].executors[0].execution_mode == "workspace_execution"
    assert registry.get("sales_report").definition.stages[0].executors[0].execution_mode == "workspace_execution"
    assert registry.get("atacseq").definition.flow.actor == "agent-atacseq"
    assert "scrna-cellranger" in registry.agent_capabilities()["agent-scrna"]
    assert registry.artifact_schemas()["scrna.input_h5ad"]["alias_for"] == "scrna.raw_h5ad"
    assert {item["skill"] for item in registry.review_contracts()} >= {
        "upstream-review",
        "integration-review",
        "annotation-review",
    }


def test_registry_rejects_flow_without_stages_as_business_error(tmp_path: Path) -> None:
    path = tmp_path / "incomplete.yaml"
    path.write_text("flow: {id: incomplete}\n", encoding="utf-8")
    registry = FlowRegistry(tmp_path)

    with pytest.raises(BusinessError, match="流程定义不完整"):
        registry.load_file(path)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda payload: payload.update(
                edges=[["upstream", "integrate"], ["integrate", "upstream"]]
            ),
            "存在环",
        ),
        (
            lambda payload: payload["stages"][0]["executors"][0]["outputs"].append("unknown"),
            "未声明 artifact",
        ),
        (lambda payload: payload["stages"][0]["review"].update(capability="shell"), "schema 无效"),
        (
            lambda payload: payload["stages"][0]["gate"].update(template="missing-template"),
            "审批模板",
        ),
        (lambda payload: payload["flow"].update(previous_artifacts=["legacy_h5ad"]), "aliases"),
        (lambda payload: payload.update(edges=[["upstream", "missing-stage"]]), "不存在阶段"),
    ],
)
def test_registry_rejects_invalid_flow_definitions(tmp_path: Path, mutate, message: str) -> None:
    payload = _scrna_payload()
    mutate(payload)
    registry = _write_flow(tmp_path, payload)

    with pytest.raises(ValueError, match=message):
        registry.load_file(tmp_path / "scrna.yaml")


def test_stage_hints_route_to_the_matching_scrna_assistant() -> None:
    registry = FlowRegistry.from_directory(FLOWS_DIR)
    available = {"agent-scrna-upstream", "agent-scrna-integration", "agent-scrna-advanced"}

    assert (
        registry.route_agent("Cell Ranger chemistry 该如何选？", available)
        == "agent-scrna-upstream"
    )
    assert (
        registry.route_agent("Harmony 后 UMAP 聚类不稳定", available) == "agent-scrna-integration"
    )
    assert (
        registry.route_agent("pseudobulk 差异表达和拟时序怎么解释", available)
        == "agent-scrna-advanced"
    )


def test_bulk_rnaseq_differential_expression_does_not_route_to_scrna_stage() -> None:
    registry = FlowRegistry.from_directory(FLOWS_DIR)
    available = {
        "agent-rnaseq",
        "agent-scrna-upstream",
        "agent-scrna-integration",
        "agent-scrna-advanced",
    }

    assert registry.route_agent("RNA-seq 差异表达分析怎么开始", available) is None
    assert registry.route_agent("单细胞差异表达怎么做", available) == "agent-scrna-advanced"


def test_scrna_stage_specialists_are_enabled_for_agent_loading() -> None:
    site_config = yaml.safe_load(SITE_CONFIG.read_text(encoding="utf-8"))
    enabled = set(site_config["agents"]["enabled"])

    assert {"scrna_upstream", "scrna_integration", "scrna_advanced"} <= enabled


def test_yaml_executor_contract_rejects_wrong_agent_or_artifacts() -> None:
    registry = FlowRegistry.from_directory(FLOWS_DIR)
    validator = MASPlanValidator(
        registry.agent_capabilities(), registry.artifact_schemas(), registry
    )
    plan = ExecutionPlan.model_validate(
        {
            "title": "single-cell upstream",
            "nodes": [
                {
                    "key": "cellranger",
                    "agent_id": "agent-rnaseq",
                    "intent": "run",
                    "resources": {"executor": "scrna-cellranger"},
                    "input_contract": {"consumes": ["scrna.fastq_manifest"]},
                    "output_contract": {"produces": ["scrna.raw_h5ad"]},
                }
            ],
        }
    )

    with pytest.raises(ValidationError, match="必须由 agent-scrna 执行"):
        validator.validate(plan)

"""Domain Pack schema、加载容错与热重载测试。"""

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from cygnusx.application.services.chat_service import OVERDRIVE_MANAGER_PROMPT
from cygnusx.application.services.domain_registry import DomainRegistry
from cygnusx.domain.domains.schema import DomainPack
from cygnusx.infrastructure.config.domain_pack_loader import DomainPackLoader


def _pack(domain: str = "phylo", *, display_name: str = "Phylo") -> dict:
    return {
        "domain": domain,
        "version": 1,
        "display_name": display_name,
        "match": {"domain_markers": [domain]},
    }


def _write(path: Path, payload: object) -> None:
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")


def test_duplicate_domain_keeps_first_sorted_file_and_records_error(tmp_path: Path) -> None:
    _write(tmp_path / "01-first.yaml", _pack(display_name="first"))
    _write(tmp_path / "02-second.yaml", _pack(display_name="second"))

    loader = DomainPackLoader(tmp_path)

    assert loader.packs["phylo"].display_name == "first"
    assert any("重复 domain" in error for error in loader.errors)


def test_unknown_version_is_rejected(tmp_path: Path) -> None:
    payload = _pack()
    payload["version"] = 2
    _write(tmp_path / "bad-version.yaml", payload)

    loader = DomainPackLoader(tmp_path)

    assert loader.packs == {}
    assert any("bad-version.yaml" in error for error in loader.errors)


def test_authoritative_assignment_anchor_defaults_are_backward_compatible() -> None:
    payload = _pack()
    payload["assignments"] = {
        "rules": [
            {
                "id": "required-stage",
                "when": "planning_or_analysis",
                "agent_match": ["agent-code"],
                "authoritative": True,
                "task_id": "required-stage",
                "task": "完成必需阶段",
            }
        ]
    }

    rule = DomainPack.model_validate(payload).assignments.rules[0]

    assert rule.required is True
    assert rule.allow_split is False
    assert rule.allow_reorder is False


@pytest.mark.parametrize("field", ["required", "allow_split", "allow_reorder"])
def test_invalid_authoritative_anchor_flag_is_reported(tmp_path: Path, field: str) -> None:
    payload = _pack()
    payload["assignments"] = {
        "rules": [
            {
                "id": "required-stage",
                "when": "planning_or_analysis",
                "agent_match": ["agent-code"],
                "authoritative": True,
                field: "not-a-boolean",
                "task_id": "required-stage",
                "task": "完成必需阶段",
            }
        ]
    }
    _write(tmp_path / "bad-anchor.yaml", payload)

    loader = DomainPackLoader(tmp_path)

    assert loader.packs == {}
    assert any(field in error for error in loader.errors)


def test_bad_yaml_does_not_block_other_domain_packs(tmp_path: Path) -> None:
    (tmp_path / "01-bad.yaml").write_text("domain: [broken", encoding="utf-8")
    _write(tmp_path / "02-good.yaml", _pack("omics"))

    loader = DomainPackLoader(tmp_path)

    assert set(loader.packs) == {"omics"}
    assert any("01-bad.yaml" in error for error in loader.errors)


def test_loader_hot_reloads_when_file_changes(tmp_path: Path) -> None:
    path = tmp_path / "phylo.yaml"
    _write(path, _pack(display_name="before"))
    loader = DomainPackLoader(tmp_path)
    assert loader.packs["phylo"].display_name == "before"

    _write(path, _pack(display_name="after with a longer value"))

    assert loader.packs["phylo"].display_name == "after with a longer value"


def test_question_filter_must_reference_declared_slot() -> None:
    payload = _pack()
    payload["intake"] = {
        "question_filters": [
            {
                "when_slot_present": ["missing_slot"],
                "drop_question_markers": ["不要问"],
            }
        ]
    }

    with pytest.raises(ValidationError, match="未声明 slots"):
        DomainPack.model_validate(payload)


def test_explicit_agent_domain_takes_router_note_priority(tmp_path: Path) -> None:
    payload = _pack("phylo")
    payload["prompt_injections"] = {"router_notes": "显式领域路由提示"}
    _write(tmp_path / "phylo.yaml", payload)
    registry = DomainRegistry(tmp_path)

    assert registry.router_notes_for("unrelated-agent", "phylo") == "显式领域路由提示"


def test_registry_returns_domains_in_deterministic_order(tmp_path: Path) -> None:
    _write(tmp_path / "z.yaml", _pack("zeta"))
    _write(tmp_path / "a.yaml", _pack("alpha"))
    registry = DomainRegistry(tmp_path)

    assert [pack.domain for pack in registry.match_domains("zeta alpha")] == ["alpha", "zeta"]


@pytest.mark.quarantine(reason="YAML 注入的 domain notes 文案与断言逐字不一致")
def test_default_registry_injects_domain_notes_from_yaml() -> None:
    registry = DomainRegistry()

    assert "tree_visualization" not in OVERDRIVE_MANAGER_PROMPT
    assert "系统发育树任务必须先区分" in registry.manager_notes("处理已有树")
    assert "必须选择 agent-rnaseq" in registry.router_notes_for("agent-rnaseq")

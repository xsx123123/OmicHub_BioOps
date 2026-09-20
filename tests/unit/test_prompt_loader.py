from pathlib import Path

import pytest
import yaml

from cygnusx.infrastructure.config.prompt_loader import PromptRegistry


def _registry(tmp_path: Path, content: str, variables: list[str] | None = None) -> PromptRegistry:
    (tmp_path / "sample.md").write_text(content, encoding="utf-8")
    registry = {
        "version": 1,
        "prompts": {
            "sample": {
                "file": "sample.md",
                "kind": "template",
                "owners": ["test"],
                "variables": variables or [],
            }
        },
    }
    path = tmp_path / "registry.yaml"
    path.write_text(yaml.safe_dump(registry), encoding="utf-8")
    return PromptRegistry(path)


def test_prompt_registry_reads_and_renders(tmp_path: Path):
    registry = _registry(tmp_path, "Hello {{name}}", ["name"])
    assert registry.render("sample", name="CygnusX") == "Hello CygnusX"


def test_prompt_registry_rejects_missing_or_unknown_variables(tmp_path: Path):
    registry = _registry(tmp_path, "Hello {{name}}", ["name"])
    with pytest.raises(ValueError, match="缺少变量"):
        registry.render("sample")
    with pytest.raises(ValueError, match="未声明变量"):
        registry.render("sample", name="x", extra="y")


def test_prompt_registry_rejects_path_escape(tmp_path: Path):
    path = tmp_path / "registry.yaml"
    path.write_text(
        yaml.safe_dump({"prompts": {"bad": {"file": "../secret.md", "kind": "system"}}}),
        encoding="utf-8",
    )
    assert PromptRegistry(path).get("bad", "fallback") == "fallback"

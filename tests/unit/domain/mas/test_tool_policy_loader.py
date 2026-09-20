from pathlib import Path

from cygnusx.domain.mas.tool_policy import load_execution_policies


def test_load_execution_policies_fails_closed_for_missing_file(tmp_path: Path) -> None:
    assert load_execution_policies(tmp_path / "missing.yaml") == {}
    path = tmp_path / "policies.yaml"
    path.write_text(
        "policies:\n  - tool_key: plot.deg_volcano\n    allowed_images: [cygnusx/analysis-plot:latest]\n    allowed_write_roots: [/workspace/plots]\n"
    )
    assert "plot.deg_volcano" in load_execution_policies(path)

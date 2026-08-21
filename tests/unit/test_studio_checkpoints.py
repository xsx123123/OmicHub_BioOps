"""Studio 工作区检查点测试。"""

from pathlib import Path

import pytest

from omichub.application.services import studio_checkpoints


@pytest.mark.unit
def test_checkpoint_commit_list_and_restore(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace = tmp_path / "session"
    monkeypatch.setattr(
        studio_checkpoints.studio_sandbox_manager,
        "workspace_dir",
        lambda _session_id: workspace,
    )

    studio_checkpoints.ensure_checkpoint_repository("session")
    (workspace / "result.txt").write_text("one", encoding="utf-8")
    first = studio_checkpoints.create_checkpoint("session", "tc-1")
    (workspace / "result.txt").write_text("two", encoding="utf-8")
    second = studio_checkpoints.create_checkpoint("session", "tc-2")

    assert first["checkpoint_id"] != second["checkpoint_id"]
    assert len(studio_checkpoints.list_checkpoints("session")) == 2

    studio_checkpoints.restore_checkpoint("session", first["checkpoint_id"])
    assert (workspace / "result.txt").read_text(encoding="utf-8") == "one"


@pytest.mark.unit
def test_checkpoint_excludes_input_and_records_large_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace = tmp_path / "session"
    monkeypatch.setattr(
        studio_checkpoints.studio_sandbox_manager,
        "workspace_dir",
        lambda _session_id: workspace,
    )
    studio_checkpoints.ensure_checkpoint_repository("session")
    (workspace / "input").mkdir()
    (workspace / "input" / "mounted.txt").write_text("mounted", encoding="utf-8")
    large = workspace / "large.bin"
    with large.open("wb") as handle:
        handle.truncate(10 * 1024 * 1024 + 1)

    checkpoint = studio_checkpoints.create_checkpoint("session", "tc-large")

    assert "large.bin" in checkpoint["skipped"]
    assert "input/mounted.txt" not in checkpoint["skipped"]


@pytest.mark.unit
def test_checkpoint_retention_keeps_latest_twenty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace = tmp_path / "session"
    monkeypatch.setattr(
        studio_checkpoints.studio_sandbox_manager,
        "workspace_dir",
        lambda _session_id: workspace,
    )

    for index in range(22):
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "report.txt").write_text(str(index), encoding="utf-8")
        studio_checkpoints.create_checkpoint("session", f"tool-{index}")

    checkpoints = studio_checkpoints.list_checkpoints("session")

    assert len(checkpoints) == 20
    assert {item["tool_call_id"] for item in checkpoints} == {
        f"tool-{index}" for index in range(2, 22)
    }

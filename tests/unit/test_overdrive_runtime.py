from __future__ import annotations

import json

from omichub.application.services.overdrive_runtime import (
    OverdriveManifest,
    assignment_waves,
    build_upstream_context,
    infer_contract_dependencies,
)


def test_contract_dependency_is_inferred_only_for_unique_producer() -> None:
    assignments = [
        {"task_id": "bulk", "depends_on": [], "accepts_inputs": [], "produces_outputs": ["table"]},
        {"task_id": "scrna", "depends_on": [], "accepts_inputs": [], "produces_outputs": ["cells"]},
        {"task_id": "viz", "depends_on": [], "accepts_inputs": ["table"], "produces_outputs": []},
    ]
    inferred = infer_contract_dependencies(assignments)
    assert inferred[1]["depends_on"] == []
    assert inferred[2]["depends_on"] == ["bulk"]


def test_wave_limit_and_cycle_warning() -> None:
    independent = [{"task_id": f"t{i}", "depends_on": []} for i in range(5)]
    waves, warnings = assignment_waves(independent, max_parallel=4)
    assert [len(wave) for wave in waves] == [4, 1]
    assert warnings == []

    cyclic = [
        {"task_id": "a", "depends_on": ["b"]},
        {"task_id": "b", "depends_on": ["a"]},
    ]
    _, warnings = assignment_waves(cyclic, max_parallel=4)
    assert warnings and "循环依赖" in warnings[0]


def test_manifest_artifacts_are_atomic_and_resume_running(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "omichub.application.services.overdrive_runtime.overdrive_root",
        lambda _session_id: tmp_path / "output" / "overdrive" / "session-1",
    )
    manifest = OverdriveManifest("session-1")
    assignments = [{"task_id": "a", "agent_id": "agent-a", "task": "分析", "depends_on": []}]
    manifest.initialize(run_id="run-1", request="same", assignments=assignments)
    manifest.update_task("a", "running")
    manifest.write_artifacts("a", "正文\n\n## 执行摘要\n精简摘要", 1500)

    resumed = manifest.initialize(run_id="run-2", request="same", assignments=assignments)
    assert resumed["run_id"] == "run-1"
    assert resumed["tasks"][0]["status"] == "ready"
    assert manifest.read_summary("a", 1500) == "精简摘要\n"
    assert json.loads(manifest.path.read_text(encoding="utf-8"))["tasks"][0]["task_id"] == "a"
    assert not list(manifest.root.rglob("*.tmp"))


def test_upstream_context_contains_summary_paths_not_full_result(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        "omichub.application.services.overdrive_runtime.overdrive_root",
        lambda _session_id: tmp_path / "output" / "overdrive" / "session-1",
    )
    manifest = OverdriveManifest("session-1")
    manifest.initialize(
        run_id="run-1",
        request="request",
        assignments=[{"task_id": "a", "agent_id": "agent-a", "task": "分析", "depends_on": []}],
    )
    full = "FULL-SECRET-DETAIL " * 2000 + "\n\n## 执行摘要\n仅注入摘要"
    manifest.write_artifacts("a", full, 1500)
    context = build_upstream_context(manifest, ["a"], summary_chars=1500, total_chars=8000)
    assert "仅注入摘要" in context
    assert "FULL-SECRET-DETAIL" not in context
    assert "tasks/a/result.md" in context
    assert "manifest.json" in context

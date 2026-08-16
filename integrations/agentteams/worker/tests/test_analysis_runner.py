from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(MODULE_DIR))
SPEC = importlib.util.spec_from_file_location("agentteams_analysis_runner", MODULE_DIR / "analysis_runner.py")
assert SPEC and SPEC.loader
analysis_runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analysis_runner
SPEC.loader.exec_module(analysis_runner)


def test_analysis_runner_requires_analysis_identity() -> None:
    try:
        analysis_runner.load_config(
            {
                "AGENTTEAMS_BRIDGE_BASE_URL": "http://bridge/v1",
                "AGENTTEAMS_BRIDGE_TOKEN": "token",
                "AGENTTEAMS_WORKER_IDENTITY": "workflow-operator",
            }
        )
    except ValueError as exc:
        assert "analysis-worker" in str(exc)
    else:
        raise AssertionError("analysis runtime accepted another identity")


def test_analysis_runner_claims_and_submits_bridge_owned_snapshot(monkeypatch) -> None:
    calls: list[str] = []
    assignment = {"case_id": "case-1", "work_item": {"work_item_id": "submit-01"}}
    monkeypatch.setattr(
        analysis_runner,
        "claim_next",
        lambda *_args, dry_run=False, **_kwargs: calls.append("preview" if dry_run else "claim")
        or {"assignment": assignment},
    )
    monkeypatch.setattr(
        analysis_runner,
        "heartbeat_work_item",
        lambda *_args, **_kwargs: calls.append("heartbeat") or {},
    )
    monkeypatch.setattr(
        analysis_runner,
        "submit_approved_work_item",
        lambda *_args, **_kwargs: calls.append("submit") or {"omic_task_id": "task-1", "status": "pending"},
    )

    result = analysis_runner.run_once(
        analysis_runner.AnalysisWorkerConfig("http://bridge/v1", "analysis-token", 1)
    )

    assert calls == ["preview", "claim", "heartbeat", "submit"]
    assert result == {
        "action": "submitted",
        "identity": "analysis-worker",
        "case_id": "case-1",
        "work_item_id": "submit-01",
        "task_id": "task-1",
        "status": "pending",
    }

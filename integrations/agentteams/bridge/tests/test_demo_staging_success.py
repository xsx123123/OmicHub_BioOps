"""Regression coverage for the documented staging-success demo sequence."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any


_DEMO_PATH = Path(__file__).parents[2] / "demo" / "run_bridge_demo.py"
_SPEC = importlib.util.spec_from_file_location("agentteams_demo", _DEMO_PATH)
assert _SPEC and _SPEC.loader
demo_module = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = demo_module
_SPEC.loader.exec_module(demo_module)


class FakeDemo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, str, dict[str, Any] | None]] = []

    def request(
        self, method: str, path: str, identity: str, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        self.calls.append((method, path, identity, payload))
        if path == "/v1/approvals":
            return {"token": "approved-token"}
        if path == "/v1/tasks":
            return {"omic_task_id": "task-001"}
        if path.endswith("/reconcile"):
            return {"work_items": [{"work_item_id": "interpret-01"}]}
        if path.endswith("/execute-readonly"):
            return {"status": "completed"}
        if path.endswith("/close"):
            return {"status": "closed", "manifest": {"task_ids": ["task-001"]}}
        return {"status": "passed"}


def test_staging_success_runs_submission_interpretation_quality_and_delivery(monkeypatch) -> None:
    demo = FakeDemo()
    monkeypatch.setattr(
        demo_module,
        "wait_for_task",
        lambda *_args, **_kwargs: {"id": "task-001", "status": "success"},
    )

    demo_module.run_staging_success(
        demo,
        "demo-case",
        {
            "flow_id": "rna_seq",
            "name": "staging-rna",
            "sample_sheet": [{"sample": "S01", "group": "control"}],
        },
        timeout=1,
    )

    assert [path for _, path, _, _ in demo.calls] == [
        "/v1/approvals",
        "/v1/cases/demo-case/work-items",
        "/v1/tasks",
        "/v1/cases/demo-case/reconcile",
        "/v1/cases/demo-case/work-items/interpret-01/claim",
        "/v1/cases/demo-case/work-items/interpret-01/execute-readonly",
        "/v1/cases/demo-case/work-items",
        "/v1/tasks/task-001/quality-gate",
        "/v1/cases/demo-case/close",
    ]
    assert demo.calls[5][2] == "agent-rnaseq"
    assert demo.calls[-1][3] == {"case_id": "demo-case", "quality_decision": "passed"}

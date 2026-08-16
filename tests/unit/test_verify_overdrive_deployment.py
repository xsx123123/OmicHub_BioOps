from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).parents[2] / "scripts" / "verify_overdrive_deployment.py"
SPEC = importlib.util.spec_from_file_location("verify_overdrive_deployment", MODULE_PATH)
assert SPEC and SPEC.loader
verification = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verification
SPEC.loader.exec_module(verification)


def test_require_qc_evidence_accepts_independent_review_with_contiguous_events() -> None:
    verification.require_qc_evidence(
        {
            "qc_task_present": True,
            "qc_has_dependencies": True,
            "qc_result_events": 1,
            "qc_review_events": 1,
            "event_count": 8,
            "last_sequence": 8,
            "qc_answer": "已完成独立检查。质量结论：通过",
        }
    )


@pytest.mark.parametrize(
    "state",
    [
        {"qc_task_present": False, "qc_has_dependencies": True, "qc_result_events": 1, "qc_review_events": 1, "event_count": 1, "last_sequence": 1, "qc_answer": "质量结论：通过"},
        {"qc_task_present": True, "qc_has_dependencies": True, "qc_result_events": 0, "qc_review_events": 1, "event_count": 1, "last_sequence": 1, "qc_answer": "质量结论：通过"},
        {"qc_task_present": True, "qc_has_dependencies": True, "qc_result_events": 1, "qc_review_events": 1, "event_count": 2, "last_sequence": 3, "qc_answer": "质量结论：通过"},
        {"qc_task_present": True, "qc_has_dependencies": True, "qc_result_events": 1, "qc_review_events": 1, "event_count": 1, "last_sequence": 1, "qc_answer": "未给出结论"},
    ],
)
def test_require_qc_evidence_rejects_missing_or_incomplete_evidence(state: dict[str, object]) -> None:
    with pytest.raises(verification.AcceptanceError):
        verification.require_qc_evidence(state)


def test_acceptance_runner_writes_machine_readable_evidence(tmp_path: Path) -> None:
    runner = verification.AcceptanceRunner(tmp_path, tmp_path / "evidence")
    runner.results.append(
        verification.CheckResult("postgres-ready", True, ["pg_isready"], 0, "accepting connections", "")
    )

    runner.write_evidence(run_id="run-1", broker_exercised=False)

    payload = json.loads((tmp_path / "evidence" / "acceptance.json").read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-1"
    assert payload["passed"] is True
    assert payload["checks"][0]["name"] == "postgres-ready"


def test_broker_exercise_requires_staging_and_confirmation(tmp_path: Path) -> None:
    runner = verification.AcceptanceRunner(tmp_path, tmp_path / "evidence")
    args = type(
        "Args",
        (),
        {
            "environment": "production",
            "confirm_broker_outage": False,
            "broker_outage_seconds": 5,
            "recovery_timeout_seconds": 1,
        },
    )()

    with pytest.raises(verification.AcceptanceError, match="staging"):
        verification.exercise_broker_recovery(runner, args, "replan-run-1")


def test_require_qc_downgrade_evidence_requires_explicit_plan_metadata() -> None:
    verification.require_qc_downgrade_evidence({"qc_task_present": False, "qc_mode": "degraded"})

    with pytest.raises(verification.AcceptanceError, match="does not declare"):
        verification.require_qc_downgrade_evidence({"qc_task_present": False, "qc_mode": "required"})

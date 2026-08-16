from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "verify_latency_budget.py"
SPEC = importlib.util.spec_from_file_location("verify_latency_budget", MODULE_PATH)
assert SPEC and SPEC.loader
verify_latency_budget = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verify_latency_budget
SPEC.loader.exec_module(verify_latency_budget)


def test_nearest_rank_p95() -> None:
    assert verify_latency_budget.percentile_95(list(range(1, 101))) == 95


def test_budget_passes_with_enough_samples(tmp_path) -> None:
    samples = tmp_path / "latency.jsonl"
    samples.write_text(
        "\n".join(
            [
                *(
                    '{"metric":"event_to_frontend_ms","duration_ms":2500}'
                    for _ in range(20)
                ),
                *(
                    '{"metric":"approval_accept_ms","duration_ms":800}'
                    for _ in range(20)
                ),
            ]
        ),
        encoding="utf-8",
    )

    report = verify_latency_budget.verify_latency_budget(
        verify_latency_budget.load_measurements(samples), min_samples=20
    )

    assert report["passed"] is True
    assert report["metrics"]["event_to_frontend_ms"]["p95_ms"] == 2500


def test_budget_fails_for_threshold_or_insufficient_samples() -> None:
    report = verify_latency_budget.verify_latency_budget(
        {
            "event_to_frontend_ms": [3100] * 20,
            "approval_accept_ms": [500] * 10,
        },
        min_samples=20,
    )

    assert report["passed"] is False
    assert report["metrics"]["event_to_frontend_ms"]["passed"] is False
    assert "at least 20" in report["metrics"]["approval_accept_ms"]["failure"]

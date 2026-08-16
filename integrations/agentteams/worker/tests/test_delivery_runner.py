from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


MODULE_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(MODULE_DIR))
SPEC = importlib.util.spec_from_file_location("agentteams_delivery_runner", MODULE_DIR / "delivery_runner.py")
assert SPEC and SPEC.loader
delivery_runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = delivery_runner
SPEC.loader.exec_module(delivery_runner)


def test_delivery_runner_requires_delivery_identity() -> None:
    try:
        delivery_runner.load_config(
            {"AGENTTEAMS_BRIDGE_BASE_URL": "http://bridge/v1", "AGENTTEAMS_BRIDGE_TOKEN": "token", "AGENTTEAMS_WORKER_IDENTITY": "quality-auditor"}
        )
    except ValueError as exc:
        assert "delivery-reporter" in str(exc)
    else:
        raise AssertionError("delivery runtime accepted another identity")


def test_delivery_runner_consults_and_closes_case(monkeypatch) -> None:
    assignment = {"case_id": "case-1", "quality_decision": "passed", "work_item": {"work_item_id": "delivery-01", "context_refs": [{"kind": "task", "id": "task-1"}]}}
    calls: list[str] = []
    monkeypatch.setattr(delivery_runner, "claim_next", lambda *_args, dry_run=False, **_kwargs: calls.append("preview" if dry_run else "claim") or {"assignment": assignment})
    monkeypatch.setattr(delivery_runner, "heartbeat_work_item", lambda *_args, **_kwargs: calls.append("heartbeat") or {})
    monkeypatch.setattr(delivery_runner, "execute_readonly_work_item", lambda *_args, **_kwargs: calls.append("consult") or {"status": "completed", "summary": "交付清单与风险"})
    monkeypatch.setattr(delivery_runner, "close_case", lambda *_args, **_kwargs: calls.append("close") or {"status": "closed", "manifest_uri": "manifest.json"})

    result = delivery_runner.run_once(delivery_runner.DeliveryWorkerConfig("http://bridge/v1", "token", 1))

    assert calls == ["preview", "claim", "heartbeat", "consult", "close"]
    assert result["action"] == "closed"


def test_delivery_runner_requires_quality_decision(monkeypatch) -> None:
    assignment = {"case_id": "case-1", "work_item": {"work_item_id": "delivery-01"}}
    monkeypatch.setattr(delivery_runner, "claim_next", lambda *_args, dry_run=False, **_kwargs: {"assignment": assignment})
    monkeypatch.setattr(delivery_runner, "heartbeat_work_item", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(delivery_runner, "execute_readonly_work_item", lambda *_args, **_kwargs: {"status": "completed", "summary": "交付清单"})
    monkeypatch.setattr(delivery_runner, "close_case", lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("must not close")))

    result = delivery_runner.run_once(delivery_runner.DeliveryWorkerConfig("http://bridge/v1", "token", 1))

    assert result["action"] == "manual_review"
    assert result["reason"] == "missing_or_invalid_quality_decision"

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

MODULE_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(MODULE_DIR))
SPEC = importlib.util.spec_from_file_location("agentteams_worker_runner", MODULE_DIR / "worker_runner.py")
assert SPEC and SPEC.loader
worker_runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = worker_runner
SPEC.loader.exec_module(worker_runner)


def test_load_config_uses_its_own_identity_token() -> None:
    config = worker_runner.load_config(
        {
            "AGENTTEAMS_BRIDGE_BASE_URL": "http://bridge:8080/v1",
            "AGENTTEAMS_WORKER_IDENTITY": "agent-code",
            "BRIDGE_IDENTITIES": "agent-viz:viz,agent-code:code",
            "AGENTTEAMS_WORKER_AUTOCOMPLETE_DEMO": "true",
        }
    )

    assert config.token == "code"
    assert config.auto_complete_demo is True


def test_run_once_only_claims_prefixed_read_only_demo_assignments(monkeypatch) -> None:
    config = worker_runner.WorkerConfig(
        bridge_url="http://bridge:8080/v1",
        identity="agent-code",
        token="code",
        poll_seconds=1,
        auto_complete_demo=True,
        acceptance_case_prefix="agentteams-acceptance-",
    )
    assignment = {
        "case_id": "agentteams-acceptance-001",
        "work_item": {"work_item_id": "code-01", "read_only": True},
    }
    claims: list[bool] = []

    def fake_claim_next(*_args, dry_run: bool = False, **_kwargs):
        claims.append(dry_run)
        return {"assignment": assignment}

    monkeypatch.setattr(worker_runner, "claim_next", fake_claim_next)
    monkeypatch.setattr(
        worker_runner,
        "complete_work_item",
        lambda *_args, **_kwargs: {"work_item_id": "code-01", "status": "completed"},
    )

    result = worker_runner.run_once(config)

    assert claims == [True, False]
    assert result == {
        "action": "completed",
        "identity": "agent-code",
        "case_id": "agentteams-acceptance-001",
        "work_item_id": "code-01",
    }


def test_run_once_never_claims_non_acceptance_case(monkeypatch) -> None:
    config = worker_runner.WorkerConfig(
        bridge_url="http://bridge:8080/v1",
        identity="agent-code",
        token="code",
        poll_seconds=1,
        auto_complete_demo=True,
        acceptance_case_prefix="agentteams-acceptance-",
    )
    monkeypatch.setattr(
        worker_runner,
        "claim_next",
        lambda *_args, **_kwargs: {
            "assignment": {"case_id": "production-001", "work_item": {"read_only": True}}
        },
    )

    result = worker_runner.run_once(config)

    assert result == {
        "action": "awaiting_skill_runtime",
        "identity": "agent-code",
        "case_id": "production-001",
    }

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import threading
import time

MODULE_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(MODULE_DIR))
SPEC = importlib.util.spec_from_file_location(
    "agentteams_production_runner", MODULE_DIR / "production_runner.py"
)
assert SPEC and SPEC.loader
production_runner = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = production_runner
SPEC.loader.exec_module(production_runner)


def test_production_worker_requires_supported_identity(monkeypatch) -> None:
    config = production_runner.load_config(
        {
            "AGENTTEAMS_BRIDGE_BASE_URL": "http://bridge:8080/v1",
            "AGENTTEAMS_WORKER_IDENTITY": "unknown-worker",
            "AGENTTEAMS_BRIDGE_TOKEN": "token",
        }
    )
    monkeypatch.setattr(
        production_runner,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("unsupported")),
    )
    try:
        production_runner.load_worker_profile(config)
    except ValueError:
        pass
    else:
        raise AssertionError("unsupported production identity was accepted")


def test_production_worker_supports_rnaseq_research_identity() -> None:
    config = production_runner.load_config(
        {
            "AGENTTEAMS_BRIDGE_BASE_URL": "http://bridge:8080/v1",
            "AGENTTEAMS_WORKER_IDENTITY": "agent-rnaseq",
            "AGENTTEAMS_BRIDGE_TOKEN": "rnaseq-token",
        }
    )

    assert config.identity == "agent-rnaseq"


def test_production_worker_pool_loads_multiple_role_credentials() -> None:
    config = production_runner.load_pool_config(
        {
            "AGENTTEAMS_BRIDGE_BASE_URL": "http://bridge:8080/v1",
            "AGENTTEAMS_WORKER_IDENTITIES": "agent-code,agent-viz,agent-rnaseq",
            "AGENTTEAMS_AGENT_CODE_TOKEN": "code-token",
            "AGENTTEAMS_AGENT_VIZ_TOKEN": "viz-token",
            "AGENTTEAMS_AGENT_RNASEQ_TOKEN": "rnaseq-token",
            "AGENTTEAMS_WORKER_MAX_CONCURRENT": "2",
        }
    )

    assert [worker.identity for worker in config.workers] == [
        "agent-code",
        "agent-viz",
        "agent-rnaseq",
    ]
    assert [worker.token for worker in config.workers] == [
        "code-token",
        "viz-token",
        "rnaseq-token",
    ]
    assert config.max_concurrent == 2


def test_production_worker_pool_rejects_partial_credentials() -> None:
    try:
        production_runner.load_pool_config(
            {
                "AGENTTEAMS_BRIDGE_BASE_URL": "http://bridge:8080/v1",
                "AGENTTEAMS_WORKER_IDENTITIES": "agent-code,agent-viz",
                "AGENTTEAMS_AGENT_CODE_TOKEN": "code-token",
            }
        )
    except ValueError as exc:
        assert "agent-viz" in str(exc)
    else:
        raise AssertionError("partially credentialed Worker pool was accepted")


def test_production_worker_loads_profile_from_bridge(monkeypatch) -> None:
    config = production_runner.ProductionWorkerConfig(
        "http://bridge:8080/v1", "agent-atacseq", "token", 1
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"worker_profiles":{"agent-atacseq":{"agent_id":"agent-atacseq","capability":"interpretation"}}}'

    monkeypatch.setattr(production_runner, "urlopen", lambda *_args, **_kwargs: Response())

    assert production_runner.load_worker_profile(config) == ("agent-atacseq", "interpretation", ())


def test_production_worker_claims_and_uses_bridge_execution(monkeypatch) -> None:
    calls: list[str] = []
    assignment = {
        "case_id": "case-1",
        "work_item": {
            "work_item_id": "code-01",
            "objective": "Review this analysis script.",
            "context_refs": [{"kind": "project", "id": "project-1"}],
        },
    }

    def fake_claim(*_args, dry_run: bool = False, **_kwargs):
        calls.append("preview" if dry_run else "claim")
        return {"assignment": assignment, "claimed": not dry_run}

    def fake_heartbeat(*_args, **_kwargs):
        calls.append("heartbeat")
        return {"status": "claimed"}

    def fake_execute(*_args, **kwargs):
        calls.append("execute")
        assert kwargs["agent_id"] == "agent-code"
        assert kwargs["capability"] == "planning_advice"
        assert "Review this analysis script" in kwargs["question"]
        return {"status": "completed", "work_item_id": "code-01"}

    monkeypatch.setattr(production_runner, "claim_next", fake_claim)
    monkeypatch.setattr(
        production_runner, "load_worker_profile", lambda _config: ("agent-code", "planning_advice", ())
    )
    monkeypatch.setattr(production_runner, "heartbeat_work_item", fake_heartbeat)
    monkeypatch.setattr(production_runner, "execute_readonly_work_item", fake_execute)
    config = production_runner.ProductionWorkerConfig(
        bridge_url="http://bridge:8080/v1", identity="agent-code", token="code", poll_seconds=1
    )

    result = production_runner.run_once(config)

    assert calls == ["preview", "claim", "heartbeat", "heartbeat", "execute"]
    assert result["action"] == "completed"
    assert result["work_item_id"] == "code-01"


def test_production_worker_forwards_workspace_execution_mode(monkeypatch) -> None:
    assignment = {
        "case_id": "case-1",
        "work_item": {
            "work_item_id": "exec-01",
            "objective": "Build tree.",
            "execution_mode": "workspace_execution",
        },
    }
    monkeypatch.setattr(
        production_runner, "claim_next", lambda *_args, **_kwargs: {"assignment": assignment}
    )
    monkeypatch.setattr(
        production_runner,
        "load_worker_profile",
        lambda _config: ("agent-code", "planning_advice", ("workspace_execution",)),
    )
    monkeypatch.setattr(production_runner, "heartbeat_work_item", lambda *_args, **_kwargs: {})
    observed = {}
    monkeypatch.setattr(
        production_runner,
        "execute_readonly_work_item",
        lambda *_args, **kwargs: observed.update(kwargs) or {"status": "completed"},
    )

    production_runner.run_once(
        production_runner.ProductionWorkerConfig("http://bridge", "agent-code", "token", 1)
    )

    assert observed["capability"] == "workspace_execution"
    assert observed["execution_mode"] == "workspace_execution"


def test_production_worker_runs_up_to_configured_concurrency(monkeypatch) -> None:
    active = 0
    peak = 0
    lock = threading.Lock()

    def fake_run_once(_config):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {"action": "completed"}

    monkeypatch.setattr(production_runner, "run_once", fake_run_once)
    config = production_runner.ProductionWorkerConfig(
        "http://bridge", "agent-code", "token", 1, max_concurrent=2
    )

    assert len(production_runner.run_batch_once(config)) == 2
    assert peak == 2


def test_production_worker_pool_checks_all_identities_with_bounded_concurrency(monkeypatch) -> None:
    active = 0
    peak = 0
    checked: list[str] = []
    lock = threading.Lock()

    def fake_run_once(config):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            checked.append(config.identity)
        time.sleep(0.02)
        with lock:
            active -= 1
        return {"action": "idle", "identity": config.identity}

    monkeypatch.setattr(production_runner, "run_once", fake_run_once)
    workers = tuple(
        production_runner.ProductionWorkerConfig(
            "http://bridge", identity, f"{identity}-token", 1, max_concurrent=1
        )
        for identity in ("agent-code", "agent-viz", "agent-rnaseq")
    )
    config = production_runner.ProductionWorkerPoolConfig(
        workers=workers, poll_seconds=1, max_concurrent=2
    )

    result = production_runner.run_pool_once(config)

    assert set(checked) == {"agent-code", "agent-viz", "agent-rnaseq"}
    assert peak == 2
    assert result[0]["action"] == "idle"


def test_production_worker_forwards_evidence_refs_and_readonly_tools(monkeypatch) -> None:
    assignment = {
        "case_id": "case-1",
        "work_item": {
            "work_item_id": "quality-01",
            "objective": "Review QC.",
            "context_refs": [
                {"kind": "task", "id": "task-1"},
                {"kind": "file", "id": "file-1", "location": "reports/qc.tsv"},
            ],
        },
    }
    monkeypatch.setattr(
        production_runner, "claim_next", lambda *_args, **_kwargs: {"assignment": assignment}
    )
    monkeypatch.setattr(
        production_runner, "load_worker_profile", lambda _config: ("agent-qc", "quality-gate", ())
    )
    monkeypatch.setattr(production_runner, "heartbeat_work_item", lambda *_args, **_kwargs: {})
    observed = {}
    monkeypatch.setattr(
        production_runner,
        "execute_readonly_work_item",
        lambda *_args, **kwargs: observed.update(kwargs) or {"status": "completed"},
    )

    production_runner.run_once(
        production_runner.ProductionWorkerConfig("http://bridge", "quality-auditor", "token", 1)
    )

    assert observed["evidence_refs"] == ["task:task-1", "reports/qc.tsv"]
    assert set(observed["requested_tools"]) == set(production_runner._EVIDENCE_TOOLS)


def test_production_worker_uses_file_scheme_for_uuid_file_refs(monkeypatch) -> None:
    assignment = {
        "case_id": "case-1",
        "work_item": {
            "work_item_id": "plan-01",
            "objective": "Plan analysis.",
            "context_refs": [
                {"kind": "file", "id": "cb79a200-b2ca-441f-9a42-d3417fbfa89d"},
            ],
        },
    }
    monkeypatch.setattr(
        production_runner, "claim_next", lambda *_args, **_kwargs: {"assignment": assignment}
    )
    monkeypatch.setattr(
        production_runner, "load_worker_profile", lambda _config: ("agent-code", "planning_advice", ())
    )
    monkeypatch.setattr(production_runner, "heartbeat_work_item", lambda *_args, **_kwargs: {})
    observed = {}
    monkeypatch.setattr(
        production_runner,
        "execute_readonly_work_item",
        lambda *_args, **kwargs: observed.update(kwargs) or {"status": "completed"},
    )

    production_runner.run_once(
        production_runner.ProductionWorkerConfig("http://bridge", "agent-code", "token", 1)
    )

    assert observed["evidence_refs"] == ["legacy-file:cb79a200-b2ca-441f-9a42-d3417fbfa89d"]


def test_production_worker_profile_exposes_declared_execution_modes(monkeypatch) -> None:
    config = production_runner.ProductionWorkerConfig(
        "http://bridge:8080/v1", "agent-rnaseq", "token", 1
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return (
                b'{"worker_profiles":{"agent-rnaseq":{"agent_id":"agent-rnaseq","capability":"interpretation"}},'
                b'"role_aliases":{"data-steward":"agent-data"},'
                b'"agent_capabilities":{"agent-rnaseq":{"agent_id":"agent-rnaseq",'
                b'"execution_modes":["readonly_consultation","workspace_execution"]}}}'
            )

    monkeypatch.setattr(production_runner, "urlopen", lambda *_args, **_kwargs: Response())

    assert production_runner.load_worker_profile(config) == (
        "agent-rnaseq",
        "interpretation",
        ("readonly_consultation", "workspace_execution"),
    )


def test_production_worker_profile_resolves_alias_execution_modes(monkeypatch) -> None:
    config = production_runner.ProductionWorkerConfig(
        "http://bridge:8080/v1", "data-steward", "token", 1
    )

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return (
                b'{"worker_profiles":{"data-steward":{"agent_id":"agent-data","capability":"project-preflight"}},'
                b'"role_aliases":{"data-steward":"agent-data"},'
                b'"agent_capabilities":{"agent-data":{"agent_id":"agent-data",'
                b'"execution_modes":["readonly_consultation","workspace_execution"]}}}'
            )

    monkeypatch.setattr(production_runner, "urlopen", lambda *_args, **_kwargs: Response())

    assert production_runner.load_worker_profile(config) == (
        "agent-data",
        "project-preflight",
        ("readonly_consultation", "workspace_execution"),
    )


def test_production_worker_allows_workspace_execution_for_declared_identity(monkeypatch) -> None:
    assignment = {
        "case_id": "case-1",
        "work_item": {
            "work_item_id": "exec-02",
            "objective": "Run the RNA-seq QC notebook.",
            "execution_mode": "workspace_execution",
        },
    }
    monkeypatch.setattr(
        production_runner, "claim_next", lambda *_args, **_kwargs: {"assignment": assignment}
    )
    monkeypatch.setattr(
        production_runner,
        "load_worker_profile",
        lambda _config: (
            "agent-rnaseq",
            "interpretation",
            ("readonly_consultation", "workspace_execution"),
        ),
    )
    monkeypatch.setattr(production_runner, "heartbeat_work_item", lambda *_args, **_kwargs: {})
    observed = {}
    monkeypatch.setattr(
        production_runner,
        "execute_readonly_work_item",
        lambda *_args, **kwargs: observed.update(kwargs) or {"status": "completed"},
    )

    production_runner.run_once(
        production_runner.ProductionWorkerConfig("http://bridge", "agent-rnaseq", "token", 1)
    )

    assert observed["capability"] == "workspace_execution"
    assert observed["execution_mode"] == "workspace_execution"


def test_production_worker_rejects_workspace_execution_without_declaration(monkeypatch) -> None:
    assignment = {
        "case_id": "case-1",
        "work_item": {
            "work_item_id": "exec-03",
            "objective": "Run the QC notebook.",
            "execution_mode": "workspace_execution",
        },
    }
    monkeypatch.setattr(
        production_runner, "claim_next", lambda *_args, **_kwargs: {"assignment": assignment}
    )
    monkeypatch.setattr(
        production_runner,
        "load_worker_profile",
        lambda _config: ("agent-qc", "quality-gate", ("readonly_consultation",)),
    )
    monkeypatch.setattr(production_runner, "heartbeat_work_item", lambda *_args, **_kwargs: {})

    try:
        production_runner.run_once(
            production_runner.ProductionWorkerConfig("http://bridge", "agent-qc", "token", 1)
        )
    except RuntimeError as exc:
        assert "agent-qc" in str(exc)
    else:
        raise AssertionError("workspace_execution was accepted without a registry declaration")


def test_production_worker_records_profile_failure_before_claim(monkeypatch) -> None:
    assignment = {
        "case_id": "case-1",
        "work_item": {"work_item_id": "plan-01", "objective": "Plan analysis."},
    }
    claim_calls: list[bool] = []
    monkeypatch.setattr(
        production_runner,
        "claim_next",
        lambda *_args, **kwargs: claim_calls.append(bool(kwargs.get("dry_run"))) or {"assignment": assignment},
    )
    monkeypatch.setattr(
        production_runner,
        "load_worker_profile",
        lambda _config: (_ for _ in ()).throw(ValueError("malformed profile")),
    )
    heartbeats: list[dict] = []
    failures: list[dict] = []
    monkeypatch.setattr(
        production_runner,
        "heartbeat_work_item",
        lambda *_args, **kwargs: heartbeats.append(kwargs) or {},
    )
    monkeypatch.setattr(
        production_runner,
        "record_work_item_failure",
        lambda *_args, **kwargs: failures.append(kwargs) or {},
    )

    try:
        production_runner.run_once(
            production_runner.ProductionWorkerConfig("http://bridge", "agent-code", "token", 1)
        )
    except ValueError as exc:
        assert "malformed profile" in str(exc)
    else:
        raise AssertionError("profile failure should be surfaced")

    assert not heartbeats
    assert failures and failures[0]["error"] == "malformed profile"
    assert claim_calls == [True]

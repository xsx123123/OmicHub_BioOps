from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from urllib.request import Request

MODULE_PATH = Path(__file__).parents[1] / "claim_next.py"
SPEC = importlib.util.spec_from_file_location("agentteams_claim_next", MODULE_PATH)
assert SPEC and SPEC.loader
claim_next = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = claim_next
SPEC.loader.exec_module(claim_next)


class Response:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")


def test_returns_null_when_worker_has_no_pending_assignment() -> None:
    requests: list[Request] = []

    def opener(request: Request) -> Response:
        requests.append(request)
        return Response({"items": [], "total": 0})

    result = claim_next.claim_next("http://bridge/v1", "quality-auditor", "secret", opener=opener)

    assert result == {"assignment": None}
    assert requests[0].full_url == "http://bridge/v1/work-items/assigned"


def test_claims_pending_assignment_and_outputs_only_worker_envelope() -> None:
    requests: list[Request] = []
    inbox = {
        "items": [
            {
                "case_id": "bioops_001",
                "project_ref": {"kind": "project", "id": "project-1"},
                "intent": "bulk_rnaseq_delivery",
                "status": "quality_running",
                "omic_task_ids": ["task-1"],
                "quality_decision": None,
                "work_item": {"work_item_id": "quality-01", "status": "pending"},
                "preflight_input": {"must_not": "appear"},
            }
        ],
        "total": 1,
    }

    def opener(request: Request) -> Response:
        requests.append(request)
        if request.get_method() == "GET":
            return Response(inbox)
        return Response({"work_item_id": "quality-01", "status": "claimed"})

    result = claim_next.claim_next("http://bridge/v1", "quality-auditor", "secret", opener=opener)

    assert result["claimed"] is True
    assert result["assignment"]["work_item"]["status"] == "claimed"
    assert "preflight_input" not in result["assignment"]
    assert requests[1].full_url.endswith("/cases/bioops_001/work-items/quality-01/claim")
    assert requests[1].get_method() == "POST"
    assert requests[1].headers["X-bridge-identity"] == "quality-auditor"


def test_heartbeat_includes_runtime_pod_identity(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def opener(request):
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return Response({"status": "running"})

    monkeypatch.setenv("AGENTTEAMS_POD_NAME", "worker-code-7d8f")
    claim_next.heartbeat_work_item(
        "http://bridge/v1",
        "agent-code",
        "secret",
        {"case_id": "case-1", "work_item": {"work_item_id": "code-01"}},
        trace_id="trace-1",
        opener=opener,
    )

    assert captured["payload"] == {
        "summary": "",
        "trace_id": "trace-1",
        "worker_id": "worker-code-7d8f",
    }


def test_dry_run_keeps_the_same_sanitized_assignment_envelope() -> None:
    inbox = {
        "items": [
            {
                "case_id": "bioops_001",
                "project_ref": {"kind": "project", "id": "project-1"},
                "intent": "bulk_rnaseq_delivery",
                "status": "quality_running",
                "work_item": {"work_item_id": "quality-01", "status": "pending"},
                "preflight_input": {"must_not": "appear"},
            }
        ]
    }

    def opener(_: Request) -> Response:
        return Response(inbox)

    result = claim_next.claim_next(
        "http://bridge/v1", "quality-auditor", "secret", dry_run=True, opener=opener
    )

    assert result["claimed"] is False
    assert "preflight_input" not in result["assignment"]


def test_completes_claimed_assignment_with_targeted_json_payload() -> None:
    requests: list[Request] = []

    def opener(request: Request) -> Response:
        requests.append(request)
        return Response({"work_item_id": "quality-01", "status": "completed"})

    result = claim_next.complete_work_item(
        "http://bridge/v1",
        "quality-auditor",
        "secret",
        {
            "case_id": "bioops_001",
            "work_item": {"work_item_id": "quality-01", "read_only": True},
        },
        "Completed safely.",
        opener=opener,
    )

    assert result["status"] == "completed"
    assert requests[0].full_url.endswith("/cases/bioops_001/work-items/quality-01")
    assert requests[0].get_method() == "POST"
    assert json.loads(requests[0].data.decode("utf-8")) == {
        "status": "completed",
        "summary": "Completed safely.",
    }

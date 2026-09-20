from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from cygnusx_agentteams_bridge.app import create_app
from cygnusx_agentteams_bridge.audit import AuditStore
from cygnusx_agentteams_bridge.case_store import CaseStore
from cygnusx_agentteams_bridge.client import CygnusXClient
from cygnusx_agentteams_bridge.config import BridgeSettings
from cygnusx_agentteams_bridge.models import CaseRecord


class FixtureCygnusXClient:
    """Loop-neutral CygnusX fake used by ASGI contract tests."""

    def __init__(self, settings: BridgeSettings, calls: list[httpx.Request]) -> None:
        self._settings = settings
        self._calls = calls

    async def aclose(self) -> None:
        return None

    async def list_flows(self) -> dict:
        self._record("GET", "/api/v1/flows")
        return {
            "items": [{"id": "rna_seq"}, {"id": "test_general"}, {"id": "blocked_flow"}],
            "total": 3,
        }

    async def get_agentteams_capabilities(self) -> dict:
        self._record("GET", "/api/v1/agent-teams/capabilities")
        return {
            "allowed_flow_ids": ["rna_seq", "scrna_seq", "test_general"],
            "flow_agent_map": {
                "rna_seq": "agent-rnaseq",
                "scrna_seq": "agent-scrna",
                "test_general": "agent-code",
            },
            "flow_quality_gate_map": {
                "rna_seq": True,
                "scrna_seq": True,
                "test_general": False,
            },
            "role_agent_map": {"test-specialist": "agent-code"},
            "worker_profiles": {
                "test-specialist": {
                    "identity": "test-specialist",
                    "agent_id": "agent-code",
                    "capability": "planning_advice",
                }
            },
        }

    async def get_flow_schema(self, flow_id: str) -> dict:
        self._record("GET", f"/api/v1/flows/{flow_id}/schema")
        return {"id": flow_id}

    async def submit_task(self, payload: dict) -> dict:
        self._record("POST", "/api/v1/tasks", payload)
        return {"id": "task-001", "status": "pending"}

    async def get_task(self, task_id: str) -> dict:
        self._record("GET", f"/api/v1/tasks/{task_id}")
        return {"id": task_id, "status": "success", "result_path": "/data/secret/result"}

    async def cancel_task(self, task_id: str) -> dict:
        self._record("POST", f"/api/v1/tasks/{task_id}/cancel")
        return {"id": task_id, "status": "cancelled"}

    def _record(self, method: str, path: str, payload: dict | None = None) -> None:
        headers = {"Authorization": f"Bearer {self._settings.cygnusx_service_token}"}
        self._calls.append(
            httpx.Request(method, f"http://omic.test{path}", headers=headers, json=payload)
        )


@pytest.mark.asyncio
async def test_healthz_exposes_build_metadata(tmp_path: Path) -> None:
    settings = BridgeSettings(
        case_store_path=str(tmp_path / "cases.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        worker_token_store_path=str(tmp_path / "tokens.json"),
        manifest_dir=str(tmp_path / "manifests"),
        build_sha="abc123",
        build_time="2026-08-19T00:00:00Z",
    )
    app = create_app(settings, FixtureCygnusXClient(settings, []))
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://bridge.test"
    ) as client:
        response = await client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "case_store_skipped_cases": 0,
        "build_sha": "abc123",
        "build_time": "2026-08-19T00:00:00Z",
        "minio_enabled": False,
    }


class LoopLocalASGIClient:
    """Create the Bridge app and HTTPX transport inside each test event loop."""

    def __init__(self, settings: BridgeSettings, calls: list[httpx.Request]) -> None:
        self._settings = settings
        self._calls = calls
        self._clients: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}

    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if loop not in self._clients:
            bridge = create_app(self._settings, FixtureCygnusXClient(self._settings, self._calls))
            self._clients[loop] = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=bridge), base_url="http://bridge.test"
            )
        return self._clients[loop]

    async def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self._client().get(*args, **kwargs)

    async def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self._client().post(*args, **kwargs)


@pytest.fixture
def settings(tmp_path):
    return BridgeSettings(
        cygnusx_base_url="http://omic.test",
        cygnusx_service_token="service-token",
        approval_signing_secret="test-signing-secret",
        identities=(
            "approval-authority:approval,bioops-manager:manager,data-steward:steward,"
            "workflow-operator:operator,quality-auditor:auditor,delivery-reporter:reporter,"
            "agent-code:code,agent-viz:viz,agent-scrna:scrna,agent-atacseq:atacseq,"
            "analysis-worker:analysis"
        ),
        allowed_flow_ids="rna_seq",
        role_agent_map="data-steward:agent-data,quality-auditor:agent-qc,delivery-reporter:agent-delivery,agent-code:agent-code,agent-viz:agent-viz,agent-scrna:agent-scrna,agent-rnaseq:agent-rnaseq,agent-atacseq:agent-atacseq",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        case_store_path=str(tmp_path / "cases.json"),
        manifest_dir=str(tmp_path / "manifests"),
    )


@pytest.fixture
def client(settings):
    calls: list[httpx.Request] = []
    return LoopLocalASGIClient(settings, calls), calls


def headers(identity: str, token: str) -> dict[str, str]:
    return {"X-Bridge-Identity": identity, "X-Bridge-Token": token}


def test_production_settings_reject_default_bridge_secrets() -> None:
    with pytest.raises(ValueError, match="审批签名密钥"):
        BridgeSettings(
            environment="production",
            cygnusx_service_token="restricted-token",
            identities="approval-authority:approval,bioops-manager:manager",
            allowed_flow_ids="rna_seq",
        )


def test_production_settings_reject_template_bridge_secrets() -> None:
    with pytest.raises(ValueError, match="CygnusX 受限服务令牌或 API Key"):
        BridgeSettings(
            environment="production",
            cygnusx_service_token="replace-with-restricted-service-user-token",
            approval_signing_secret="replace-with-32-byte-random-secret",
            identities="approval-authority:replace-human-approval-gateway",
            allowed_flow_ids="rna_seq",
        )


def test_production_settings_rejects_multiple_upstream_credentials() -> None:
    with pytest.raises(ValueError, match="只能配置一种"):
        BridgeSettings(
            environment="production",
            cygnusx_service_token="restricted-token",
            cygnusx_api_key="omh_restricted_key",
            approval_signing_secret="test-signing-secret",
            identities="approval-authority:approval,bioops-manager:manager,data-steward:steward,workflow-operator:operator,quality-auditor:auditor,delivery-reporter:reporter",
            allowed_flow_ids="rna_seq",
        )


async def create_case(request_client: httpx.AsyncClient, case_id: str = "bioops_001") -> None:
    response = await request_client.post(
        "/v1/cases",
        headers=headers("bioops-manager", "manager"),
        json={
            "case_id": case_id,
            "project_ref": {"kind": "project", "id": "project-1"},
            "intent": "bulk_rnaseq_delivery",
            "requester_ref": "user-1",
        },
    )
    assert response.status_code == 201


async def create_chat_case(request_client: httpx.AsyncClient, case_id: str = "bioops_chat_001") -> None:
    response = await request_client.post(
        "/v1/cases",
        headers=headers("bioops-manager", "manager"),
        json={
            "case_id": case_id,
            "intent": "介绍一下 Manager 能做什么",
            "requester_ref": "user-1",
            "context_refs": [{"kind": "workspace", "id": "user-1"}],
        },
    )
    assert response.status_code == 201


async def create_flow_case(request_client: httpx.AsyncClient, case_id: str = "bioops_flow_001") -> None:
    response = await request_client.post(
        "/v1/cases",
        headers=headers("bioops-manager", "manager"),
        json={
            "case_id": case_id,
            "project_ref": {"kind": "project", "id": "project-1"},
            "intent": "bulk_rnaseq_delivery",
            "requester_ref": "user-1",
            "flow_id": "rna_seq",
        },
    )
    assert response.status_code == 201


@pytest.mark.asyncio
async def test_flow_allowlist_and_identity_boundary(client) -> None:
    request_client, _ = client
    denied = await request_client.get("/v1/flows")
    assert denied.status_code == 401

    response = await request_client.get("/v1/flows", headers=headers("data-steward", "steward"))
    assert response.status_code == 200
    assert response.json() == {"items": [{"id": "rna_seq"}], "total": 1}


@pytest.mark.asyncio
async def test_capability_reload_discovers_new_flow_without_restart(client) -> None:
    request_client, calls = client
    snapshot = await request_client.get(
        "/v1/capabilities?reload=true", headers=headers("bioops-manager", "manager")
    )
    flows = await request_client.get("/v1/flows", headers=headers("bioops-manager", "manager"))

    assert snapshot.status_code == 200
    assert snapshot.json()["allowed_flow_ids"] == ["rna_seq", "scrna_seq", "test_general"]
    assert snapshot.json()["flow_agent_map"]["test_general"] == "agent-code"
    assert snapshot.json()["worker_profiles"]["test-specialist"]["agent_id"] == "agent-code"
    assert flows.json()["items"] == [{"id": "rna_seq"}, {"id": "test_general"}]
    assert any(request.url.path == "/api/v1/agent-teams/capabilities" for request in calls)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("worker", "token", "skill_name"),
    [
        ("agent-code", "code", "code-review"),
        ("agent-viz", "viz", "visualization-review"),
        ("agent-scrna", "scrna", "scrna-interpretation"),
        ("agent-atacseq", "atacseq", "atacseq-interpretation"),
    ],
)
async def test_professional_agent_worker_can_claim_and_complete_own_read_only_work_item(
    client, worker: str, token: str, skill_name: str
) -> None:
    request_client, _ = client
    case_id = f"{worker}-case"
    work_item_id = f"{worker}-review"
    await create_case(request_client, case_id)

    assigned = await request_client.post(
        f"/v1/cases/{case_id}/work-items",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": work_item_id,
            "target": worker,
            "objective": "提供可追溯的只读专业建议。",
            "skill_name": skill_name,
            "context_refs": [{"kind": "project", "id": "project-1"}],
            "read_only": True,
        },
    )
    assert assigned.status_code == 201

    inbox = await request_client.get("/v1/work-items/assigned", headers=headers(worker, token))
    assert inbox.status_code == 200
    assert [item["work_item"]["work_item_id"] for item in inbox.json()["items"]] == [work_item_id]

    claimed = await request_client.post(
        f"/v1/cases/{case_id}/work-items/{work_item_id}/claim",
        headers=headers(worker, token),
    )
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "claimed"

    completed = await request_client.post(
        f"/v1/cases/{case_id}/work-items/{work_item_id}",
        headers=headers(worker, token),
        json={"status": "completed", "summary": "已完成只读专业建议。"},
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "completed"


@pytest.mark.asyncio
async def test_professional_agent_worker_rejects_writable_work_item(client) -> None:
    request_client, _ = client
    await create_case(request_client, "code-write-case")

    response = await request_client.post(
        "/v1/cases/code-write-case/work-items",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "code-write",
            "target": "agent-code",
            "objective": "尝试创建可写任务。",
            "skill_name": "code-review",
            "read_only": False,
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "Professional agent work items must be read-only"


@pytest.mark.asyncio
async def test_preflight_blocks_incomplete_sample_sheet(client) -> None:
    request_client, _ = client
    await create_case(request_client)
    response = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={"case_id": "bioops_001", "flow_id": "rna_seq", "sample_sheet": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "blocked"
    assert body["findings"][0]["code"] == "MISSING_SAMPLE_SHEET"


@pytest.mark.asyncio
async def test_submit_is_approval_scoped_idempotent_and_audited(client, settings) -> None:
    request_client, calls = client
    await create_case(request_client)
    preflight = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_001",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01"}],
        },
    )
    assert preflight.status_code == 200
    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={"case_id": "bioops_001", "action": "submit_task", "flow_id": "rna_seq"},
    )
    assert approval.status_code == 201
    token = approval.json()["token"]
    payload = {
        "case_id": "bioops_001",
        "idempotency_key": "bioops-001-rna-v1",
        "approval_token": token,
        "task": {"flow_id": "rna_seq", "name": "RNA demo", "sample_sheet": [{"sample": "S01"}]},
    }
    first = await request_client.post(
        "/v1/tasks", headers=headers("workflow-operator", "operator"), json=payload
    )
    second = await request_client.post(
        "/v1/tasks", headers=headers("workflow-operator", "operator"), json=payload
    )

    assert first.status_code == 201
    assert first.json()["omic_task_id"] == "task-001"
    assert second.status_code == 201
    assert second.json()["idempotent_replay"] is True
    assert (
        len([call for call in calls if call.url.path == "/api/v1/tasks" and call.method == "POST"])
        == 1
    )
    assert calls[-1].headers["authorization"] == "Bearer service-token"
    audit_text = Path(settings.audit_log_path).read_text(encoding="utf-8")
    audit_events = [json.loads(line) for line in audit_text.splitlines()]
    assert any(event["event_type"] == "omic_task.submitted" for event in audit_events)


@pytest.mark.asyncio
async def test_upstream_uses_api_key_when_configured(settings) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(200, json={"items": [], "total": 0})

    api_key_settings = settings.model_copy(
        update={"cygnusx_service_token": "", "cygnusx_api_key": "omh_restricted_key"}
    )
    upstream = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://omic.test"
    )
    client = CygnusXClient(api_key_settings, upstream)
    await client.list_flows()
    await upstream.aclose()

    assert calls[0].headers["x-api-key"] == "omh_restricted_key"
    assert "authorization" not in calls[0].headers


@pytest.mark.asyncio
async def test_capability_snapshot_uses_only_integration_token(settings) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "allowed_flow_ids": [],
                "flow_agent_map": {},
                "flow_quality_gate_map": {},
                "role_agent_map": {},
                "worker_profiles": {},
            },
        )

    api_key_settings = settings.model_copy(
        update={
            "cygnusx_service_token": "",
            "cygnusx_api_key": "omh_restricted_key",
            "cygnusx_integration_token": "integration-secret",
        }
    )
    upstream = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://omic.test"
    )
    client = CygnusXClient(api_key_settings, upstream)
    await client.get_agentteams_capabilities()
    await upstream.aclose()

    assert calls[0].headers["x-integration-token"] == "integration-secret"
    assert "x-api-key" not in calls[0].headers
    assert "authorization" not in calls[0].headers


@pytest.mark.asyncio
async def test_submit_rejects_wrong_approval_scope(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_001")
    await create_case(request_client, "bioops_002")
    for case_id in ("bioops_001", "bioops_002"):
        preflight = await request_client.post(
            "/v1/projects/project-1/preflight",
            headers=headers("data-steward", "steward"),
            json={
                "case_id": case_id,
                "flow_id": "rna_seq",
                "sample_sheet": [{"sample": "S01"}],
            },
        )
        assert preflight.status_code == 200
    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={"case_id": "bioops_001", "action": "submit_task", "flow_id": "rna_seq"},
    )
    response = await request_client.post(
        "/v1/tasks",
        headers=headers("workflow-operator", "operator"),
        json={
            "case_id": "bioops_002",
            "idempotency_key": "bioops-002-rna-v1",
            "approval_token": approval.json()["token"],
            "task": {"flow_id": "rna_seq", "name": "RNA demo"},
        },
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Approval scope mismatch"


@pytest.mark.asyncio
async def test_submit_approval_requires_passed_preflight(client) -> None:
    request_client, _ = client
    await create_case(request_client)

    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={"case_id": "bioops_001", "action": "submit_task", "flow_id": "rna_seq"},
    )

    assert approval.status_code == 409
    assert approval.json()["detail"] == "Task submission approval requires a passed preflight"


@pytest.mark.asyncio
async def test_approved_submission_is_queued_without_exposing_approval_to_analysis_worker(
    client,
) -> None:
    request_client, calls = client
    await create_case(request_client)
    preflight = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_001",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01", "group": "control"}],
        },
    )
    assert preflight.status_code == 200
    assigned = await request_client.post(
        "/v1/cases/bioops_001/work-items",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "submit-01",
            "target": "analysis-worker",
            "objective": "Submit approved analysis",
            "skill_name": "workflow-submit",
            "read_only": False,
            "approval_required": True,
        },
    )
    assert assigned.status_code == 201
    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={
            "case_id": "bioops_001",
            "work_item_id": "submit-01",
            "action": "submit_task",
            "flow_id": "rna_seq",
        },
    )
    assert approval.status_code == 201
    queued = await request_client.post(
        "/v1/approved-submissions",
        headers=headers("approval-authority", "approval"),
        json={
            "case_id": "bioops_001",
            "work_item_id": "submit-01",
            "idempotency_key": "bioops-001-analysis-v1",
            "approval_token": approval.json()["token"],
            "task": {
                "flow_id": "rna_seq",
                "name": "RNA cluster delivery",
                "sample_sheet": [{"sample": "S01", "group": "control"}],
                "execution_mode": "cluster",
            },
        },
    )
    assert queued.status_code == 201
    assert queued.json()["status"] == "queued"

    inbox = await request_client.get(
        "/v1/work-items/assigned", headers=headers("analysis-worker", "analysis")
    )
    assert inbox.status_code == 200
    assert "approval_token" not in inbox.text
    claim = await request_client.post(
        "/v1/cases/bioops_001/work-items/submit-01/claim",
        headers=headers("analysis-worker", "analysis"),
    )
    assert claim.status_code == 200
    submitted = await request_client.post(
        "/v1/cases/bioops_001/work-items/submit-01/submit-approved",
        headers=headers("analysis-worker", "analysis"),
    )
    assert submitted.status_code == 201
    assert submitted.json()["omic_task_id"] == "task-001"
    assert [call.url.path for call in calls].count("/api/v1/tasks") == 1

    repeated = await request_client.post(
        "/v1/cases/bioops_001/work-items/submit-01/submit-approved",
        headers=headers("analysis-worker", "analysis"),
    )
    assert repeated.status_code == 409
    assert [call.url.path for call in calls].count("/api/v1/tasks") == 1


@pytest.mark.asyncio
async def test_queued_scrna_submission_refreshes_a_stale_flow_allowlist(client, settings) -> None:
    request_client, calls = client
    await create_case(request_client, "bioops_scrna_refresh")
    preflight = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_scrna_refresh",
            "flow_id": "scrna_seq",
            "sample_sheet": [{"sample": "S01", "group": "control"}],
        },
    )
    assert preflight.status_code == 200
    assigned = await request_client.post(
        "/v1/cases/bioops_scrna_refresh/work-items",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "submit-01",
            "target": "analysis-worker",
            "objective": "Submit approved scRNA analysis",
            "skill_name": "workflow-submit",
            "read_only": False,
            "approval_required": True,
        },
    )
    assert assigned.status_code == 201
    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={
            "case_id": "bioops_scrna_refresh",
            "work_item_id": "submit-01",
            "action": "submit_task",
            "flow_id": "scrna_seq",
        },
    )
    assert approval.status_code == 201

    settings.allowed_flow_ids = "rna_seq"
    queued = await request_client.post(
        "/v1/approved-submissions",
        headers=headers("approval-authority", "approval"),
        json={
            "case_id": "bioops_scrna_refresh",
            "work_item_id": "submit-01",
            "idempotency_key": "bioops-scrna-refresh-v1",
            "approval_token": approval.json()["token"],
            "task": {
                "flow_id": "scrna_seq",
                "name": "scRNA cluster delivery",
                "sample_sheet": [{"sample": "S01", "group": "control"}],
                "execution_mode": "cluster",
            },
        },
    )

    assert queued.status_code == 201
    assert queued.json()["status"] == "queued"
    assert sum(
        request.url.path == "/api/v1/agent-teams/capabilities" for request in calls
    ) >= 2


@pytest.mark.asyncio
async def test_case_success_path_generates_quality_evidence_and_manifest(client) -> None:
    request_client, _ = client
    await create_case(request_client)
    for work_item_id, target, skill_name in [
        ("preflight-01", "data-steward", "project-preflight"),
        ("submit-01", "workflow-operator", "workflow-submit"),
        ("quality-01", "quality-auditor", "quality-gate"),
        ("delivery-01", "delivery-reporter", "delivery-pack"),
    ]:
        assigned = await request_client.post(
            "/v1/cases/bioops_001/work-items",
            headers=headers("bioops-manager", "manager"),
            json={
                "work_item_id": work_item_id,
                "target": target,
                "objective": f"Run {skill_name}",
                "skill_name": skill_name,
            },
        )
        assert assigned.status_code == 201
    preflight = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_001",
            "work_item_id": "preflight-01",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01", "group": "control"}],
        },
    )
    assert preflight.status_code == 200
    assert preflight.json()["status"] == "passed"

    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={"case_id": "bioops_001", "action": "submit_task", "flow_id": "rna_seq"},
    )
    submit = await request_client.post(
        "/v1/tasks",
        headers=headers("workflow-operator", "operator"),
        json={
            "case_id": "bioops_001",
            "work_item_id": "submit-01",
            "idempotency_key": "bioops-001-success-v1",
            "approval_token": approval.json()["token"],
            "task": {
                "flow_id": "rna_seq",
                "name": "RNA success",
                "sample_sheet": [{"sample": "S01", "group": "control"}],
            },
        },
    )
    assert submit.status_code == 201

    artifacts = await request_client.get(
        "/v1/tasks/task-001/artifacts", headers=headers("quality-auditor", "auditor")
    )
    assert artifacts.status_code == 200
    assert artifacts.json()["artifacts"] == [
        {"kind": "task_result", "uri": "omic://tasks/task-001/result", "available": True}
    ]
    quality = await request_client.post(
        "/v1/tasks/task-001/quality-gate",
        headers=headers("quality-auditor", "auditor"),
        json={
            "case_id": "bioops_001",
            "work_item_id": "quality-01",
            "rule_version": "rna-qc-1.0",
            "decision": "passed",
            "summary": "All required artifacts are present.",
            "evidence_refs": [{"kind": "task", "id": "task-001"}],
            "artifact_hashes": {"artifact-001": "abc123"},
            # 产物血缘（F1）硬约束：上报 artifact_hashes 必须携带 source_refs。
            "source_refs": [{"artifact_id": "projects/p1/input.fastq", "relation": "input_to"}],
            "execution_summary": "rna_seq run over the declared input sheet",
        },
    )
    assert quality.status_code == 200

    closed = await request_client.post(
        "/v1/cases/bioops_001/close",
        headers=headers("delivery-reporter", "reporter"),
        json={"case_id": "bioops_001", "quality_decision": "passed"},
    )
    assert closed.status_code == 200
    assert closed.json()["status"] == "closed"
    assert closed.json()["manifest"]["task_ids"] == ["task-001"]
    assert closed.json()["manifest"]["artifact_checksums"] == {"artifact-001": "abc123"}
    assert closed.json()["manifest"]["omic_task_snapshots"][0]["id"] == "task-001"
    assert [item["status"] for item in closed.json()["manifest"]["case"]["work_items"]] == [
        "completed",
        "completed",
        "completed",
        "pending",
    ]
    events = await request_client.get(
        "/v1/cases/bioops_001/events", headers=headers("delivery-reporter", "reporter")
    )
    event_types = {event["event_type"] for event in events.json()["events"]}
    assert {"case.created", "quality.decision", "case.closed"}.issubset(event_types)
    metrics = await request_client.get("/v1/metrics", headers=headers("bioops-manager", "manager"))
    assert metrics.status_code == 200
    assert metrics.json()["closed_case_count"] == 1


@pytest.mark.asyncio
async def test_case_state_machine_rejects_skip_to_closed(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_002")
    response = await request_client.post(
        "/v1/cases/bioops_002/state",
        headers=headers("bioops-manager", "manager"),
        json={"status": "closed", "reason": "not allowed"},
    )
    assert response.status_code == 409


@pytest.mark.asyncio
async def test_case_list_is_manager_only_and_filters_requester(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_005")
    denied = await request_client.get("/v1/cases", headers=headers("data-steward", "steward"))
    assert denied.status_code == 403
    listed = await request_client.get(
        "/v1/cases?requester_ref=user-1", headers=headers("bioops-manager", "manager")
    )
    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["case_id"] == "bioops_005"


@pytest.mark.asyncio
async def test_case_create_ignores_legacy_element_room_url(client) -> None:
    request_client, _ = client
    created = await request_client.post(
        "/v1/cases",
        headers=headers("bioops-manager", "manager"),
        json={
            "case_id": "bioops_006",
            "project_ref": {"kind": "project", "id": "project-1"},
            "intent": "bulk_rnaseq_delivery",
            "requester_ref": "user-1",
            "element_room_url": "https://element.example.com/#/room/!legacy:matrix.example.com",
        },
    )
    assert created.status_code == 201
    assert "element_room_url" not in created.json()


@pytest.mark.asyncio
async def test_case_block_can_be_corrected_and_retried(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_003")
    blocked = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={"case_id": "bioops_003", "flow_id": "rna_seq", "sample_sheet": []},
    )
    assert blocked.json()["status"] == "blocked"
    passed = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_003",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01", "group": "control"}],
        },
    )
    assert passed.status_code == 200
    assert passed.json()["status"] == "passed"
    current = await request_client.get(
        "/v1/cases/bioops_003", headers=headers("bioops-manager", "manager")
    )
    assert current.json()["status"] == "approval_pending"


@pytest.mark.asyncio
async def test_cancel_requires_scoped_approval_and_updates_case(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_004")
    assigned = await request_client.post(
        "/v1/cases/bioops_004/work-items",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "cancel-01",
            "target": "workflow-operator",
            "objective": "Cancel the approved workflow when requested",
            "skill_name": "workflow-cancel",
            "approval_required": True,
            "read_only": False,
        },
    )
    assert assigned.status_code == 201
    await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_004",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01"}],
        },
    )
    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={
            "case_id": "bioops_004",
            "action": "submit_task",
            "flow_id": "rna_seq",
        },
    )
    submit = await request_client.post(
        "/v1/tasks",
        headers=headers("workflow-operator", "operator"),
        json={
            "case_id": "bioops_004",
            "idempotency_key": "bioops-004-submit-v1",
            "approval_token": approval.json()["token"],
            "task": {
                "flow_id": "rna_seq",
                "name": "RNA cancel",
                "sample_sheet": [{"sample": "S01"}],
            },
        },
    )
    assert submit.status_code == 201
    cancel_approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={
            "case_id": "bioops_004",
            "action": "cancel_task",
            "task_id": "task-001",
        },
    )
    cancelled = await request_client.post(
        "/v1/tasks/task-001/cancel",
        headers=headers("workflow-operator", "operator"),
        json={
            "case_id": "bioops_004",
            "approval_token": cancel_approval.json()["token"],
            "reason": "用户主动终止",
        },
    )
    assert cancelled.status_code == 200
    current = await request_client.get(
        "/v1/cases/bioops_004", headers=headers("bioops-manager", "manager")
    )
    assert current.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_manager_can_cancel_pending_plan_without_task_approval(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_reject")
    await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_reject",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01", "group": "control"}],
        },
    )
    response = await request_client.post(
        "/v1/cases/bioops_reject/cancel",
        headers=headers("bioops-manager", "manager"),
        json={"reason": "User rejected the frozen plan."},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "cancelled"
    events = await request_client.get(
        "/v1/cases/bioops_reject/events", headers=headers("bioops-manager", "manager")
    )
    assert any(event["event_type"] == "case.cancelled" for event in events.json()["events"])


@pytest.mark.asyncio
async def test_case_and_audit_indexes_restore_from_disk(settings) -> None:
    first_case_store = CaseStore(settings.case_store_path)
    now = datetime.now(UTC)
    case = CaseRecord(
        case_id="bioops_restore",
        project_ref={"kind": "project", "id": "project-1"},
        intent="restore-test",
        requester_ref="user-1",
        team_id="bioops-delivery",
        created_at=now,
        updated_at=now,
    )
    await first_case_store.create(case)
    first_audit = AuditStore(settings.audit_log_path)
    receipt = {
        "case_id": "bioops_restore",
        "omic_task_id": "task-restore",
        "status": "pending",
        "submitted_at": now.isoformat(),
    }
    await first_audit.record(
        case_id="bioops_restore",
        actor="workflow-operator",
        event_type="omic_task.submitted",
        payload={"idempotency_key": "restore-key", "receipt": receipt},
    )
    restored_case = await CaseStore(settings.case_store_path).get("bioops_restore")
    restored_audit = AuditStore(settings.audit_log_path)
    assert restored_case.case_id == "bioops_restore"
    assert await restored_audit.get_receipt("restore-key") == receipt


def test_case_store_rejects_corrupt_state_file(settings, caplog) -> None:
    Path(settings.case_store_path).write_text("{broken-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="state file is invalid"):
        CaseStore(settings.case_store_path)

    assert "cannot be read or parsed" in caplog.text


def test_case_store_reports_skipped_invalid_case_records(settings, caplog) -> None:
    Path(settings.case_store_path).write_text(
        json.dumps({"bad-case": {"case_id": "bad-case"}, "not-an-object": "invalid"}),
        encoding="utf-8",
    )

    store = CaseStore(settings.case_store_path)

    assert store.skipped_case_count == 2
    assert "Skipping invalid CaseStore entry" in caplog.text


@pytest.mark.asyncio
async def test_events_endpoint_enforces_limit_contract(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_limit_contract")
    request_headers = headers("bioops-manager", "manager")

    lower = await request_client.get(
        "/v1/cases/bioops_limit_contract/events?limit=0", headers=request_headers
    )
    upper = await request_client.get(
        "/v1/cases/bioops_limit_contract/events?limit=101", headers=request_headers
    )
    valid = await request_client.get(
        "/v1/cases/bioops_limit_contract/events?limit=100", headers=request_headers
    )

    assert lower.status_code == 422
    assert upper.status_code == 422
    assert valid.status_code == 200


@pytest.mark.asyncio
async def test_manager_assigns_three_workers_and_only_targets_can_report(client) -> None:
    request_client, _ = client
    await create_flow_case(request_client, "bioops_collab")
    work_items = [
        ("preflight-01", "data-steward", "project-preflight"),
        ("submit-01", "workflow-operator", "workflow-submit"),
        ("quality-01", "quality-auditor", "quality-gate"),
    ]
    for work_item_id, target, skill_name in work_items:
        assigned = await request_client.post(
            "/v1/cases/bioops_collab/work-items",
            headers=headers("bioops-manager", "manager"),
            json={
                "work_item_id": work_item_id,
                "target": target,
                "objective": f"Run {skill_name}",
                "skill_name": skill_name,
                "context_refs": [{"kind": "project", "id": "project-1"}],
            },
        )
        assert assigned.status_code == 201

    denied = await request_client.post(
        "/v1/cases/bioops_collab/work-items/preflight-01",
        headers=headers("quality-auditor", "auditor"),
        json={"status": "completed", "summary": "not my work item"},
    )
    assert denied.status_code == 403

    skipped_claim = await request_client.post(
        "/v1/cases/bioops_collab/work-items/preflight-01",
        headers=headers("data-steward", "steward"),
        json={"status": "completed", "summary": "attempted without claim"},
    )
    forged_start = await request_client.post(
        "/v1/cases/bioops_collab/work-items/preflight-01",
        headers=headers("data-steward", "steward"),
        json={"status": "in_progress", "summary": "attempted direct start"},
    )
    assert skipped_claim.status_code == 409
    assert forged_start.status_code == 409

    for work_item_id, target, _ in work_items:
        token = {
            "data-steward": "steward",
            "workflow-operator": "operator",
            "quality-auditor": "auditor",
        }[target]
        claimed = await request_client.post(
            f"/v1/cases/bioops_collab/work-items/{work_item_id}/claim",
            headers=headers(target, token),
        )
        assert claimed.status_code == 200
        completed = await request_client.post(
            f"/v1/cases/bioops_collab/work-items/{work_item_id}",
            headers=headers(target, token),
            json={"status": "completed", "summary": f"{target} finished"},
        )
        assert completed.status_code == 200

    case = await request_client.get(
        "/v1/cases/bioops_collab", headers=headers("bioops-manager", "manager")
    )
    statuses = {item["work_item_id"]: item["status"] for item in case.json()["work_items"]}
    assert [statuses[work_item_id] for work_item_id, _, _ in work_items] == ["completed"] * 3
    events = await request_client.get(
        "/v1/cases/bioops_collab/events", headers=headers("bioops-manager", "manager")
    )
    event_types = [event["event_type"] for event in events.json()["events"]]
    # 3 manual assignments + plan-01 created by auto-reconcile once all items are terminal
    assert event_types.count("work_item.assigned") == 4
    assert event_types.count("skill.finished") == 3


@pytest.mark.asyncio
async def test_external_worker_inbox_poll_does_not_spam_the_audit_stream(client) -> None:
    """Inbox 轮询是 operational 心跳：只进内存心跳表，不再写审计事件流。"""
    request_client, _ = client
    await create_case(request_client, "bioops_inbox_audit")
    assigned = await request_client.post(
        "/v1/cases/bioops_inbox_audit/work-items",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "code-01",
            "target": "agent-code",
            "objective": "Review the assigned evidence.",
            "skill_name": "code-review",
            "read_only": True,
        },
    )
    assert assigned.status_code == 201

    inbox = await request_client.get(
        "/v1/work-items/assigned", headers=headers("agent-code", "code")
    )
    assert inbox.status_code == 200
    assert [item["work_item"]["work_item_id"] for item in inbox.json()["items"]] == ["code-01"]

    events = await request_client.get(
        "/v1/cases/bioops_inbox_audit/events", headers=headers("bioops-manager", "manager")
    )
    assert not [
        event
        for event in events.json()["events"]
        if event["event_type"] == "worker.inbox_polled"
    ]


@pytest.mark.asyncio
async def test_case_and_event_queries_support_scoped_cursor_pagination(client) -> None:
    request_client, _ = client
    for case_id, project_id in [
        ("bioops_page_one", "project-page"),
        ("bioops_page_two", "project-page"),
        ("bioops_other", "project-other"),
    ]:
        response = await request_client.post(
            "/v1/cases",
            headers=headers("bioops-manager", "manager"),
            json={
                "case_id": case_id,
                "project_ref": {"kind": "project", "id": project_id},
                "intent": "pagination-test",
                "requester_ref": "user-1",
            },
        )
        assert response.status_code == 201

    first_page = await request_client.get(
        "/v1/cases?requester_ref=user-1&project_id=project-page&limit=1",
        headers=headers("bioops-manager", "manager"),
    )
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 2
    assert len(first_page.json()["items"]) == 1
    cursor = first_page.json()["next_cursor"]
    assert cursor

    second_page = await request_client.get(
        f"/v1/cases?requester_ref=user-1&project_id=project-page&limit=1&cursor={cursor}",
        headers=headers("bioops-manager", "manager"),
    )
    assert second_page.status_code == 200
    assert len(second_page.json()["items"]) == 1
    assert second_page.json()["next_cursor"] is None

    assigned = await request_client.post(
        "/v1/cases/bioops_page_two/work-items",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "page-item",
            "target": "data-steward",
            "objective": "Produce a paged event",
            "skill_name": "project-preflight",
        },
    )
    assert assigned.status_code == 201
    events = await request_client.get(
        "/v1/cases/bioops_page_two/events?limit=1",
        headers=headers("bioops-manager", "manager"),
    )
    assert events.status_code == 200
    assert len(events.json()["events"]) == 1
    event_cursor = events.json()["next_cursor"]
    assert event_cursor
    incremental = await request_client.get(
        f"/v1/cases/bioops_page_two/events?cursor={event_cursor}",
        headers=headers("bioops-manager", "manager"),
    )
    assert incremental.status_code == 200
    assert incremental.json()["events"]


@pytest.mark.asyncio
async def test_bridge_rejects_oversized_request_before_route_execution(settings, tmp_path) -> None:
    limited_settings = settings.model_copy(update={"max_request_bytes": 1_024})
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    bridge = create_app(limited_settings, CygnusXClient(limited_settings, upstream))
    transport = httpx.ASGITransport(app=bridge)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://bridge.test"
    ) as request_client:
        response = await request_client.post(
            "/v1/cases",
            headers=headers("bioops-manager", "manager"),
            json={
                "case_id": "bioops_oversized",
                "project_ref": {"kind": "project", "id": "project-1"},
                "intent": "x" * 2_000,
                "requester_ref": "user-1",
            },
        )
    await upstream.aclose()
    assert response.status_code == 413
    assert response.json()["detail"] == "Request body exceeds Bridge limit"


@pytest.mark.asyncio
async def test_bridge_rejects_oversized_response(settings) -> None:
    limited_settings = settings.model_copy(update={"max_response_bytes": 1_024})
    upstream = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(404)))
    bridge = create_app(limited_settings, CygnusXClient(limited_settings, upstream))
    transport = httpx.ASGITransport(app=bridge)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://bridge.test"
    ) as request_client:
        for number in range(8):
            response = await request_client.post(
                "/v1/cases",
                headers=headers("bioops-manager", "manager"),
                json={
                    "case_id": f"bioops_response_{number}",
                    "project_ref": {"kind": "project", "id": "project-1"},
                    "intent": "response-limit-test",
                    "requester_ref": "user-1",
                },
            )
            assert response.status_code == 201
        response = await request_client.get(
            "/v1/cases?requester_ref=user-1&limit=100",
            headers=headers("bioops-manager", "manager"),
        )
    await upstream.aclose()
    assert response.status_code == 502
    assert response.json()["detail"] == "Bridge response exceeds configured limit"


@pytest.mark.asyncio
async def test_submit_rejects_input_different_from_preflight_snapshot(client) -> None:
    request_client, _ = client
    await create_case(request_client)
    preflight = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_001",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01", "group": "control"}],
        },
    )
    assert preflight.status_code == 200
    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={"case_id": "bioops_001", "action": "submit_task", "flow_id": "rna_seq"},
    )
    response = await request_client.post(
        "/v1/tasks",
        headers=headers("workflow-operator", "operator"),
        json={
            "case_id": "bioops_001",
            "idempotency_key": "bioops-001-drift-v1",
            "approval_token": approval.json()["token"],
            "task": {
                "flow_id": "rna_seq",
                "name": "RNA input drift",
                "sample_sheet": [{"sample": "S01", "group": "treatment"}],
            },
        },
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Task input differs from the approved preflight snapshot"


@pytest.mark.asyncio
async def test_worker_case_access_requires_an_assigned_work_item(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_private")

    denied_case = await request_client.get(
        "/v1/cases/bioops_private", headers=headers("data-steward", "steward")
    )
    denied_events = await request_client.get(
        "/v1/cases/bioops_private/events", headers=headers("quality-auditor", "auditor")
    )
    assert denied_case.status_code == 403
    assert denied_events.status_code == 403
    assert denied_case.json()["detail"] == "Case is not assigned to this worker identity"

    assigned = await request_client.post(
        "/v1/cases/bioops_private/work-items",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "private-preflight",
            "target": "data-steward",
            "objective": "Validate the assigned project metadata",
            "skill_name": "project-preflight",
        },
    )
    assert assigned.status_code == 201

    allowed = await request_client.get(
        "/v1/cases/bioops_private", headers=headers("data-steward", "steward")
    )
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_evidence_requires_the_assigned_worker(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_evidence")
    assigned = await request_client.post(
        "/v1/cases/bioops_evidence/work-items",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "quality-evidence-01",
            "target": "quality-auditor",
            "objective": "Record quality evidence",
            "skill_name": "quality-gate",
        },
    )
    assert assigned.status_code == 201

    denied = await request_client.post(
        "/v1/cases/bioops_evidence/evidence",
        headers=headers("data-steward", "steward"),
        json={
            "work_item_id": "quality-evidence-01",
            "event_type": "quality.evidence",
            "summary": "Should not be able to write another worker's evidence",
        },
    )
    assert denied.status_code == 403
    assert denied.json()["detail"] == "Case is not assigned to this worker identity"

    allowed = await request_client.post(
        "/v1/cases/bioops_evidence/evidence",
        headers=headers("quality-auditor", "auditor"),
        json={
            "work_item_id": "quality-evidence-01",
            "event_type": "quality.evidence",
            "summary": "All required quality evidence is available",
        },
    )
    assert allowed.status_code == 201


@pytest.mark.asyncio
async def test_reconcile_skips_planning_for_chat_case_without_flow_id(client, settings) -> None:
    request_client, _ = client
    await create_chat_case(request_client, "bioops_chat_skip_plan")

    reconciled = await request_client.post(
        "/v1/cases/bioops_chat_skip_plan/reconcile", headers=headers("bioops-manager", "manager")
    )
    assert reconciled.status_code == 200
    body = reconciled.json()
    assert body["status"] == "received"
    assert body["flow_id"] is None
    assert not any(item["work_item_id"] == "plan-01" for item in body["work_items"])

    audit_text = Path(settings.audit_log_path).read_text(encoding="utf-8")
    audit_events = [json.loads(line) for line in audit_text.splitlines()]
    skip_events = [
        event
        for event in audit_events
        if event["event_type"] == "case.reconciled"
        and event.get("payload", {}).get("reason") == "chat_case_skips_auto_planning"
    ]
    assert len(skip_events) == 1
    assert skip_events[0]["payload"]["from_status"] == "received"
    assert skip_events[0]["payload"]["to_status"] == "received"

    repeated = await request_client.post(
        "/v1/cases/bioops_chat_skip_plan/reconcile", headers=headers("bioops-manager", "manager")
    )
    assert repeated.status_code == 200
    audit_events = [json.loads(line) for line in Path(settings.audit_log_path).read_text(encoding="utf-8").splitlines()]
    repeated_skip_events = [
        event
        for event in audit_events
        if event["event_type"] == "case.reconciled"
        and event.get("payload", {}).get("reason") == "chat_case_skips_auto_planning"
    ]
    assert len(repeated_skip_events) == 1


@pytest.mark.asyncio
async def test_reconcile_creates_quality_work_item_only_after_observed_success(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_reconcile")
    for work_item_id, target, skill_name in [
        ("preflight-01", "data-steward", "project-preflight"),
        ("submit-01", "workflow-operator", "workflow-submit"),
    ]:
        assigned = await request_client.post(
            "/v1/cases/bioops_reconcile/work-items",
            headers=headers("bioops-manager", "manager"),
            json={
                "work_item_id": work_item_id,
                "target": target,
                "objective": f"Run {skill_name}",
                "skill_name": skill_name,
            },
        )
        assert assigned.status_code == 201
    preflight = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_reconcile",
            "work_item_id": "preflight-01",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01"}],
        },
    )
    assert preflight.status_code == 200
    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={"case_id": "bioops_reconcile", "action": "submit_task", "flow_id": "rna_seq"},
    )
    submitted = await request_client.post(
        "/v1/tasks",
        headers=headers("workflow-operator", "operator"),
        json={
            "case_id": "bioops_reconcile",
            "work_item_id": "submit-01",
            "idempotency_key": "bioops-reconcile-submit-v1",
            "approval_token": approval.json()["token"],
            "task": {
                "flow_id": "rna_seq",
                "name": "Reconcile",
                "sample_sheet": [{"sample": "S01"}],
            },
        },
    )
    assert submitted.status_code == 201

    reconciled = await request_client.post(
        "/v1/cases/bioops_reconcile/reconcile", headers=headers("bioops-manager", "manager")
    )
    assert reconciled.status_code == 200
    assert reconciled.json()["status"] == "quality_running"
    interpretation_items = [
        item for item in reconciled.json()["work_items"] if item["work_item_id"] == "interpret-01"
    ]
    assert len(interpretation_items) == 1
    assert interpretation_items[0]["target"] == "agent-rnaseq"
    assert interpretation_items[0]["depends_on"] == ["submit-01"]
    quality_items = [
        item for item in reconciled.json()["work_items"] if item["work_item_id"] == "quality-01"
    ]
    assert len(quality_items) == 1
    assert quality_items[0]["target"] == "quality-auditor"
    assert quality_items[0]["parent_work_item_id"] == "interpret-01"
    assert quality_items[0]["depends_on"] == ["interpret-01"]

    replay = await request_client.post(
        "/v1/cases/bioops_reconcile/reconcile", headers=headers("bioops-manager", "manager")
    )
    assert replay.status_code == 200
    assert [item["work_item_id"] for item in replay.json()["work_items"]].count("quality-01") == 1
    assert [item["work_item_id"] for item in replay.json()["work_items"]].count("interpret-01") == 1


@pytest.mark.asyncio
async def test_quality_pass_creates_delivery_work_item_without_closing_case(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_delivery")
    for work_item_id, target, skill_name in [
        ("preflight-01", "data-steward", "project-preflight"),
        ("submit-01", "workflow-operator", "workflow-submit"),
    ]:
        response = await request_client.post(
            "/v1/cases/bioops_delivery/work-items",
            headers=headers("bioops-manager", "manager"),
            json={
                "work_item_id": work_item_id,
                "target": target,
                "objective": f"Run {skill_name}",
                "skill_name": skill_name,
            },
        )
        assert response.status_code == 201
    await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_delivery",
            "work_item_id": "preflight-01",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01"}],
        },
    )
    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={"case_id": "bioops_delivery", "action": "submit_task", "flow_id": "rna_seq"},
    )
    await request_client.post(
        "/v1/tasks",
        headers=headers("workflow-operator", "operator"),
        json={
            "case_id": "bioops_delivery",
            "work_item_id": "submit-01",
            "idempotency_key": "bioops-delivery-submit-v1",
            "approval_token": approval.json()["token"],
            "task": {"flow_id": "rna_seq", "name": "Delivery", "sample_sheet": [{"sample": "S01"}]},
        },
    )
    reconciled = await request_client.post(
        "/v1/cases/bioops_delivery/reconcile", headers=headers("bioops-manager", "manager")
    )
    quality = await request_client.post(
        "/v1/tasks/task-001/quality-gate",
        headers=headers("quality-auditor", "auditor"),
        json={
            "case_id": "bioops_delivery",
            "work_item_id": "quality-01",
            "rule_version": "rna-qc-1.0",
            "decision": "passed",
            "summary": "Required result is available.",
        },
    )
    assert reconciled.status_code == 200
    assert quality.status_code == 200
    current = await request_client.get(
        "/v1/cases/bioops_delivery", headers=headers("bioops-manager", "manager")
    )
    assert current.json()["status"] == "delivery_ready"
    delivery = next(
        item for item in current.json()["work_items"] if item["work_item_id"] == "delivery-01"
    )
    assert delivery["target"] == "delivery-reporter"
    assert delivery["status"] == "pending"


@pytest.mark.asyncio
async def test_worker_inbox_and_case_view_are_scoped_to_the_assigned_identity(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_inbox")
    for work_item_id, target, skill_name in [
        ("preflight-01", "data-steward", "project-preflight"),
        ("quality-01", "quality-auditor", "quality-gate"),
    ]:
        assigned = await request_client.post(
            "/v1/cases/bioops_inbox/work-items",
            headers=headers("bioops-manager", "manager"),
            json={
                "work_item_id": work_item_id,
                "target": target,
                "objective": f"Run {skill_name}",
                "skill_name": skill_name,
                "context_refs": [{"kind": "project", "id": "project-1"}],
            },
        )
        assert assigned.status_code == 201
    preflight = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_inbox",
            "work_item_id": "preflight-01",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01"}],
        },
    )
    assert preflight.status_code == 200

    steward_inbox = await request_client.get(
        "/v1/work-items/assigned", headers=headers("data-steward", "steward")
    )
    auditor_inbox = await request_client.get(
        "/v1/work-items/assigned", headers=headers("quality-auditor", "auditor")
    )
    assert steward_inbox.status_code == 200
    assert auditor_inbox.status_code == 200
    assert [item["work_item"]["work_item_id"] for item in steward_inbox.json()["items"]] == []
    assert [item["work_item"]["work_item_id"] for item in auditor_inbox.json()["items"]] == [
        "quality-01"
    ]

    worker_case = await request_client.get(
        "/v1/cases/bioops_inbox", headers=headers("data-steward", "steward")
    )
    manager_case = await request_client.get(
        "/v1/cases/bioops_inbox", headers=headers("bioops-manager", "manager")
    )
    assert worker_case.status_code == 200
    assert manager_case.status_code == 200
    assert "requester_ref" not in worker_case.json()
    assert "preflight_input" not in worker_case.json()
    assert "task_specs" not in worker_case.json()
    assert [item["work_item_id"] for item in worker_case.json()["work_items"]] == ["preflight-01"]
    assert manager_case.json()["preflight_input"]["sample_sheet"] == [{"sample": "S01"}]


@pytest.mark.asyncio
async def test_manager_cannot_use_worker_inbox_endpoint(client) -> None:
    request_client, _ = client
    response = await request_client.get(
        "/v1/work-items/assigned", headers=headers("bioops-manager", "manager")
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_health_probes_validate_identity_and_worker_inbox_heartbeat(client) -> None:
    request_client, _ = client

    identity = await request_client.get(
        "/v1/health/identity", headers=headers("data-steward", "steward")
    )
    assert identity.status_code == 200
    assert identity.json() == {"status": "ok", "identity": "data-steward"}

    before = await request_client.get(
        "/v1/health/workers", headers=headers("bioops-manager", "manager")
    )
    assert before.status_code == 200
    assert not next(item for item in before.json()["workers"] if item["identity"] == "agent-code")[
        "active"
    ]

    inbox = await request_client.get(
        "/v1/work-items/assigned", headers=headers("agent-code", "code")
    )
    assert inbox.status_code == 200

    after = await request_client.get(
        "/v1/health/workers", headers=headers("bioops-manager", "manager")
    )
    agent_code = next(item for item in after.json()["workers"] if item["identity"] == "agent-code")
    assert agent_code["configured"] is True
    assert agent_code["active"] is True
    assert agent_code["last_seen_at"]
    assert after.json()["allowed_flows"] == ["rna_seq"]


@pytest.mark.asyncio
async def test_preflight_preserves_consultation_summary_as_non_blocking_evidence(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_consultation")
    response = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_consultation",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01"}],
            "consultation_summary": "优先核验样本质量，再进行差异设计。",
        },
    )

    assert response.status_code == 200
    assert response.json()["status"] == "passed"
    assert response.json()["next_actions"] == ["request_submission_approval"]
    assert response.json()["findings"][0]["code"] == "CONSULTATION_CONTEXT"

    case = await request_client.get(
        "/v1/cases/bioops_consultation", headers=headers("bioops-manager", "manager")
    )
    assert case.json()["status"] == "approval_pending"
    assert (
        case.json()["preflight_input"]["consultation_summary"]
        == "优先核验样本质量，再进行差异设计。"
    )

    events = await request_client.get(
        "/v1/cases/bioops_consultation/events", headers=headers("bioops-manager", "manager")
    )
    preflight_event = next(
        item for item in events.json()["events"] if item["event_type"] == "skill.finished"
    )
    assert preflight_event["payload"]["summary"] == "预检已引用会诊纪要并通过。"


@pytest.mark.asyncio
async def test_worker_claim_is_atomic_and_target_scoped(client) -> None:
    request_client, _ = client
    await create_case(request_client, "bioops_claim")
    assigned = await request_client.post(
        "/v1/cases/bioops_claim/work-items",
        headers=headers("bioops-manager", "manager"),
        json={
            "work_item_id": "claim-quality-01",
            "target": "quality-auditor",
            "objective": "Inspect the assigned task evidence",
            "skill_name": "quality-gate",
        },
    )
    assert assigned.status_code == 201

    wrong_worker = await request_client.post(
        "/v1/cases/bioops_claim/work-items/claim-quality-01/claim",
        headers=headers("data-steward", "steward"),
    )
    manager = await request_client.post(
        "/v1/cases/bioops_claim/work-items/claim-quality-01/claim",
        headers=headers("bioops-manager", "manager"),
    )
    assert wrong_worker.status_code == 403
    assert manager.status_code == 403

    claimed = await request_client.post(
        "/v1/cases/bioops_claim/work-items/claim-quality-01/claim",
        headers=headers("quality-auditor", "auditor"),
    )
    duplicate = await request_client.post(
        "/v1/cases/bioops_claim/work-items/claim-quality-01/claim",
        headers=headers("quality-auditor", "auditor"),
    )
    assert claimed.status_code == 200
    assert claimed.json()["status"] == "claimed"
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Work item is already claimed or completed"

    inbox = await request_client.get(
        "/v1/work-items/assigned", headers=headers("quality-auditor", "auditor")
    )
    assert inbox.status_code == 200
    assert inbox.json()["items"][0]["work_item"]["status"] == "claimed"


@pytest.mark.asyncio
async def test_standard_work_item_targets_come_from_flow_config(client, settings) -> None:
    """O5:flow YAML standard_work_items 经 capability snapshot 派生后,无需改 service 即可调度。"""
    settings.apply_capability_snapshot(
        {
            "allowed_flow_ids": ["rna_seq"],
            "flow_agent_map": {"rna_seq": "agent-rnaseq"},
            "flow_quality_gate_map": {"rna_seq": True},
            "flow_standard_work_items": {
                "rna_seq": {
                    "quality": "agent-viz",
                    "delivery": "agent-code",
                    "interpret": "agent-atacseq",
                }
            },
        }
    )
    request_client, _ = client
    await create_case(request_client, "bioops_swi")
    for work_item_id, target, skill_name in [
        ("preflight-01", "data-steward", "project-preflight"),
        ("submit-01", "workflow-operator", "workflow-submit"),
    ]:
        assigned = await request_client.post(
            "/v1/cases/bioops_swi/work-items",
            headers=headers("bioops-manager", "manager"),
            json={
                "work_item_id": work_item_id,
                "target": target,
                "objective": f"Run {skill_name}",
                "skill_name": skill_name,
            },
        )
        assert assigned.status_code == 201
    preflight = await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_swi",
            "work_item_id": "preflight-01",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01"}],
        },
    )
    assert preflight.status_code == 200
    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={"case_id": "bioops_swi", "action": "submit_task", "flow_id": "rna_seq"},
    )
    submitted = await request_client.post(
        "/v1/tasks",
        headers=headers("workflow-operator", "operator"),
        json={
            "case_id": "bioops_swi",
            "work_item_id": "submit-01",
            "idempotency_key": "bioops-swi-submit-v1",
            "approval_token": approval.json()["token"],
            "task": {"flow_id": "rna_seq", "name": "SWI", "sample_sheet": [{"sample": "S01"}]},
        },
    )
    assert submitted.status_code == 201

    reconciled = await request_client.post(
        "/v1/cases/bioops_swi/reconcile", headers=headers("bioops-manager", "manager")
    )
    assert reconciled.status_code == 200
    work_items = {item["work_item_id"]: item for item in reconciled.json()["work_items"]}
    # 配置化 target 生效:interpret/quality 不再使用硬编码缺省。
    assert work_items["interpret-01"]["target"] == "agent-atacseq"
    assert work_items["quality-01"]["target"] == "agent-viz"

    quality = await request_client.post(
        "/v1/tasks/task-001/quality-gate",
        headers=headers("agent-viz", "viz"),
        json={
            "case_id": "bioops_swi",
            "work_item_id": "quality-01",
            "rule_version": "rna-qc-1.0",
            "decision": "passed",
            "summary": "Configured target works.",
        },
    )
    assert quality.status_code == 200
    current = await request_client.get(
        "/v1/cases/bioops_swi", headers=headers("bioops-manager", "manager")
    )
    delivery = next(
        item for item in current.json()["work_items"] if item["work_item_id"] == "delivery-01"
    )
    assert delivery["target"] == "agent-code"
    closed = await request_client.post(
        "/v1/cases/bioops_swi/close",
        headers=headers("agent-code", "code"),
        json={"case_id": "bioops_swi", "quality_decision": "passed"},
    )
    assert closed.status_code == 200


@pytest.mark.asyncio
async def test_standard_work_item_targets_fall_back_to_legacy_defaults(client) -> None:
    """O5 迁移期兼容:snapshot 未声明 standard_work_items 时沿用硬编码缺省。"""
    request_client, _ = client
    await create_case(request_client, "bioops_swi_default")
    for work_item_id, target, skill_name in [
        ("preflight-01", "data-steward", "project-preflight"),
        ("submit-01", "workflow-operator", "workflow-submit"),
    ]:
        assigned = await request_client.post(
            "/v1/cases/bioops_swi_default/work-items",
            headers=headers("bioops-manager", "manager"),
            json={
                "work_item_id": work_item_id,
                "target": target,
                "objective": f"Run {skill_name}",
                "skill_name": skill_name,
            },
        )
        assert assigned.status_code == 201
    await request_client.post(
        "/v1/projects/project-1/preflight",
        headers=headers("data-steward", "steward"),
        json={
            "case_id": "bioops_swi_default",
            "work_item_id": "preflight-01",
            "flow_id": "rna_seq",
            "sample_sheet": [{"sample": "S01"}],
        },
    )
    approval = await request_client.post(
        "/v1/approvals",
        headers=headers("approval-authority", "approval"),
        json={"case_id": "bioops_swi_default", "action": "submit_task", "flow_id": "rna_seq"},
    )
    await request_client.post(
        "/v1/tasks",
        headers=headers("workflow-operator", "operator"),
        json={
            "case_id": "bioops_swi_default",
            "work_item_id": "submit-01",
            "idempotency_key": "bioops-swi-default-submit-v1",
            "approval_token": approval.json()["token"],
            "task": {"flow_id": "rna_seq", "name": "SWI default", "sample_sheet": [{"sample": "S01"}]},
        },
    )

    reconciled = await request_client.post(
        "/v1/cases/bioops_swi_default/reconcile", headers=headers("bioops-manager", "manager")
    )
    assert reconciled.status_code == 200
    work_items = {item["work_item_id"]: item for item in reconciled.json()["work_items"]}
    assert work_items["interpret-01"]["target"] == "agent-rnaseq"
    assert work_items["quality-01"]["target"] == "quality-auditor"


@pytest.mark.asyncio
async def test_query_case_facts_uses_integration_token_and_forwards_payload(settings) -> None:
    """F4 自省查询面：Bridge 内部客户端只转发，scope/denied 在平台端强制。"""
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/introspection/schema"):
            return httpx.Response(200, json={"document": "schema doc"})
        return httpx.Response(
            200,
            json={
                "case_id": "bioops_case1",
                "rows": [],
                "row_count": 0,
                "total_count": 0,
                "truncated": False,
                "aggregate": {},
            },
        )

    token_settings = settings.model_copy(
        update={
            "cygnusx_service_token": "",
            "cygnusx_api_key": "omh_restricted_key",
            "cygnusx_integration_token": "integration-secret",
        }
    )
    upstream = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="http://omic.test"
    )
    client = CygnusXClient(token_settings, upstream)
    result = await client.query_case_facts(
        case_id="bioops_case1",
        caller="manager",
        room_id="room-1",
        template="artifact_lineage",
        limit=20,
    )
    schema = await client.get_introspection_schema()
    await upstream.aclose()

    query_call, schema_call = calls
    assert query_call.url.path == "/api/v1/agent-teams/introspection/query"
    assert query_call.headers["x-integration-token"] == "integration-secret"
    assert "x-api-key" not in query_call.headers
    assert "authorization" not in query_call.headers
    body = json.loads(query_call.content)
    assert body == {
        "case_id": "bioops_case1",
        "caller": "manager",
        "room_id": "room-1",
        "template": "artifact_lineage",
        "limit": 20,
    }
    assert result["truncated"] is False
    assert schema_call.url.path == "/api/v1/agent-teams/introspection/schema"
    assert schema["document"] == "schema doc"

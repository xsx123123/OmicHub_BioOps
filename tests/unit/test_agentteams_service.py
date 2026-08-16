"""AgentTeams user proxy tests: browser-facing access stays requester-scoped."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from omichub.api.v1.agentteams import (
    AgentTeamsCaseCreateRequest,
    _is_chat_case_flow_allowed,
    create_case,
)
from omichub.application.services.agentteams_intent_router import IntentRoute
from omichub.application.services.agentteams_service import AgentTeamsService
from omichub.application.services.project_service import ProjectService
from omichub.core.config import Settings
from omichub.core.exceptions import BusinessError, NotFoundError


@pytest.fixture
def service() -> AgentTeamsService:
    return AgentTeamsService(
        Settings(
            agentteams_bridge_enabled=True,
            agentteams_bridge_url="http://bridge.test",
            agentteams_bridge_manager_token="manager-token",
            agentteams_bridge_data_steward_token="steward-token",
            agentteams_bridge_approval_token="approval-token",
            agentteams_bridge_workflow_operator_token="operator-token",
        )
    )


def test_direct_case_api_flow_guard_uses_configured_and_registry_flows(monkeypatch) -> None:
    monkeypatch.setattr(
        "omichub.api.v1.agentteams.get_settings",
        lambda: Settings(agentteams_chat_flow_whitelist="approved-flow"),
    )
    monkeypatch.setattr(
        "omichub.api.v1.agentteams.get_flow_registry",
        lambda: type("Registry", (), {"bridge_flow_ids": lambda self: {"registry-flow"}})(),
    )

    assert _is_chat_case_flow_allowed("approved-flow")
    assert _is_chat_case_flow_allowed("registry-flow")
    assert not _is_chat_case_flow_allowed("unapproved-flow")


@pytest.mark.asyncio
async def test_direct_case_api_rejects_project_not_owned_by_requester(monkeypatch) -> None:
    request = AgentTeamsCaseCreateRequest(
        project_id=str(uuid4()),
        intent="bulk_rnaseq_delivery",
        flow_id="approved-flow",
        sample_sheet=[{"sample": "S01"}],
    )
    service = SimpleNamespace(create_case=AsyncMock())

    monkeypatch.setattr("omichub.api.v1.agentteams._is_chat_case_flow_allowed", lambda _flow: True)
    monkeypatch.setattr(
        "omichub.api.v1.agentteams.get_agentteams_capability_registry",
        lambda: SimpleNamespace(agent_for_flow=lambda _flow: "agent-rnaseq"),
    )

    async def reject_project(*_args, **_kwargs):
        raise NotFoundError("项目不存在")

    monkeypatch.setattr(ProjectService, "get_project", reject_project)

    with pytest.raises(NotFoundError, match="项目不存在"):
        await create_case(request, str(uuid4()), service, SimpleNamespace())
    service.create_case.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_case_api_rejects_non_whitelisted_flow_before_project_lookup(
    monkeypatch,
) -> None:
    request = AgentTeamsCaseCreateRequest(
        project_id=str(uuid4()),
        intent="bulk_rnaseq_delivery",
        flow_id="not-allowed",
        sample_sheet=[{"sample": "S01"}],
    )
    service = SimpleNamespace(create_case=AsyncMock())
    get_project = AsyncMock()
    monkeypatch.setattr(ProjectService, "get_project", get_project)
    monkeypatch.setattr("omichub.api.v1.agentteams._is_chat_case_flow_allowed", lambda _flow: False)

    with pytest.raises(BusinessError, match="白名单"):
        await create_case(request, str(uuid4()), service, SimpleNamespace())
    get_project.assert_not_awaited()
    service.create_case.assert_not_awaited()


@pytest.mark.asyncio
async def test_direct_case_api_creates_case_for_owned_project(monkeypatch) -> None:
    user_id = uuid4()
    project_id = uuid4()
    request = AgentTeamsCaseCreateRequest(
        project_id=str(project_id),
        intent="bulk_rnaseq_delivery",
        flow_id="approved-flow",
        sample_sheet=[{"sample": "S01"}],
        comparisons=[{"control": "control", "treatment": "treatment"}],
    )
    service = SimpleNamespace(
        create_case=AsyncMock(return_value={"case_id": "bioops_001"}),
        provision_case_room=AsyncMock(return_value=None),
    )
    get_project = AsyncMock(return_value={"id": str(project_id)})
    monkeypatch.setattr(ProjectService, "get_project", get_project)
    monkeypatch.setattr("omichub.api.v1.agentteams._is_chat_case_flow_allowed", lambda _flow: True)
    monkeypatch.setattr(
        "omichub.api.v1.agentteams.get_agentteams_capability_registry",
        lambda: SimpleNamespace(agent_for_flow=lambda _flow: "agent-rnaseq"),
    )

    response = await create_case(request, str(user_id), service, SimpleNamespace())

    assert response == {"case_id": "bioops_001"}
    get_project.assert_awaited_once_with(user_id, project_id)
    service.create_case.assert_awaited_once()
    assert service.create_case.await_args.kwargs["project_id"] == str(project_id)
    assert service.create_case.await_args.kwargs["requester_ref"] == str(user_id)


@pytest.mark.asyncio
async def test_direct_case_api_binds_created_case_to_chat_session(monkeypatch) -> None:
    user_id = uuid4()
    project_id = uuid4()
    session = SimpleNamespace(
        session_id="session-1",
        user_id=str(user_id),
        sandbox_meta={"project_id": str(project_id)},
        updated_at=None,
    )

    class Db:
        flushed = 0

        async def scalar(self, _query):
            return session

        async def flush(self):
            self.flushed += 1

    db = Db()
    request = AgentTeamsCaseCreateRequest(
        session_id="session-1",
        project_id=str(project_id),
        intent="bulk_rnaseq_delivery",
        flow_id="approved-flow",
    )
    service = SimpleNamespace(
        create_case=AsyncMock(
            return_value={"case_id": "bioops_001", "status": "planning_running"}
        ),
        provision_case_room=AsyncMock(return_value=None),
    )
    monkeypatch.setattr(ProjectService, "get_project", AsyncMock())
    monkeypatch.setattr("omichub.api.v1.agentteams._is_chat_case_flow_allowed", lambda _flow: True)
    monkeypatch.setattr(
        "omichub.api.v1.agentteams.get_agentteams_capability_registry",
        lambda: SimpleNamespace(agent_for_flow=lambda _flow: "agent-rnaseq"),
    )

    response = await create_case(request, str(user_id), service, db)

    assert response["case_id"] == "bioops_001"
    assert session.sandbox_meta["active_case_id"] == "bioops_001"
    assert session.sandbox_meta["agentteams_case_ids"] == ["bioops_001"]
    assert db.flushed == 1


@pytest.mark.asyncio
async def test_direct_case_api_allows_general_workspace_case(monkeypatch) -> None:
    user_id = uuid4()
    request = AgentTeamsCaseCreateRequest(
        intent="build a treeplot from fasta files",
        context_refs=[{"kind": "file", "id": "tree-a.fa"}, {"kind": "file", "id": "tree-b.fa"}],
    )
    service = SimpleNamespace(
        create_case=AsyncMock(return_value={"case_id": "general_001"}),
        provision_case_room=AsyncMock(return_value=None),
    )

    response = await create_case(request, str(user_id), service, SimpleNamespace())

    assert response == {"case_id": "general_001"}
    assert service.create_case.await_args.kwargs["project_id"] is None
    assert service.create_case.await_args.kwargs["context_refs"] == [
        {"kind": "file", "id": "tree-a.fa"},
        {"kind": "file", "id": "tree-b.fa"},
    ]
    assert service.create_case.await_args.kwargs["flow_id"] is None
    assert service.create_case.await_args.kwargs["sample_sheet"] is None


@pytest.mark.asyncio
async def test_get_case_rejects_other_requester(service: AgentTeamsService, monkeypatch) -> None:
    async def fake_request(path: str, **kwargs):
        assert path == "/v1/cases/case-other"
        return {"case_id": "case-other", "requester_ref": "other-user"}

    monkeypatch.setattr(service, "_request", fake_request)

    with pytest.raises(BusinessError, match="无权查看"):
        await service.get_case("case-other", "current-user")


@pytest.mark.asyncio
async def test_create_case_starts_planning_with_the_selected_flow(
    service: AgentTeamsService, monkeypatch
) -> None:
    captured: list[tuple[str, dict]] = []

    async def fake_request(path: str, **kwargs):
        captured.append((path, kwargs))
        return {"case_id": "bioops_001", "requester_ref": "current-user"}

    monkeypatch.setattr(service, "_request", fake_request)

    response = await service.create_case(
        case_id="bioops_001",
        project_id="project-1",
        intent="bulk_rnaseq_delivery",
        requester_ref="current-user",
        flow_id="rna_seq",
        sample_sheet=[{"sample": "S01", "group": "control"}],
        comparisons=[{"control": "control", "treatment": "treatment"}],
    )

    assert response["requester_ref"] == "current-user"
    assert captured == [
        (
            "/v1/cases",
            {
                "method": "POST",
                "json": {
                    "case_id": "bioops_001",
                    "project_ref": {"kind": "project", "id": "project-1"},
                    "intent": "bulk_rnaseq_delivery",
                    "requester_ref": "current-user",
                    "execution_mode": "cluster_case",
                    "flow_id": "rna_seq",
                },
            },
        ),
    ]


@pytest.mark.asyncio
async def test_create_general_case_uses_file_context_without_project(
    service: AgentTeamsService, monkeypatch
) -> None:
    captured: list[tuple[str, dict]] = []

    async def fake_request(path: str, **kwargs):
        captured.append((path, kwargs))
        return {"case_id": "general_001", "requester_ref": "current-user"}

    monkeypatch.setattr(service, "_request", fake_request)
    monkeypatch.setattr(
        "omichub.application.services.agentteams_service.infer_intent_route",
        lambda _intent: None,
    )

    await service.create_case(
        case_id="general_001",
        project_id=None,
        context_refs=[{"kind": "file", "id": "fasta-a"}, {"kind": "file", "id": "fasta-b"}],
        intent="build a treeplot from two fasta files",
        requester_ref="current-user",
        flow_id=None,
    )

    assert captured[0][1]["json"] == {
        "case_id": "general_001",
        "context_refs": [{"kind": "file", "id": "fasta-a"}, {"kind": "file", "id": "fasta-b"}],
        "intent": "build a treeplot from two fasta files",
        "requester_ref": "current-user",
        "execution_mode": "cluster_case",
        "lead_planner": None,
    }


@pytest.mark.asyncio
async def test_create_chat_case_routes_rnaseq_intent_to_flow_analyst(
    service: AgentTeamsService, monkeypatch
) -> None:
    captured: list[tuple[str, dict]] = []

    async def fake_request(path: str, **kwargs):
        captured.append((path, kwargs))
        return {"case_id": "bioops_002", "requester_ref": "current-user"}

    monkeypatch.setattr(service, "_request", fake_request)
    monkeypatch.setattr(
        "omichub.application.services.agentteams_service.infer_intent_route",
        lambda _intent: IntentRoute(flow_id="rna_seq", lead_planner="agent-rnaseq"),
    )

    await service.create_case(
        case_id="bioops_002",
        project_id=None,
        intent="帮我分析一批rna-seq数据",
        requester_ref="current-user",
        flow_id=None,
    )

    payload = captured[0][1]["json"]
    assert payload["lead_planner"] is None
    assert "flow_id" not in payload


@pytest.mark.asyncio
async def test_create_chat_case_falls_back_to_agent_code_when_router_fails(
    service: AgentTeamsService, monkeypatch
) -> None:
    captured: list[tuple[str, dict]] = []

    async def fake_request(path: str, **kwargs):
        captured.append((path, kwargs))
        return {"case_id": "bioops_003", "requester_ref": "current-user"}

    def _broken_router(_intent: str):
        raise RuntimeError("registry broken")

    monkeypatch.setattr(service, "_request", fake_request)
    monkeypatch.setattr(
        "omichub.application.services.agentteams_service.infer_intent_route",
        _broken_router,
    )

    await service.create_case(
        case_id="bioops_003",
        project_id=None,
        intent="帮我分析一批rna-seq数据",
        requester_ref="current-user",
        flow_id=None,
    )

    assert captured[0][1]["json"]["lead_planner"] is None


@pytest.mark.asyncio
async def test_list_cases_forwards_scoped_filters(service: AgentTeamsService, monkeypatch) -> None:
    captured = {}

    async def fake_request(path: str, **kwargs):
        captured["path"] = path
        captured.update(kwargs)
        return {"items": [], "total": 0, "next_cursor": None}

    monkeypatch.setattr(service, "_request", fake_request)

    await service.list_cases(
        "current-user",
        case_status="approval_pending",
        project_id="project-1",
        cursor="case-previous",
        limit=10,
    )

    assert captured == {
        "path": "/v1/cases",
        "params": {
            "requester_ref": "current-user",
            "limit": 10,
            "status": "approval_pending",
            "project_id": "project-1",
            "cursor": "case-previous",
        },
    }


@pytest.mark.asyncio
async def test_case_event_stream_checks_owner_before_connecting_to_bridge(
    service: AgentTeamsService, monkeypatch
) -> None:
    async def fake_owner(case_id: str, requester_ref: str):
        assert (case_id, requester_ref) == ("bioops_001", "current-user")
        return {"case_id": case_id, "requester_ref": requester_ref}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        async def aiter_lines(self):
            yield 'data: {"event_id":"evt-1","event_type":"case.created"}'

    class FakeStream:
        async def __aenter__(self):
            return FakeResponse()

        async def __aexit__(self, *_args):
            return None

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs["base_url"] == "http://bridge.test"

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def stream(self, method: str, path: str, **kwargs):
            assert method == "GET"
            assert path == "/v1/cases/bioops_001/events/stream"
            assert kwargs["params"] == {"watch_seconds": 1, "cursor": "evt-0"}
            assert kwargs["headers"]["X-Bridge-Identity"] == "bioops-manager"
            return FakeStream()

    monkeypatch.setattr(service, "_get_case_for_requester", fake_owner)
    monkeypatch.setattr(
        "omichub.application.services.agentteams_service.httpx.AsyncClient", FakeClient
    )

    events = [
        event
        async for event in service.stream_case_events(
            "bioops_001", "current-user", cursor="evt-0", watch_seconds=1
        )
    ]

    assert events == [{"event_id": "evt-1", "event_type": "case.created"}]


@pytest.mark.asyncio
async def test_admin_resource_snapshot_groups_cases_by_team(
    service: AgentTeamsService, monkeypatch
) -> None:
    async def fake_health():
        return {"connection": {"connected": True}, "workers": []}

    async def fake_request(path: str, **kwargs):
        assert path == "/v1/cases"
        assert kwargs == {"params": {"limit": 100}}
        return {
            "items": [
                {"case_id": "case-a", "team_id": "team-red", "preflight_input": {}},
                {"case_id": "case-b", "team_id": "team-red", "task_specs": {}},
                {"case_id": "case-c", "team_id": "team-blue"},
            ],
            "total": 3,
        }

    monkeypatch.setattr(service, "health_check", fake_health)
    monkeypatch.setattr(service, "_request", fake_request)

    snapshot = await service.admin_resource_snapshot()

    assert snapshot["total_cases"] == 3
    assert snapshot["teams"] == [
        {"team_id": "team-blue", "case_count": 1},
        {"team_id": "team-red", "case_count": 2},
    ]
    assert "preflight_input" not in snapshot["cases"][0]
    assert "task_specs" not in snapshot["cases"][1]


@pytest.mark.asyncio
async def test_health_check_merges_alias_worker_heartbeats_into_canonical_role(
    service: AgentTeamsService, monkeypatch
) -> None:
    """别名 identity 有心跳时，canonical role 不再被误报为缺心跳。"""

    async def fake_request(path: str, **kwargs):
        if path == "/healthz":
            return {"status": "ok"}
        if path == "/v1/health/workers":
            return {
                "workers": [
                    {
                        "identity": "agent-data",
                        "configured": True,
                        "active": False,
                        "last_seen_at": None,
                        "age_seconds": None,
                    },
                    {
                        "identity": "data-steward",
                        "configured": True,
                        "active": True,
                        "last_seen_at": "2026-08-12T16:00:00+00:00",
                        "age_seconds": 45,
                    },
                    {
                        "identity": "agent-qc",
                        "configured": True,
                        "active": True,
                        "last_seen_at": "2026-08-12T17:00:00+00:00",
                        "age_seconds": 10,
                    },
                    {
                        "identity": "quality-auditor",
                        "configured": False,
                        "active": False,
                        "last_seen_at": "2026-08-12T15:00:00+00:00",
                        "age_seconds": 300,
                    },
                ],
                "allowed_flows": [],
            }
        raise AssertionError(f"Unexpected request: {path}")

    async def fake_request_as(identity: str, token: str, path: str, **kwargs):
        return {"status": "ok", "identity": identity}

    monkeypatch.setattr(service, "_request", fake_request)
    monkeypatch.setattr(service, "_request_as", fake_request_as)
    monkeypatch.setattr(
        "omichub.application.services.agentteams_service.get_agentteams_capability_registry",
        lambda: SimpleNamespace(
            role_agent_map=lambda: {"agent-data": "agent-data", "agent-qc": "agent-qc"},
            role_alias_map=lambda: {
                "data-steward": "agent-data",
                "quality-auditor": "agent-qc",
            },
        ),
    )

    health = await service.health_check()

    assert health["workers"] == [
        {
            "identity": "agent-data",
            "configured": True,
            "active": True,
            "last_seen_at": "2026-08-12T16:00:00+00:00",
            "age_seconds": 45,
        },
        {
            "identity": "agent-qc",
            "configured": True,
            "active": True,
            "last_seen_at": "2026-08-12T17:00:00+00:00",
            "age_seconds": 10,
        },
    ]


@pytest.mark.asyncio
async def test_reconcile_approval_timeouts_uses_bridge_maintenance_endpoint(
    service: AgentTeamsService, monkeypatch
) -> None:
    async def fake_request(path: str, **kwargs):
        assert path == "/v1/maintenance/approval-timeouts"
        assert kwargs == {"method": "POST"}
        return {"scanned": 2, "reminded": 1, "cancelled": 1}

    monkeypatch.setattr(service, "_request", fake_request)

    assert await service.reconcile_approval_timeouts() == {
        "scanned": 2,
        "reminded": 1,
        "cancelled": 1,
    }


@pytest.mark.asyncio
async def test_case_owner_approval_submits_with_separate_bridge_identities(
    service: AgentTeamsService, monkeypatch
) -> None:
    requests: list[tuple[str, dict]] = []

    async def fake_request(path: str, **kwargs):
        requests.append((path, kwargs))
        if path == "/v1/cases/bioops_001":
            return {
                "case_id": "bioops_001",
                "requester_ref": "current-user",
                "status": "approval_pending",
                "flow_id": "rna_seq",
                "project_ref": {"kind": "project", "id": "project-1"},
                "preflight_input": {
                    "flow_id": "rna_seq",
                    "sample_sheet": [{"sample": "S01", "group": "control"}],
                    "comparisons": [{"control": "control", "treatment": "treatment"}],
                },
            }
        return {"case_id": "bioops_001"}

    async def fake_request_as(identity: str, token: str, path: str, **kwargs):
        requests.append((path, {"identity": identity, "token": token, **kwargs}))
        if path == "/v1/approvals":
            return {"token": "short-lived-approval-token"}
        return {"work_item_id": "submit-01", "status": "queued"}

    monkeypatch.setattr(service, "_request", fake_request)
    monkeypatch.setattr(service, "_request_as", fake_request_as)

    result = await service.approve_and_submit_task(
        case_id="bioops_001",
        requester_ref="current-user",
        task_name="RNA delivery",
    )

    assert result == {"work_item_id": "submit-01", "status": "queued"}
    assert requests[1][0] == "/v1/cases/bioops_001/work-items"
    assert requests[2] == (
        "/v1/approvals",
        {
            "identity": "approval-authority",
            "token": "approval-token",
            "method": "POST",
            "json": {
                "case_id": "bioops_001",
                "work_item_id": "submit-01",
                "action": "submit_task",
                "flow_id": "rna_seq",
            },
        },
    )
    assert requests[3] == (
        "/v1/approved-submissions",
        {
            "identity": "approval-authority",
            "token": "approval-token",
            "method": "POST",
            "json": {
                "case_id": "bioops_001",
                "work_item_id": "submit-01",
                "idempotency_key": "bioops_001-submit-v1",
                "approval_token": "short-lived-approval-token",
                "task": {
                    "flow_id": "rna_seq",
                    "name": "RNA delivery",
                    "sample_sheet": [{"sample": "S01", "group": "control"}],
                    "comparisons": [{"control": "control", "treatment": "treatment"}],
                    "execution_mode": "cluster",
                },
            },
        },
    )


@pytest.mark.asyncio
async def test_case_owner_approval_executes_frozen_general_plan(
    service: AgentTeamsService, monkeypatch
) -> None:
    requests: list[tuple[str, dict]] = []

    async def fake_request(path: str, **kwargs):
        requests.append((path, kwargs))
        return {"case_id": "general_001", "requester_ref": "current-user", "status": "approval_pending", "plan_hash": "abc"}

    async def fake_request_as(identity: str, token: str, path: str, **kwargs):
        requests.append((path, {"identity": identity, "token": token, **kwargs}))
        return {"token": "general-approval"} if path == "/v1/approvals" else {"status": "approved"}

    monkeypatch.setattr(service, "_request", fake_request)
    monkeypatch.setattr(service, "_request_as", fake_request_as)

    result = await service.approve_and_submit_task(case_id="general_001", requester_ref="current-user", task_name="ignored")

    assert result == {"status": "approved"}
    assert requests[1][0] == "/v1/approvals"
    assert requests[1][1]["json"] == {"case_id": "general_001", "action": "execute_plan"}
    assert requests[2][0] == "/v1/general-plans/execute"


@pytest.mark.asyncio
async def test_submit_rejects_case_without_passed_preflight(
    service: AgentTeamsService, monkeypatch
) -> None:
    async def fake_request(path: str, **kwargs):
        if path == "/v1/cases/bioops_001":
            return {
                "case_id": "bioops_001",
                "requester_ref": "current-user",
                "status": "preflight_blocked",
            }
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(service, "_request", fake_request)

    with pytest.raises(BusinessError, match="尚未满足人工审批"):
        await service.approve_and_submit_task(
            case_id="bioops_001",
            requester_ref="current-user",
            task_name="RNA delivery",
        )


@pytest.mark.asyncio
async def test_submit_quality_gate_issues_worker_token_and_calls_bridge(
    service: AgentTeamsService, monkeypatch
) -> None:
    requests: list[tuple[str, dict]] = []

    async def fake_request(path: str, **kwargs):
        requests.append((path, kwargs))
        if path == "/v1/cases/bioops_001":
            return {
                "case_id": "bioops_001",
                "requester_ref": "current-user",
                "status": "quality_running",
                "omic_task_ids": ["task-123"],
            }
        if path == "/v1/worker-tokens":
            return {"token": "qa-token", "record": {"id": "token-id-1"}}
        return {}

    async def fake_request_as(identity: str, token: str, path: str, **kwargs):
        requests.append((path, {"identity": identity, "token": token, **kwargs}))
        return {"case_id": "bioops_001", "task_id": "task-123", "decision": "manual_review"}

    monkeypatch.setattr(service, "_request", fake_request)
    monkeypatch.setattr(service, "_request_as", fake_request_as)

    result = await service.submit_quality_gate(
        case_id="bioops_001",
        requester_ref="current-user",
        task_id=None,
        decision="manual_review",
        rule_version="demo-rna-qc-1.0",
        summary="需要人工复核",
        evidence_refs=[{"kind": "task", "id": "task-123"}],
    )

    assert result["decision"] == "manual_review"
    assert requests[1] == (
        "/v1/worker-tokens",
        {"method": "POST", "json": {"identity": "quality-auditor", "ttl_seconds": 120, "note": "frontend quality gate submission"}},
    )
    assert requests[2] == (
        "/v1/tasks/task-123/quality-gate",
        {
            "identity": "quality-auditor",
            "token": "qa-token",
            "method": "POST",
            "json": {
                "case_id": "bioops_001",
                "rule_version": "demo-rna-qc-1.0",
                "decision": "manual_review",
                "summary": "需要人工复核",
                "evidence_refs": [{"kind": "task", "id": "task-123"}],
            },
        },
    )


@pytest.mark.asyncio
async def test_public_case_view_strips_internal_preflight_input(
    service: AgentTeamsService, monkeypatch
) -> None:
    async def fake_request(path: str, **kwargs):
        return {
            "case_id": "bioops_001",
            "requester_ref": "current-user",
            "intent": "创建一个数据质控团队：",
            "preflight_input": {"sample_sheet": [{"sample": "S01"}]},
            "task_specs": [{"sample_sheet": [{"sample": "S01"}]}],
        }

    monkeypatch.setattr(service, "_request", fake_request)

    case = await service.get_case("bioops_001", "current-user")

    assert "preflight_input" not in case
    assert "task_specs" not in case
    assert case["display_title"] == "数据质控团队"


def test_bridge_proxy_is_unavailable_without_all_server_settings() -> None:
    assert (
        AgentTeamsService(
            Settings(
                agentteams_bridge_enabled=False,
                agentteams_bridge_url="",
                agentteams_bridge_manager_token="",
                agentteams_bridge_data_steward_token="",
                agentteams_bridge_approval_token="",
                agentteams_bridge_workflow_operator_token="",
            )
        ).available
        is False
    )
    assert (
        AgentTeamsService(
            Settings(
                agentteams_bridge_enabled=True,
                agentteams_bridge_url="",
                agentteams_bridge_manager_token="",
                agentteams_bridge_data_steward_token="",
                agentteams_bridge_approval_token="",
                agentteams_bridge_workflow_operator_token="",
            )
        ).available
        is False
    )


def test_production_rejects_incomplete_agentteams_bridge_settings() -> None:
    with pytest.raises(ValueError, match="AgentTeams Bridge"):
        Settings(
            app_env="production",
            app_secret_key="app-secret",
            jwt_secret_key="jwt-secret",
            redis_password="redis-secret",
            ai_provider_key_encryption_key="encryption-secret",
            workflow_monitor_enabled=False,
            agentteams_bridge_enabled=True,
            agentteams_bridge_url="",
            agentteams_bridge_manager_token="",
            agentteams_bridge_data_steward_token="",
            agentteams_bridge_approval_token="",
            agentteams_bridge_workflow_operator_token="",
        )


def test_production_rejects_template_agentteams_manager_token() -> None:
    with pytest.raises(ValueError, match="AgentTeams Bridge"):
        Settings(
            app_env="production",
            app_secret_key="app-secret",
            jwt_secret_key="jwt-secret",
            redis_password="redis-secret",
            ai_provider_key_encryption_key="encryption-secret",
            workflow_monitor_enabled=False,
            agentteams_bridge_enabled=True,
            agentteams_bridge_url="http://bridge.test",
            agentteams_bridge_manager_token="replace-with-bioops-manager-token",
            agentteams_bridge_data_steward_token="steward-token",
            agentteams_bridge_approval_token="approval-token",
            agentteams_bridge_workflow_operator_token="operator-token",
        )


@pytest.mark.asyncio
async def test_refresh_case_reconciles_only_after_owner_check(
    service: AgentTeamsService, monkeypatch
) -> None:
    requests: list[tuple[str, dict]] = []

    async def fake_request(path: str, **kwargs):
        requests.append((path, kwargs))
        if path == "/v1/cases/bioops_001" and kwargs.get("method", "GET") == "GET":
            return {
                "case_id": "bioops_001",
                "requester_ref": "current-user",
                "status": "executing",
                "preflight_input": {"sample_sheet": [{"sample": "S01"}]},
                "task_specs": [{"sample_sheet": [{"sample": "S01"}]}],
            }
        if path == "/v1/cases/bioops_001/reconcile":
            assert kwargs["method"] == "POST"
            return {
                "case_id": "bioops_001",
                "requester_ref": "current-user",
                "status": "quality_running",
                "preflight_input": {"sample_sheet": [{"sample": "S01"}]},
                "task_specs": [{"sample_sheet": [{"sample": "S01"}]}],
            }
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(service, "_request", fake_request)

    case = await service.refresh_case("bioops_001", "current-user")

    assert case["status"] == "quality_running"
    assert "preflight_input" not in case
    assert "task_specs" not in case
    assert [path for path, _ in requests] == [
        "/v1/cases/bioops_001",
        "/v1/cases/bioops_001/reconcile",
    ]


@pytest.mark.asyncio
async def test_retry_case_issues_fresh_approval_then_calls_bridge_retry(
    service: AgentTeamsService, monkeypatch
) -> None:
    manager_requests: list[tuple[str, dict]] = []
    approval_requests: list[tuple[str, str, str, dict]] = []

    async def fake_request(path: str, **kwargs):
        manager_requests.append((path, kwargs))
        if path == "/v1/cases/bioops_001":
            return {
                "case_id": "bioops_001",
                "requester_ref": "current-user",
                "status": "execution_failed",
                "preflight_input": {"flow_id": "rna_seq"},
            }
        if path == "/v1/cases/bioops_001/retry":
            assert kwargs == {"method": "POST", "json": {"approval_token": "approval-v2"}}
            return {"case_id": "bioops_001", "status": "queued", "work_item_id": "submit-02"}
        raise AssertionError(f"Unexpected request: {path}")

    async def fake_request_as(identity: str, token: str, path: str, **kwargs):
        approval_requests.append((identity, token, path, kwargs))
        return {"token": "approval-v2"}

    monkeypatch.setattr(service, "_request", fake_request)
    monkeypatch.setattr(service, "_request_as", fake_request_as)

    result = await service.retry_case("bioops_001", "current-user")

    assert result["work_item_id"] == "submit-02"
    assert approval_requests == [
        (
            "approval-authority",
            "approval-token",
            "/v1/approvals",
            {
                "method": "POST",
                "json": {
                    "case_id": "bioops_001",
                    "action": "submit_task",
                    "flow_id": "rna_seq",
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_status_uses_bridge_health_not_only_configuration(
    service: AgentTeamsService, monkeypatch
) -> None:
    async def healthy_request(path: str, **kwargs):
        assert path == "/healthz"
        return {"status": "ok"}

    monkeypatch.setattr(service, "_request", healthy_request)
    assert await service.is_connected() is True

    async def failed_request(path: str, **kwargs):
        raise BusinessError("Agent 协作中心暂时不可用")

    monkeypatch.setattr(service, "_request", failed_request)
    assert await service.is_connected() is False


@pytest.mark.asyncio
async def test_connection_status_distinguishes_missing_configuration_from_unreachable_bridge(
    service: AgentTeamsService, monkeypatch
) -> None:
    async def failed_request(path: str, **kwargs):
        assert path == "/healthz"
        raise BusinessError("Agent 协作中心暂时不可用")

    monkeypatch.setattr(service, "_request", failed_request)
    assert await service.connection_status() == {
        "available": False,
        "enabled": True,
        "configured": True,
        "connected": False,
        "configuration_source": "environment",
        "reason": "bridge_unreachable",
    }

    unconfigured = AgentTeamsService(
        Settings(
            agentteams_bridge_enabled=False,
            agentteams_bridge_url="",
            agentteams_bridge_manager_token="",
            agentteams_bridge_data_steward_token="",
            agentteams_bridge_approval_token="",
            agentteams_bridge_workflow_operator_token="",
        )
    )
    assert await unconfigured.connection_status() == {
        "available": False,
        "enabled": False,
        "configured": False,
        "connected": False,
        "configuration_source": "environment",
        "reason": "disabled",
    }


@pytest.mark.asyncio
async def test_connection_status_reports_enabled_but_incomplete_configuration() -> None:
    service = AgentTeamsService(
        Settings(
            agentteams_bridge_enabled=True,
            agentteams_bridge_url="http://bridge.test",
            agentteams_bridge_manager_token="",
            agentteams_bridge_data_steward_token="",
            agentteams_bridge_approval_token="",
            agentteams_bridge_workflow_operator_token="",
        )
    )

    assert await service.connection_status() == {
        "available": False,
        "enabled": True,
        "configured": False,
        "connected": False,
        "configuration_source": "environment",
        "reason": "incomplete_configuration",
    }


def test_matrix_identity_for_requester_mapping() -> None:
    from omichub.application.services.agentteams_service import (
        matrix_identity_for_requester,
    )

    assert matrix_identity_for_requester("user-1") == "omichub-user-user-1"
    assert matrix_identity_for_requester("User@Example.com") == "omichub-user-user-example.com"
    assert matrix_identity_for_requester(" 张三 ") == "omichub-user"
    assert matrix_identity_for_requester("") == "omichub-user"
    assert matrix_identity_for_requester("u" * 200) == "omichub-user-" + "u" * 48


@pytest.mark.asyncio
async def test_provision_case_room_ensures_and_invites_requester_identity(monkeypatch) -> None:
    service = AgentTeamsService(
        Settings(
            agentteams_bridge_enabled=True,
            agentteams_bridge_url="http://bridge.test",
            agentteams_bridge_manager_token="manager-token",
        )
    )
    calls: dict[str, object] = {}

    class FakeGateway:
        available = True

        async def ensure_users(self, identities):
            calls["ensured"] = identities
            return {"ensured": identities}

        async def create_room(self, session_id, identities):
            calls["created"] = (session_id, identities)
            return {"room_id": "!room:test", "element_room_url": "http://element/#/room/!room:test"}

    monkeypatch.setattr(
        "omichub.application.services.agentteams_service.AgentTeamsRoomGatewayService",
        lambda *args, **kwargs: FakeGateway(),
    )
    service.post_case_evidence = AsyncMock(return_value={})
    monkeypatch.setattr(
        "omichub.application.services.agentteams_room_sync_service.record_room_binding",
        AsyncMock(),
    )

    room = await service.provision_case_room("case-1", requester_ref="User@Example.com")

    assert room is not None and room["room_id"] == "!room:test"
    assert calls["ensured"] == ["bioops-manager", "omichub-user", "omichub-user-user-example.com"]
    assert calls["created"] == (
        "case-1",
        ["bioops-manager", "omichub-user", "omichub-user-user-example.com"],
    )


@pytest.mark.asyncio
async def test_provision_case_room_survives_ensure_users_failure(monkeypatch) -> None:
    service = AgentTeamsService(
        Settings(
            agentteams_bridge_enabled=True,
            agentteams_bridge_url="http://bridge.test",
            agentteams_bridge_manager_token="manager-token",
        )
    )

    class FakeGateway:
        available = True

        async def ensure_users(self, identities):
            raise RuntimeError("ensure endpoint unavailable")

        async def create_room(self, session_id, identities):
            return {"room_id": "!room:test", "element_room_url": None}

    monkeypatch.setattr(
        "omichub.application.services.agentteams_service.AgentTeamsRoomGatewayService",
        lambda *args, **kwargs: FakeGateway(),
    )
    service.post_case_evidence = AsyncMock(return_value={})
    monkeypatch.setattr(
        "omichub.application.services.agentteams_room_sync_service.record_room_binding",
        AsyncMock(),
    )

    room = await service.provision_case_room("case-1", requester_ref="user-1")
    assert room is not None and room["room_id"] == "!room:test"


@pytest.mark.asyncio
async def test_delete_case_checks_owner_before_bridge_delete(
    service: AgentTeamsService, monkeypatch
) -> None:
    requests: list[tuple[str, dict]] = []

    async def fake_request(path: str, **kwargs):
        requests.append((path, kwargs))
        if path == "/v1/cases/bioops_001" and kwargs.get("method", "GET") == "GET":
            return {"case_id": "bioops_001", "requester_ref": "current-user"}
        if path == "/v1/cases/bioops_001" and kwargs.get("method") == "DELETE":
            return {"case_id": "bioops_001", "deleted": True}
        raise AssertionError(f"Unexpected request: {path}")

    monkeypatch.setattr(service, "_request", fake_request)

    result = await service.delete_case("bioops_001", "current-user")

    assert result == {"case_id": "bioops_001", "deleted": True}
    assert [(path, kwargs.get("method", "GET")) for path, kwargs in requests] == [
        ("/v1/cases/bioops_001", "GET"),
        ("/v1/cases/bioops_001", "DELETE"),
    ]


@pytest.mark.asyncio
async def test_delete_case_rejects_other_requester(
    service: AgentTeamsService, monkeypatch
) -> None:
    async def fake_request(path: str, **kwargs):
        assert path == "/v1/cases/case-other"
        return {"case_id": "case-other", "requester_ref": "other-user"}

    monkeypatch.setattr(service, "_request", fake_request)

    with pytest.raises(BusinessError, match="无权查看"):
        await service.delete_case("case-other", "current-user")


@pytest.mark.asyncio
async def test_start_chat_planning_creates_plan01_then_transitions_state(
    service: AgentTeamsService, monkeypatch
) -> None:
    requests: list[tuple[str, dict]] = []

    async def fake_request(path: str, **kwargs):
        requests.append((path, kwargs))
        return {}

    monkeypatch.setattr(service, "_request", fake_request)

    await service.start_chat_planning(
        case_id="bioops_001",
        requester_ref="user-1",
        objective="对这个 treefile 进行可视化并解释\n\n请输出 proposed_submission，结构含 work_items",
        context_refs=[{"kind": "file", "id": "tree-1"}],
    )

    assert [path for path, _ in requests] == [
        "/v1/cases/bioops_001/work-items",
        "/v1/cases/bioops_001/state",
    ]
    work_item = requests[0][1]["json"]
    assert work_item["work_item_id"] == "plan-01"
    assert work_item["target"] == "agent-code"
    assert work_item["skill_name"] == "planning_advice"
    assert work_item["read_only"] is True
    assert work_item["context_refs"] == [{"kind": "file", "id": "tree-1"}]
    assert "work_items" in work_item["objective"]
    assert requests[1][1] == {
        "method": "POST",
        "json": {"status": "planning_running", "reason": "chat_execution_intent"},
    }


@pytest.mark.asyncio
async def test_start_chat_planning_falls_back_to_workspace_ref_when_no_refs(
    service: AgentTeamsService, monkeypatch
) -> None:
    requests: list[tuple[str, dict]] = []

    async def fake_request(path: str, **kwargs):
        requests.append((path, kwargs))
        return {}

    monkeypatch.setattr(service, "_request", fake_request)

    await service.start_chat_planning(
        case_id="bioops_001",
        requester_ref="user-1",
        objective="把 result.csv 画成热图",
        context_refs=[],
    )

    assert requests[0][1]["json"]["context_refs"] == [{"kind": "workspace", "id": "user-1"}]


@pytest.mark.asyncio
async def test_start_chat_planning_swallows_bridge_failure(
    service: AgentTeamsService, monkeypatch
) -> None:
    async def failing_request(path: str, **kwargs):
        raise BusinessError("Agent 协作中心暂时不可用")

    monkeypatch.setattr(service, "_request", failing_request)

    await service.start_chat_planning(
        case_id="bioops_001",
        requester_ref="user-1",
        objective="把 result.csv 画成热图",
        context_refs=[],
    )


def test_bridge_client_cache_is_scoped_to_event_loop(service: AgentTeamsService) -> None:
    """Celery 任务用 asyncio.run() 每次新建事件循环；跨 loop 复用同一 httpx.AsyncClient
    会抛 "Event loop is closed"，因此缓存必须按 loop 隔离、loop 变化时重建。"""

    async def grab() -> object:
        return service._bridge_client()

    async def grab_twice() -> tuple[object, object]:
        return service._bridge_client(), service._bridge_client()

    first, same_loop = asyncio.run(grab_twice())
    assert first is same_loop

    second = asyncio.run(grab())
    assert second is not first

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport
from omichub_agent_gateway.app import create_app
from omichub_agent_gateway.client import OmicHubConsultationClient
from omichub_agent_gateway.config import GatewaySettings


def headers() -> dict[str, str]:
    return {"X-Gateway-Identity": "bioops-manager", "X-Gateway-Token": "manager-secret"}


@pytest.fixture
def settings(tmp_path: Path) -> GatewaySettings:
    return GatewaySettings(
        omichub_base_url="http://omic.test",
        omichub_integration_token="integration-token",
        audit_log_path=str(tmp_path / "gateway-audit.jsonl"),
        request_timeout_seconds=0.05,
    )


def make_client(
    settings: GatewaySettings, handler: httpx.MockTransport
) -> tuple[httpx.AsyncClient, httpx.AsyncClient]:
    upstream = httpx.AsyncClient(transport=handler, base_url="http://omic.test")
    app = create_app(settings, OmicHubConsultationClient(settings, upstream))
    api = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://gateway.test")
    return api, upstream


def read_audit_log(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def test_production_gateway_requires_dedicated_integration_token() -> None:
    with pytest.raises(ValueError, match="集成令牌"):
        GatewaySettings(
            environment="production",
            omichub_integration_token="",
            identities="bioops-manager:manager-secret",
        )


def test_production_gateway_accepts_dedicated_integration_token() -> None:
    settings = GatewaySettings(
        environment="production",
        omichub_integration_token="integration-secret",
        identities="bioops-manager:manager-secret",
        state_store_url="redis://localhost:6379/0",
    )

    assert settings.omichub_integration_token == "integration-secret"
    capabilities, tools = settings.agent_policy_map()["agent-data"]
    assert capabilities == {"project-preflight", "workspace_execution"}
    assert tools == {
        "task_result_summary",
        "task_file_preview",
        "workspace_file_preview",
        "workspace_read_file",
        "task_compare_metrics",
        "rule_threshold_lookup",
    }
    assert settings.agent_policy_map()["agent-qc"] == (
        {"quality-gate", "workspace_execution"},
        tools,
    )
    assert settings.agent_policy_map()["agent-delivery"] == (
        {"delivery-pack", "workspace_execution"},
        tools,
    )


def test_gateway_static_policies_match_yaml_workspace_execution_declarations() -> None:
    """Static fallback policies must mirror data/ai/*.yaml execution_modes declarations."""
    policies = GatewaySettings().agent_policy_map()
    declared = {
        "agent-rnaseq",
        "agent-scrna",
        "agent-viz",
        "agent-code",
        "agent-data",
        "agent-qc",
        "agent-delivery",
    }
    for agent_id in declared:
        assert "workspace_execution" in policies[agent_id][0], agent_id


def test_gateway_builds_policies_for_all_recruitable_agents_from_registry() -> None:
    settings = GatewaySettings()
    agent_ids = [
        "agent-data",
        "agent-rnaseq",
        "agent-atacseq",
        "agent-scrna",
        "agent-scrna-upstream",
        "agent-scrna-integration",
        "agent-scrna-advanced",
        "agent-code",
        "agent-viz",
        "agent-qc",
        "agent-delivery",
        "agent-cloud-ops",
        "agent-general",
        "agent-mcp-builder",
    ]
    settings.apply_capability_snapshot(
        {
            "agent_capabilities": {
                agent_id: {
                    "agent_id": agent_id,
                    "recruitable": True,
                    "planner_eligible": agent_id not in {"agent-qc", "agent-delivery"},
                    "worker_capability": f"{agent_id}-capability",
                    "execution_modes": ["workspace_execution"]
                    if agent_id in {"agent-code", "agent-viz"}
                    else ["readonly_consultation"],
                }
                for agent_id in agent_ids
            }
        }
    )

    policies = settings.agent_policy_map()

    assert set(agent_ids).issubset(policies)
    assert policies["agent-atacseq"][0] == {
        "agent-atacseq-capability",
        "planning_advice",
    }
    assert "workspace_execution" in policies["agent-code"][0]
    assert "planning_advice" not in policies["agent-qc"][0]


def test_discovered_and_static_policies_allow_workspace_read_file() -> None:
    """动态发现策略会覆盖静态策略，两处都必须放行 workspace_read_file（工作区只读工具）。"""
    static_policies = GatewaySettings().agent_policy_map()
    for agent_id in ("agent-code", "agent-viz", "agent-data", "agent-qc", "agent-delivery"):
        assert "workspace_read_file" in static_policies[agent_id][1], agent_id

    settings = GatewaySettings()
    settings.apply_capability_snapshot(
        {
            "agent_capabilities": {
                "agent-code": {
                    "agent_id": "agent-code",
                    "recruitable": True,
                    "planner_eligible": True,
                    "worker_capability": "agent-code-capability",
                    "execution_modes": ["workspace_execution"],
                }
            }
        }
    )
    discovered = settings.agent_policy_map()
    assert "workspace_read_file" in discovered["agent-code"][1]


def test_allowlisted_agent_returns_fixed_schema_and_strips_raw_response(
    settings: GatewaySettings,
) -> None:
    asyncio.run(_test_allowlisted_agent_returns_fixed_schema_and_strips_raw_response(settings))


async def _test_allowlisted_agent_returns_fixed_schema_and_strips_raw_response(
    settings: GatewaySettings,
) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "conclusion": "QC supports the stated interpretation.",
                "recommendations": ["Review dispersion diagnostics."],
                "evidence_refs": ["omic://reports/qc-1"],
                "risks": ["Small sample size."],
                "token_usage": 120,
            },
        )

    api, upstream = make_client(settings, httpx.MockTransport(handler))
    try:
        response = await api.post(
            "/v1/scientific-interpretation",
            headers=headers(),
            json={
                "case_id": "case-1",
                "requester_ref": "user-1",
                "agent_id": "agent-rnaseq",
                "question": "Interpret RNA-seq QC results.",
                "capability": "qc_advice",
                "evidence_refs": ["omic://reports/qc-1"],
                "requested_tools": ["ensembl.lookup_gene"],
            },
        )
    finally:
        await api.aclose()
        await upstream.aclose()

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "schema_version",
        "status",
        "conclusion",
        "recommendations",
        "evidence_refs",
        "risks",
        "agent_id",
        "schema_ver",
        "duration_ms",
        "token_usage",
        "error",
        "proposed_submission",
        "artifacts",
        "hard_gate",
    }
    assert body["status"] == "completed"
    assert body["schema_version"] == "1.0"
    assert calls[0].url.path == "/api/v1/agent-teams/consultations/scientific-interpretation"
    upstream_payload = json.loads(calls[0].content)
    assert upstream_payload["read_only"] is True
    assert upstream_payload["allow_task_actions"] is False
    assert upstream_payload["allow_file_write"] is False
    assert upstream_payload["allow_database_access"] is False
    assert upstream_payload["allow_shell"] is False
    assert upstream_payload["requester_ref"] == "user-1"
    assert calls[0].headers["X-Integration-Token"] == "integration-token"


def test_disallowed_tool_is_rejected_and_audited(settings: GatewaySettings) -> None:
    asyncio.run(_test_disallowed_tool_is_rejected_and_audited(settings))


async def _test_disallowed_tool_is_rejected_and_audited(settings: GatewaySettings) -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(500, json={"unexpected": True})

    api, upstream = make_client(settings, httpx.MockTransport(handler))
    try:
        response = await api.post(
            "/v1/scientific-interpretation",
            headers=headers(),
            json={
                "case_id": "case-2",
                "requester_ref": "user-2",
                "agent_id": "agent-rnaseq",
                "question": "Please submit a task after interpreting this result.",
                "capability": "result_interpretation",
                "requested_tools": ["tasks.submit"],
            },
        )
    finally:
        await api.aclose()
        await upstream.aclose()

    assert response.status_code == 200
    assert response.json()["status"] == "rejected"
    assert response.json()["error"]["code"] == "TOOL_NOT_ALLOWED"
    assert calls == []
    audit_text = read_audit_log(settings.audit_log_path)
    event = json.loads(audit_text.splitlines()[-1])
    assert event["event_type"] == "agent.consultation"
    assert event["payload"]["error_code"] == "TOOL_NOT_ALLOWED"
    assert "submit a task" in event["payload"]["question_summary"]


def test_call_and_token_limits_return_structured_rejections(tmp_path: Path) -> None:
    asyncio.run(_test_call_and_token_limits_return_structured_rejections(tmp_path))


async def _test_call_and_token_limits_return_structured_rejections(tmp_path: Path) -> None:
    settings = GatewaySettings(
        omichub_base_url="http://omic.test",
        audit_log_path=str(tmp_path / "gateway-audit.jsonl"),
        max_calls_per_case=1,
        max_tokens_per_case=100,
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"conclusion": "Result.", "token_usage": 101})

    api, upstream = make_client(settings, httpx.MockTransport(handler))
    payload = {
        "case_id": "case-3",
        "requester_ref": "user-3",
        "agent_id": "agent-rnaseq",
        "question": "Interpret results.",
        "capability": "interpretation",
    }
    try:
        token_limited = await api.post(
            "/v1/scientific-interpretation", headers=headers(), json=payload
        )
        call_limited = await api.post(
            "/v1/scientific-interpretation", headers=headers(), json=payload
        )
    finally:
        await api.aclose()
        await upstream.aclose()

    assert token_limited.json()["status"] == "rejected"
    assert token_limited.json()["error"]["code"] == "CASE_TOKEN_LIMIT_EXCEEDED"
    assert call_limited.json()["status"] == "rejected"
    assert call_limited.json()["error"]["code"] == "CASE_CALL_LIMIT_EXCEEDED"


def test_timeout_returns_manual_review_and_audit_event(settings: GatewaySettings) -> None:
    asyncio.run(_test_timeout_returns_manual_review_and_audit_event(settings))


def test_code_agent_is_allowlisted_for_read_only_consultation(settings: GatewaySettings) -> None:
    policy = settings.agent_policy_map()["agent-code"]

    assert "interpretation" in policy[0]
    assert "ensembl.lookup_gene" in policy[1]


async def _test_timeout_returns_manual_review_and_audit_event(settings: GatewaySettings) -> None:
    async def slow_handler(_: httpx.Request) -> httpx.Response:
        await asyncio.sleep(0.1)
        return httpx.Response(200, json={"conclusion": "Too late.", "token_usage": 1})

    api, upstream = make_client(settings, httpx.MockTransport(slow_handler))
    try:
        response = await api.post(
            "/v1/scientific-interpretation",
            headers=headers(),
            json={
                "case_id": "case-4",
                "requester_ref": "user-4",
                "agent_id": "agent-rnaseq",
                "question": "Interpret results.",
                "capability": "interpretation",
            },
        )
    finally:
        await api.aclose()
        await upstream.aclose()

    assert response.json()["status"] == "manual_review"
    assert response.json()["error"]["code"] == "UPSTREAM_TIMEOUT"
    audit_text = read_audit_log(settings.audit_log_path)
    event = json.loads(audit_text.splitlines()[-1])
    assert event["payload"]["status"] == "manual_review"


class FakeMatrixClient:
    def __init__(self) -> None:
        self.created: list[tuple[str, str, list[str]]] = []
        self.sent: list[dict[str, object]] = []
        self.ensured: list[list[str]] = []

    async def close(self) -> None:
        pass

    async def ensure_identities(self, identities: list[str]) -> None:
        self.ensured.append(list(identities))

    async def create_room(self, room_name: str, creator_identity: str, invitees: list[str]) -> str:
        self.created.append((room_name, creator_identity, invitees))
        return "!room:test"

    async def send_message(
        self, room_id: str, sender_identity: str, content: str, sender: dict, source: str
    ) -> str:
        self.sent.append(
            {
                "room_id": room_id,
                "identity": sender_identity,
                "content": content,
                "sender": sender,
                "source": source,
            }
        )
        return "$event-1"

    async def messages(self, room_id: str, since: str | None, limit: int):
        from omichub_agent_gateway.models import RoomMessage

        return (
            [
                RoomMessage(
                    event_id="$external",
                    room_id=room_id,
                    sender_identity="external",
                    content="hello",
                )
            ],
            "cursor-1",
        )

    async def stream_sync(self, room_id: str, since: str | None):
        from omichub_agent_gateway.models import RoomMessage

        yield (
            [
                RoomMessage(
                    event_id="$external",
                    room_id=room_id,
                    sender_identity="external",
                    content="hello",
                )
            ],
            "cursor-2",
        )


def test_matrix_room_endpoints_create_send_read_and_sync(tmp_path: Path) -> None:
    asyncio.run(_test_matrix_room_endpoints_create_send_read_and_sync(tmp_path))


async def _test_matrix_room_endpoints_create_send_read_and_sync(tmp_path: Path) -> None:
    settings = GatewaySettings(
        omichub_base_url="http://omic.test",
        audit_log_path=str(tmp_path / "gateway-audit.jsonl"),
        matrix_homeserver_url="http://matrix.test",
        matrix_service_token="matrix-secret",
        matrix_identities="bioops-manager=@manager:test,omichub-user=@user:test,agent-rnaseq=@rnaseq:test",
        element_base_url="http://element.test",
    )
    upstream = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})),
        base_url="http://omic.test",
    )
    matrix = FakeMatrixClient()
    app = create_app(settings, OmicHubConsultationClient(settings, upstream), matrix)  # type: ignore[arg-type]
    api = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://gateway.test")
    try:
        created = await api.post(
            "/rooms",
            headers=headers(),
            json={"session_id": "session-1", "identities": ["bioops-manager", "agent-rnaseq"]},
        )
        sent = await api.post(
            "/rooms/!room:test/messages",
            headers=headers(),
            json={
                "sender_identity": "agent-rnaseq",
                "content": "worker result",
                "sender": {"name": "RNA"},
            },
        )
        history = await api.get("/rooms/!room:test/messages", headers=headers())
        sync = await api.get("/rooms/!room:test/sync", headers=headers())
    finally:
        await api.aclose()
        await upstream.aclose()

    assert created.status_code == 200
    assert created.json()["room_id"] == "!room:test"
    assert created.json()["element_room_url"] == "http://element.test/#/room/!room:test"
    assert matrix.created == [
        ("omichub-session-session-1", "bioops-manager", ["bioops-manager", "agent-rnaseq"])
    ]
    assert sent.json() == {"event_id": "$event-1"}
    assert matrix.sent[0]["identity"] == "agent-rnaseq"
    assert history.json()["next_batch"] == "cursor-1"
    assert '"event_id":"$external"' in sync.text


def test_matrix_dynamic_user_mapping() -> None:
    settings = GatewaySettings(
        matrix_homeserver_url="http://matrix.test",
        matrix_service_token="matrix-secret",
        matrix_server_name="matrix.example.internal",
        matrix_identities="bioops-manager=@manager:test,omichub-user=@user:test",
    )
    assert settings.matrix_user_for_identity("bioops-manager") == "@manager:test"
    assert (
        settings.matrix_user_for_identity("omichub-user-u42")
        == "@omichub-user-u42:matrix.example.internal"
    )
    # 未知静态身份、非法 localpart、空前缀后缀均不映射
    assert settings.matrix_user_for_identity("agent-rnaseq") is None
    assert settings.matrix_user_for_identity("omichub-user-") is None
    assert settings.matrix_user_for_identity("omichub-user-Bad/Char") is None
    # 反向解析：动态账号 ↔ identity，供 sync 事件归源
    assert (
        settings.matrix_identity_by_user_dynamic("@omichub-user-u42:matrix.example.internal")
        == "omichub-user-u42"
    )
    assert settings.matrix_identity_by_user_dynamic("@manager:test") == "bioops-manager"
    assert settings.matrix_identity_by_user_dynamic("@omichub-user-u42:other.server") is None


def test_ensure_users_endpoint_provisions_dynamic_accounts(tmp_path: Path) -> None:
    asyncio.run(_test_ensure_users_endpoint(tmp_path))


async def _test_ensure_users_endpoint(tmp_path: Path) -> None:
    settings = GatewaySettings(
        omichub_base_url="http://omic.test",
        audit_log_path=str(tmp_path / "gateway-audit.jsonl"),
        matrix_homeserver_url="http://matrix.test",
        matrix_service_token="matrix-secret",
        matrix_server_name="test",
        matrix_identities="bioops-manager=@manager:test,omichub-user=@user:test",
    )
    upstream = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})),
        base_url="http://omic.test",
    )
    matrix = FakeMatrixClient()
    app = create_app(settings, OmicHubConsultationClient(settings, upstream), matrix)  # type: ignore[arg-type]
    api = httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://gateway.test")
    try:
        ensured = await api.post(
            "/users/ensure",
            headers=headers(),
            json={"identities": ["omichub-user-u42", "bioops-manager", "omichub-user-u42"]},
        )
        rejected = await api.post(
            "/users/ensure",
            headers=headers(),
            json={"identities": ["omichub-user-Bad/Char"]},
        )
        # 建房同样接受动态平台用户身份并供给其账号
        created = await api.post(
            "/rooms",
            headers=headers(),
            json={"session_id": "session-2", "identities": ["bioops-manager", "omichub-user-u42"]},
        )
    finally:
        await api.aclose()
        await upstream.aclose()

    assert ensured.status_code == 200
    assert ensured.json() == {"ensured": ["omichub-user-u42", "bioops-manager"]}
    assert matrix.ensured[0] == ["omichub-user-u42", "bioops-manager"]
    assert rejected.status_code == 503
    assert created.status_code == 200
    assert matrix.created[-1] == (
        "omichub-session-session-2",
        "bioops-manager",
        ["bioops-manager", "omichub-user-u42"],
    )

"""Default local AgentTeams contract path; no external service or credentials required."""

from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest


BRIDGE_PACKAGE = Path(__file__).parents[3] / "integrations" / "agentteams" / "bridge"
if str(BRIDGE_PACKAGE) not in sys.path:
    sys.path.insert(0, str(BRIDGE_PACKAGE))

from omichub_agentteams_bridge.app import create_app
from omichub_agentteams_bridge.config import BridgeSettings


def _headers(identity: str, token: str) -> dict[str, str]:
    return {"X-Bridge-Identity": identity, "X-Bridge-Token": token}


@pytest.mark.e2e
@pytest.mark.asyncio
async def test_default_case_dispatch_and_event_projection_contract(tmp_path: Path) -> None:
    settings = BridgeSettings(
        omichub_service_token="service-token",
        approval_signing_secret="test-signing-secret",
        identities="bioops-manager:manager,agent-code:code",
        role_agent_map="agent-code:agent-code",
        case_store_path=str(tmp_path / "cases.json"),
        worker_token_store_path=str(tmp_path / "tokens.json"),
        audit_log_path=str(tmp_path / "audit.jsonl"),
        manifest_dir=str(tmp_path / "manifests"),
    )
    app = create_app(settings)
    manager = _headers("bioops-manager", "manager")

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://bridge.test"
    ) as client:
        created = await client.post(
            "/v1/cases",
            headers=manager,
            json={
                "case_id": "default-e2e-case",
                "intent": "review controlled analysis",
                "requester_ref": "user-e2e",
                "context_refs": [{"kind": "project", "id": "project-e2e"}],
            },
        )
        assert created.status_code == 201
        assigned = await client.post(
            "/v1/cases/default-e2e-case/work-items",
            headers=manager,
            json={
                "work_item_id": "review-01",
                "target": "agent-code",
                "objective": "Review the controlled analysis.",
                "skill_name": "code-review",
                "context_refs": [{"kind": "project", "id": "project-e2e"}],
                "read_only": True,
            },
        )
        assert assigned.status_code == 201, assigned.text
        claimed = await client.post(
            "/v1/cases/default-e2e-case/work-items/review-01/claim",
            headers=_headers("agent-code", "code"),
        )
        assert claimed.status_code == 200
        events = await client.get(
            "/v1/cases/default-e2e-case/events?limit=100", headers=manager
        )
        assert events.status_code == 200
        event_types = [event["event_type"] for event in events.json()["events"]]
        assert "case.created" in event_types
        assert "work_item.assigned" in event_types
        assert "work_item.claimed" in event_types

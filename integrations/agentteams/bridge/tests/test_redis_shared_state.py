from __future__ import annotations

import asyncio
import os
from uuid import uuid4

import pytest

from cygnusx_agentteams_bridge.audit import AuditStore
from cygnusx_agentteams_bridge.case_store import CaseStore
from cygnusx_agentteams_bridge.config import BridgeSettings
from cygnusx_agentteams_bridge.models import CaseCreateRequest, ContextRef, WorkItemCreateRequest
from cygnusx_agentteams_bridge.service import BridgeService


REDIS_URL = os.getenv("AGENTTEAMS_TEST_REDIS_URL")
pytestmark = pytest.mark.skipif(not REDIS_URL, reason="set AGENTTEAMS_TEST_REDIS_URL to run Redis integration tests")


class FakeCygnusXClient:
    async def aclose(self) -> None:
        return None


def make_service(tmp_path, suffix: str, key_prefix: str) -> BridgeService:
    settings = BridgeSettings(
        cygnusx_service_token="service-token",
        approval_signing_secret="test-signing-secret",
        identities="bioops-manager:manager,agent-code:code",
        audit_log_path=str(tmp_path / f"{suffix}.audit.jsonl"),
        case_store_path=str(tmp_path / f"{suffix}.cases.json"),
        manifest_dir=str(tmp_path / "manifests"),
        state_store_url=REDIS_URL or "",
        state_store_key_prefix=key_prefix,
    )
    return BridgeService(
        settings,
        FakeCygnusXClient(),
        AuditStore(settings.audit_log_path, settings.state_store_url, f"{settings.state_store_key_prefix}:audit"),
        CaseStore(settings.case_store_path, settings.state_store_url, f"{settings.state_store_key_prefix}:cases"),
    )


@pytest.mark.asyncio
async def test_redis_state_is_visible_and_claim_is_atomic_across_bridge_replicas(tmp_path) -> None:
    key_prefix = f"cygnusx:agentteams:test:{uuid4().hex}"
    first = make_service(tmp_path, "first", key_prefix)
    second = make_service(tmp_path, "second", key_prefix)
    try:
        await first.create_case(
            CaseCreateRequest(
                case_id="redis-cluster-case",
                project_ref=ContextRef(kind="project", id="project-1"),
                intent="shared_state_test",
                requester_ref="user-1",
            ),
            "bioops-manager",
        )
        await first.assign_work_item(
            "redis-cluster-case",
            WorkItemCreateRequest(
                work_item_id="code-01",
                target="agent-code",
                objective="Review code.",
                skill_name="code-review",
            ),
            "bioops-manager",
        )

        inbox = await second.list_worker_inbox("agent-code")
        assert [item.work_item.work_item_id for item in inbox.items] == ["code-01"]

        results = await asyncio.gather(
            first.claim_work_item("redis-cluster-case", "code-01", "agent-code"),
            second.claim_work_item("redis-cluster-case", "code-01", "agent-code"),
            return_exceptions=True,
        )
        assert sum(result.status == "claimed" for result in results if not isinstance(result, Exception)) == 1
        assert sum(isinstance(result, Exception) for result in results) == 1

        events = await second.get_case_events("redis-cluster-case", "bioops-manager")
        assert {event["event_type"] for event in events.events} >= {
            "case.created",
            "work_item.assigned",
            "work_item.claimed",
        }
    finally:
        await first._audit.aclose()
        await first._cases.aclose()
        await second._audit.aclose()
        await second._cases.aclose()

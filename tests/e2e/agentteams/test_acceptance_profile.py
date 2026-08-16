"""Opt-in live acceptance test for the no-model AgentTeams worker profile."""

from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest

RUN_ACCEPTANCE = os.environ.get("AGENTTEAMS_ACCEPTANCE_E2E") == "1"
BRIDGE_URL = os.environ.get("AGENTTEAMS_E2E_BRIDGE_URL", "").rstrip("/")
MANAGER_TOKEN = os.environ.get("AGENTTEAMS_E2E_MANAGER_TOKEN", "")

pytestmark = pytest.mark.skipif(
    not (RUN_ACCEPTANCE and BRIDGE_URL and MANAGER_TOKEN),
    reason="set AGENTTEAMS_ACCEPTANCE_E2E=1 with Bridge URL and Manager token to run",
)


def _headers() -> dict[str, str]:
    return {
        "X-Bridge-Identity": "bioops-manager",
        "X-Bridge-Token": MANAGER_TOKEN,
    }


def _event_pairs(events: list[dict[str, object]]) -> set[tuple[str, str]]:
    return {
        (str(event.get("actor") or ""), str(event.get("event_type") or ""))
        for event in events
    }


def test_acceptance_profile_completes_three_readonly_experts() -> None:
    case_id = f"agentteams-acceptance-{uuid.uuid4().hex[:16]}"
    workers = {
        "agent-code": "acceptance-code",
        "agent-viz": "acceptance-viz",
        "agent-scrna": "acceptance-scrna",
    }
    with httpx.Client(base_url=BRIDGE_URL, headers=_headers(), timeout=10) as client:
        created = client.post(
            "/cases",
            json={
                "case_id": case_id,
                "intent": "controlled three-expert acceptance",
                "requester_ref": "agentteams-acceptance-e2e",
                "context_refs": [{"kind": "project", "id": "acceptance-project"}],
            },
        )
        created.raise_for_status()
        try:
            for identity, work_item_id in workers.items():
                assigned = client.post(
                    f"/cases/{case_id}/work-items",
                    json={
                        "work_item_id": work_item_id,
                        "target": identity,
                        "objective": "Complete the controlled read-only acceptance assignment.",
                        "skill_name": "acceptance-readonly",
                        "read_only": True,
                    },
                )
                assigned.raise_for_status()

            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                response = client.get(f"/cases/{case_id}/events")
                response.raise_for_status()
                events = response.json()["events"]
                pairs = _event_pairs(events)
                if all((identity, "skill.finished") in pairs for identity in workers):
                    break
                time.sleep(1)
            else:
                pytest.fail("acceptance workers did not complete all three assignments in 45 seconds")

            for identity in workers:
                assert (identity, "worker.inbox_polled") in pairs
                assert (identity, "work_item.claimed") in pairs
                assert (identity, "skill.finished") in pairs
        finally:
            cancelled = client.post(
                f"/cases/{case_id}/cancel",
                json={"reason": "controlled acceptance completed"},
            )
            assert cancelled.status_code in {200, 409}

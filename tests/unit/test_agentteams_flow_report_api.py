"""Authorization orchestration tests for the AgentTeams flow report endpoint."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cygnusx.api.v1 import agentteams as agentteams_api
from cygnusx.application.services.agentteams_flow_report_service import FlowReportArtifact


@pytest.mark.asyncio
async def test_member_flow_report_reads_bridge_data_as_room_owner(monkeypatch) -> None:
    room = SimpleNamespace(owner_id="owner-1", _agentteams_role="invited")
    monkeypatch.setattr(agentteams_api, "_get_turn_room", AsyncMock(return_value=room))
    monkeypatch.setattr(
        agentteams_api,
        "_get_report_events",
        AsyncMock(return_value=[{"event_id": "evt-1"}]),
    )
    captured: dict[str, object] = {}

    class FakeReportService:
        def __init__(self, _db) -> None:
            pass

        async def generate(self, **kwargs):
            captured.update(kwargs)
            evidence = await kwargs["publish_evidence"]({"artifact_id": "reports/flow.html"})
            assert evidence["event_id"] == "evt-report"
            return FlowReportArtifact(
                artifact_id="reports/flow.html",
                artifact_path="reports/flow.html",
                version_id="version-1",
                version_no=1,
                checksum_sha256="a" * 64,
                content_checksum_sha256="b" * 64,
                size_bytes=12,
                storage_uri="s3://agentteams-evidence/case-1/reports/flow.html",
                generated_at="2026-08-22T00:00:00+00:00",
            )

    monkeypatch.setattr(agentteams_api, "AgentTeamsFlowReportService", FakeReportService)
    service = SimpleNamespace(
        get_case=AsyncMock(return_value={"case_id": "case-1"}),
        post_case_evidence=AsyncMock(return_value={"event_id": "evt-report"}),
    )

    result = await agentteams_api.create_case_flow_report(
        "case-1", "member-2", service, AsyncMock()
    )

    assert service.get_case.await_args.args == ("case-1", "owner-1")
    assert captured["viewer_role"] == "invited"
    assert service.post_case_evidence.await_args.kwargs["event_type"] == "report.flow_exported"
    assert result["artifact_path"] == "reports/flow.html"

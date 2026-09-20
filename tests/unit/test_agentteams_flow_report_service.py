"""Regression tests for AgentTeams offline flow report exports."""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from cygnusx.application.services import agentteams_flow_report_service as report_module
from cygnusx.application.services.agentteams_flow_report_service import (
    AgentTeamsFlowReportService,
)


class FakeMinioStore:
    bucket = "agentteams-evidence"

    def __init__(self, turn: dict[str, object]) -> None:
        self._turn = turn
        self.report_bytes = b""
        self.report_path = ""

    def read_turn_record(self, *_args, **_kwargs) -> bytes:
        return json.dumps(self._turn, ensure_ascii=False).encode("utf-8")

    def put_case_object(self, _case_id: str, path: str, local_path, _content_type: str) -> str:
        self.report_path = path
        self.report_bytes = local_path.read_bytes()
        return f"s3://{self.bucket}/case-1/{path}"


class FakeLineageService:
    registered: dict[str, object] | None = None
    dependencies: dict[str, object] | None = None

    def __init__(self, _db) -> None:
        pass

    async def case_lineage(self, _case_id: str) -> dict[str, object]:
        return {
            "versions": [
                {
                    "version_id": "artifact-version-12345678",
                    "artifact_id": "work-1/result.tsv",
                    "checksum_sha256": "abc123",
                }
            ],
            "dependencies": [],
        }

    async def register_version(self, **kwargs):
        FakeLineageService.registered = kwargs
        return SimpleNamespace(id=uuid4(), version_no=2)

    async def register_dependencies(self, **kwargs):
        FakeLineageService.dependencies = kwargs
        return []


@pytest.mark.asyncio
async def test_member_flow_report_is_server_trimmed_and_lineage_registered(monkeypatch) -> None:
    turn = {
        "record_id": "record-12345678",
        "round_number": 2,
        "call_seq": 1,
        "agent_id": "agent-qc",
        "model": "model-a",
        "status": "ok",
        "messages": [{"role": "user", "content": "<secret prompt>"}],
        "reasoning_text": "<private reasoning>",
        "output_text": "<safe output>",
        "tool_calls": [{"name": "tool-a", "arguments": "{}"}],
    }
    store = FakeMinioStore(turn)
    db = AsyncMock()
    db.scalars = AsyncMock(
        return_value=[
            SimpleNamespace(
                s3_uri=(
                    "s3://agentteams-evidence/cases/case-1/"
                    "turns/work-1/0002/call-01-record-12345678.json"
                )
            )
        ]
    )
    monkeypatch.setattr(report_module, "AgentTeamsArtifactLineageService", FakeLineageService)
    async def run_sync(func, *args, **kwargs):
        return func(*args, **kwargs)

    monkeypatch.setattr(report_module.asyncio, "to_thread", run_sync)
    published = AsyncMock(return_value={"event_id": "evt-report-1"})

    artifact = await AgentTeamsFlowReportService(db, minio_store=store).generate(
        case_id="case-1",
        case={"case_id": "case-1", "intent": "<case title>", "status": "closed"},
        events=[
            {
                "event_id": "evt-message-12345678",
                "event_type": "room.user_message",
                "payload": {"payload": {"actor": "member-b", "content": "<hello>"}},
            }
        ],
        generated_by="member-b",
        viewer_role="invited",
        publish_evidence=published,
    )

    report_html = store.report_bytes.decode("utf-8")
    assert "<secret prompt>" not in report_html
    assert "<private reasoning>" not in report_html
    assert "已按权限裁剪" in report_html
    assert "&lt;safe output&gt;" in report_html
    assert "TRN-0002-01-record-1" in report_html
    assert "EVT-evt-mess" in report_html
    assert "ART-artifact" in report_html
    assert "完整事件 ID" in report_html
    assert "完整版本 ID" in report_html
    assert "data-copy" in report_html
    assert "环境快照" in report_html
    assert "content_checksum_sha256" in report_html
    assert artifact.artifact_path == store.report_path
    assert artifact.checksum_sha256 == hashlib.sha256(store.report_bytes).hexdigest()
    assert FakeLineageService.registered is not None
    assert FakeLineageService.registered["producing_event_id"] == "evt-report-1"
    assert FakeLineageService.registered["checksum_sha256"] == artifact.checksum_sha256
    assert FakeLineageService.dependencies is not None
    assert FakeLineageService.dependencies["downstream_artifact_id"] == artifact.artifact_id
    assert published.await_count == 1

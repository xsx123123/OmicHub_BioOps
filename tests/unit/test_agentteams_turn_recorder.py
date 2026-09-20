"""AgentTeams 过程记录的非阻塞与序列化回归测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cygnusx.application.services import agentteams_turn_recorder as recorder_module
from cygnusx.application.services.agentteams_turn_recorder import AgentTeamsTurnRecorder
from cygnusx.core.agentteams_context import agentteams_ctx_var


@pytest.mark.asyncio
async def test_schedule_freezes_payload_and_uses_required_object_key(monkeypatch) -> None:
    persisted = AsyncMock()
    monkeypatch.setattr(AgentTeamsTurnRecorder, "_persist", persisted)
    monkeypatch.setattr(
        recorder_module,
        "MinioStore",
        lambda probe=False: SimpleNamespace(bucket="agentteams-evidence"),
    )
    token = agentteams_ctx_var.set(
        {
            "case_id": "case-1",
            "work_item_id": "work-1",
            "round_number": 2,
            "call_seq": 3,
            "agent_id": "agent-qc",
        }
    )
    messages = [{"role": "user", "content": "original"}]
    try:
        uri = AgentTeamsTurnRecorder.schedule(
            messages=messages,
            output_text="answer",
            reasoning_text="reasoning",
            tool_calls=[{"name": "tool"}],
            usage={"total_tokens": 7},
            duration_ms=12,
            finish_reason="stop",
            status="completed",
            error=None,
            child_session_id="agentteams:case-1:child:run:0",
            provider="provider-a",
            model="model-a",
            sampling={"temperature": 0.3},
        )
        messages[0]["content"] = "mutated"
        await asyncio.sleep(0)
    finally:
        agentteams_ctx_var.reset(token)

    assert uri is not None
    assert "/cases/case-1/turns/work-1/0002/call-03-" in uri
    payload = persisted.await_args.kwargs["payload"]
    assert payload["messages"][0]["content"] == "original"
    assert persisted.await_args.kwargs["key"].startswith("turns/work-1/0002/call-03-")


@pytest.mark.asyncio
async def test_persist_swallows_object_storage_failure(monkeypatch) -> None:
    class FailingStore:
        bucket = "agentteams-evidence"

        def put_turn_record(self, *_args) -> None:
            raise OSError("minio unavailable")

    monkeypatch.setattr(recorder_module, "MinioStore", lambda probe=False: FailingStore())
    monkeypatch.setattr(
        recorder_module.asyncio,
        "to_thread",
        AsyncMock(side_effect=OSError("minio unavailable")),
    )
    payload = {
        "case_id": "case-1",
        "work_item_id": "work-1",
        "round_number": 1,
        "agent_id": "agent-qc",
        "status": "failed",
        "recorded_at": "2026-08-22T00:00:00+00:00",
    }

    await AgentTeamsTurnRecorder._persist(
        payload=payload,
        record_id="record-1",
        call_seq=1,
        key="turns/work-1/0001/call-01-record-1.json",
        uri="s3://agentteams-evidence/cases/case-1/turns/work-1/0001/call-01-record-1.json",
    )

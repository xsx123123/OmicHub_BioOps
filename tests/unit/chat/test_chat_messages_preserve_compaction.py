"""R1 contract: context compaction never changes the persisted message view."""

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from cygnusx.application.services.chat.session_management import ChatSessionManagement
from cygnusx.application.services.chat.dto_support import ChatDtoSupport
from cygnusx.infrastructure.database.models.chat import ChatMessageEventModel, ChatMessageModel


class _Result:
    def __init__(self, *, rows=None, scalar_rows=None):
        self._rows = list(rows or [])
        self._scalar_rows = list(scalar_rows or [])

    def all(self):
        return self._rows

    def scalars(self):
        return SimpleNamespace(all=lambda: self._scalar_rows)


class _ReadDb:
    def __init__(self, event, snapshot):
        self._results = [
            _Result(rows=[(event.message_id,)]),
            _Result(scalar_rows=[event]),
            _Result(rows=[(snapshot[0], snapshot[1])]),
        ]

    async def execute(self, _statement):
        return self._results.pop(0)


class _ReadSessions:
    def __init__(self, messages):
        self._messages = messages

    async def get_messages(self, _session_id):
        return self._messages


class _ReadService(ChatSessionManagement, ChatDtoSupport):
    pass


@pytest.mark.asyncio
async def test_get_messages_keeps_db_snapshot_when_compaction_event_exists() -> None:
    created_at = datetime.now(UTC)
    assistant_metadata = {
        "tool_invocations": [
            {"tool_call_id": "call-1", "ui_payload": {"stdout": "done"}}
        ],
        "usage": {"prompt_tokens": 120, "completion_tokens": 8, "total_tokens": 128},
    }
    messages = [
        ChatMessageModel(
            message_id="user-1",
            session_id="session-1",
            role="user",
            content="原始用户问题",
            content_type="text",
            status="complete",
            metadata_json={},
            created_at=created_at,
        ),
        ChatMessageModel(
            message_id="assistant-1",
            session_id="session-1",
            role="assistant",
            content="原始终态回答",
            content_type="text",
            status="complete",
            metadata_json=assistant_metadata,
            created_at=created_at,
        ),
    ]
    compaction_event = ChatMessageEventModel(
        message_id="assistant-1",
        seq=1,
        event_type="context_compacted",
        payload={"tokens_before": 1200, "tokens_after": 400},
    )
    service = object.__new__(_ReadService)
    service._sessions = _ReadSessions(messages)
    service._db = _ReadDb(compaction_event, ("assistant-1", assistant_metadata))

    result = await service.get_messages("session-1")

    assert [item.content for item in result] == ["原始用户问题", "原始终态回答"]
    assistant = result[1]
    assert assistant.metadata_json == assistant_metadata
    assert "tool_output_replay" not in assistant.metadata_json

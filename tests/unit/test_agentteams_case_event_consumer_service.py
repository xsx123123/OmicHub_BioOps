"""Bridge SSE Case event consumer cursor and projection tests."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

import omichub.application.services.agentteams_case_event_consumer_service as consumer_module
from omichub.application.services.agentteams_case_event_consumer_service import (
    AgentTeamsCaseEventConsumerService,
)
from omichub.infrastructure.database.models.chat import (
    AgentTeamsCaseCursorModel,
    ChatSessionModel,
)


class FakeDb:
    def __init__(self) -> None:
        self.session = SimpleNamespace(
            session_id="session-1",
            user_id="user-1",
            sandbox_meta={
                "agentteams_case_ids": ["case-1"],
                "agentteams_case_status": {"case-1": "executing"},
                "flow_id": "rna_seq",
            },
            updated_at=None,
        )
        self.cursor: AgentTeamsCaseCursorModel | None = None
        self.commits = 0

    async def scalar(self, query):
        entity = query.column_descriptions[0].get("entity")
        if entity is ChatSessionModel:
            return self.session
        assert entity is AgentTeamsCaseCursorModel
        return self.cursor

    def add(self, value: object) -> None:
        assert isinstance(value, AgentTeamsCaseCursorModel)
        self.cursor = value

    async def commit(self) -> None:
        self.commits += 1


class FakeAgentTeams:
    available = True

    def __init__(self, expected_cursor: str | None, events: list[dict[str, object]]) -> None:
        self.expected_cursor = expected_cursor
        self.events = events

    async def stream_case_events(self, case_id: str, requester_ref: str, **kwargs):
        assert case_id == "case-1"
        assert requester_ref == "user-1"
        assert kwargs == {"cursor": self.expected_cursor, "watch_seconds": 55}
        for event in self.events:
            yield event


@pytest.mark.asyncio
async def test_consumer_replays_from_persisted_cursor_and_projects(monkeypatch) -> None:
    db = FakeDb()
    published: list[dict[str, object]] = []

    async def publish(_session_id: str, event: dict[str, object]) -> None:
        published.append(event)

    monkeypatch.setattr(consumer_module, "publish_chat_case_event", publish)
    service = AgentTeamsCaseEventConsumerService(db)
    first = await service.consume(
        "session-1",
        "case-1",
        watch_seconds=55,
        agentteams=FakeAgentTeams(
            None,
            [
                {
                    "event_id": "event-1",
                    "event_type": "case.state_changed",
                    "case_id": "case-1",
                    "actor": "bioops-manager",
                    "payload": {"status": "delivery_ready"},
                }
            ],
        ),
    )
    second = await service.consume(
        "session-1",
        "case-1",
        watch_seconds=55,
        agentteams=FakeAgentTeams(
            "event-1",
            [
                {
                    "event_id": "event-2",
                    "event_type": "delivery.published",
                    "case_id": "case-1",
                    "actor": "delivery-reporter",
                    "payload": {},
                }
            ],
        ),
    )

    assert first["events"] == 1
    assert second["events"] == 1
    assert db.cursor is not None
    assert db.cursor.event_cursor == "event-2"
    assert db.session.sandbox_meta["agentteams_case_event_cursor"] == {"case-1": "event-2"}
    assert db.session.sandbox_meta["agentteams_case_cursor_migration"]["mode"] == "dual_write"
    assert db.session.sandbox_meta["agentteams_case_status"]["case-1"] == "delivery_ready"
    assert db.commits == 2
    assert published


@pytest.mark.asyncio
async def test_consumer_skips_terminal_case_without_opening_stream() -> None:
    db = FakeDb()
    db.session.sandbox_meta["agentteams_case_status"]["case-1"] = "closed"

    result = await AgentTeamsCaseEventConsumerService(db).consume(
        "session-1",
        "case-1",
        watch_seconds=55,
        agentteams=FakeAgentTeams(None, []),
    )

    assert result == {"events": 0, "projected": 0, "skipped": 1}
    assert db.cursor is None


@pytest.mark.asyncio
async def test_consumer_legacy_only_reuses_sandbox_cursor(monkeypatch) -> None:
    db = FakeDb()
    db.session.sandbox_meta["agentteams_case_event_cursor"] = {"case-1": "legacy-event"}
    monkeypatch.setattr(
        consumer_module,
        "get_settings",
        lambda: SimpleNamespace(agentteams_case_cursor_migration_mode="legacy_only"),
    )

    await AgentTeamsCaseEventConsumerService(db).consume(
        "session-1",
        "case-1",
        watch_seconds=55,
        agentteams=FakeAgentTeams(
            "legacy-event",
            [
                {
                    "event_id": "event-2",
                    "event_type": "delivery.published",
                    "case_id": "case-1",
                    "actor": "delivery-reporter",
                    "payload": {},
                }
            ],
        ),
    )

    assert db.cursor is not None
    assert db.cursor.event_cursor == "legacy-event"
    assert db.session.sandbox_meta["agentteams_case_event_cursor"] == {"case-1": "event-2"}

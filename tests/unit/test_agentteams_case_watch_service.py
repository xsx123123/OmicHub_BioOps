"""AgentTeams Case 状态回流的去重与失败隔离测试。"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

import cygnusx.application.services.agentteams_case_watch_service as watch_module
from cygnusx.application.services.agentteams_case_watch_service import (
    AgentTeamsCaseWatchService,
    _watchable_sessions_query,
)
from cygnusx.infrastructure.database.models.chat import (
    AgentTeamsCaseCursorModel,
    ChatMessageModel,
    ChatSessionModel,
)


class FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []
        self.flushes = 0
        self.cursor_states: dict[tuple[str, str], AgentTeamsCaseCursorModel] = {}

    def add(self, value: object) -> None:
        self.added.append(value)
        if isinstance(value, AgentTeamsCaseCursorModel):
            self.cursor_states[(value.session_id, value.case_id)] = value

    async def scalar(self, query):
        entity = query.column_descriptions[0].get("entity")
        if entity is AgentTeamsCaseCursorModel:
            params = query.compile().params
            session_id = next(value for key, value in params.items() if key.startswith("session_id"))
            case_id = next(value for key, value in params.items() if key.startswith("case_id"))
            return self.cursor_states.get((session_id, case_id))
        assert entity is ChatSessionModel
        return None

    async def flush(self) -> None:
        self.flushes += 1


@pytest.mark.unit
def test_watch_query_filters_sessions_without_case_bindings() -> None:
    statement = _watchable_sessions_query()
    sql = str(statement.compile(dialect=postgresql.dialect()))

    assert "sandbox_meta IS NOT NULL" in sql
    assert " ? " in sql


class FakeAgentTeams:
    async def refresh_case(self, case_id: str, requester_ref: str):
        assert case_id == "case-1"
        assert requester_ref == "user-1"
        return {"case_id": case_id, "intent": "RNA-seq 全流程交付", "status": "approval_pending"}

    async def get_case_events(self, case_id: str, requester_ref: str, **_kwargs):
        assert case_id == "case-1"
        assert requester_ref == "user-1"
        return {"events": [], "next_cursor": None}


@pytest.mark.asyncio
async def test_watch_notifies_each_case_status_once(monkeypatch) -> None:
    db = FakeDb()
    service = AgentTeamsCaseWatchService(db)
    published: list[tuple[str, dict[str, str]]] = []

    async def publish(session_id: str, event: dict[str, str]) -> None:
        published.append((session_id, event))

    monkeypatch.setattr(watch_module, "publish_chat_case_event", publish)
    session = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        sandbox_meta={
            "agentteams_case_ids": ["case-1"],
            "agentteams_case_status": {"case-1": "received"},
            "agentteams_case_notified": {"case-1": []},
            "agentteams_case_event_cursor": {"case-1": "event-0"},
        },
        updated_at=None,
        message_count=0,
        last_message_at=None,
    )

    first = await service._scan_session(session, FakeAgentTeams())
    second = await service._scan_session(session, FakeAgentTeams())

    assert first == {"scanned": 1, "notified": 1, "failed": 0}
    assert second == {"scanned": 1, "notified": 0, "failed": 0}
    assert len(db.added) == 2
    assert len(published) == 1
    state = db.cursor_states[("session-1", "case-1")]
    assert state.event_cursor == "event-0"
    assert state.notified_statuses == ["approval_pending"]
    assert session.sandbox_meta["agentteams_case_notified"] == {"case-1": ["approval_pending"]}
    assert session.sandbox_meta["agentteams_case_event_cursor"] == {"case-1": "event-0"}
    assert session.sandbox_meta["agentteams_case_cursor_migration"]["mode"] == "dual_write"


@pytest.mark.asyncio
async def test_watch_notifies_closed_flow_case_as_analysis_completion(monkeypatch) -> None:
    db = FakeDb()
    service = AgentTeamsCaseWatchService(db)
    published: list[dict[str, str]] = []

    async def publish(_session_id: str, event: dict[str, str]) -> None:
        published.append(event)

    monkeypatch.setattr(watch_module, "publish_chat_case_event", publish)
    session = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        sandbox_meta={
            "agentteams_case_ids": ["case-1"],
            "agentteams_case_status": {"case-1": "executing"},
        },
        updated_at=None,
        message_count=0,
        last_message_at=None,
    )

    class ClosedFlowAgentTeams:
        async def refresh_case(self, case_id: str, requester_ref: str):
            assert (case_id, requester_ref) == ("case-1", "user-1")
            return {
                "case_id": case_id,
                "intent": "小鼠单细胞分析",
                "status": "closed",
                "flow_id": "scrna",
            }

        async def get_case_events(self, *_args, **_kwargs):
            return {"events": [], "next_cursor": None}

    result = await service._scan_session(session, ClosedFlowAgentTeams())

    assert result == {"scanned": 1, "notified": 1, "failed": 0}
    assert published[0]["status"] == "closed"
    assert published[0]["completion_kind"] == "analysis_execution"
    notification = next(item for item in db.added if isinstance(item, ChatMessageModel))
    assert "分析执行完成" in notification.content


@pytest.mark.asyncio
async def test_watch_new_only_clears_legacy_cursor_fields(monkeypatch) -> None:
    db = FakeDb()
    service = AgentTeamsCaseWatchService(db)
    monkeypatch.setattr(
        watch_module,
        "get_settings",
        lambda: SimpleNamespace(agentteams_case_cursor_migration_mode="new_only"),
    )
    session = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        sandbox_meta={
            "agentteams_case_ids": ["case-1"],
            "agentteams_case_status": {"case-1": "received"},
            "agentteams_case_notified": {"case-1": ["approval_pending"]},
            "agentteams_case_event_cursor": {"case-1": "event-0"},
        },
        updated_at=None,
        message_count=0,
        last_message_at=None,
    )

    await service._scan_session(session, FakeAgentTeams())

    assert "agentteams_case_notified" not in session.sandbox_meta
    assert "agentteams_case_event_cursor" not in session.sandbox_meta
    assert session.sandbox_meta["agentteams_case_cursor_migration"]["mode"] == "new_only"


@pytest.mark.asyncio
async def test_watch_continues_when_one_case_read_fails() -> None:
    db = FakeDb()
    service = AgentTeamsCaseWatchService(db)
    session = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        sandbox_meta={"agentteams_case_ids": ["case-1"], "agentteams_case_status": {}},
        updated_at=None,
        message_count=0,
        last_message_at=None,
    )

    class BrokenAgentTeams:
        async def refresh_case(self, *_args, **_kwargs):
            raise RuntimeError("bridge unavailable")

    result = await service._scan_session(session, BrokenAgentTeams())

    assert result == {"scanned": 1, "notified": 0, "failed": 1}
    assert db.added == []
    assert session.sandbox_meta["agentteams_case_watch_failures"] == {"case-1": 1}


@pytest.mark.asyncio
async def test_watch_projects_sync_warning_after_three_consecutive_failures(monkeypatch) -> None:
    db = FakeDb()
    service = AgentTeamsCaseWatchService(db)
    published: list[dict[str, object]] = []

    async def publish(_session_id: str, event: dict[str, object]) -> None:
        published.append(event)

    monkeypatch.setattr(watch_module, "publish_chat_case_event", publish)
    session = SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        sandbox_meta={
            "agentteams_case_ids": ["case-1"],
            "agentteams_case_status": {},
            "agentteams_case_titles": {"case-1": "RNA-seq 失败恢复"},
        },
        updated_at=None,
        message_count=0,
        last_message_at=None,
    )

    class BrokenAgentTeams:
        async def refresh_case(self, *_args, **_kwargs):
            raise RuntimeError("bridge unavailable")

    results = [await service._scan_session(session, BrokenAgentTeams()) for _ in range(4)]

    assert [item["notified"] for item in results] == [0, 0, 1, 0]
    assert session.sandbox_meta["agentteams_case_watch_failures"] == {"case-1": 4}
    assert len(published) == 1
    assert published[0]["type"] == "room_speech"
    assert "连续 3 次同步失败" in str(published[0]["content"])


class _DeliveryGateAgentTeams:
    """delivery_ready 场景的最小 AgentTeams 替身：可物化交付产物并接收审计事件。"""

    def __init__(self, files: list[str], *, materialize_error: Exception | None = None) -> None:
        self._files = files
        self._materialize_error = materialize_error
        self.materialize_calls = 0
        self.evidence_events: list[dict] = []

    async def refresh_case(self, case_id: str, requester_ref: str):
        assert (case_id, requester_ref) == ("case-1", "user-1")
        return {"case_id": case_id, "intent": "RNA-seq 交付", "status": "delivery_ready"}

    async def get_case_events(self, *_args, **_kwargs):
        return {"events": [], "next_cursor": None}

    async def materialize_case_delivery(self, case_id: str, requester_ref: str, db):
        self.materialize_calls += 1
        if self._materialize_error is not None:
            raise self._materialize_error
        return {"output_dir": "", "files": list(self._files), "checksum_verification": []}

    async def post_case_evidence(self, case_id: str, **kwargs):
        self.evidence_events.append(kwargs)
        return {"event_id": "evt-gate"}


def _watch_session() -> SimpleNamespace:
    return SimpleNamespace(
        session_id="session-1",
        user_id="user-1",
        sandbox_meta={
            "agentteams_case_ids": ["case-1"],
            "agentteams_case_status": {"case-1": "executing"},
        },
        updated_at=None,
        message_count=0,
        last_message_at=None,
    )


@pytest.mark.asyncio
async def test_delivery_gate_blocks_and_reroutes_to_quality_blocked(tmp_path, monkeypatch) -> None:
    """delivery_ready 时交付门判定 BLOCKED → 转既有 quality_blocked 路径并带结构化原因。"""
    db = FakeDb()
    service = AgentTeamsCaseWatchService(db)
    published: list[dict] = []

    async def publish(_session_id: str, event: dict) -> None:
        published.append(event)

    monkeypatch.setattr(watch_module, "publish_chat_case_event", publish)
    good = tmp_path / "report.html"
    good.write_text("<html>ok</html>", encoding="utf-8")
    empty = tmp_path / "empty.html"
    empty.write_text("", encoding="utf-8")
    agentteams = _DeliveryGateAgentTeams([str(good), str(empty)])
    session = _watch_session()

    first = await service._scan_session(session, agentteams)

    assert first == {"scanned": 1, "notified": 1, "failed": 0}
    assert published[0]["status"] == "quality_blocked"
    notification = next(item for item in db.added if isinstance(item, ChatMessageModel))
    assert "quality_blocked" in notification.content
    assert "原因：" in notification.content
    assert notification.metadata_json["status_reason"]
    # 门判定投影为 quality.light_gate 审计事件（结构化留痕）
    assert agentteams.evidence_events[0]["event_type"] == "quality.light_gate"
    assert agentteams.evidence_events[0]["payload"]["decision"] == "BLOCKED"

    # 第二个 tick：Bridge 状态未变，命中缓存——不重复物化、不重复投影、不重复通知
    second = await service._scan_session(session, agentteams)
    assert second == {"scanned": 1, "notified": 0, "failed": 0}
    assert agentteams.materialize_calls == 1
    assert len(agentteams.evidence_events) == 1
    cached = session.sandbox_meta["agentteams_case_delivery_gate"]["case-1"]
    assert cached["gate"]["decision"] == "BLOCKED"
    assert session.sandbox_meta["agentteams_case_status"]["case-1"] == "quality_blocked"


@pytest.mark.asyncio
async def test_delivery_gate_passes_and_notifies_delivery_ready(tmp_path, monkeypatch) -> None:
    db = FakeDb()
    service = AgentTeamsCaseWatchService(db)
    published: list[dict] = []

    async def publish(_session_id: str, event: dict) -> None:
        published.append(event)

    monkeypatch.setattr(watch_module, "publish_chat_case_event", publish)
    good = tmp_path / "report.html"
    good.write_text("<html>ok</html>", encoding="utf-8")
    agentteams = _DeliveryGateAgentTeams([str(good)])

    result = await service._scan_session(_watch_session(), agentteams)

    assert result["notified"] == 1
    assert published[0]["status"] == "delivery_ready"
    assert agentteams.evidence_events[0]["payload"]["decision"] == "PASSED"


@pytest.mark.asyncio
async def test_delivery_gate_materialize_failure_falls_back(monkeypatch) -> None:
    """物化失败不阻断 watch 主流程：按既有路径放行 delivery_ready 通知。"""
    db = FakeDb()
    service = AgentTeamsCaseWatchService(db)
    published: list[dict] = []

    async def publish(_session_id: str, event: dict) -> None:
        published.append(event)

    monkeypatch.setattr(watch_module, "publish_chat_case_event", publish)
    agentteams = _DeliveryGateAgentTeams([], materialize_error=RuntimeError("bridge down"))

    result = await service._scan_session(_watch_session(), agentteams)

    assert result["notified"] == 1
    assert published[0]["status"] == "delivery_ready"
    assert agentteams.evidence_events == []

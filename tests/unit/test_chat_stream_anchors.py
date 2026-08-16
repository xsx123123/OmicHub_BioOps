"""流式聊天关键持久化锚点测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from omichub.application.services import chat_service
from omichub.application.services.chat_service import ChatService
from omichub.infrastructure.database.models.chat import ChatMessageModel


@pytest.mark.asyncio
async def test_stream_anchor_commits_async_database_session() -> None:
    db = MagicMock()
    db.commit = AsyncMock()

    await ChatService(db)._commit_stream_anchor()

    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_stream_anchor_skips_database_without_commit() -> None:
    await ChatService(object())._commit_stream_anchor()


@pytest.mark.asyncio
async def test_user_message_anchor_uses_independent_database_session(monkeypatch) -> None:
    class FakeResult:
        def __init__(self, session) -> None:
            self._session = session

        def scalar_one_or_none(self):
            return self._session

    class FakeDb:
        def __init__(self) -> None:
            self.added = []
            self.session = SimpleNamespace(message_count=0, last_message_at=None, updated_at=None)
            self.commit = AsyncMock()
            self.flush = AsyncMock()

        def add(self, value) -> None:
            self.added.append(value)

        async def execute(self, _statement):
            return FakeResult(self.session)

    class FakeContext:
        def __init__(self, db: FakeDb) -> None:
            self._db = db

        async def __aenter__(self) -> FakeDb:
            return self._db

        async def __aexit__(self, *_args) -> None:
            return None

    source_db = FakeDb()
    anchor_db = FakeDb()
    monkeypatch.setattr(chat_service, "AsyncSession", FakeDb)
    monkeypatch.setattr(chat_service, "get_session_factory", lambda: lambda: FakeContext(anchor_db))

    message = await ChatService(source_db)._record_user_message_anchor(
        "session-1", "persist me", metadata={"marker": True}
    )

    assert isinstance(message, ChatMessageModel)
    source_db.commit.assert_awaited_once()
    assert source_db.added == []
    anchor_db.commit.assert_awaited_once()
    assert len(anchor_db.added) == 1
    assert anchor_db.added[0].content == "persist me"
    assert anchor_db.added[0].metadata_json == {"marker": True}

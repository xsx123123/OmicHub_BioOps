"""SessionService 落库清洗：剥离 PostgreSQL 无法存储的 NUL 字符。

回归背景：模型输出/工具结果夹带 \\x00 时，asyncpg 抛 UntranslatableCharacterError
并回滚整个事务，导致整轮回复丢失（2026-09-03 线上 70708e98 会话实测）。
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from cygnusx.application.services.chat.session_service import (
    SessionService,
    _strip_pg_unsafe_text,
)


@pytest.mark.unit
def test_strip_pg_unsafe_text_removes_nul_recursively():
    payload = {
        "content": "abc\x00def",
        "nested": [{"tool_output": "line1\x00\nline2"}],
        "clean": "无 NUL 不动",
        "num": 42,
    }
    result = _strip_pg_unsafe_text(payload)
    assert result["content"] == "abcdef"
    assert result["nested"][0]["tool_output"] == "line1\nline2"
    assert result["clean"] == "无 NUL 不动"
    assert result["num"] == 42
    # 原对象不被原地修改
    assert payload["content"] == "abc\x00def"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_add_message_strips_nul_before_flush():
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None))
    )
    db.flush = AsyncMock()
    service = SessionService(db)

    message = await service.add_message(
        session_id="s1",
        role="assistant",
        content="结果：A\x00B",
        content_type="text",
        status="done",
        metadata={"tool_invocations": [{"result": "x\x00y"}]},
    )
    assert message.content == "结果：AB"
    assert message.metadata_json["tool_invocations"][0]["result"] == "xy"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_update_message_content_strips_nul():
    existing = SimpleNamespace(
        content="",
        status="streaming",
        metadata_json={"attachments": [{"name": "a\x00.csv"}]},
    )
    db = MagicMock()
    db.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=existing))
    )
    db.flush = AsyncMock()
    service = SessionService(db)

    await service.update_message_content(
        message_id="m1",
        content="正文\x00含 NUL",
        status="done",
        metadata={"usage": {"note": "o\x00k"}},
    )
    assert existing.content == "正文含 NUL"
    # 合并后的 metadata 整体清洗（含既有部分）
    assert existing.metadata_json["attachments"][0]["name"] == "a.csv"
    assert existing.metadata_json["usage"]["note"] == "ok"


@pytest.mark.unit
def test_strip_pg_unsafe_text_passthrough_normal_content():
    now = datetime.now(UTC)
    assert _strip_pg_unsafe_text("正常文本") == "正常文本"
    assert _strip_pg_unsafe_text(None) is None
    assert _strip_pg_unsafe_text(now) is now

"""上下文压缩审计的 defer/flush 行为测试（LangGraph 并发落库修复）"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from cygnusx.application.services.chat_service import ChatService


@pytest.mark.unit
async def test_compaction_audit_deferred_when_flag_set():
    """图 task 路径（_defer_compaction_audit=True）只暂存，不触碰请求级 session"""
    service = ChatService(db=AsyncMock())
    service._active_context_session_id = "sess-1"
    service._defer_compaction_audit = True

    await service._persist_context_compaction_audit(tokens=100, calibrated_tokens=90.0)

    assert service._deferred_compaction_audit is not None
    assert service._deferred_compaction_audit["tokens"] == 100
    service._db.execute.assert_not_called()


@pytest.mark.unit
async def test_compaction_audit_flushed_by_consumer():
    """消费协程收尾时统一落库暂存的审计，并清空暂存"""
    service = ChatService(db=AsyncMock())
    service._active_context_session_id = "sess-1"
    service._defer_compaction_audit = True
    await service._persist_context_compaction_audit(tokens=100, calibrated_tokens=90.0)

    # 模拟消费侧收尾：此时已不在图 task 内，直接 flush 暂存审计
    service._db.execute.return_value.scalar_one_or_none.return_value = None
    await service._flush_deferred_compaction_audit()

    assert service._deferred_compaction_audit is None
    service._db.execute.assert_called_once()


@pytest.mark.unit
async def test_compaction_audit_writes_inline_without_defer():
    """未开启 defer 时保持原行为：直接写请求级 session"""
    service = ChatService(db=AsyncMock())
    service._active_context_session_id = "sess-1"
    service._db.execute.return_value.scalar_one_or_none.return_value = None

    await service._persist_context_compaction_audit(tokens=50, calibrated_tokens=45.0)

    assert getattr(service, "_deferred_compaction_audit", None) is None
    service._db.execute.assert_called_once()

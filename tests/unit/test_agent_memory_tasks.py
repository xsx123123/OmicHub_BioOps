"""长期记忆异步摘要任务的无外部依赖契约测试。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from cygnusx.application.services.chat_service import ChatService
from cygnusx.infrastructure.celery_app.tasks.memory import (
    _conversation_text,
    _settle_session_memory_v2,
    _summary_content,
    is_agentteams_synthetic_session,
)


def test_conversation_text_excludes_empty_and_non_chat_messages() -> None:
    messages = [
        SimpleNamespace(role="user", content="我使用 GRCh38"),
        SimpleNamespace(role="tool", content="不应进入摘要"),
        SimpleNamespace(role="assistant", content="收到"),
        SimpleNamespace(role="assistant", content="  "),
    ]

    assert _conversation_text(messages) == "user: 我使用 GRCh38\nassistant: 收到"


def test_summary_content_is_single_line_and_bounded() -> None:
    response = {
        "choices": [
            {"message": {"content": "  用户使用\nGRCh38 作为参考基因组。  "}}
        ]
    }

    assert _summary_content(response) == "用户使用 GRCh38 作为参考基因组。"
    assert _summary_content({"choices": []}) == ""


# --- M0：settle 泄漏面封堵（AgentTeams 合成会话排除） ---


def _settings(**overrides) -> SimpleNamespace:
    base = {"memory_v2_enabled": True, "memory_settle_min_new_messages": 4}
    base.update(overrides)
    return SimpleNamespace(**base)


def _capture_enqueue(monkeypatch, settings) -> list:
    calls: list = []
    monkeypatch.setattr("cygnusx.core.config.get_settings", lambda: settings)
    monkeypatch.setattr(
        "cygnusx.infrastructure.task_queue.dispatcher.enqueue_task",
        lambda task, *args, **kwargs: calls.append(task),
    )
    return calls


def _session(**overrides) -> SimpleNamespace:
    base = {
        "session_id": "chat-normal-1",
        "mode": "chat",
        "status": "active",
        "message_count": 8,
        "agent_id": "agent-scrna",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "marker",
    [
        {"mode": "agentteams"},
        {"status": "system"},
        {"session_id": "agentteams:case-1"},
    ],
    ids=["mode_agentteams", "status_system", "session_id_prefix"],
)
async def test_settle_entries_skip_agentteams_synthetic_sessions(monkeypatch, marker) -> None:
    """三种排除标记各一条：两个投递点（删除/消息阈值）均不投递 settle。"""
    calls = _capture_enqueue(monkeypatch, _settings())
    service = ChatService(None)
    session = _session(**marker)

    await service._enqueue_memory_summary(session)
    await service._maybe_enqueue_memory_settle(session)

    assert calls == []


@pytest.mark.asyncio
async def test_settle_task_body_skips_agentteams_synthetic(monkeypatch) -> None:
    """任务体双保险：直接调用任务（绕过入口排除）命中标记即幂等返回。"""
    chat_session = _session(mode="agentteams", status="system", session_id="agentteams:case-9")
    fake_db = SimpleNamespace(scalar=AsyncMock(return_value=chat_session))

    class _Ctx:
        async def __aenter__(self) -> SimpleNamespace:
            return fake_db

        async def __aexit__(self, *exc: object) -> bool:
            return False

    monkeypatch.setattr(
        "cygnusx.infrastructure.database.session.get_session_factory",
        lambda: (lambda: _Ctx()),
    )

    result = await _settle_session_memory_v2("agentteams:case-9")

    assert result == {"status": "skipped_agentteams"}
    # 只读了会话行即返回，未继续取消息、未写 settlement、未动游标
    assert fake_db.scalar.await_count == 1


@pytest.mark.asyncio
async def test_normal_session_settle_behavior_unchanged(monkeypatch) -> None:
    """回归：普通会话两个投递点行为不变（v2 开启时正常入队）。"""
    calls = _capture_enqueue(monkeypatch, _settings())
    service = ChatService(None)

    await service._enqueue_memory_summary(_session())
    await service._maybe_enqueue_memory_settle(_session())

    assert len(calls) == 2


@pytest.mark.asyncio
async def test_v2_off_never_enqueues_settle(monkeypatch) -> None:
    """回归：v2 off 路径零变化——普通与合成会话都不投递。"""
    calls = _capture_enqueue(monkeypatch, _settings(memory_v2_enabled=False))
    service = ChatService(None)

    await service._enqueue_memory_summary(_session())
    await service._maybe_enqueue_memory_settle(_session())
    await service._enqueue_memory_summary(_session(mode="agentteams"))

    assert calls == []


def test_is_agentteams_synthetic_session_predicate() -> None:
    assert is_agentteams_synthetic_session(_session(mode="agentteams"))
    assert is_agentteams_synthetic_session(_session(status="system"))
    assert is_agentteams_synthetic_session(_session(session_id="agentteams:case-1"))
    assert not is_agentteams_synthetic_session(_session())

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from cygnusx.application.services import chat_service as chat_service_module
from cygnusx.application.services.chat.request_preparation import (
    AgentRequestPreparationFailure,
    PreparedAgentRequest,
    prepare_agent_request,
)


class _Builder:
    def __init__(self, context: object) -> None:
        self.context = context
        self.calls: list[dict[str, object]] = []

    async def assemble(self, *args: object, **kwargs: object) -> object:
        self.calls.append({"args": args, "kwargs": kwargs})
        return self.context


@pytest.mark.asyncio
async def test_preparation_uses_last_user_message_and_model_override() -> None:
    default_model = SimpleNamespace(
        name="Default", api_key="key", model="other", max_tokens=1024
    )
    override = SimpleNamespace(
        name="DeepSeek",
        api_key="override-key",
        model="deepseek-v3",
        max_tokens=8192,
    )
    context = SimpleNamespace(
        user_capabilities_customized=False,
        model_config=default_model,
        max_tokens=4096,
        agent=SimpleNamespace(name="Researcher"),
    )
    builder = _Builder(context)

    result = await prepare_agent_request(
        db=object(),
        agent_id="agent-1",
        user_id="user-1",
        messages=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "latest query"},
        ],
        mode="studio",
        model_id=uuid4(),
        deep_thinking=True,
        resolve_model=lambda _model_id: _async_value(override),
        context_builder_factory=lambda *_args, **_kwargs: builder,
        agent_service_factory=lambda _db: object(),
        settings_provider=lambda: SimpleNamespace(sensitive_keywords=["secret"]),
    )

    assert isinstance(result, PreparedAgentRequest)
    assert result.context is context
    assert result.model_config is override
    assert result.effective_max_tokens == 8192
    assert result.sensitive_keywords == ["secret"]
    assert builder.calls == [
        {
            "args": ("agent-1", "user-1"),
            "kwargs": {"user_message": "latest query", "mode": "studio"},
        }
    ]


@pytest.mark.asyncio
async def test_explicit_model_override_wins_over_user_capability_profile() -> None:
    profile_model = SimpleNamespace(
        name="Qwen profile default", api_key="profile-key", model="qwen", max_tokens=4096
    )
    selected_model = SimpleNamespace(
        name="DeepSeek v4", api_key="deepseek-key", model="deepseek-v4", max_tokens=8192
    )
    context = SimpleNamespace(
        user_capabilities_customized=True,
        model_config=profile_model,
        max_tokens=4096,
        agent=SimpleNamespace(name="Researcher"),
    )

    result = await prepare_agent_request(
        db=object(),
        agent_id="agent-1",
        user_id="user-1",
        messages=[{"role": "user", "content": "use the selected model"}],
        mode="chat",
        model_id=uuid4(),
        deep_thinking=False,
        resolve_model=lambda _model_id: _async_value(selected_model),
        context_builder_factory=lambda *_args, **_kwargs: _Builder(context),
        agent_service_factory=lambda _db: object(),
        settings_provider=lambda: SimpleNamespace(sensitive_keywords=[]),
    )

    assert isinstance(result, PreparedAgentRequest)
    assert result.model_config is selected_model


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("context", "model_id", "resolved_model", "message"),
    [
        (None, None, None, "Agent 不存在或已停用"),
        (
            SimpleNamespace(
                user_capabilities_customized=False,
                model_config=SimpleNamespace(
                    name="Default", api_key="key", model="default", max_tokens=1
                ),
                max_tokens=1,
                agent=SimpleNamespace(name="Researcher"),
            ),
            uuid4(),
            None,
            "指定的模型不存在或未启用",
        ),
        (
            SimpleNamespace(
                user_capabilities_customized=False,
                model_config=SimpleNamespace(
                    name="Default", api_key="key", model="default", max_tokens=1
                ),
                max_tokens=1,
                agent=SimpleNamespace(name="Researcher"),
            ),
            uuid4(),
            SimpleNamespace(name="Override", api_key="", model="default", max_tokens=1),
            "模型 'Override' 的 API Key 未配置，请联系管理员设置",
        ),
    ],
)
async def test_preparation_returns_streamable_model_errors(
    context: object,
    model_id: object,
    resolved_model: object,
    message: str,
) -> None:
    builder = _Builder(context)

    result = await prepare_agent_request(
        db=object(),
        agent_id="agent-1",
        user_id="user-1",
        messages=[],
        mode=None,
        model_id=model_id,
        deep_thinking=False,
        resolve_model=lambda _model_id: _async_value(resolved_model),
        context_builder_factory=lambda *_args, **_kwargs: builder,
        agent_service_factory=lambda _db: object(),
        settings_provider=lambda: SimpleNamespace(sensitive_keywords=[]),
    )

    assert result == AgentRequestPreparationFailure(message)


@pytest.mark.asyncio
async def test_chat_service_streams_preparation_failure_before_session_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = object.__new__(chat_service_module.ChatService)
    service._db = object()
    service._ensure_cookie_balance = AsyncMock(return_value=None)
    prepare_request = AsyncMock(
        return_value=AgentRequestPreparationFailure("指定的模型不存在或未启用")
    )
    monkeypatch.setattr(chat_service_module, "prepare_agent_request", prepare_request)

    chunks = [
        chunk
        async for chunk in service._stream_agent_chat_inner(
            user_id="user-1",
            agent_id="agent-1",
            messages=[{"role": "user", "content": "hello"}],
        )
    ]

    assert [(chunk.type, chunk.content) for chunk in chunks] == [
        ("error", "指定的模型不存在或未启用")
    ]
    prepare_request.assert_awaited_once()


async def _async_value(value: object) -> object:
    return value

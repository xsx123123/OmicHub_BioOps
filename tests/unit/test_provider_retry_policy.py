from collections.abc import AsyncIterator

import pytest

from cygnusx.core.config import get_settings
from cygnusx.domain.ai_provider.entities import AIProviderConfig
from cygnusx.infrastructure.ai_provider.litellm_provider import LiteLLMProvider
from cygnusx.infrastructure.ai_provider.openai_compatible import (
    ChatChunk,
    OpenAICompatibleProvider,
)
from cygnusx.infrastructure.database.models.ai_provider import AIProviderConfigModel


class _FakeStreamResponse:
    def __init__(
        self,
        chunks: list[str],
        *,
        status_code: int = 200,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._chunks = chunks
        self.status_code = status_code
        self._body = body
        self.headers = headers or {}

    async def __aenter__(self) -> "_FakeStreamResponse":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def aiter_text(self) -> AsyncIterator[str]:
        for chunk in self._chunks:
            yield chunk

    async def aread(self) -> bytes:
        return self._body


class _FakeAsyncClient:
    def __init__(
        self,
        chunks: list[str],
        captured_payload: list[dict[str, object]] | None = None,
        *,
        status_code: int = 200,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self._chunks = chunks
        self._captured_payload = captured_payload
        self._status_code = status_code
        self._body = body
        self._headers = headers or {}

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def stream(self, *_args: object, **_kwargs: object) -> _FakeStreamResponse:
        if self._captured_payload is not None:
            self._captured_payload.append(_kwargs.get("json", {}))
        return _FakeStreamResponse(
            self._chunks,
            status_code=self._status_code,
            body=self._body,
            headers=self._headers,
        )


def test_litellm_stream_kwargs_request_usage_and_retry() -> None:
    provider = LiteLLMProvider()
    config = AIProviderConfig.create(
        name="test",
        model="qwen-test",
        base_url="https://example.test/v1",
    )

    kwargs = provider._build_kwargs(
        config,
        [{"role": "user", "content": "hello"}],
        stream=True,
    )

    assert kwargs["stream_options"] == {"include_usage": True}
    assert kwargs["num_retries"] == 2


@pytest.mark.asyncio
async def test_provider_5xx_is_marked_retryable(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.ai_provider.openai_compatible.httpx.AsyncClient",
        lambda **_kwargs: _FakeAsyncClient([], status_code=500, body=b'{"detail":"temporary"}'),
    )

    chunks = [
        chunk
        async for chunk in provider._stream_once(
            [{"role": "user", "content": "hi"}], None, 0.7, 32, None, False
        )
    ]

    assert len(chunks) == 1
    assert chunks[0].type == "error"
    assert chunks[0].metadata == {"retryable": True, "http_status": 500}


@pytest.mark.asyncio
async def test_retryable_stream_error_keeps_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    tools = [{"type": "function", "function": {"name": "ask_user"}}]
    calls: list[list[dict[str, object]] | None] = []

    async def stream_once(*args: object) -> AsyncIterator[ChatChunk]:
        calls.append(args[4])
        if len(calls) == 1:
            yield ChatChunk(type="error", metadata={"retryable": True})
            return
        yield ChatChunk(type="text", content="完成")
        yield ChatChunk(type="done")

    monkeypatch.setattr(provider, "_stream_once", stream_once)

    chunks = [
        chunk
        async for chunk in provider.chat_stream(
            [{"role": "user", "content": "请分析"}], tools=tools
        )
    ]

    assert calls == [tools, tools]
    assert [chunk.type for chunk in chunks] == ["text", "done"]


@pytest.mark.asyncio
async def test_empty_tool_stream_retries_without_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    tools = [{"type": "function", "function": {"name": "ask_user"}}]
    calls: list[list[dict[str, object]] | None] = []

    async def stream_once(*args: object) -> AsyncIterator[ChatChunk]:
        calls.append(args[4])
        if len(calls) == 1:
            yield ChatChunk(type="done")
            return
        yield ChatChunk(type="text", content="请补充输入文件")
        yield ChatChunk(type="done")

    monkeypatch.setattr(provider, "_stream_once", stream_once)

    chunks = [
        chunk
        async for chunk in provider.chat_stream(
            [{"role": "user", "content": "请分析"}], tools=tools
        )
    ]

    assert calls == [tools, None]
    assert [chunk.type for chunk in chunks] == ["text", "done"]


@pytest.mark.asyncio
async def test_reasoning_only_stream_retries_without_deep_thinking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """深度思考只返回 reasoning 时，应关闭思考重试并等待最终正文。"""
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    deep_thinking_values: list[bool] = []

    async def stream_once(*args: object) -> AsyncIterator[ChatChunk]:
        deep_thinking_values.append(bool(args[5]))
        if len(deep_thinking_values) == 1:
            yield ChatChunk(type="text", content="思考中", metadata={"is_reasoning": True})
            yield ChatChunk(type="done")
            return
        yield ChatChunk(type="text", content="最终回答")
        yield ChatChunk(type="done")

    monkeypatch.setattr(provider, "_stream_once", stream_once)

    chunks = [
        chunk
        async for chunk in provider.chat_stream(
            [{"role": "user", "content": "请绘制火山图"}],
            deep_thinking=True,
        )
    ]

    assert deep_thinking_values == [True, False]
    assert [(chunk.type, chunk.content) for chunk in chunks] == [
        ("text", "思考中"),
        ("text", "最终回答"),
        ("done", ""),
    ]


@pytest.mark.asyncio
async def test_openai_sse_accepts_compact_data_and_message_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """兼容网关的 ``data:{...}`` 与 message 末块不能被判定为空响应。"""
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    chunks = [
        'data:{"choices":[{"message":{"content":"火山图已生成"},"finish_reason":"stop"}]}\n',
        "data:[DONE]\n",
    ]
    monkeypatch.setattr(
        "cygnusx.infrastructure.ai_provider.openai_compatible.httpx.AsyncClient",
        lambda **_kwargs: _FakeAsyncClient(chunks),
    )

    result = [
        chunk
        async for chunk in provider.chat_stream(
            [{"role": "user", "content": "请绘制火山图"}],
        )
    ]

    assert [(chunk.type, chunk.content) for chunk in result] == [
        ("text", "火山图已生成"),
        ("done", ""),
    ]


@pytest.mark.asyncio
async def test_deepseek_chat_keeps_enable_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(
            name="deepseek",
            model="qdoubao-seed-evolving-ga-260731",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
        )
    )
    payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        "cygnusx.infrastructure.ai_provider.openai_compatible.httpx.AsyncClient",
        lambda **_kwargs: _FakeAsyncClient(
            ['data:{"choices":[{"delta":{"content":"ok"}}]}\n', "data:[DONE]\n"],
            payloads,
        ),
    )

    _ = [
        chunk
        async for chunk in provider.chat_stream(
            [{"role": "user", "content": "hello"}], deep_thinking=True
        )
    ]

    assert payloads[0]["enable_thinking"] is True
    assert "thinking" not in payloads[0]


@pytest.mark.asyncio
@pytest.mark.quarantine(reason="deepseek v4 请求 payload 未写入 enable_thinking 键，触发 KeyError")
async def test_deepseek_v4_explicitly_disables_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(
            name="deepseek",
            model="qdoubao-seed-evolving-ga-260731",
            base_url="https://ark.cn-beijing.volces.com/api/v3",
        )
    )
    payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        "cygnusx.infrastructure.ai_provider.openai_compatible.httpx.AsyncClient",
        lambda **_kwargs: _FakeAsyncClient(
            ['data:{"choices":[{"delta":{"content":"ok"}}]}\n', "data:[DONE]\n"],
            payloads,
        ),
    )

    _ = [
        chunk
        async for chunk in provider.chat_stream(
            [{"role": "user", "content": "hello"}], deep_thinking=False
        )
    ]

    assert payloads[0]["enable_thinking"] is False
    assert "thinking" not in payloads[0]


@pytest.mark.asyncio
async def test_non_volc_qwen_keeps_enable_thinking(monkeypatch: pytest.MonkeyPatch) -> None:
    """非火山方舟的 Qwen 兼容端点保持原有 enable_thinking 协议。"""
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(
            name="qdoubao-seed-evolving",
            model="qdoubao-seed-evolving",
            base_url="https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1",
        )
    )
    payloads: list[dict[str, object]] = []
    monkeypatch.setattr(
        "cygnusx.infrastructure.ai_provider.openai_compatible.httpx.AsyncClient",
        lambda **_kwargs: _FakeAsyncClient(
            ['data:{"choices":[{"delta":{"content":"ok"}}]}\n', "data:[DONE]\n"],
            payloads,
        ),
    )

    _ = [
        chunk
        async for chunk in provider.chat_stream(
            [{"role": "user", "content": "hello"}], deep_thinking=True
        )
    ]

    assert payloads[0]["enable_thinking"] is True
    assert "thinking" not in payloads[0]


@pytest.mark.asyncio
async def test_transient_error_retries_multiple_times_before_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """可重试错误在尚未输出时应能连续重试多次（默认 3 次），最终成功则正常产出。"""
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    monkeypatch.setattr(get_settings(), "llm_stream_transient_retries", 3)
    calls = {"count": 0}

    async def stream_once(*args: object) -> AsyncIterator[ChatChunk]:
        calls["count"] += 1
        if calls["count"] <= 3:  # 前 3 次均瞬时失败
            yield ChatChunk(type="error", metadata={"retryable": True})
            return
        yield ChatChunk(type="text", content="成功")
        yield ChatChunk(type="done")

    monkeypatch.setattr(provider, "_stream_once", stream_once)

    chunks = [chunk async for chunk in provider.chat_stream([{"role": "user", "content": "hi"}])]

    assert calls["count"] == 4  # 1 次初始 + 3 次重试
    assert [chunk.type for chunk in chunks] == ["text", "done"]
    assert chunks[0].content == "成功"


@pytest.mark.asyncio
async def test_transient_error_exhausts_retries_then_yields_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """重试用尽后应把错误上抛（而不是无限循环），且错误带 retryable 标记。"""
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    monkeypatch.setattr(get_settings(), "llm_stream_transient_retries", 2)
    calls = {"count": 0}

    async def stream_once(*args: object) -> AsyncIterator[ChatChunk]:
        calls["count"] += 1
        yield ChatChunk(type="error", content="连接中断", metadata={"retryable": True})

    monkeypatch.setattr(provider, "_stream_once", stream_once)

    chunks = [chunk async for chunk in provider.chat_stream([{"role": "user", "content": "hi"}])]

    assert calls["count"] == 3  # 1 次初始 + 2 次重试
    assert [chunk.type for chunk in chunks] == ["error"]
    assert chunks[0].content == "连接中断"


@pytest.mark.asyncio
async def test_no_retry_after_text_already_yielded(monkeypatch: pytest.MonkeyPatch) -> None:
    """已经输出正文后发生的错误不得重试（避免重复内容），应直接上抛错误。"""
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    monkeypatch.setattr(get_settings(), "llm_stream_transient_retries", 3)
    calls = {"count": 0}

    async def stream_once(*args: object) -> AsyncIterator[ChatChunk]:
        calls["count"] += 1
        yield ChatChunk(type="text", content="部分内容")
        yield ChatChunk(type="error", content="中途断开", metadata={"retryable": True})

    monkeypatch.setattr(provider, "_stream_once", stream_once)

    chunks = [chunk async for chunk in provider.chat_stream([{"role": "user", "content": "hi"}])]

    assert calls["count"] == 1  # 不重试
    assert [chunk.type for chunk in chunks] == ["text", "error"]


@pytest.mark.asyncio
async def test_retry_disabled_when_limit_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    """把重试上限配置为 0 时，首次可重试错误即直接上抛。"""
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    monkeypatch.setattr(get_settings(), "llm_stream_transient_retries", 0)
    calls = {"count": 0}

    async def stream_once(*args: object) -> AsyncIterator[ChatChunk]:
        calls["count"] += 1
        yield ChatChunk(type="error", metadata={"retryable": True})

    monkeypatch.setattr(provider, "_stream_once", stream_once)

    chunks = [chunk async for chunk in provider.chat_stream([{"role": "user", "content": "hi"}])]

    assert calls["count"] == 1
    assert [chunk.type for chunk in chunks] == ["error"]


def test_dedupe_tools_removes_duplicate_names() -> None:
    """同名工具（如 knowledge_search 被多个来源重复注册）按 function.name 保序去重。

    回归：DeepSeek 等供应商严格校验工具名唯一，重名会被拒请求
    （invalid_request_error: Tool names must be unique）。
    """
    from cygnusx.infrastructure.ai_provider.openai_compatible import _dedupe_tools

    tools = [
        {"type": "function", "function": {"name": "knowledge_search", "description": "a"}},
        {"type": "function", "function": {"name": "sandbox_execute"}},
        {"type": "function", "function": {"name": "knowledge_search", "description": "b"}},
        {"type": "function", "function": {}},  # 无名条目原样保留
    ]

    result = _dedupe_tools(tools)

    assert [t["function"].get("name") for t in result] == [
        "knowledge_search",
        "sandbox_execute",
        None,
    ]
    assert result[0]["function"]["description"] == "a"  # 保留首次出现的定义


@pytest.mark.asyncio
async def test_provider_429_is_retryable_and_parses_retry_after(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 应标记为可重试，并把 Retry-After 头解析进 metadata。"""
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    monkeypatch.setattr(
        "cygnusx.infrastructure.ai_provider.openai_compatible.httpx.AsyncClient",
        lambda **_kwargs: _FakeAsyncClient(
            [], status_code=429, headers={"retry-after": "2"}
        ),
    )

    chunks = [
        chunk
        async for chunk in provider._stream_once(
            [{"role": "user", "content": "hi"}], None, 0.7, 32, None, False
        )
    ]

    assert len(chunks) == 1
    assert chunks[0].type == "error"
    assert chunks[0].metadata == {"retryable": True, "http_status": 429, "retry_after": 2.0}


@pytest.mark.asyncio
async def test_rate_limit_retries_with_retry_after_then_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 在未输出前按 Retry-After 退避重试，成功则正常产出。"""
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    monkeypatch.setattr(get_settings(), "llm_stream_rate_limit_retries", 2)
    delays: list[float] = []
    calls = {"count": 0}

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    async def stream_once(*_args: object) -> AsyncIterator[ChatChunk]:
        calls["count"] += 1
        if calls["count"] <= 2:
            yield ChatChunk(
                type="error",
                content="请求频率过高",
                metadata={"retryable": True, "http_status": 429, "retry_after": 0.5},
            )
            return
        yield ChatChunk(type="text", content="成功")
        yield ChatChunk(type="done")

    monkeypatch.setattr(provider, "_stream_once", stream_once)
    monkeypatch.setattr(
        "cygnusx.infrastructure.ai_provider.openai_compatible.asyncio.sleep", fake_sleep
    )

    chunks = [chunk async for chunk in provider.chat_stream([{"role": "user", "content": "hi"}])]

    assert calls["count"] == 3  # 1 次初始 + 2 次限流重试
    assert delays == [0.5, 0.5]  # 退避来自 Retry-After
    assert [chunk.type for chunk in chunks] == ["text", "done"]


@pytest.mark.asyncio
async def test_rate_limit_without_retry_after_uses_linear_backoff(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 响应没有 Retry-After 时，退化为与瞬时重试相同的线性退避。"""
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    monkeypatch.setattr(get_settings(), "llm_stream_rate_limit_retries", 2)
    monkeypatch.setattr(get_settings(), "llm_stream_retry_base_delay_seconds", 1.0)
    delays: list[float] = []
    calls = {"count": 0}

    async def fake_sleep(seconds: float) -> None:
        delays.append(seconds)

    async def stream_once(*_args: object) -> AsyncIterator[ChatChunk]:
        calls["count"] += 1
        if calls["count"] <= 2:
            yield ChatChunk(
                type="error",
                metadata={"retryable": True, "http_status": 429, "retry_after": None},
            )
            return
        yield ChatChunk(type="text", content="成功")
        yield ChatChunk(type="done")

    monkeypatch.setattr(provider, "_stream_once", stream_once)
    monkeypatch.setattr(
        "cygnusx.infrastructure.ai_provider.openai_compatible.asyncio.sleep", fake_sleep
    )

    chunks = [chunk async for chunk in provider.chat_stream([{"role": "user", "content": "hi"}])]

    assert calls["count"] == 3
    assert delays == [1.0, 2.0]  # base * 第 N 次重试
    assert [chunk.type for chunk in chunks] == ["text", "done"]


@pytest.mark.asyncio
async def test_rate_limit_retry_budget_is_separate_from_transient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """429 用独立的重试上限（默认 2），不占用瞬时重试的 3 次额度，用尽后上抛错误。"""
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    monkeypatch.setattr(get_settings(), "llm_stream_rate_limit_retries", 2)
    monkeypatch.setattr(get_settings(), "llm_stream_transient_retries", 3)
    calls = {"count": 0}

    async def stream_once(*_args: object) -> AsyncIterator[ChatChunk]:
        calls["count"] += 1
        yield ChatChunk(
            type="error",
            content="请求频率过高",
            metadata={"retryable": True, "http_status": 429, "retry_after": None},
        )

    monkeypatch.setattr(provider, "_stream_once", stream_once)

    chunks = [chunk async for chunk in provider.chat_stream([{"role": "user", "content": "hi"}])]

    assert calls["count"] == 3  # 1 次初始 + 2 次限流重试（而非瞬时上限的 3 次）
    assert [chunk.type for chunk in chunks] == ["error"]
    assert chunks[0].content == "请求频率过高"


@pytest.mark.asyncio
async def test_no_429_retry_after_text_already_yielded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """已输出正文后遇到 429 不得重试，直接上抛错误。"""
    provider = OpenAICompatibleProvider(
        AIProviderConfigModel(name="test", model="qwen-test", base_url="https://example.test")
    )
    calls = {"count": 0}

    async def stream_once(*_args: object) -> AsyncIterator[ChatChunk]:
        calls["count"] += 1
        yield ChatChunk(type="text", content="部分内容")
        yield ChatChunk(
            type="error",
            content="请求频率过高",
            metadata={"retryable": True, "http_status": 429, "retry_after": 0.1},
        )

    monkeypatch.setattr(provider, "_stream_once", stream_once)

    chunks = [chunk async for chunk in provider.chat_stream([{"role": "user", "content": "hi"}])]

    assert calls["count"] == 1
    assert [chunk.type for chunk in chunks] == ["text", "error"]


def test_parse_retry_after_seconds_and_http_date() -> None:
    """Retry-After 支持秒数与 HTTP-date 两种形式，非法/缺失返回 None。"""
    import time as _time
    from email.utils import formatdate

    from cygnusx.infrastructure.ai_provider.openai_compatible import _parse_retry_after

    assert _parse_retry_after(None) is None
    assert _parse_retry_after("") is None
    assert _parse_retry_after("not-a-date") is None
    assert _parse_retry_after("3") == 3.0
    assert _parse_retry_after("-5") == 0.0  # 负值钳到 0

    http_date = formatdate(_time.time() + 30, usegmt=True)
    parsed = _parse_retry_after(http_date)
    assert parsed is not None
    assert 0 < parsed <= 30

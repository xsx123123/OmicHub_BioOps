"""LiteLLM 适配器 — 统一支持 100+ LLM provider"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Any

import litellm
from loguru import logger

from omichub.core.config import get_settings
from omichub.core.telemetry import get_tracer
from omichub.domain.ai_provider.entities import AIProviderConfig
from omichub.infrastructure.ai_provider.base import StreamEvent
from omichub.infrastructure.ai_provider.openai_compatible import (
    normalize_token_usage,
    record_ai_call_metrics,
)


class LiteLLMProvider:
    """LiteLLM Provider 适配器

    通过 OpenAI 兼容格式统一调用各类 LLM，支持异步流式、工具调用、自定义 base_url。
    """

    def __init__(self, config: AIProviderConfig | None = None) -> None:
        self._config = config
        self._settings = get_settings()

    async def _get_config(self) -> AIProviderConfig | None:
        """获取生效配置：显式配置 > 数据库默认配置 > None"""
        if self._config is not None:
            return self._config

        # 尝试从数据库读取默认配置
        settings = self._settings
        if settings.ai_default_provider_id:
            try:
                from omichub.infrastructure.database.repositories.ai_provider_repository import (
                    SqlAlchemyAIProviderConfigRepository,
                )
                from omichub.infrastructure.database.session import get_session_factory

                factory = get_session_factory()
                if factory is not None:
                    from uuid import UUID

                    async with factory() as session:
                        repo = SqlAlchemyAIProviderConfigRepository(session)
                        config = await repo.get_by_id(UUID(settings.ai_default_provider_id))
                        if config and config.is_active:
                            return config
            except Exception as e:  # noqa: BLE001
                logger.debug(f"读取默认 AI Provider 失败: {e}")

        try:
            from omichub.infrastructure.database.session import get_session_factory

            factory = get_session_factory()
            if factory is not None:
                from omichub.infrastructure.database.repositories.ai_provider_repository import (
                    SqlAlchemyAIProviderConfigRepository,
                )

                async with factory() as session:
                    repo = SqlAlchemyAIProviderConfigRepository(session)
                    return await repo.get_default()
        except Exception as e:  # noqa: BLE001
            logger.debug(f"读取默认 AI Provider 失败: {e}")

        return None

    @staticmethod
    def _route_model(model: str, has_custom_base: bool) -> str:
        """litellm 按模型名路由：自定义 OpenAI 兼容端点必须加 ``openai/`` 前缀，
        否则 litellm 无法判定 provider 会抛 BadRequestError。

        - 已带 provider 前缀（含 ``/``，如 ``openai/``、``azure/``）则原样返回；
        - 设置了自定义 ``api_base`` 且模型名无前缀时，统一补 ``openai/`` 前缀；
        - 未设置 ``api_base`` 的原生模型（如 ``gpt-4o``）交由 litellm 自动路由。
        """
        if not model or "/" in model:
            return model
        if has_custom_base:
            return f"openai/{model}"
        return model

    def _build_kwargs(
        self, config: AIProviderConfig | None, messages: list[dict[str, str]], **overrides: Any
    ) -> dict[str, Any]:
        """构建 LiteLLM 调用参数"""
        if config is not None:
            kwargs: dict[str, Any] = {
                "model": config.model,
                "messages": messages,
                "temperature": config.temperature,
                "max_tokens": config.max_tokens,
                "top_p": config.top_p,
                "timeout": config.timeout,
            }
            if config.api_key:
                kwargs["api_key"] = config.api_key
            if config.base_url:
                kwargs["api_base"] = config.base_url
            if config.extra_params:
                kwargs.update(config.extra_params)
        else:
            # 兜底：使用环境变量中的 Kimi/OpenAI 配置
            kwargs = {
                "model": self._settings.kimi_model,
                "messages": messages,
                "temperature": self._settings.ai_temperature,
                "api_key": self._settings.kimi_api_key,
                "api_base": self._settings.kimi_base_url,
            }
            if self._settings.openai_api_key and self._settings.llm_provider == "openai":
                kwargs.update(
                    {
                        "model": self._settings.openai_model,
                        "api_key": self._settings.openai_api_key,
                        "api_base": self._settings.openai_base_url,
                    }
                )

        # 覆盖参数
        for key in (
            "stream",
            "temperature",
            "max_tokens",
            "top_p",
            "timeout",
            "tools",
            "stream_options",
        ):
            if key in overrides:
                kwargs[key] = overrides[key]

        kwargs.setdefault("num_retries", 2)
        if kwargs.get("stream"):
            stream_options = dict(kwargs.get("stream_options") or {})
            stream_options.setdefault("include_usage", True)
            kwargs["stream_options"] = stream_options

        # litellm 路由：自定义 OpenAI 兼容端点需 openai/ 前缀，否则 BadRequestError
        kwargs["model"] = self._route_model(
            str(kwargs.get("model", "")), bool(kwargs.get("api_base"))
        )

        return kwargs

    async def chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """非流式对话"""
        overrides: dict[str, Any] = {}
        if model:
            overrides["model"] = model
        if temperature is not None:
            overrides["temperature"] = temperature
        if tools is not None:
            overrides["tools"] = tools

        config = await self._get_config()
        kwargs = self._build_kwargs(config, messages, **overrides)
        logger.debug(f"LiteLLM chat call: model={kwargs.get('model')}")
        tracer = get_tracer("omichub.ai")
        with tracer.start_as_current_span(
            "ai.chat",
            attributes={"ai.provider": "litellm", "ai.model": str(kwargs.get("model", ""))},
        ) as span:
            start = time.perf_counter()
            status = "success"
            usage: dict[str, Any] | None = None
            finish_reason: str | None = None
            try:
                response = await litellm.acompletion(**kwargs)
                data = response.model_dump() if hasattr(response, "model_dump") else dict(response)
                usage = normalize_token_usage(data.get("usage"))
                if usage:
                    span.set_attribute("ai.prompt_tokens", usage.get("prompt_tokens", 0))
                    span.set_attribute("ai.completion_tokens", usage.get("completion_tokens", 0))
                    span.set_attribute("ai.total_tokens", usage.get("total_tokens", 0))
                return data
            except Exception as exc:  # noqa: BLE001
                status = "error"
                span.record_exception(exc)
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                span.set_attribute("ai.status", status)
                span.set_attribute("ai.duration_ms", round(duration_ms, 2))
                record_ai_call_metrics(
                    "litellm", str(kwargs.get("model", "")), status, duration_ms, usage
                )
                logger.bind(
                    event="ai.chat",
                    provider="litellm",
                    model=str(kwargs.get("model", "")),
                    status=status,
                    duration_ms=round(duration_ms, 2),
                    usage=usage,
                ).info("ai.chat completed")

    async def stream_chat(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """流式对话 - 逐 token 返回"""
        overrides: dict[str, Any] = {"stream": True}
        if model:
            overrides["model"] = model
        if temperature is not None:
            overrides["temperature"] = temperature

        config = await self._get_config()
        kwargs = self._build_kwargs(config, messages, **overrides)
        logger.debug(f"LiteLLM stream call: model={kwargs.get('model')}")
        tracer = get_tracer("omichub.ai")
        with tracer.start_as_current_span(
            "ai.chat",
            attributes={"ai.provider": "litellm", "ai.model": str(kwargs.get("model", ""))},
        ) as span:
            start = time.perf_counter()
            status = "success"
            usage: dict[str, Any] | None = None
            try:
                stream = await litellm.acompletion(**kwargs)
                async for chunk in stream:
                    chunk_usage = getattr(chunk, "usage", None)
                    if chunk_usage:
                        usage = normalize_token_usage(
                            chunk_usage.model_dump()
                            if hasattr(chunk_usage, "model_dump")
                            else dict(chunk_usage)
                        )
                    delta = chunk.choices[0].delta if chunk.choices else None
                    if delta is None:
                        continue
                    content = delta.content or ""
                    if content:
                        yield content
            except Exception as e:  # noqa: BLE001
                status = "error"
                span.record_exception(e)
                logger.warning(f"LiteLLM 流式调用失败: {e}")
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                span.set_attribute("ai.status", status)
                span.set_attribute("ai.duration_ms", round(duration_ms, 2))
                if usage:
                    span.set_attribute("ai.prompt_tokens", usage.get("prompt_tokens", 0))
                    span.set_attribute("ai.completion_tokens", usage.get("completion_tokens", 0))
                record_ai_call_metrics(
                    "litellm", str(kwargs.get("model", "")), status, duration_ms, usage
                )
                logger.bind(
                    event="ai.chat",
                    provider="litellm",
                    model=str(kwargs.get("model", "")),
                    status=status,
                    duration_ms=round(duration_ms, 2),
                    usage=usage,
                ).info("ai.chat completed")

    async def stream_chat_with_tools(
        self,
        messages: list[dict[str, str]],
        model: str = "",
        temperature: float | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> AsyncIterator[StreamEvent]:
        """流式对话 + 工具调用 — 逐 token 推送 + 流末组装 tool_calls

        遍历 litellm.acompletion(stream=True, tools=...) 的 chunk：
        - delta.content → yield StreamEvent("text")
        - delta.tool_calls → 按 index 累积 id/function.name/function.arguments（字符串拼接）
        - 流末若 tc_acc 非空 → 解析 arguments JSON → yield StreamEvent("tool_calls")

        降级：litellm.BadRequestError 时回退非流式 self.chat(tools=tools)
        """
        overrides: dict[str, Any] = {"stream": True}
        if model:
            overrides["model"] = model
        if temperature is not None:
            overrides["temperature"] = temperature
        if tools is not None:
            overrides["tools"] = tools

        config = await self._get_config()
        kwargs = self._build_kwargs(config, messages, **overrides)

        tc_acc: dict[int, dict[str, Any]] = {}
        tracer = get_tracer("omichub.ai")
        with tracer.start_as_current_span(
            "ai.chat",
            attributes={"ai.provider": "litellm", "ai.model": str(kwargs.get("model", ""))},
        ) as span:
            start = time.perf_counter()
            status = "success"
            usage: dict[str, Any] | None = None
            try:
                try:
                    logger.debug(f"LiteLLM stream+tools call: model={kwargs.get('model')}")
                    stream = await litellm.acompletion(**kwargs)
                    async for chunk in stream:
                        chunk_usage = getattr(chunk, "usage", None)
                        if chunk_usage:
                            usage = normalize_token_usage(
                                chunk_usage.model_dump()
                                if hasattr(chunk_usage, "model_dump")
                                else dict(chunk_usage)
                            )
                        if not chunk.choices:
                            continue
                        delta = chunk.choices[0].delta
                        finish = chunk.choices[0].finish_reason
                        if finish and finish != "null":
                            finish_reason = str(finish)

                        # 1. 内容 token
                        content = getattr(delta, "content", None) or ""
                        if content:
                            yield StreamEvent(type="text", content=content)

                        # 2. 工具调用增量累积（按 index 分片拼接）
                        raw_tc = getattr(delta, "tool_calls", None)
                        if raw_tc:
                            for tc in raw_tc:
                                idx = getattr(tc, "index", 0) or 0
                                if idx not in tc_acc:
                                    tc_acc[idx] = {
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""},
                                    }
                                if getattr(tc, "id", None):
                                    tc_acc[idx]["id"] = tc.id
                                func = getattr(tc, "function", None)
                                if func:
                                    if getattr(func, "name", None):
                                        tc_acc[idx]["function"]["name"] += func.name
                                    if getattr(func, "arguments", None):
                                        tc_acc[idx]["function"]["arguments"] += func.arguments

                        # 3. finish_reason 处理
                        if finish and finish != "null" and finish == "content_filter":
                            yield StreamEvent(type="text", content="[输出被内容安全过滤器拦截]")
                        # 注意：不在此处 return，等流自然结束

                except litellm.BadRequestError as e:
                    # 降级：provider 不支持 stream+tools
                    logger.warning(f"Stream+tools 不支持，降级非流式: {e}")
                    response = await self.chat(
                        messages, model=model, temperature=temperature, tools=tools
                    )
                    message = response.get("choices", [{}])[0].get("message", {})
                    content = message.get("content", "") or ""
                    if content:
                        yield StreamEvent(type="text", content=content)
                    raw_tool_calls = message.get("tool_calls") or []
                    if raw_tool_calls:
                        yield StreamEvent(type="tool_calls", tool_calls=raw_tool_calls)
                    yield StreamEvent(type="done")
                    return
                except Exception as e:  # noqa: BLE001
                    status = "error"
                    span.record_exception(e)
                    logger.warning(f"LiteLLM stream+tools 调用失败: {e}")
                    raise

                # 流结束：组装 tool_calls
                if tc_acc:
                    assembled: list[dict[str, Any]] = []
                    for idx in sorted(tc_acc):
                        tc = tc_acc[idx]
                        assembled.append(
                            {
                                "id": tc["id"] or f"call_{idx}",
                                "type": "function",
                                "function": {
                                    "name": tc["function"]["name"],
                                    "arguments": tc["function"]["arguments"],
                                },
                            }
                        )
                    yield StreamEvent(type="tool_calls", tool_calls=assembled)

                done_metadata = {"usage": usage} if usage else {}
                if finish_reason:
                    done_metadata["finish_reason"] = finish_reason
                yield StreamEvent(type="done", metadata=done_metadata)
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                span.set_attribute("ai.status", status)
                span.set_attribute("ai.duration_ms", round(duration_ms, 2))
                if usage:
                    span.set_attribute("ai.prompt_tokens", usage.get("prompt_tokens", 0))
                    span.set_attribute("ai.completion_tokens", usage.get("completion_tokens", 0))
                record_ai_call_metrics(
                    "litellm", str(kwargs.get("model", "")), status, duration_ms, usage
                )
                logger.bind(
                    event="ai.chat",
                    provider="litellm",
                    model=str(kwargs.get("model", "")),
                    status=status,
                    duration_ms=round(duration_ms, 2),
                    usage=usage,
                ).info("ai.chat completed")

    async def is_configured(self) -> bool:
        """检查是否已配置有效 API Key 与模型"""
        config = await self._get_config()
        if config is not None:
            return bool(config.api_key) and bool(config.model)
        if self._settings.llm_provider == "openai":
            return bool(self._settings.openai_api_key) and bool(self._settings.openai_model)
        return bool(self._settings.kimi_api_key) and bool(self._settings.kimi_model)

    async def embeddings(self, text: str, model: str = "") -> list[float]:
        """文本嵌入向量（可选能力）"""
        config = await self._get_config()
        kwargs: dict[str, Any] = {"input": text}
        if model:
            kwargs["model"] = model
        elif config is not None:
            kwargs["model"] = config.model
        else:
            kwargs["model"] = "text-embedding-3-small"

        if config is not None:
            if config.api_key:
                kwargs["api_key"] = config.api_key
            if config.base_url:
                kwargs["api_base"] = config.base_url
        else:
            kwargs["api_key"] = self._settings.openai_api_key or self._settings.kimi_api_key

        tracer = get_tracer("omichub.ai")
        with tracer.start_as_current_span(
            "ai.embedding",
            attributes={"ai.provider": "litellm", "ai.model": str(kwargs.get("model", ""))},
        ) as span:
            start = time.perf_counter()
            status = "success"
            usage: dict[str, Any] | None = None
            try:
                response = await litellm.aembedding(**kwargs)
                data: dict[str, Any] = (
                    response.model_dump() if hasattr(response, "model_dump") else dict(response)
                )
                usage = normalize_token_usage(data.get("usage"))
                embedding_data: list[dict[str, Any]] = data.get("data", [{}])
                embedding: list[float] = (
                    embedding_data[0].get("embedding", []) if embedding_data else []
                )
                return embedding
            except Exception as exc:  # noqa: BLE001
                status = "error"
                span.record_exception(exc)
                raise
            finally:
                duration_ms = (time.perf_counter() - start) * 1000
                span.set_attribute("ai.status", status)
                span.set_attribute("ai.duration_ms", round(duration_ms, 2))
                record_ai_call_metrics(
                    "litellm", str(kwargs.get("model", "")), status, duration_ms, usage
                )
                logger.bind(
                    event="ai.embedding",
                    provider="litellm",
                    model=str(kwargs.get("model", "")),
                    status=status,
                    duration_ms=round(duration_ms, 2),
                    usage=usage,
                ).info("ai.embedding completed")

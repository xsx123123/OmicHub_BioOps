"""Reusable agent-context and model preflight for chat runtimes."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from cygnusx.application.services.agent_context_builder import AgentContextBuilder
from cygnusx.application.services.agent_service import AgentService
from cygnusx.core.config import get_settings


@dataclass(frozen=True)
class PreparedAgentRequest:
    """Validated runtime inputs derived from an agent chat request."""

    context: Any
    model_config: Any
    sensitive_keywords: Any
    effective_max_tokens: int


@dataclass(frozen=True)
class AgentRequestPreparationFailure:
    """A user-facing preflight failure that should be streamed as an error chunk."""

    message: str


async def prepare_agent_request(
    *,
    db: Any,
    agent_id: str,
    user_id: str,
    messages: Sequence[Mapping[str, Any]],
    mode: str | None,
    model_id: UUID | None,
    deep_thinking: bool,
    resolve_model: Callable[[UUID], Awaitable[Any | None]],
    context_builder_factory: Callable[..., AgentContextBuilder] = AgentContextBuilder,
    agent_service_factory: Callable[[Any], AgentService] = AgentService,
    settings_provider: Callable[[], Any] = get_settings,
) -> PreparedAgentRequest | AgentRequestPreparationFailure:
    """Build an agent context and enforce the shared model availability policy."""
    tool_query = next(
        (
            message.get("content")
            for message in reversed(messages)
            if message.get("role") == "user" and message.get("content")
        ),
        None,
    )
    context = await context_builder_factory(
        db,
        agent_service=agent_service_factory(db),
    ).assemble(
        agent_id,
        user_id,
        user_message=tool_query,
        mode=mode or "chat",
    )
    if context is None:
        return AgentRequestPreparationFailure("Agent 不存在或已停用")

    # A model selected for the current request/session is an explicit runtime
    # override. It must win over the Agent default and over a persisted
    # per-user capability profile; otherwise the UI can report one model while
    # the request silently falls back to the profile's model.
    if model_id is not None:
        override = await resolve_model(model_id)
        if override is None:
            return AgentRequestPreparationFailure("指定的模型不存在或未启用")
        if not override.api_key:
            return AgentRequestPreparationFailure(
                f"模型 '{override.name}' 的 API Key 未配置，请联系管理员设置"
            )
        context.model_config = override

    if context.model_config is None:
        return AgentRequestPreparationFailure(
            f"Agent '{context.agent.name}' 未绑定可用模型，请联系管理员在 AI 资源中心配置"
        )
    if not context.model_config.api_key:
        return AgentRequestPreparationFailure(
            f"模型 '{context.model_config.name}' 的 API Key 未配置，请联系管理员设置"
        )

    model_config = context.model_config
    effective_max_tokens = context.max_tokens
    if deep_thinking and "deepseek" in str(model_config.model).lower():
        effective_max_tokens = max(effective_max_tokens, int(model_config.max_tokens or 0))

    return PreparedAgentRequest(
        context=context,
        model_config=model_config,
        sensitive_keywords=settings_provider().sensitive_keywords,
        effective_max_tokens=effective_max_tokens,
    )

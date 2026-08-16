"""AI Provider 适配器"""

from __future__ import annotations

from functools import lru_cache

from omichub.core.config import get_settings
from omichub.infrastructure.ai_provider.base import LLMProvider
from omichub.infrastructure.ai_provider.kimi import KimiProvider
from omichub.infrastructure.ai_provider.litellm_provider import LiteLLMProvider


@lru_cache
def get_llm_provider() -> LLMProvider:
    """根据配置返回 LLM Provider 单例

    优先使用管理员在数据库中配置的默认 AI Provider；未配置时使用环境变量兜底。
    """
    settings = get_settings()

    # 若显式指定了默认 provider id，则尝试读取数据库配置。
    # 实际配置在 LiteLLMProvider.chat/stream_chat 中异步加载。
    if settings.ai_default_provider_id:
        return LiteLLMProvider()

    # 兼容旧配置
    if settings.llm_provider == "openai":
        provider = KimiProvider()
        provider.base_url = settings.openai_base_url
        provider.api_key = settings.openai_api_key
        provider.model = settings.openai_model
        return provider

    return LiteLLMProvider()

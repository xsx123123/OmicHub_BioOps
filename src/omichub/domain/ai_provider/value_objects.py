"""AI Provider 配置值对象"""

from enum import StrEnum


class ProviderType(StrEnum):
    """LLM Provider 类型

    LiteLLM 统一用 OpenAI 格式调用，provider_type 主要用于 UI 展示、
    默认值提示以及后续扩展 provider 特定逻辑。
    """

    OPENAI_COMPATIBLE = "openai_compatible"
    KIMI = "kimi"
    DEEPSEEK = "deepseek"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE = "azure"
    OLLAMA = "ollama"
    VLLM = "vllm"

    @classmethod
    def choices(cls) -> list[str]:
        return [m.value for m in cls]

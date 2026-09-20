"""现有手写 Agent 循环的 Runtime 适配器。"""

from __future__ import annotations

from cygnusx.application.services.chat.runtimes.delegating_runtime import DelegatingAgentRuntime


class LegacyChatRuntime(DelegatingAgentRuntime):
    """复用现有内部生成器，作为逐步迁移的零行为差异起点。"""

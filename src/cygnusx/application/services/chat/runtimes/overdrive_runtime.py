"""Overdrive Runtime 适配器。"""

from cygnusx.application.services.chat.runtimes.delegating_runtime import DelegatingAgentRuntime


class OverdriveChatRuntime(DelegatingAgentRuntime):
    """Overdrive 请求的显式 Runtime 身份，保留既有执行语义。"""

"""聊天 Runtime 使用的不可变 Agent 执行上下文。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentContext:
    """在 Runtime 选择前一次性收集的会话与 Agent 装配结果。"""

    session: Any
    assembled: Any
    mode: str
    execution_path: str
    trace_id: str
    run_id: str

    @property
    def session_id(self) -> str:
        return str(self.session.session_id)

    @property
    def agent(self) -> Any:
        return self.assembled.agent

    @property
    def model_config(self) -> Any:
        return self.assembled.model_config

    @property
    def system_prompt(self) -> str:
        return self.assembled.system_prompt

    @property
    def tools(self) -> list[dict[str, Any]]:
        return self.assembled.tools

    @property
    def mcp_servers(self) -> list[Any]:
        return self.assembled.mcp_servers

    @property
    def skills(self) -> list[Any]:
        return self.assembled.skills

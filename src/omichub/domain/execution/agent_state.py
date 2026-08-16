"""LangGraph AgentState 定义（阶段 1 裁剪版）

贯穿 LangGraph 所有节点的状态载体。相比 2026-07-06 参考实现裁剪了
HITL / checkpoint / task_context 字段，仅保留 ReAct 工具循环所需的最小状态：

- messages: OpenAI 格式 dict 列表，经 reducer 累加（节点只返回增量）
- rounds:   已执行的 LLM 轮次（tool_exec 后用于轮次上限判断）
- usage:    累计 token 用量（各轮 merge 后的快照，节点整体覆盖）
- error:    节点执行错误信息，非空即路由到 END
- handoff:  已校验的 Agent 交接指令；tool_exec 后立即结束当前图，由 ChatService 接管
- ask_request: ask_user 澄清请求（tool_call_id + 原始 args）；tool_exec 后立即结束
  当前图，由 ChatService 产出 ask_request 事件并收尾本轮，等用户下条消息回答
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class AgentState(TypedDict, total=False):
    """LangGraph Agent 状态（OpenAI 消息格式，不引入 langchain 消息封装）"""

    messages: Annotated[list[dict[str, Any]], operator.add]
    rounds: int
    usage: dict[str, Any] | None
    error: str | None
    handoff: dict[str, Any] | None
    ask_request: dict[str, Any] | None

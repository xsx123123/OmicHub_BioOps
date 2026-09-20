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
- finalize: submit_output 显式 Finalize 动作（tool_call_id + output）；tool_exec 后
  立即结束当前图，由 ChatService 把 output 作为最终正文收尾本轮（openai4s 外循环
  三选一之一，见 agent_execution_framework.md §3.3）
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
    finalize: dict[str, Any] | None
    #: 上一轮 tool 批次是否全部为代码执行类工具（Code Cell）：为 True 时下一轮
    #: llm_call 不递增轮次预算（Code Cell 不占 tool 轮次，§3.3.2）
    code_cell_only_round: bool

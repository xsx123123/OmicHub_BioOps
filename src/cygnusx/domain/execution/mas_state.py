"""LangGraph MASState 定义（生物信息部门 Supervisor-Worker 图）。

对齐 AgentState（domain/execution/agent_state.py）风格：裸 dict + operator.add，
不引入 langchain 消息封装。

- messages: OpenAI 格式 dict 列表，经 reducer 累加（节点只返回增量）
- orchestration_rounds: Supervisor 派工轮次（熔断计数，仅 Supervisor 递增）
- next_worker: supervisor 路由结果；"__finish__" 表终结
- pending_plan / plan_decision: 人工判断点（interrupt/resume，阶段 3）
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

FINISH_SENTINEL = "__finish__"


class MASState(TypedDict, total=False):
    """生物信息部门 MAS 状态（OpenAI 消息格式，不引入 langchain 消息封装）"""

    messages: Annotated[list[dict[str, Any]], operator.add]
    orchestration_rounds: int
    next_worker: str | None
    room_id: str
    run_id: str
    pending_plan: dict[str, Any] | None
    plan_decision: dict[str, Any] | None
    error: str | None

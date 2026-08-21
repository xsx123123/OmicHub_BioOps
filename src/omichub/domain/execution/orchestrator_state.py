"""LangGraph OrchestratorState 定义（MAS Orchestrator 编排图）

贯穿编排图 plan_generate → plan_confirm → dispatch → aggregate 四个节点的
状态载体。与 agent_state.py（单 Agent ReAct 循环）同级，风格对齐：

- plan_*:  计划草稿/已确认版本的快照（version + hash 与 OverdriveRunService
           freeze_plan 的不可变计划契约一致；权威账本仍是 overdrive_runs 表，
           这里只是图执行视角的镜像）
- revision_*: 修改次数与文字反馈（revise 路径回灌 plan_generate 重新规划）
- dispatched / dispatch_waves: dispatch 节点落账标记与拓扑波次（恢复时对账用）
- audit:   节点迁移审计摘要，经 reducer 累加（节点只返回增量），供可观测排查

注意：本 state 只作 LangGraph 图执行与 checkpoint 恢复载体，禁止把业务权威
状态写在这里替代 overdrive_runs/overdrive_events 表（P0 决策：明确权威状态存储）。
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict


class OrchestratorState(TypedDict, total=False):
    """MAS Orchestrator 编排图状态（task dict 与 Overdrive plan schema 兼容）"""

    run_id: str
    session_id: str
    user_id: str
    root_request: str
    # revise(文字反馈) 路径的修改意见，回灌给 plan_generate 重新规划
    revision_feedback: str
    # 冻结计划快照（对齐 OverdriveRunService.freeze_plan 契约）
    plan_content: str
    plan_tasks: list[dict[str, Any]]
    plan_summary: dict[str, Any]
    plan_version: int
    plan_hash: str
    # not_started / awaiting_confirmation / approved / cancelled
    plan_status: str
    revision_count: int
    # dispatch 节点是否已把 run 交给 Overdrive 派发链（advance_run）
    dispatched: bool
    dispatch_waves: list[list[str]]
    # aggregate 节点的聚合说明（聚合执行由现有 Celery 链异步推进）
    aggregate_note: str
    error: str | None
    # 节点迁移审计（状态 diff 摘要），reducer 累加
    audit: Annotated[list[dict[str, Any]], operator.add]

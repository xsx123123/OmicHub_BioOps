"""MAS Orchestrator 编排图：plan_generate → plan_confirm → dispatch → aggregate

对应 P0"Orchestrator 迁移 LangGraph"的核心图结构，节点全部做**薄委派**，
不复制 Overdrive 既有编排逻辑：

- plan_generate: 委派注入的 prepare_plan（生产实现 = OverdrivePlanningService
  .prepare_plan，含证据检索、plan_builder、validate_plan 契约校验与
  freeze_plan 版本化 + sha256），输出与 Overdrive plan task dict schema
  完全兼容（task_id/depends_on/accepts_inputs/produces_outputs/
  completion_criteria/tools/timeout_seconds/retry/requires_approval）。
- plan_confirm:  ``interrupt()`` 推送计划确认（落实 orchestrator.yaml 的
  requires_plan_confirmation: true）。resume 值支持 确认/修改/取消：
    * approve: 委派 decide_plan（command_id 幂等 + 版本/hash 校验）→ dispatch
    * revise + tasks: 用户直接编辑 DAG（如删掉非必需分支）→ 回写 state 后
      重新跑 validate_plan（含环检测），freeze 新版本后重新 interrupt 确认
    * revise + feedback: 文字修改意见 → 回灌 plan_generate 重新规划
    * cancel:  委派 decide_plan(cancel) → END
  decide 时若账本版本/hash 漂移（如旁路 replan 已冻结新版本），先对账
  ledger（refresh_plan）再重新 interrupt，不重复确认旧快照。
- dispatch:      按拓扑波次（task_waves）委派现有 Overdrive 派发链
  （advance_run → OverdriveScheduler.recruit_ready → run_assistant_job）。
  决策记录：不接 Bridge——Bridge 工单协议服务 AgentTeams Case 域，
  MAS/Overdrive 从未经过 Bridge；Overdrive 派发链即"现有派发通道"。
  生产实现先做 ledger 对账（assert_execution_allowed + 状态检查），
  保证崩溃恢复后已落账的派发不重复执行。
- aggregate:     薄委派聚合入口；实际聚合（manager review /
  DeliveryAssembler）由 advance_run 链异步推进，本节点只登记移交说明，
  不在 HTTP 请求生命周期内阻塞等待执行结果。

设计原则（对齐 langgraph_nodes.py）：
    - 节点为 (state, deps) → 增量 state，副作用全部经 OrchestratorDeps 注入
    - 权威状态账本仍是 overdrive_runs/overdrive_events 表；图 state 与
      checkpoint 只作执行恢复载体（P0 决策：明确权威状态存储）
    - 节点进入/退出、interrupt 触发与恢复都打结构化日志（loguru logger
      自动携带 trace 上下文）
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol, cast

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from loguru import logger

from omichub.core.exceptions import ValidationError
from omichub.domain.execution.orchestrator_state import OrchestratorState
from omichub.infrastructure.ai_provider.openai_compatible import ChatChunk

# plan_generate 产出契约：冻结计划快照（与 freeze_plan 返回的 run.plan 对齐）
PreparePlanFn = Callable[[OrchestratorState], Awaitable[dict[str, Any]]]
# decide_plan 薄委派：(state, action, feedback, command_id) → decide_plan result
DecidePlanFn = Callable[[OrchestratorState, str, str, str], Awaitable[dict[str, Any]]]
# 用户直接编辑 DAG 后的重冻结：(state, edited_tasks) → 新 plan 快照（version+1）
FreezeRevisionFn = Callable[[OrchestratorState, list[dict[str, Any]]], Awaitable[dict[str, Any]]]
# dispatch 薄委派：(run_id, tasks, waves) → None（生产实现触发 advance_run 链）
DispatchRunFn = Callable[[str, list[dict[str, Any]], list[list[str]]], Awaitable[None]]
# aggregate 薄委派：(run_id) → 聚合移交说明
AggregateRunFn = Callable[[str], Awaitable[str]]
# ledger 对账：从权威账本重读最新冻结计划快照
RefreshPlanFn = Callable[[OrchestratorState], Awaitable[dict[str, Any]]]
# DAG 契约校验（默认 = OverdriveRunService validate_plan，含环检测）
ValidatePlanFn = Callable[[str, list[dict[str, Any]], set[str]], None]
EventEmitter = Callable[[ChatChunk], Awaitable[None]]


def _default_validate_plan(
    content: str, tasks: list[dict[str, Any]], known_agent_ids: set[str]
) -> None:
    """默认 DAG 校验：直接复用 Overdrive 权威 validate_plan（含环检测）。"""
    from omichub.application.services.overdrive_run_service import validate_plan

    validate_plan(content, tasks, known_agent_ids)


@dataclass
class OrchestratorDeps:
    """编排图节点依赖容器 — 由引擎构造方注入，便于测试 mock"""

    prepare_plan: PreparePlanFn | None = None
    decide_plan: DecidePlanFn | None = None
    freeze_revision: FreezeRevisionFn | None = None
    dispatch_run: DispatchRunFn | None = None
    aggregate_run: AggregateRunFn | None = None
    refresh_plan: RefreshPlanFn | None = None
    validate_plan: ValidatePlanFn = _default_validate_plan
    known_agent_ids: set[str] = field(default_factory=set)
    emit: EventEmitter | None = None
    max_revisions: int = 3

    async def emit_chunk(self, chunk: ChatChunk) -> None:
        if self.emit is not None:
            await self.emit(chunk)


def _audit(node: str, **diff: Any) -> list[dict[str, Any]]:
    """节点迁移审计摘要（状态 diff），累加进 state["audit"] 供排查还原路径。"""
    return [{"node": node, **diff}]


async def plan_generate_node(
    state: OrchestratorState, deps: OrchestratorDeps
) -> dict[str, Any]:
    """生成 DAG 计划草稿：委派 Overdrive 规划管线，输出兼容 plan task schema。"""
    run_id = state.get("run_id", "")
    if deps.prepare_plan is None:
        return {"error": "plan_generate 节点缺少 prepare_plan 依赖"}
    logger.info(
        "orchestrator.plan_generate 进入 run_id={} revision_count={} feedback={}",
        run_id,
        state.get("revision_count", 0),
        bool(state.get("revision_feedback")),
    )
    try:
        plan = await deps.prepare_plan(state)
    except Exception as e:  # noqa: BLE001
        logger.exception("orchestrator.plan_generate 失败 run_id={} error={}", run_id, e)
        await deps.emit_chunk(ChatChunk(type="error", content=f"计划生成失败: {e}"))
        return {"error": str(e), "audit": _audit("plan_generate", error=str(e))}
    logger.info(
        "orchestrator.plan_generate 完成 run_id={} version={} hash={} tasks={}",
        run_id,
        plan.get("version"),
        str(plan.get("hash") or "")[:16],
        len(plan.get("tasks") or []),
    )
    await deps.emit_chunk(
        ChatChunk(
            type="overdrive_progress",
            metadata={
                "phase": "plan_ready",
                "label": "规划 Agent 已交付 plan.md，等待你确认",
                "run_id": run_id,
                "plan_version": plan.get("version"),
            },
        )
    )
    return {
        "plan_content": str(plan.get("content") or ""),
        "plan_tasks": list(plan.get("tasks") or []),
        "plan_summary": dict(plan.get("summary") or {}),
        "plan_version": int(plan.get("version") or 0),
        "plan_hash": str(plan.get("hash") or ""),
        "plan_status": "awaiting_confirmation",
        "error": None,
        "audit": _audit(
            "plan_generate",
            plan_version=plan.get("version"),
            task_count=len(plan.get("tasks") or []),
        ),
    }


async def plan_confirm_node(
    state: OrchestratorState, deps: OrchestratorDeps
) -> dict[str, Any]:
    """计划确认 interrupt：推送确认卡，resume 值驱动 确认/修改/取消 分支。"""
    run_id = state.get("run_id", "")
    payload = {
        "kind": "plan_confirmation",
        "run_id": run_id,
        "plan_version": state.get("plan_version"),
        "plan_hash": state.get("plan_hash"),
        "summary": state.get("plan_summary") or {},
        "actions": ["approve", "revise", "cancel"],
    }
    logger.info(
        "orchestrator.plan_confirm interrupt 触发 run_id={} version={}",
        run_id,
        payload["plan_version"],
    )
    # interrupt() 首次执行时暂停图并把 payload 透出；resume 时返回用户决策
    decision = interrupt(payload)
    logger.info(
        "orchestrator.plan_confirm 恢复 run_id={} decision_action={}",
        run_id,
        decision.get("action") if isinstance(decision, dict) else type(decision).__name__,
    )
    if not isinstance(decision, dict):
        return {"error": "计划确认的恢复值必须是决策对象"}
    action = str(decision.get("action") or "")
    command_id = str(
        decision.get("command_id") or f"graph-plan-{run_id}-{uuid.uuid4().hex[:8]}"
    )
    revision_count = int(state.get("revision_count") or 0)

    if action == "approve":
        try:
            if deps.decide_plan is not None:
                await deps.decide_plan(state, "approve", "", command_id)
        except ValidationError as e:
            # 账本版本/hash 漂移（旁路 replan 已冻结新版本）：对账后重新确认，
            # 不重复确认旧快照。
            logger.warning(
                "orchestrator.plan_confirm 对账 run_id={} reason={}", run_id, e
            )
            if deps.refresh_plan is None:
                return {"error": f"计划账本对账失败且无 refresh_plan 依赖: {e}"}
            refreshed = await deps.refresh_plan(state)
            return {
                **refreshed,
                "plan_status": "awaiting_confirmation",
                "audit": _audit("plan_confirm", reconciled=True, reason=str(e)),
            }
        return {
            "plan_status": "approved",
            "audit": _audit("plan_confirm", action="approve", command_id=command_id),
        }

    if action == "cancel":
        if deps.decide_plan is not None:
            await deps.decide_plan(state, "cancel", "", command_id)
        return {
            "plan_status": "cancelled",
            "audit": _audit("plan_confirm", action="cancel", command_id=command_id),
        }

    if action == "revise":
        next_count = revision_count + 1
        if next_count > deps.max_revisions:
            return {"error": "计划修改已达到上限，只能确认当前版本或取消"}
        edited_tasks = decision.get("tasks")
        if isinstance(edited_tasks, list):
            # 用户直接编辑 DAG（如删掉一个非必需分支）：回写 state 后重新校验
            # （validate_plan 含环检测与依赖合法性），冻结新版本再确认一次。
            if deps.freeze_revision is None:
                return {"error": "revise(tasks) 缺少 freeze_revision 依赖"}
            try:
                deps.validate_plan(
                    str(state.get("plan_content") or ""),
                    [dict(item) for item in edited_tasks],
                    deps.known_agent_ids,
                )
            except ValidationError as e:
                return {"error": f"修改后的计划未通过契约校验: {e}"}
            new_plan = await deps.freeze_revision(state, [dict(item) for item in edited_tasks])
            logger.info(
                "orchestrator.plan_confirm 修改回写 run_id={} new_version={} tasks={}",
                run_id,
                new_plan.get("version"),
                len(edited_tasks),
            )
            return {
                "plan_tasks": [dict(item) for item in edited_tasks],
                "plan_version": int(new_plan.get("version") or state.get("plan_version") or 0),
                "plan_hash": str(new_plan.get("hash") or state.get("plan_hash") or ""),
                "plan_summary": dict(new_plan.get("summary") or state.get("plan_summary") or {}),
                "plan_status": "awaiting_confirmation",
                "revision_count": next_count,
                "audit": _audit(
                    "plan_confirm",
                    action="revise_tasks",
                    new_version=new_plan.get("version"),
                    task_count=len(edited_tasks),
                ),
            }
        feedback = str(decision.get("feedback") or "").strip()
        if not feedback:
            return {"error": "提出修改时必须填写修改意见"}
        if deps.decide_plan is not None:
            await deps.decide_plan(state, "revise", feedback, command_id)
        return {
            "plan_status": "replanning",
            "revision_feedback": feedback,
            "revision_count": next_count,
            "audit": _audit("plan_confirm", action="revise_feedback"),
        }

    return {"error": f"未知的计划确认动作: {action or '<empty>'}"}


async def dispatch_node(
    state: OrchestratorState, deps: OrchestratorDeps
) -> dict[str, Any]:
    """按拓扑波次委派 Overdrive 派发链（advance_run → recruit_ready → 每实例 job）。"""
    run_id = state.get("run_id", "")
    if state.get("plan_status") != "approved":
        return {"error": "计划尚未确认，禁止派发执行"}
    if deps.dispatch_run is None:
        return {"error": "dispatch 节点缺少 dispatch_run 依赖"}
    from omichub.application.services.overdrive_planning_service import task_waves

    tasks = list(state.get("plan_tasks") or [])
    waves = task_waves(tasks)
    logger.info(
        "orchestrator.dispatch 进入 run_id={} tasks={} waves={}",
        run_id,
        len(tasks),
        len(waves),
    )
    try:
        await deps.dispatch_run(run_id, tasks, waves)
    except Exception as e:  # noqa: BLE001
        logger.exception("orchestrator.dispatch 失败 run_id={} error={}", run_id, e)
        await deps.emit_chunk(ChatChunk(type="error", content=f"任务派发失败: {e}"))
        return {"error": str(e), "audit": _audit("dispatch", error=str(e))}
    await deps.emit_chunk(
        ChatChunk(
            type="overdrive_progress",
            metadata={
                "phase": "dispatching",
                "label": "计划已确认，按依赖拓扑派发执行任务",
                "run_id": run_id,
                "completed": 0,
                "total": len(tasks),
            },
        )
    )
    return {
        "dispatched": True,
        "dispatch_waves": waves,
        "error": None,
        "audit": _audit("dispatch", tasks=len(tasks), waves=len(waves)),
    }


async def aggregate_node(
    state: OrchestratorState, deps: OrchestratorDeps
) -> dict[str, Any]:
    """聚合入口薄委派：实际聚合由 advance_run 链异步推进，这里登记移交说明。"""
    run_id = state.get("run_id", "")
    note = ""
    if deps.aggregate_run is not None:
        try:
            note = await deps.aggregate_run(run_id)
        except Exception as e:  # noqa: BLE001
            logger.exception("orchestrator.aggregate 失败 run_id={} error={}", run_id, e)
            return {"error": str(e), "audit": _audit("aggregate", error=str(e))}
    logger.info("orchestrator.aggregate 完成 run_id={} note={}", run_id, note[:80])
    await deps.emit_chunk(
        ChatChunk(
            type="overdrive_progress",
            metadata={
                "phase": "aggregating",
                "label": note or "各分支结果将由 Manager 复核并汇总交付",
                "run_id": run_id,
            },
        )
    )
    return {
        "aggregate_note": note,
        "error": None,
        "audit": _audit("aggregate", note=note[:120]),
    }


def route_after_plan_generate(state: OrchestratorState) -> str:
    if state.get("error"):
        return "end"
    return "plan_confirm"


def route_after_plan_confirm(state: OrchestratorState) -> str:
    """确认后路由：approved→dispatch；cancelled/出错→end；
    文字反馈→plan_generate 重规划；修改回写→plan_confirm 重新确认。"""
    if state.get("error"):
        return "end"
    status = state.get("plan_status")
    if status == "approved":
        return "dispatch"
    if status == "replanning":
        return "plan_generate"
    return "plan_confirm"


class OrchestratorEngine(Protocol):
    """Orchestrator 引擎抽象点（B 方案预留）：当前唯一实现是 LangGraph 编排图，
    未来可替换为专用引擎而不影响 chat_service 接线。"""

    def stream(self, initial: OrchestratorState) -> AsyncIterator[ChatChunk]: ...
    def resume(self, run_id: str, decision: dict[str, Any]) -> AsyncIterator[ChatChunk]: ...


class LangGraphOrchestratorEngine:
    """LangGraph 编排图引擎 — 驱动 4 节点图并透出 ChatChunk（不产 done，由调用方收尾）

    checkpointer 即图执行恢复载体：生产环境挂 PostgresSaver（见
    checkpointer.py），测试环境用 InMemorySaver。thread_id = run_id，
    崩溃后从最后一致 checkpoint 恢复；已落账的派发/确认由生产 delegate
    的 ledger 对账保证不重复执行。
    """

    def __init__(self, deps: OrchestratorDeps, checkpointer: Any = None) -> None:
        self._deps = deps
        self._checkpointer = checkpointer if checkpointer is not None else InMemorySaver()
        self.last_state: dict[str, Any] = {}
        self.error: str | None = None
        # interrupt 触发时透出给调用方的确认卡 payload（kind=plan_confirmation）
        self.interrupt_payload: dict[str, Any] | None = None
        self._graph = self._build_graph()

    def _build_graph(self) -> Any:
        deps = self._deps

        async def _plan_generate(state: OrchestratorState) -> dict[str, Any]:
            return await plan_generate_node(state, deps)

        async def _plan_confirm(state: OrchestratorState) -> dict[str, Any]:
            return await plan_confirm_node(state, deps)

        async def _dispatch(state: OrchestratorState) -> dict[str, Any]:
            return await dispatch_node(state, deps)

        async def _aggregate(state: OrchestratorState) -> dict[str, Any]:
            return await aggregate_node(state, deps)

        builder: StateGraph[OrchestratorState] = StateGraph(OrchestratorState)
        builder.add_node("plan_generate", _plan_generate)
        builder.add_node("plan_confirm", _plan_confirm)
        builder.add_node("dispatch", _dispatch)
        builder.add_node("aggregate", _aggregate)
        builder.set_entry_point("plan_generate")
        builder.add_conditional_edges(
            "plan_generate",
            route_after_plan_generate,
            {"plan_confirm": "plan_confirm", "end": END},
        )
        builder.add_conditional_edges(
            "plan_confirm",
            route_after_plan_confirm,
            {
                "dispatch": "dispatch",
                "plan_generate": "plan_generate",
                "plan_confirm": "plan_confirm",
                "end": END,
            },
        )
        builder.add_edge("dispatch", "aggregate")
        builder.add_edge("aggregate", END)
        return builder.compile(checkpointer=self._checkpointer)

    @staticmethod
    def _config(run_id: str) -> dict[str, Any]:
        return {"configurable": {"thread_id": run_id}}

    async def get_state(self, run_id: str) -> dict[str, Any]:
        """读取线程最新 checkpoint state（测试与恢复对账用）。"""
        snapshot = await self._graph.aget_state(self._config(run_id))
        return dict(snapshot.values or {})

    def _handle_result(self, result: dict[str, Any]) -> list[ChatChunk]:
        """把图执行结果映射为收尾 chunk：interrupt → ask_request 确认卡。"""
        self.last_state = {
            key: value for key, value in result.items() if key != "__interrupt__"
        }
        self.error = self.last_state.get("error")
        interrupts = result.get("__interrupt__") or []
        tail: list[ChatChunk] = []
        if interrupts:
            payload = dict(getattr(interrupts[0], "value", None) or {})
            self.interrupt_payload = payload
            if payload.get("kind") == "plan_confirmation":
                tail.append(
                    ChatChunk(
                        type="ask_request",
                        metadata={
                            "kind": "plan_confirmation",
                            "run_id": payload.get("run_id"),
                            "plan_version": payload.get("plan_version"),
                            "plan_hash": payload.get("plan_hash"),
                            "summary": payload.get("summary") or {},
                            "actions": payload.get("actions")
                            or ["approve", "revise", "cancel"],
                        },
                    )
                )
        elif self.error:
            tail.append(ChatChunk(type="error", content=self.error))
        return tail

    async def _drive(
        self, input_value: Any, run_id: str
    ) -> AsyncIterator[ChatChunk]:
        queue: asyncio.Queue[ChatChunk | None] = asyncio.Queue()

        async def _emit(chunk: ChatChunk) -> None:
            await queue.put(chunk)

        self._deps.emit = _emit

        async def _run() -> None:
            try:
                result = cast(
                    dict[str, Any],
                    await self._graph.ainvoke(
                        input_value,
                        config={**self._config(run_id), "recursion_limit": 24},
                    ),
                )
                for chunk in self._handle_result(result):
                    await queue.put(chunk)
            except Exception as e:  # noqa: BLE001
                self.error = str(e)
                await queue.put(ChatChunk(type="error", content=f"编排图运行时异常: {e}"))
            finally:
                await queue.put(None)

        task = asyncio.create_task(_run())
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            if not task.done():
                task.cancel()

    def stream(self, initial: OrchestratorState) -> AsyncIterator[ChatChunk]:
        """从 plan_generate 起驱动图，interrupt 时透出 ask_request 确认卡。"""
        return self._drive(dict(initial), str(initial.get("run_id") or ""))

    def resume(self, run_id: str, decision: dict[str, Any]) -> AsyncIterator[ChatChunk]:
        """把用户决策以 Command(resume=...) 喂回 plan_confirm 的 interrupt 点。"""
        return self._drive(Command(resume=decision), run_id)


def build_orchestrator_engine(
    deps: OrchestratorDeps, checkpointer: Any = None
) -> OrchestratorEngine:
    """Orchestrator 引擎工厂（Engine Interface 抽象点，不锁死底层）。"""
    return LangGraphOrchestratorEngine(deps, checkpointer)


def build_ledger_resume_deps(
    db: Any,
    *,
    user_id: str,
    commit: Callable[[], Awaitable[None]] | None = None,
) -> OrchestratorDeps:
    """plan-decision resume 用的账本薄委派集合（decide/dispatch/aggregate/refresh）。

    决策先由 plan-decision API 经 OverdriveRunService.decide_plan 落账
    （command_id 幂等），resume 只驱动图继续走 dispatch/aggregate 节点：
    图内 decide 委派命中幂等记录直接返回，dispatch 委派先对账 ledger
    再触发 advance_run，保证恢复/重试语义下不重复确认、不重复派发。
    """
    from omichub.application.services.overdrive_run_service import OverdriveRunService

    run_service = OverdriveRunService(db)

    async def _commit() -> None:
        if commit is not None:
            await commit()

    async def decide_plan(
        state: OrchestratorState, action: str, feedback: str, command_id: str
    ) -> dict[str, Any]:
        result = await run_service.decide_plan(
            run_id=state["run_id"],
            user_id=user_id,
            command_id=command_id,
            action=action,  # type: ignore[arg-type]
            plan_version=int(state.get("plan_version") or 0),
            plan_digest=str(state.get("plan_hash") or ""),
            feedback=feedback,
        )
        await _commit()
        return result

    async def refresh_plan(state: OrchestratorState) -> dict[str, Any]:
        run = await run_service.get_for_user(state["run_id"], user_id)
        plan = dict((run.plan if run is not None else None) or {})
        return {
            "plan_version": int(plan.get("version") or 0),
            "plan_hash": str(plan.get("hash") or ""),
            "plan_summary": dict(plan.get("summary") or {}),
            "plan_tasks": [dict(task) for task in ((run.tasks if run else None) or [])],
        }

    async def dispatch_run(
        run_id: str, tasks: list[dict[str, Any]], waves: list[list[str]]
    ) -> None:
        run = await run_service.get_for_user(run_id, user_id, lock=True)
        if run is None:
            raise ValidationError("超频 run 不存在或无权访问")
        await run_service.assert_execution_allowed(run)
        if str(run.status) != "SERIAL_PREFLIGHT":
            # ledger 对账：账本已进入派发之后的状态（恢复重放/重复 resume），不重复派发
            logger.warning(
                "orchestrator.dispatch 跳过重复派发 run_id={} status={}",
                run_id,
                run.status,
            )
            return
        from omichub.infrastructure.celery_app.tasks.overdrive import advance_run

        advance_run.delay(run_id)

    async def aggregate_run(run_id: str) -> str:
        note = "各执行任务已移交 Overdrive 派发链，Manager 复核与交付汇总异步推进"
        await run_service.append_event(
            run_id,
            "orchestrator_graph_dispatched",
            {"engine": "langgraph", "note": note},
            dedupe_key=f"orchestrator_graph_dispatched:{run_id}",
        )
        await _commit()
        return note

    return OrchestratorDeps(
        decide_plan=decide_plan,
        refresh_plan=refresh_plan,
        dispatch_run=dispatch_run,
        aggregate_run=aggregate_run,
    )

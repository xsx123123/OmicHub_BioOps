"""Orchestrator 编排图单元测试：4 节点薄委派 + interrupt 确认语义

覆盖 P0 验收点：
- plan_generate 输出与 Overdrive plan task schema 兼容（depends_on/retry/
  timeout_seconds 等契约字段），环检测拒绝循环依赖；
- plan_confirm interrupt 暂停 + approve resume 走到 dispatch/aggregate；
- 用户在确认点修改计划（删掉一个非必需分支）→ 回写 state 后重跑
  validate_plan，dispatch 按修改后计划执行；
- cancel / revise(feedback) 重规划 / 修改次数上限 / 账本漂移对账路径。
"""

from __future__ import annotations

from typing import Any

from omichub.core.exceptions import ValidationError
from omichub.infrastructure.execution.orchestrator_graph import (
    OrchestratorDeps,
    build_orchestrator_engine,
)

KNOWN_AGENTS = {"agent-rnaseq", "agent-general"}


def _task(
    task_id: str,
    *,
    agent_id: str = "agent-rnaseq",
    depends_on: list[str] | None = None,
) -> dict[str, Any]:
    """对齐 Overdrive plan task dict schema 的最小合法任务。"""
    return {
        "task_id": task_id,
        "agent_id": agent_id,
        "depends_on": list(depends_on or []),
        "accepts_inputs": [],
        "produces_outputs": [f"{task_id}-result"],
        "completion_criteria": [f"真实产出并登记 {task_id}-result"],
        "tools": ["workspace_read"],
        "timeout_seconds": 600,
        "retry": {"max_attempts": 2, "backoff_seconds": 5},
        "requires_approval": False,
    }


def _plan_markdown() -> str:
    """生成通过 validate_plan 章节校验的最小 plan.md（12 个必备章节）。"""
    from omichub.application.services.overdrive_run_service import PLAN_SECTIONS

    return "\n".join(
        f"## {index}. {section}\n\n- 占位\n"
        for index, section in enumerate(PLAN_SECTIONS, start=1)
    )


def _make_deps(
    tasks: list[dict[str, Any]],
    *,
    calls: list[tuple],
    decide_error: Exception | None = None,
) -> OrchestratorDeps:
    """mock 全部副作用依赖；validate_plan 用真实实现（含环检测）。"""

    async def prepare_plan(state: dict[str, Any]) -> dict[str, Any]:
        calls.append(("prepare_plan", state.get("revision_feedback", "")))
        version = len([c for c in calls if c[0] == "prepare_plan"])
        return {
            "content": _plan_markdown(),
            "tasks": [dict(task) for task in tasks],
            "summary": {"title": "测试计划"},
            "version": version,
            "hash": f"sha256:{version:064d}",
        }

    async def decide_plan(
        state: dict[str, Any], action: str, feedback: str, command_id: str
    ) -> dict[str, Any]:
        calls.append(("decide_plan", action, command_id))
        if decide_error is not None and action == "approve":
            raise decide_error
        return {"status": "ok"}

    async def freeze_revision(
        state: dict[str, Any], edited_tasks: list[dict[str, Any]]
    ) -> dict[str, Any]:
        calls.append(("freeze_revision", [t["task_id"] for t in edited_tasks]))
        return {
            "version": int(state.get("plan_version") or 1) + 1,
            "hash": "sha256:" + "f" * 64,
            "summary": {"title": "测试计划（修订）"},
        }

    async def refresh_plan(state: dict[str, Any]) -> dict[str, Any]:
        calls.append(("refresh_plan", state.get("run_id")))
        return {
            "plan_version": 9,
            "plan_hash": "sha256:" + "9" * 64,
            "plan_summary": {"title": "账本最新计划"},
            "plan_tasks": [dict(task) for task in tasks],
        }

    async def dispatch_run(
        run_id: str, dispatched: list[dict[str, Any]], waves: list[list[str]]
    ) -> None:
        calls.append(("dispatch_run", run_id, [t["task_id"] for t in dispatched], waves))

    async def aggregate_run(run_id: str) -> str:
        calls.append(("aggregate_run", run_id))
        return "聚合已移交"

    return OrchestratorDeps(
        prepare_plan=prepare_plan,
        decide_plan=decide_plan,
        freeze_revision=freeze_revision,
        refresh_plan=refresh_plan,
        dispatch_run=dispatch_run,
        aggregate_run=aggregate_run,
        known_agent_ids=set(KNOWN_AGENTS),
    )


def _initial(run_id: str = "run-1") -> dict[str, Any]:
    return {
        "run_id": run_id,
        "session_id": "s-1",
        "user_id": "u-1",
        "root_request": "做 RNA-seq 差异表达并出报告",
        "revision_feedback": "",
        "plan_status": "not_started",
        "revision_count": 0,
        "dispatched": False,
    }


async def test_plan_generate_outputs_schema_compatible_and_interrupts() -> None:
    """复合意图 → plan_generate 产出合法 DAG（含 depends_on/retry/timeout），
    图停在 plan_confirm interrupt 并透出 ask_request(kind=plan_confirmation)。"""
    tasks = [_task("qc"), _task("deg", depends_on=["qc"])]
    calls: list[tuple] = []
    engine = build_orchestrator_engine(_make_deps(tasks, calls=calls))

    chunks = [chunk async for chunk in engine.stream(_initial())]

    ask = [c for c in chunks if c.type == "ask_request"]
    assert len(ask) == 1
    assert ask[0].metadata["kind"] == "plan_confirmation"
    assert ask[0].metadata["run_id"] == "run-1"
    assert ask[0].metadata["plan_version"] == 1
    assert ask[0].metadata["actions"] == ["approve", "revise", "cancel"]
    # 未确认前绝不派发
    assert not any(call[0] == "dispatch_run" for call in calls)
    # plan_generate 产出的 task dict 与 Overdrive schema 兼容（真实 validate_plan 放行）
    from omichub.application.services.overdrive_run_service import validate_plan

    validate_plan(_plan_markdown(), tasks, KNOWN_AGENTS)
    state = await engine.get_state("run-1")
    assert state["plan_status"] == "awaiting_confirmation"
    assert [t["task_id"] for t in state["plan_tasks"]] == ["qc", "deg"]


async def test_cycle_in_revised_plan_rejected_by_validation() -> None:
    """确认点把计划改成循环依赖 → validate_plan 环检测拒绝，图以 error 收尾。"""
    tasks = [_task("qc"), _task("deg", depends_on=["qc"])]
    calls: list[tuple] = []
    engine = build_orchestrator_engine(_make_deps(tasks, calls=calls))
    [chunk async for chunk in engine.stream(_initial())]

    cyclic = [_task("qc", depends_on=["deg"]), _task("deg", depends_on=["qc"])]
    chunks = [
        chunk
        async for chunk in engine.resume(
            "run-1", {"action": "revise", "tasks": cyclic, "command_id": "cmd-cyc"}
        )
    ]

    assert engine.error is not None and "循环依赖" in engine.error
    assert not any(call[0] == "freeze_revision" for call in calls)
    assert not any(call[0] == "dispatch_run" for call in calls)
    assert any(c.type == "error" for c in chunks)


async def test_approve_resume_dispatches_and_aggregates() -> None:
    """approve resume → decide_plan(approve) → dispatch 按拓扑波次 → aggregate。"""
    tasks = [_task("qc"), _task("deg", depends_on=["qc"])]
    calls: list[tuple] = []
    engine = build_orchestrator_engine(_make_deps(tasks, calls=calls))
    [chunk async for chunk in engine.stream(_initial())]

    chunks = [
        chunk
        async for chunk in engine.resume(
            "run-1", {"action": "approve", "command_id": "cmd-approve"}
        )
    ]

    assert ("decide_plan", "approve", "cmd-approve") in calls
    dispatch = next(call for call in calls if call[0] == "dispatch_run")
    assert dispatch[1] == "run-1"
    assert dispatch[2] == ["qc", "deg"]
    assert dispatch[3] == [["qc"], ["deg"]]  # 拓扑波次：qc 先行，deg 依赖 qc
    assert ("aggregate_run", "run-1") in calls
    assert any(
        c.type == "overdrive_progress" and c.metadata.get("phase") == "dispatching"
        for c in chunks
    )
    state = await engine.get_state("run-1")
    assert state["plan_status"] == "approved"
    assert state["dispatched"] is True
    assert state["aggregate_note"] == "聚合已移交"


async def test_revise_with_edited_tasks_revalidates_and_redispatches() -> None:
    """确认点删掉一个非必需分支 → 回写重校验冻结新版本 → 再次确认后
    dispatch 只按修改后的计划执行。"""
    tasks = [_task("qc"), _task("deg", depends_on=["qc"]), _task("enrich", depends_on=["deg"])]
    calls: list[tuple] = []
    engine = build_orchestrator_engine(_make_deps(tasks, calls=calls))
    [chunk async for chunk in engine.stream(_initial())]

    edited = [_task("qc"), _task("deg", depends_on=["qc"])]  # 删掉 enrich 分支
    chunks = [
        chunk
        async for chunk in engine.resume(
            "run-1", {"action": "revise", "tasks": edited, "command_id": "cmd-edit"}
        )
    ]

    # 修改回写后冻结 v2 并重新 interrupt 等待确认
    assert ("freeze_revision", ["qc", "deg"]) in calls
    ask = [c for c in chunks if c.type == "ask_request"]
    assert len(ask) == 1
    assert ask[0].metadata["plan_version"] == 2
    assert not any(call[0] == "dispatch_run" for call in calls)

    chunks = [
        chunk
        async for chunk in engine.resume(
            "run-1", {"action": "approve", "command_id": "cmd-approve-2"}
        )
    ]
    dispatch = next(call for call in calls if call[0] == "dispatch_run")
    assert dispatch[2] == ["qc", "deg"]  # 按修改后计划派发，不含 enrich
    state = await engine.get_state("run-1")
    assert state["revision_count"] == 1
    assert state["dispatched"] is True


async def test_cancel_resume_ends_graph_without_dispatch() -> None:
    """cancel resume → decide_plan(cancel) → 图结束，不派发不聚合。"""
    calls: list[tuple] = []
    engine = build_orchestrator_engine(_make_deps([_task("qc")], calls=calls))
    [chunk async for chunk in engine.stream(_initial())]

    [  # cancel 收尾不产出业务 chunk，只驱动图到 END
        chunk
        async for chunk in engine.resume(
            "run-1", {"action": "cancel", "command_id": "cmd-cancel"}
        )
    ]

    assert ("decide_plan", "cancel", "cmd-cancel") in calls
    assert not any(call[0] == "dispatch_run" for call in calls)
    assert not any(call[0] == "aggregate_run" for call in calls)
    state = await engine.get_state("run-1")
    assert state["plan_status"] == "cancelled"


async def test_revise_with_feedback_regenerates_plan() -> None:
    """revise(文字反馈) → 回灌 plan_generate 重新规划 → 再次 interrupt。"""
    calls: list[tuple] = []
    engine = build_orchestrator_engine(_make_deps([_task("qc")], calls=calls))
    [chunk async for chunk in engine.stream(_initial())]

    chunks = [
        chunk
        async for chunk in engine.resume(
            "run-1",
            {"action": "revise", "feedback": "请补充通路富集分析", "command_id": "cmd-fb"},
        )
    ]

    prepare_calls = [call for call in calls if call[0] == "prepare_plan"]
    assert len(prepare_calls) == 2
    assert prepare_calls[1][1] == "请补充通路富集分析"  # 反馈回灌重规划
    assert ("decide_plan", "revise", "cmd-fb") in calls
    ask = [c for c in chunks if c.type == "ask_request"]
    assert len(ask) == 1  # 新计划再次等待确认
    state = await engine.get_state("run-1")
    assert state["revision_count"] == 1


async def test_revise_limit_blocks_further_revisions() -> None:
    """修改次数达到上限后拒绝继续 revise。"""
    calls: list[tuple] = []
    deps = _make_deps([_task("qc")], calls=calls)
    deps.max_revisions = 1
    engine = build_orchestrator_engine(deps)
    [chunk async for chunk in engine.stream(_initial())]
    [chunk async for chunk in engine.resume(
        "run-1", {"action": "revise", "feedback": "第一次修改", "command_id": "cmd-r1"}
    )]

    chunks = [
        chunk
        async for chunk in engine.resume(
            "run-1", {"action": "revise", "feedback": "第二次修改", "command_id": "cmd-r2"}
        )
    ]

    assert engine.error is not None and "上限" in engine.error
    assert any(c.type == "error" for c in chunks)


async def test_stale_ledger_version_reconciles_and_reconfirms() -> None:
    """decide 时账本版本/hash 漂移（旁路 replan 已冻结新版本）→ 对账
    refresh_plan 后重新 interrupt，不重复确认旧快照。"""
    calls: list[tuple] = []
    deps = _make_deps(
        [_task("qc")], calls=calls, decide_error=ValidationError("计划版本已变化，请刷新后重新确认")
    )
    engine = build_orchestrator_engine(deps)
    [chunk async for chunk in engine.stream(_initial())]

    chunks = [
        chunk
        async for chunk in engine.resume(
            "run-1", {"action": "approve", "command_id": "cmd-stale"}
        )
    ]

    assert ("refresh_plan", "run-1") in calls
    ask = [c for c in chunks if c.type == "ask_request"]
    assert len(ask) == 1
    assert ask[0].metadata["plan_version"] == 9  # 对账后的账本最新版本
    assert not any(call[0] == "dispatch_run" for call in calls)

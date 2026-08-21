"""Orchestrator 编排图 checkpoint 恢复测试（InMemorySaver 模拟）

对应 P0 验收"执行中途重启服务，从最后 checkpoint 恢复，不重复已完成的派发"：
- interrupt 后用同一 saver 重建引擎（模拟服务重启），resume 继续执行；
- 已确认的计划不重复确认（decide 只调用一次）；
- 已派发的任务不重复派发（重复 resume 是 no-op，dispatch 只调用一次）；
- 崩溃发生在 dispatch 之后（aggregate 抛错）：ledger 对账型 dispatch 委派
  在恢复重放时跳过重复派发。

生产环境 checkpointer 为 PostgresSaver（同一代码路径，仅后端不同）。
"""

from __future__ import annotations

from typing import Any

from langgraph.checkpoint.memory import InMemorySaver

from omichub.infrastructure.execution.orchestrator_graph import (
    OrchestratorDeps,
    build_orchestrator_engine,
)

TASK = {
    "task_id": "deg",
    "agent_id": "agent-rnaseq",
    "depends_on": [],
    "accepts_inputs": [],
    "produces_outputs": ["deg-result"],
    "completion_criteria": ["真实产出并登记 deg-result"],
    "tools": ["workspace_read"],
    "timeout_seconds": 600,
    "retry": {"max_attempts": 2, "backoff_seconds": 5},
    "requires_approval": False,
}

INITIAL = {
    "run_id": "run-recover",
    "session_id": "s-1",
    "user_id": "u-1",
    "root_request": "差异表达分析",
    "revision_feedback": "",
    "plan_status": "not_started",
    "revision_count": 0,
    "dispatched": False,
}


def _make_deps(calls: list[tuple], **overrides: Any) -> OrchestratorDeps:
    async def prepare_plan(state: dict[str, Any]) -> dict[str, Any]:
        calls.append(("prepare_plan",))
        return {
            "content": "plan",
            "tasks": [dict(TASK)],
            "summary": {},
            "version": 1,
            "hash": "sha256:" + "0" * 64,
        }

    async def decide_plan(
        state: dict[str, Any], action: str, feedback: str, command_id: str
    ) -> dict[str, Any]:
        calls.append(("decide_plan", action))
        return {"status": "ok"}

    async def dispatch_run(
        run_id: str, tasks: list[dict[str, Any]], waves: list[list[str]]
    ) -> None:
        calls.append(("dispatch_run", run_id))

    async def aggregate_run(run_id: str) -> str:
        calls.append(("aggregate_run", run_id))
        return "聚合已移交"

    deps = OrchestratorDeps(
        prepare_plan=prepare_plan,
        decide_plan=decide_plan,
        dispatch_run=dispatch_run,
        aggregate_run=aggregate_run,
        known_agent_ids={"agent-rnaseq"},
    )
    for key, value in overrides.items():
        setattr(deps, key, value)
    return deps


async def test_rebuild_engine_from_checkpoint_resumes_interrupt() -> None:
    """interrupt 后重建引擎（模拟重启）：从 checkpoint 恢复，resume 后
    plan_generate 不重跑、确认不重复、派发只执行一次。"""
    saver = InMemorySaver()
    calls: list[tuple] = []
    deps = _make_deps(calls)

    engine_v1 = build_orchestrator_engine(deps, checkpointer=saver)
    chunks = [chunk async for chunk in engine_v1.stream(INITIAL)]
    assert any(c.type == "ask_request" for c in chunks)
    assert [c[0] for c in calls] == ["prepare_plan"]

    # 服务重启：同一 saver（生产为同库 PostgresSaver）重建引擎再 resume
    engine_v2 = build_orchestrator_engine(deps, checkpointer=saver)
    chunks = [
        chunk
        async for chunk in engine_v2.resume(
            "run-recover", {"action": "approve", "command_id": "cmd-1"}
        )
    ]

    names = [c[0] for c in calls]
    assert names == ["prepare_plan", "decide_plan", "dispatch_run", "aggregate_run"]
    assert not any(c.type == "ask_request" for c in chunks)  # 不重复推送确认卡
    state = await engine_v2.get_state("run-recover")
    assert state["dispatched"] is True
    assert state["plan_status"] == "approved"


async def test_duplicate_resume_after_completion_does_not_redispatch() -> None:
    """恢复完成后重复 resume（API 重试/双击）：不重复确认、不重复派发。"""
    saver = InMemorySaver()
    calls: list[tuple] = []
    deps = _make_deps(calls)

    engine = build_orchestrator_engine(deps, checkpointer=saver)
    [chunk async for chunk in engine.stream(INITIAL)]
    [chunk async for chunk in engine.resume(
        "run-recover", {"action": "approve", "command_id": "cmd-1"}
    )]

    # 重复 resume：图已在终态，checkpoint 语义下不产生任何节点重放
    chunks = [
        chunk
        async for chunk in engine.resume(
            "run-recover", {"action": "approve", "command_id": "cmd-1"}
        )
    ]

    names = [c[0] for c in calls]
    assert names.count("decide_plan") == 1
    assert names.count("dispatch_run") == 1
    assert names.count("aggregate_run") == 1
    assert chunks == []


async def test_crash_after_dispatch_recovers_without_duplicate_dispatch() -> None:
    """崩溃发生在 dispatch 落账之后（aggregate 首次执行抛错）：恢复时
    ledger 对账型 dispatch 委派看到账本已推进则跳过，不重复派发。"""
    saver = InMemorySaver()
    calls: list[tuple] = []
    ledger = {"status": "AWAITING_PLAN_CONFIRMATION"}
    dispatched: list[str] = []

    async def ledger_guarded_dispatch(
        run_id: str, tasks: list[dict[str, Any]], waves: list[list[str]]
    ) -> None:
        # 模拟生产 dispatch 委派的 ledger 对账：已确认 → 置 SERIAL_PREFLIGHT 后
        # 触发派发；恢复重放时账本已越过 SERIAL_PREFLIGHT → 跳过。
        calls.append(("dispatch_run", run_id))
        if ledger["status"] != "SERIAL_PREFLIGHT":
            return
        ledger["status"] = "RECRUITING"
        dispatched.append(run_id)

    deps = _make_deps(calls, dispatch_run=ledger_guarded_dispatch)

    async def decide_and_advance(
        state: dict[str, Any], action: str, feedback: str, command_id: str
    ) -> dict[str, Any]:
        calls.append(("decide_plan", action))
        if action == "approve":
            ledger["status"] = "SERIAL_PREFLIGHT"  # decide_plan(approve) 落账语义
        return {"status": "ok"}

    deps.decide_plan = decide_and_advance

    crashed = {"once": False}

    async def flaky_aggregate(run_id: str) -> str:
        calls.append(("aggregate_run", run_id))
        if not crashed["once"]:
            crashed["once"] = True
            raise RuntimeError("模拟聚合前崩溃")
        return "聚合已移交"

    deps.aggregate_run = flaky_aggregate

    engine_v1 = build_orchestrator_engine(deps, checkpointer=saver)
    [chunk async for chunk in engine_v1.stream(INITIAL)]
    chunks = [
        chunk
        async for chunk in engine_v1.resume(
            "run-recover", {"action": "approve", "command_id": "cmd-1"}
        )
    ]
    assert any(c.type == "error" for c in chunks)  # aggregate 崩溃透出 error
    assert dispatched == ["run-recover"]  # dispatch 已落账执行过一次

    # 服务重启后重建引擎；此时图无 pending interrupt，重复 resume 是 no-op，
    # 即便重放 dispatch，ledger 对账委派也会因 status=RECRUITING 跳过。
    engine_v2 = build_orchestrator_engine(deps, checkpointer=saver)
    recovered = await engine_v2.get_state("run-recover")
    assert recovered.get("dispatched") is True  # checkpoint 恢复了 dispatched 落账标记
    await ledger_guarded_dispatch("run-recover", [dict(TASK)], [["deg"]])
    assert dispatched == ["run-recover"]  # 不重复派发

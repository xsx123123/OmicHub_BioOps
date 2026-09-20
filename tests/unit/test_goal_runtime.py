"""Focused unit coverage for the isolated persistent Goal runtime."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.goal import (
    GoalAnswerRequest,
    GoalControlRequest,
    GoalStartRequest,
)
from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.goal_adapters.fanout_adapter import GoalFanoutAdapter
from cygnusx.application.services.goal_evaluator import GoalEvaluator
from cygnusx.application.services.goal_execution_engine import (
    ChatServiceGoalStepExecutor,
    GoalExecutionEngine,
    GoalStepResult,
    GoalStepSnapshot,
)
from cygnusx.application.services.goal_service import GoalService
from cygnusx.application.services.goal_terminal_tools import GoalTerminalToolService
from cygnusx.infrastructure.database.models.goal import AgentGoalModel, AgentGoalWorkUnitModel


def _goal() -> AgentGoalModel:
    now = datetime.now(UTC)
    return AgentGoalModel(
        id=uuid4(),
        user_id=uuid4(),
        manager_agent_id="general",
        objective="Summarize the current platform",
        success_criteria=["A concise summary"],
        mode="chat",
        permission="safe",
        status="in_progress",
        event_sequence=0,
        version=0,
        turn_count=0,
        max_turns=20,
        tokens_used=0,
        plan_snapshot={},
        started_at=now,
        created_at=now,
        updated_at=now,
    )


def test_goal_model_uses_optimistic_version_column() -> None:
    assert AgentGoalModel.__mapper__.version_id_col is AgentGoalModel.__table__.c.version


def test_goal_events_have_per_goal_dedupe_constraint() -> None:
    from cygnusx.infrastructure.database.models.goal import AgentGoalEventModel

    constraints = {
        tuple(column.name for column in constraint.columns)
        for constraint in AgentGoalEventModel.__table__.constraints
        if constraint.name == "uq_goal_events_goal_dedupe_key"
    }

    assert constraints == {("goal_id", "dedupe_key")}


@pytest.mark.asyncio
async def test_goal_engine_skips_step_when_redis_lease_is_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class DeniedLease:
        acquired = False
        lost = False

        def __init__(self, *_args: object, **_kwargs: object) -> None:
            pass

        async def __aenter__(self) -> DeniedLease:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    executor = Mock()
    monkeypatch.setattr(
        "cygnusx.infrastructure.cache.goal_lease.GoalRedisLease",
        DeniedLease,
    )

    should_continue = await GoalExecutionEngine(Mock(), step_executor=executor).run_once(uuid4())

    assert should_continue is False
    executor.execute.assert_not_called()


@pytest.mark.asyncio
async def test_goal_pause_records_auditable_event(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cygnusx.application.services.goal_service.get_settings",
        lambda: SimpleNamespace(goal_runtime_enabled=True),
    )
    session = Mock()
    session.flush = AsyncMock()
    service = GoalService(session)
    goal = _goal()
    service._owned_goal = AsyncMock(return_value=goal)  # type: ignore[method-assign]

    response = await service.pause_goal(str(goal.user_id), goal.id, GoalControlRequest(reason="review"))

    assert response.status == "paused"
    assert goal.version == 1
    assert goal.event_sequence == 1
    event = session.add.call_args.args[0]
    assert event.event_type == "paused"
    assert event.payload == {"reason": "review"}


@pytest.mark.asyncio
async def test_goal_resume_only_accepts_paused_or_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "cygnusx.application.services.goal_service.get_settings",
        lambda: SimpleNamespace(goal_runtime_enabled=True),
    )
    session = Mock()
    session.flush = AsyncMock()
    service = GoalService(session)
    goal = _goal()
    service._owned_goal = AsyncMock(return_value=goal)  # type: ignore[method-assign]

    with pytest.raises(Exception, match="不允许切换"):
        await service.resume_goal(str(goal.user_id), goal.id, GoalControlRequest())


@pytest.mark.asyncio
async def test_goal_phase_one_rejects_studio_or_non_safe_permissions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cygnusx.application.services.goal_service.get_settings",
        lambda: SimpleNamespace(goal_runtime_enabled=True),
    )
    service = GoalService(Mock())

    with pytest.raises(Exception, match=r"仅支持 chat \+ safe"):
        await service.create_goal(
            str(uuid4()),
            GoalStartRequest(
                objective="Run a Studio task",
                session_id="session-1",
                mode="studio",
                permission="full",
            ),
        )


@pytest.mark.asyncio
async def test_goal_answer_requires_waiting_state_and_is_audited(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cygnusx.application.services.goal_service.get_settings",
        lambda: SimpleNamespace(goal_runtime_enabled=True),
    )
    session = Mock()
    session.flush = AsyncMock()
    service = GoalService(session)
    goal = _goal()
    goal.status = "waiting_user"
    goal.plan_snapshot = {"pending_user_request": {"question": "Which sample?"}}
    service._owned_goal = AsyncMock(return_value=goal)  # type: ignore[method-assign]

    response = await service.answer_goal(
        str(goal.user_id), goal.id, GoalAnswerRequest(answer="Use sample A")
    )

    assert response.status == "in_progress"
    assert "pending_user_request" not in goal.plan_snapshot
    assert goal.plan_snapshot["latest_user_answer"]["answer"] == "Use sample A"
    event = session.add.call_args.args[0]
    assert event.event_type == "user_answered"


@pytest.mark.asyncio
async def test_goal_resume_cannot_bypass_waiting_user_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "cygnusx.application.services.goal_service.get_settings",
        lambda: SimpleNamespace(goal_runtime_enabled=True),
    )
    session = Mock()
    session.flush = AsyncMock()
    service = GoalService(session)
    goal = _goal()
    goal.status = "waiting_user"
    service._owned_goal = AsyncMock(return_value=goal)  # type: ignore[method-assign]

    with pytest.raises(Exception, match="不允许切换"):
        await service.resume_goal(str(goal.user_id), goal.id, GoalControlRequest())


def test_goal_step_prompt_includes_latest_user_answer() -> None:
    snapshot = GoalStepSnapshot(
        goal_id=uuid4(),
        user_id=str(uuid4()),
        session_id="session-1",
        manager_agent_id="agent-general",
        objective="Build a report",
        success_criteria=["Report exists"],
        mode="chat",
        turn_count=1,
        max_turns=5,
        plan_snapshot={"latest_user_answer": {"answer": "Use sample A"}},
    )

    prompt = ChatServiceGoalStepExecutor._build_prompt(snapshot)

    assert "Latest user answer:\nUse sample A" in prompt


def test_goal_step_prompt_is_bounded_and_carries_checkpoint() -> None:
    snapshot = GoalStepSnapshot(
        goal_id=uuid4(),
        user_id=str(uuid4()),
        session_id="session-1",
        manager_agent_id="general",
        objective="Build a report",
        success_criteria=["Report exists"],
        mode="chat",
        turn_count=1,
        max_turns=5,
        plan_snapshot={"last_response": "previous evidence"},
    )

    prompt = ChatServiceGoalStepExecutor._build_prompt(snapshot)

    assert "Iteration: 2/5" in prompt
    assert "Build a report" in prompt
    assert "Report exists" in prompt
    assert "previous evidence" in prompt


def test_goal_token_budget_uses_total_tokens_only() -> None:
    assert GoalExecutionEngine._token_total({"total_tokens": 42}) == 42
    assert GoalExecutionEngine._token_total({"total_tokens": "7"}) == 7
    assert GoalExecutionEngine._token_total({"total_tokens": -1}) == 0
    assert GoalExecutionEngine._token_total({"prompt_tokens": 3}) == 0


@pytest.mark.asyncio
async def test_goal_step_passes_idempotent_context_to_chat_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeChunk:
        type = "text"
        content = "checkpoint"

    class FakeChatService:
        def __init__(self, _db: object) -> None:
            pass

        async def stream_agent_chat(self, **kwargs):
            captured.update(kwargs)
            yield FakeChunk()

    monkeypatch.setattr(
        "cygnusx.application.services.chat_service.ChatService",
        FakeChatService,
    )
    snapshot = GoalStepSnapshot(
        goal_id=uuid4(),
        user_id=str(uuid4()),
        session_id="session-1",
        manager_agent_id="agent-general",
        objective="Build a report",
        success_criteria=["Report exists"],
        mode="chat",
        turn_count=1,
        max_turns=5,
        plan_snapshot={},
    )

    result = await ChatServiceGoalStepExecutor().execute(object(), snapshot)

    assert result.content == "checkpoint"
    assert captured["runtime_context"] == {
        "goal_id": str(snapshot.goal_id),
        "work_unit_key": "turn-2",
        "idempotency_key": f"{snapshot.goal_id}:turn:2",
        "goal_safe_only": True,
        "goal_fanout_enabled": False,
    }


@pytest.mark.asyncio
async def test_goal_step_enables_parallel_subagents_when_fanout_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    class FakeChatService:
        def __init__(self, _db: object) -> None:
            pass

        async def stream_agent_chat(self, **kwargs):
            captured.update(kwargs)
            if False:
                yield None

    monkeypatch.setattr(
        "cygnusx.application.services.chat_service.ChatService",
        FakeChatService,
    )
    monkeypatch.setattr(
        "cygnusx.application.services.goal_execution_engine.get_settings",
        lambda: SimpleNamespace(goal_fanout_enabled=True),
    )
    snapshot = GoalStepSnapshot(
        goal_id=uuid4(),
        user_id=str(uuid4()),
        session_id="session-1",
        manager_agent_id="agent-general",
        objective="Build a report",
        success_criteria=["Report exists"],
        mode="chat",
        turn_count=1,
        max_turns=5,
        plan_snapshot={},
    )

    await ChatServiceGoalStepExecutor().execute(object(), snapshot)

    assert captured["multi_agent"] is True
    assert captured["runtime_context"]["goal_fanout_enabled"] is True


@pytest.mark.asyncio
async def test_goal_fanout_adapter_assigns_stable_worker_ids() -> None:
    goal_id = uuid4()
    db = AsyncSession()
    context = ToolInvocationContext(
        user_id=str(uuid4()),
        agent_id="manager",
        session_id="session-1",
        db=db,
        extra={"goal_id": str(goal_id), "work_unit_key": "turn-2", "goal_safe_only": True},
    )
    fanout_service = SimpleNamespace(run_parallel_subagents=AsyncMock())
    envelope = {"success": True, "llm_payload": {"results": []}}
    fanout_service.run_parallel_subagents.return_value = envelope
    adapter = GoalFanoutAdapter(fanout_service=fanout_service)
    adapter._start_units = AsyncMock(return_value=None)
    adapter._finish_units = AsyncMock()

    try:
        result = await adapter.execute(
            context_summary="Goal context",
            tasks=[
                {"agent_id": "agent-a", "task": "Research A"},
                {"agent_id": "agent-b", "task": "Research B"},
            ],
            context=context,
        )
    finally:
        await db.close()

    normalized_tasks = fanout_service.run_parallel_subagents.await_args.kwargs["tasks"]
    assert [task["task_id"] for task in normalized_tasks] == [
        "turn-2:fanout:worker:1",
        "turn-2:fanout:worker:2",
    ]
    assert result is envelope
    adapter._finish_units.assert_awaited_once()


@pytest.mark.asyncio
async def test_goal_fanout_adapter_persists_worker_evidence() -> None:
    goal = _goal()
    child = AgentGoalWorkUnitModel(
        goal_id=goal.id,
        work_unit_key="turn-2:fanout:worker:1",
        kind="parallel_worker",
        title="Worker",
        instruction="Research",
        status="running",
        attempt=1,
        idempotency_key=f"{goal.id}:worker:1",
    )
    parent = AgentGoalWorkUnitModel(
        goal_id=goal.id,
        work_unit_key="turn-2:fanout",
        kind="parallel_fanout",
        title="Fanout",
        instruction="Run workers",
        status="running",
        attempt=1,
        idempotency_key=f"{goal.id}:fanout",
    )

    class FakeResult:
        def scalar_one(self):
            return goal

    class FakeDB:
        def __init__(self) -> None:
            self.added: list[object] = []

        async def execute(self, _query):
            return FakeResult()

        def add(self, item: object) -> None:
            self.added.append(item)

        async def commit(self) -> None:
            pass

    fake_db = FakeDB()

    class FakeSessionContext:
        async def __aenter__(self):
            return fake_db

        async def __aexit__(self, *_exc):
            return False

    adapter = GoalFanoutAdapter(session_factory=lambda: FakeSessionContext())
    adapter._unit = AsyncMock(side_effect=[child, parent])
    adapter._publish = AsyncMock()
    envelope = {
        "success": True,
        "llm_payload": {
            "summary": "1/1 worker succeeded",
            "results": [
                {
                    "task_id": child.work_unit_key,
                    "status": "ok",
                    "answer": "Evidence-backed answer",
                    "workdir": "/tmp/goal-worker",
                }
            ],
        },
    }

    await adapter._finish_units(
        goal.id,
        parent.work_unit_key,
        [{"task_id": child.work_unit_key, "agent_id": "agent-a", "task": "Research"}],
        envelope,
    )

    assert child.status == "succeeded"
    assert child.output_ref == {"result": envelope["llm_payload"]["results"][0]}
    assert child.evidence_refs == [
        {"type": "worker_answer", "value": "Evidence-backed answer"},
        {"type": "workspace", "path": "/tmp/goal-worker"},
    ]
    assert parent.status == "succeeded"
    assert parent.output_ref == {"envelope": envelope}
    assert [event.event_type for event in fake_db.added] == [
        "worker_result",
        "fanout_finished",
    ]


@pytest.mark.asyncio
async def test_goal_step_records_usage_from_done_chunk(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeChunk:
        def __init__(self, chunk_type: str, content: str = "", metadata: dict | None = None) -> None:
            self.type = chunk_type
            self.content = content
            self.metadata = metadata or {}

    class FakeChatService:
        def __init__(self, _db: object) -> None:
            pass

        async def stream_agent_chat(self, **_kwargs):
            yield FakeChunk("text", "checkpoint")
            yield FakeChunk("done", metadata={"usage": {"total_tokens": 18}})

    monkeypatch.setattr(
        "cygnusx.application.services.chat_service.ChatService",
        FakeChatService,
    )
    snapshot = GoalStepSnapshot(
        goal_id=uuid4(),
        user_id=str(uuid4()),
        session_id="session-1",
        manager_agent_id="agent-general",
        objective="Build a report",
        success_criteria=["Report exists"],
        mode="chat",
        turn_count=1,
        max_turns=5,
        plan_snapshot={},
    )

    result = await ChatServiceGoalStepExecutor().execute(object(), snapshot)

    assert result.content == "checkpoint"
    assert result.token_usage == {"total_tokens": 18, "prompt_tokens": 0, "completion_tokens": 0}


@pytest.mark.asyncio
async def test_goal_step_stops_for_ask_user(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeChunk:
        type = "ask_request"
        content = ""
        metadata = {"questions": [{"id": "sample", "question": "Which sample?"}]}

    class FakeChatService:
        def __init__(self, _db: object) -> None:
            pass

        async def stream_agent_chat(self, **_kwargs):
            yield FakeChunk()

    monkeypatch.setattr(
        "cygnusx.application.services.chat_service.ChatService",
        FakeChatService,
    )
    snapshot = GoalStepSnapshot(
        goal_id=uuid4(),
        user_id=str(uuid4()),
        session_id="session-1",
        manager_agent_id="agent-general",
        objective="Build a report",
        success_criteria=["Report exists"],
        mode="chat",
        turn_count=1,
        max_turns=5,
        plan_snapshot={},
    )

    result = await ChatServiceGoalStepExecutor().execute(object(), snapshot)

    assert result.waiting_for_user == {
        "questions": [{"id": "sample", "question": "Which sample?"}]
    }


@pytest.mark.asyncio
async def test_goal_complete_tool_requires_manager_and_criterion_evidence() -> None:
    goal = _goal()
    result_proxy = Mock()
    result_proxy.scalar_one_or_none.return_value = goal
    db = AsyncSession()
    db.execute = AsyncMock(return_value=result_proxy)
    context = ToolInvocationContext(
        user_id=str(goal.user_id),
        agent_id=goal.manager_agent_id,
        session_id="session-1",
        db=db,
        extra={"goal_id": str(goal.id)},
    )

    result = await GoalTerminalToolService().execute(
        "goal_complete",
        {
            "evidence": [
                {"criterion": "A concise summary", "evidence": "summary.md"},
            ]
        },
        context,
    )

    assert result["success"] is True
    assert result["result"]["llm_payload"]["action"] == "complete"
    await db.close()


def test_goal_step_result_keeps_terminal_claim() -> None:
    result = GoalStepResult(
        content="done",
        terminal_claim={"action": "complete", "evidence": [], "reason": ""},
    )

    assert result.terminal_claim["action"] == "complete"


def test_goal_evaluator_requires_evidence_for_every_success_criterion() -> None:
    result = GoalEvaluator().evaluate(
        ["Report exists", "Sources listed"],
        """Done.
```goal_result
{"action":"goal_complete","evidence":[
  {"criterion":"Report exists","evidence":"report.md"},
  {"criterion":"Sources listed","evidence":"sources.md"}
]}
```""",
    )

    assert result.action == "complete"


def test_goal_evaluator_rejects_unstructured_completion_claim() -> None:
    result = GoalEvaluator().evaluate(["Report exists"], "Everything is complete.")

    assert result.action == "continue"

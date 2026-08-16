from types import SimpleNamespace
from uuid import uuid4

import pytest

from omichub.application.services.mas_scheduler_service import MASSchedulerService
from omichub.domain.mas.models import (
    A2AEvent,
    A2AEventType,
    AgentRecipient,
    AgentSender,
)


def test_scheduler_only_unlocks_nodes_after_successful_dependencies() -> None:
    nodes = [
        SimpleNamespace(node_key="download", status="succeeded", depends_on=[]),
        SimpleNamespace(node_key="analyse", status="pending", depends_on=["download"]),
        SimpleNamespace(node_key="plot", status="pending", depends_on=["analyse"]),
        SimpleNamespace(node_key="blocked", status="pending", depends_on=["missing"]),
    ]

    assert [node.node_key for node in MASSchedulerService.eligible_nodes(nodes)] == ["analyse"]


class _InMemoryRepository:
    def __init__(self, run: SimpleNamespace, nodes: list[SimpleNamespace]) -> None:
        self.run = run
        self.nodes = {node.node_key: node for node in nodes}
        self.run_transitions: list[tuple[str, str]] = []

    async def get_node(self, run_id, node_key):
        return self.nodes.get(node_key)

    async def transition_node(self, *, node_id, expected_version, current_status, target_status, attempt_count=None):
        node = next(node for node in self.nodes.values() if node.id == node_id)
        if node.version != expected_version or node.status != current_status:
            return False
        node.status = target_status
        node.version += 1
        if attempt_count is not None:
            node.attempt_count = attempt_count
        return True

    async def list_nodes(self, run_id):
        return list(self.nodes.values())

    async def get_run(self, run_id):
        return self.run

    async def transition_run(self, *, run_id, expected_version, current_status, target_status):
        if self.run.version != expected_version or self.run.status != current_status:
            return False
        self.run.status = target_status
        self.run.version += 1
        self.run_transitions.append((current_status, target_status))
        return True


class _RecordedEvents:
    def __init__(self) -> None:
        self.items: list[A2AEvent] = []

    async def record(self, event: A2AEvent) -> bool:
        self.items.append(event)
        return True


def _scheduler(repository: _InMemoryRepository, events: _RecordedEvents) -> MASSchedulerService:
    scheduler = MASSchedulerService.__new__(MASSchedulerService)
    scheduler._repository = repository
    scheduler._events = events
    return scheduler


@pytest.mark.asyncio
async def test_scheduler_dispatches_a_ready_node_once(monkeypatch) -> None:
    import omichub.application.services.mas_scheduler_service as scheduler_module

    enqueued: list[tuple] = []
    monkeypatch.setattr(
        scheduler_module, "enqueue_task", lambda task, *args, **kwargs: enqueued.append(args)
    )
    run_id = uuid4()
    node = SimpleNamespace(
        id=uuid4(),
        node_key="download",
        status="ready",
        version=1,
        attempt_count=0,
        agent_id="agent-rnaseq",
        intent="download",
        resources={"executor": "fake"},
        depends_on=[],
    )
    events = _RecordedEvents()
    scheduler = _scheduler(
        _InMemoryRepository(SimpleNamespace(id=run_id, status="running", version=1), [node]), events
    )

    assert await scheduler.dispatch_ready_node(run_id, "download", "trace-1")
    assert not await scheduler.dispatch_ready_node(run_id, "download", "trace-1")
    assert node.status == "dispatched"
    assert [event.event_type for event in events.items] == [A2AEventType.NODE_DISPATCHED]
    assert enqueued == [(str(run_id), "download")]


@pytest.mark.asyncio
async def test_scheduler_fails_node_with_unknown_executor(monkeypatch) -> None:
    """未知/缺失 executor 的节点必须被显式判失败，不能停在 dispatched 静默悬挂。"""
    import omichub.application.services.mas_scheduler_service as scheduler_module

    enqueued: list[tuple] = []
    monkeypatch.setattr(
        scheduler_module, "enqueue_task", lambda task, *args, **kwargs: enqueued.append(args)
    )
    run_id = uuid4()
    node = SimpleNamespace(
        id=uuid4(),
        node_key="mystery",
        status="ready",
        version=1,
        attempt_count=0,
        agent_id="agent-general",
        intent="mystery",
        resources={"executor": "not-a-real-executor"},
        depends_on=[],
    )
    events = _RecordedEvents()
    repository = _InMemoryRepository(
        SimpleNamespace(id=run_id, status="running", version=1), [node]
    )
    scheduler = _scheduler(repository, events)

    assert await scheduler.dispatch_ready_node(run_id, "mystery", "trace-1")
    # 未投递任何 Celery 任务
    assert enqueued == []
    # 节点判失败、run 判失败，而不是永久卡在 dispatched
    assert node.status == "failed"
    assert repository.run.status == "failed"
    assert repository.run_transitions == [("running", "failed")]
    # 依次记录 NODE_DISPATCHED（认领）与 NODE_FAILED（未知 executor）
    assert [event.event_type for event in events.items] == [
        A2AEventType.NODE_DISPATCHED,
        A2AEventType.NODE_FAILED,
    ]
    failed_event = events.items[-1]
    assert failed_event.summary.metrics["error_code"] == "UNKNOWN_EXECUTOR"


@pytest.mark.asyncio
async def test_scheduler_ignores_stale_success_and_completes_current_run() -> None:
    run_id = uuid4()
    node = SimpleNamespace(
        id=uuid4(),
        node_key="plot",
        status="running",
        version=2,
        attempt_count=1,
        agent_id="agent-viz",
        intent="plot",
        resources={},
        depends_on=[],
    )
    repository = _InMemoryRepository(SimpleNamespace(id=run_id, status="running", version=5), [node])
    scheduler = _scheduler(repository, _RecordedEvents())
    event = A2AEvent(
        event_type=A2AEventType.NODE_SUCCEEDED,
        trace_id="trace-1",
        run_id=run_id,
        node_key="plot",
        sender=AgentSender(kind="worker", id="agent-viz", attempt_count=1),
        recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
        status="succeeded",
        dedupe_key="plot:succeeded:2",
        state_version=2,
    )

    assert await scheduler.mark_node_succeeded(event)
    assert node.status == "succeeded"
    assert repository.run.status == "succeeded"
    assert repository.run_transitions == [("running", "succeeded")]

    assert not await scheduler.mark_node_succeeded(event)


@pytest.mark.asyncio
async def test_scheduler_retries_transient_failure_with_bounded_attempts() -> None:
    run_id = uuid4()
    node = SimpleNamespace(
        id=uuid4(),
        node_key="download",
        status="running",
        version=4,
        attempt_count=0,
        max_attempts=3,
        agent_id="agent-rnaseq",
        intent="download",
        resources={},
        depends_on=[],
    )
    events = _RecordedEvents()
    scheduler = _scheduler(
        _InMemoryRepository(SimpleNamespace(id=run_id, status="running", version=1), [node]), events
    )
    event = A2AEvent(
        event_type=A2AEventType.NODE_FAILED,
        trace_id="trace-1",
        run_id=run_id,
        node_key="download",
        sender=AgentSender(kind="worker", id="agent-rnaseq"),
        recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
        status="failed",
        summary={"metrics": {"error_code": "NETWORK_TIMEOUT"}},
        dedupe_key="download:failed:4",
        state_version=4,
    )

    assert await scheduler.handle_node_failure(event)
    assert node.status == "ready"
    assert node.attempt_count == 1
    assert [item.event_type for item in events.items] == [
        A2AEventType.NODE_RETRY_SCHEDULED,
        A2AEventType.NODE_READY,
    ]

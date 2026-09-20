"""Dependency-aware MAS scheduler with optimistic node state transitions."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.a2a_event_service import A2AEventService
from cygnusx.domain.mas.errors import classify_error
from cygnusx.domain.mas.models import (
    A2AEvent,
    A2AEventType,
    AgentRecipient,
    AgentSender,
    EventSummary,
    NodeState,
)
from cygnusx.infrastructure.database.models.mas import MASNodeModel
from cygnusx.infrastructure.database.repositories.mas_repository import MASRepository
from cygnusx.infrastructure.task_queue.dispatcher import enqueue_task


class MASSchedulerService:
    def __init__(self, session: AsyncSession) -> None:
        self._repository = MASRepository(session)
        self._events = A2AEventService(session)

    @staticmethod
    def eligible_nodes(nodes: list[MASNodeModel]) -> list[MASNodeModel]:
        """Return pending nodes whose declared upstream dependencies all succeeded."""
        statuses = {node.node_key: node.status for node in nodes}
        return [
            node
            for node in nodes
            if node.status == NodeState.PENDING.value
            and all(
                statuses.get(dependency) == NodeState.SUCCEEDED.value
                for dependency in node.depends_on
            )
        ]

    async def unlock_ready_nodes(self, run_id: UUID, trace_id: str) -> list[str]:
        """Move currently eligible nodes to READY; stale concurrent updates become no-ops."""
        run = await self._repository.get_run(run_id)
        if run is None or run.status not in {"queued", "running"}:
            return []

        ready_keys: list[str] = []
        for node in self.eligible_nodes(await self._repository.list_nodes(run_id)):
            if not await self._repository.transition_node(
                node_id=node.id,
                expected_version=node.version,
                current_status=NodeState.PENDING.value,
                target_status=NodeState.READY.value,
            ):
                continue
            next_version = node.version + 1
            await self._events.record(
                A2AEvent(
                    event_type=A2AEventType.NODE_READY,
                    trace_id=trace_id,
                    run_id=run_id,
                    node_key=node.node_key,
                    sender=AgentSender(kind="system", id="mas-scheduler"),
                    recipient=AgentRecipient(kind="worker", id=node.agent_id),
                    status="ready",
                    intent=node.intent,
                    dedupe_key=(
                        f"{run_id}:{node.node_key}:attempt_{node.attempt_count}:"
                        f"node.ready:state_version_{next_version}"
                    ),
                    state_version=next_version,
                )
            )
            ready_keys.append(node.node_key)
        return ready_keys

    async def dispatch_ready_node(self, run_id: UUID, node_key: str, trace_id: str) -> bool:
        """Claim a READY node exactly once and optionally dispatch the test-only fake executor."""
        node = await self._repository.get_node(run_id, node_key)
        if node is None or node.status != NodeState.READY.value:
            return False
        if not await self._repository.transition_node(
            node_id=node.id,
            expected_version=node.version,
            current_status=NodeState.READY.value,
            target_status=NodeState.DISPATCHED.value,
        ):
            return False

        next_version = node.version + 1
        await self._events.record(
            A2AEvent(
                event_type=A2AEventType.NODE_DISPATCHED,
                trace_id=trace_id,
                run_id=run_id,
                node_key=node.node_key,
                sender=AgentSender(kind="system", id="mas-scheduler"),
                recipient=AgentRecipient(kind="worker", id=node.agent_id),
                status="dispatched",
                intent=node.intent,
                dedupe_key=(
                    f"{run_id}:{node.node_key}:attempt_{node.attempt_count}:"
                    f"node.dispatched:state_version_{next_version}"
                ),
                state_version=next_version,
            )
        )
        executor = str(node.resources.get("executor") or "")
        if executor == "fake":
            from cygnusx.infrastructure.celery_app.tasks.mas import run_fake_node

            enqueue_task(run_fake_node, str(run_id), node.node_key)
        elif executor == "apptainer-rnaflow":
            from cygnusx.infrastructure.celery_app.tasks.mas import run_rnaflow_node

            enqueue_task(run_rnaflow_node, str(run_id), node.node_key)
        elif executor == "deg-volcano":
            from cygnusx.infrastructure.celery_app.tasks.mas import run_volcano_node

            enqueue_task(run_volcano_node, str(run_id), node.node_key)
        elif executor == "quality-gate":
            from cygnusx.infrastructure.celery_app.tasks.mas import run_quality_gate_node

            enqueue_task(run_quality_gate_node, str(run_id), node.node_key)
        elif executor == "ebi-download":
            from cygnusx.infrastructure.celery_app.tasks.mas import run_ebi_download_node

            enqueue_task(run_ebi_download_node, str(run_id), node.node_key)
        elif executor == "scanpy-qc":
            from cygnusx.infrastructure.celery_app.tasks.mas import run_scanpy_qc_node

            enqueue_task(run_scanpy_qc_node, str(run_id), node.node_key)
        else:
            # 未知/缺失 executor：绝不能把节点留在 dispatched 静默悬挂（否则 run 永不终结）。
            # 显式标 FAILED、记 NODE_FAILED 事件并让 run 失败，与 worker 侧失败语义一致。
            await self._fail_unknown_executor(run_id, node.node_key, executor, trace_id)
        return True

    async def _fail_unknown_executor(
        self,
        run_id: UUID,
        node_key: str,
        executor: str,
        trace_id: str,
    ) -> None:
        """把 executor 不在调度白名单的已 dispatched 节点显式判失败，避免永久悬挂。"""
        # 重新拉取以拿到 dispatch 后的当前版本，避免依赖调用方传入的版本号。
        node = await self._repository.get_node(run_id, node_key)
        if node is None or node.status != NodeState.DISPATCHED.value:
            return
        failed_version = node.version + 1
        if not await self._repository.transition_node(
            node_id=node.id,
            expected_version=node.version,
            current_status=NodeState.DISPATCHED.value,
            target_status=NodeState.FAILED.value,
        ):
            return
        error_code = "UNKNOWN_EXECUTOR"
        message = (
            f"节点 {node.node_key} 的 executor "
            f"{executor or '(未声明)'} 不在调度器支持列表中，已判定失败。"
        )
        await self._events.record(
            A2AEvent(
                event_type=A2AEventType.NODE_FAILED,
                trace_id=trace_id,
                run_id=run_id,
                node_key=node.node_key,
                sender=AgentSender(kind="system", id="mas-scheduler"),
                recipient=AgentRecipient(kind="orchestrator", id="mas-scheduler"),
                status="failed",
                intent=node.intent,
                summary=EventSummary(message=message, metrics={"error_code": error_code}),
                dedupe_key=(
                    f"{run_id}:{node.node_key}:attempt_{node.attempt_count}:"
                    f"node.failed:{error_code}:state_version_{failed_version}"
                ),
                state_version=failed_version,
            )
        )
        run = await self._repository.get_run(run_id)
        if run is not None and run.status == "running":
            await self._repository.transition_run(
                run_id=run.id,
                expected_version=run.version,
                current_status="running",
                target_status="failed",
            )

    async def mark_node_succeeded(self, event: A2AEvent) -> bool:
        """Accept only the current attempt's completion event, then unlock dependants."""
        if event.node_key is None:
            return False
        node = await self._repository.get_node(event.run_id, event.node_key)
        if (
            node is None
            or node.status != NodeState.RUNNING.value
            or node.version != event.state_version
        ):
            return False
        if not await self._repository.transition_node(
            node_id=node.id,
            expected_version=node.version,
            current_status=NodeState.RUNNING.value,
            target_status=NodeState.SUCCEEDED.value,
        ):
            return False
        await self.unlock_ready_nodes(event.run_id, event.trace_id)
        nodes = await self._repository.list_nodes(event.run_id)
        if all(
            node.status in {NodeState.SUCCEEDED.value, NodeState.SKIPPED.value} for node in nodes
        ):
            run = await self._repository.get_run(event.run_id)
            if run is not None and run.status == "running":
                await self._repository.transition_run(
                    run_id=run.id,
                    expected_version=run.version,
                    current_status="running",
                    target_status="succeeded",
                )
        return True

    async def handle_node_failure(self, event: A2AEvent) -> bool:
        """Pause only the failed node when policy requires user intervention."""
        if event.node_key is None:
            return False
        node = await self._repository.get_node(event.run_id, event.node_key)
        if (
            node is None
            or node.status != NodeState.RUNNING.value
            or node.version != event.state_version
        ):
            return False
        error_code = str(event.summary.metrics.get("error_code", "UNKNOWN"))
        decision = classify_error(error_code)
        retry_budget = min(node.max_attempts, decision.max_attempts)
        if decision.retryable and node.attempt_count < retry_budget:
            if not await self._repository.transition_node(
                node_id=node.id,
                expected_version=node.version,
                current_status=NodeState.RUNNING.value,
                target_status=NodeState.RETRY_WAIT.value,
            ):
                return False
            retry_wait_version = event.state_version + 1
            next_attempt = node.attempt_count + 1
            if not await self._repository.transition_node(
                node_id=node.id,
                expected_version=retry_wait_version,
                current_status=NodeState.RETRY_WAIT.value,
                target_status=NodeState.READY.value,
                attempt_count=next_attempt,
            ):
                return False
            ready_version = retry_wait_version + 1
            await self._events.record(
                A2AEvent(
                    event_type=A2AEventType.NODE_RETRY_SCHEDULED,
                    trace_id=event.trace_id,
                    run_id=event.run_id,
                    node_key=node.node_key,
                    sender=AgentSender(
                        kind="system", id="mas-scheduler", attempt_count=next_attempt
                    ),
                    recipient=AgentRecipient(kind="worker", id=node.agent_id),
                    status="retry_scheduled",
                    intent=node.intent,
                    dedupe_key=(
                        f"{event.run_id}:{node.node_key}:attempt_{next_attempt}:"
                        f"node.retry_scheduled:state_version_{ready_version}"
                    ),
                    state_version=ready_version,
                )
            )
            await self._events.record(
                A2AEvent(
                    event_type=A2AEventType.NODE_READY,
                    trace_id=event.trace_id,
                    run_id=event.run_id,
                    node_key=node.node_key,
                    sender=AgentSender(
                        kind="system", id="mas-scheduler", attempt_count=next_attempt
                    ),
                    recipient=AgentRecipient(kind="worker", id=node.agent_id),
                    status="ready",
                    intent=node.intent,
                    dedupe_key=(
                        f"{event.run_id}:{node.node_key}:attempt_{next_attempt}:"
                        f"node.ready:state_version_{ready_version}"
                    ),
                    state_version=ready_version,
                )
            )
            return True
        target_state = (
            NodeState.WAITING_APPROVAL if decision.requires_approval else NodeState.FAILED
        )
        if not await self._repository.transition_node(
            node_id=node.id,
            expected_version=node.version,
            current_status=NodeState.RUNNING.value,
            target_status=target_state.value,
        ):
            return False
        run = await self._repository.get_run(event.run_id)
        if decision.requires_approval:
            await self._repository.create_approval(
                run_id=event.run_id,
                node_id=node.id,
                kind=error_code.lower(),
                prompt=event.summary.message or f"节点 {node.node_key} 需要人工处理：{error_code}",
                options=[
                    {"value": "approve", "label": "确认继续"},
                    {"value": "reject", "label": "终止运行"},
                ],
            )
            if run is not None and run.status == "running":
                await self._repository.transition_run(
                    run_id=run.id,
                    expected_version=run.version,
                    current_status="running",
                    target_status="paused_for_input",
                )
        elif run is not None and run.status == "running":
            await self._repository.transition_run(
                run_id=run.id,
                expected_version=run.version,
                current_status="running",
                target_status="failed",
            )
        return True

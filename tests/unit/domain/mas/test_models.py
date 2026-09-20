from uuid import uuid4

import pytest
from pydantic import ValidationError

from cygnusx.domain.mas.models import (
    A2AEvent,
    A2AEventType,
    AgentRecipient,
    AgentSender,
    ExecutionPlan,
    MASDomainError,
    MASNode,
    NodeState,
    RunState,
    validate_transition,
)


def test_execution_plan_rejects_cycle() -> None:
    with pytest.raises(ValidationError, match="acyclic"):
        ExecutionPlan(
            title="cycle",
            nodes=(
                MASNode(
                    key="download",
                    agent_id="agent-download",
                    intent="download",
                    depends_on=("plot",),
                ),
                MASNode(key="plot", agent_id="agent-viz", intent="plot", depends_on=("download",)),
            ),
        )


def test_execution_plan_requires_known_dependencies() -> None:
    with pytest.raises(ValidationError, match="unknown nodes"):
        ExecutionPlan(
            title="unknown dependency",
            nodes=(
                MASNode(key="plot", agent_id="agent-viz", intent="plot", depends_on=("missing",)),
            ),
        )


def test_plan_unlocks_node_only_after_dependencies_succeed() -> None:
    download = MASNode(key="download", agent_id="agent-download", intent="download")
    plot = MASNode(key="plot", agent_id="agent-viz", intent="plot", depends_on=("download",))
    plan = ExecutionPlan(title="download then plot", nodes=(download, plot))

    assert not plan.dependencies_satisfied(plot, {"download": NodeState.FAILED})
    assert plan.dependencies_satisfied(plot, {"download": NodeState.SUCCEEDED})


def test_state_transition_requires_expected_version_and_legal_edge() -> None:
    assert validate_transition(NodeState.PENDING, NodeState.READY, 2) == 3
    with pytest.raises(MASDomainError, match="invalid transition"):
        validate_transition(NodeState.PENDING, NodeState.SUCCEEDED, 2)
    with pytest.raises(MASDomainError, match="non-negative"):
        validate_transition(RunState.DRAFT, RunState.AWAITING_APPROVAL, -1)


def test_event_rejects_unknown_fields_and_requires_node_key() -> None:
    common = {
        "trace_id": "trace-1",
        "run_id": uuid4(),
        "sender": AgentSender(kind="agent", id="agent-rnaseq", attempt_count=1),
        "recipient": AgentRecipient(kind="orchestrator", id="mas-scheduler"),
        "status": "success",
        "dedupe_key": "run:node:1:succeeded:3",
    }
    with pytest.raises(ValidationError, match="node_key"):
        A2AEvent(event_type=A2AEventType.NODE_SUCCEEDED, **common)
    with pytest.raises(ValidationError, match="Extra inputs"):
        A2AEvent(
            event_type=A2AEventType.NODE_SUCCEEDED, node_key="analysis", unexpected=True, **common
        )

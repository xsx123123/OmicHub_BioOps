"""Validated domain contracts for the multi-agent execution system."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class MASDomainError(ValueError):
    """Raised when a MAS domain invariant is violated."""


class RunState(StrEnum):
    DRAFT = "draft"
    AWAITING_APPROVAL = "awaiting_approval"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED_FOR_INPUT = "paused_for_input"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    FAILED = "failed"
    SUCCEEDED_WITH_WARNINGS = "succeeded_with_warnings"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"


class NodeState(StrEnum):
    PENDING = "pending"
    READY = "ready"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    VALIDATING = "validating"
    SUCCEEDED = "succeeded"
    RETRY_WAIT = "retry_wait"
    WAITING_EXTERNAL = "waiting_external"
    WAITING_APPROVAL = "waiting_approval"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"


class ArtifactState(StrEnum):
    REGISTERED = "registered"
    VALIDATED = "validated"
    INVALID = "invalid"
    EXPIRED = "expired"


class ArtifactKind(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"
    DATASET_MANIFEST = "dataset_manifest"
    REPORT = "report"
    LOG = "log"
    METRIC = "metric"


class ArtifactVisibility(StrEnum):
    PRIVATE = "private"
    RUN = "run"
    PROJECT = "project"
    SHARED = "shared"


class StorageClass(StrEnum):
    RUN_LOCAL = "run_local"
    SHARED_CACHE = "shared_cache"
    EXTERNAL_REFERENCE = "external_reference"


class A2AEventType(StrEnum):
    RUN_CREATED = "run.created"
    PLAN_APPROVED = "plan.approved"
    NODE_READY = "node.ready"
    NODE_DISPATCHED = "node.dispatched"
    NODE_STARTED = "node.started"
    NODE_PROGRESSED = "node.progressed"
    ARTIFACT_REGISTERED = "artifact.registered"
    ARTIFACT_VALIDATED = "artifact.validated"
    NODE_SUCCEEDED = "node.succeeded"
    NODE_FAILED = "node.failed"
    NODE_RETRY_SCHEDULED = "node.retry_scheduled"
    NODE_INPUT_REQUIRED = "node.input_required"
    NODE_REWORK_REQUESTED = "node.rework_requested"
    RUN_COMPLETED = "run.completed"
    RUN_FAILED = "run.failed"


class StrictMASModel(BaseModel):
    """Base model that rejects accidental protocol extensions."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MASNode(StrictMASModel):
    key: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
    agent_id: Annotated[str, Field(min_length=1, max_length=128)]
    intent: Annotated[str, Field(min_length=1, max_length=256)]
    depends_on: tuple[str, ...] = ()
    input_contract: dict[str, Any] = Field(default_factory=dict)
    output_contract: dict[str, Any] = Field(default_factory=dict)
    parameters: dict[str, Any] = Field(default_factory=dict)
    resources: dict[str, Any] = Field(default_factory=dict)
    max_attempts: Annotated[int, Field(ge=1, le=10)] = 3
    allow_skipped_dependencies: bool = False

    @field_validator("depends_on")
    @classmethod
    def validate_dependencies_are_unique(cls, dependencies: tuple[str, ...]) -> tuple[str, ...]:
        if len(dependencies) != len(set(dependencies)):
            raise ValueError("depends_on entries must be unique")
        return dependencies


class ExecutionPlan(StrictMASModel):
    schema_version: str = "1.0"
    title: Annotated[str, Field(min_length=1, max_length=200)]
    nodes: tuple[MASNode, ...]

    @model_validator(mode="after")
    def validate_dag(self) -> ExecutionPlan:
        keys = {node.key for node in self.nodes}
        if len(keys) != len(self.nodes):
            raise ValueError("plan node keys must be unique")

        for node in self.nodes:
            unknown_dependencies = set(node.depends_on) - keys
            if unknown_dependencies:
                raise ValueError(
                    f"node {node.key!r} depends on unknown nodes: {sorted(unknown_dependencies)}"
                )
            if node.key in node.depends_on:
                raise ValueError(f"node {node.key!r} cannot depend on itself")

        unresolved = {node.key: set(node.depends_on) for node in self.nodes}
        while unresolved:
            ready = {key for key, dependencies in unresolved.items() if not dependencies}
            if not ready:
                raise ValueError("execution plan must be acyclic")
            unresolved = {
                key: dependencies - ready
                for key, dependencies in unresolved.items()
                if key not in ready
            }
        return self

    def initial_ready_nodes(self) -> tuple[MASNode, ...]:
        return tuple(node for node in self.nodes if not node.depends_on)

    def dependencies_satisfied(self, node: MASNode, states: dict[str, NodeState]) -> bool:
        accepted = {NodeState.SUCCEEDED}
        if node.allow_skipped_dependencies:
            accepted.add(NodeState.SKIPPED)
        return all(states.get(dependency) in accepted for dependency in node.depends_on)


RUN_TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.DRAFT: frozenset({RunState.AWAITING_APPROVAL}),
    RunState.AWAITING_APPROVAL: frozenset({RunState.QUEUED, RunState.REJECTED}),
    RunState.QUEUED: frozenset({RunState.RUNNING, RunState.CANCELLING}),
    RunState.RUNNING: frozenset(
        {
            RunState.PAUSED_FOR_INPUT,
            RunState.CANCELLING,
            RunState.FAILED,
            RunState.SUCCEEDED_WITH_WARNINGS,
            RunState.SUCCEEDED,
        }
    ),
    RunState.PAUSED_FOR_INPUT: frozenset({RunState.QUEUED, RunState.CANCELLING}),
    RunState.CANCELLING: frozenset({RunState.CANCELLED}),
    RunState.CANCELLED: frozenset(),
    RunState.FAILED: frozenset(),
    RunState.SUCCEEDED_WITH_WARNINGS: frozenset(),
    RunState.SUCCEEDED: frozenset(),
    RunState.REJECTED: frozenset(),
}

NODE_TRANSITIONS: dict[NodeState, frozenset[NodeState]] = {
    NodeState.PENDING: frozenset({NodeState.READY, NodeState.SKIPPED, NodeState.CANCELLED}),
    NodeState.READY: frozenset({NodeState.DISPATCHED, NodeState.SKIPPED, NodeState.CANCELLED}),
    NodeState.DISPATCHED: frozenset(
        {NodeState.RUNNING, NodeState.WAITING_APPROVAL, NodeState.SKIPPED, NodeState.CANCELLED}
    ),
    NodeState.RUNNING: frozenset(
        {
            NodeState.VALIDATING,
            NodeState.RETRY_WAIT,
            NodeState.WAITING_EXTERNAL,
            NodeState.WAITING_APPROVAL,
            NodeState.FAILED,
            NodeState.CANCELLED,
        }
    ),
    NodeState.VALIDATING: frozenset(
        {NodeState.SUCCEEDED, NodeState.RETRY_WAIT, NodeState.FAILED, NodeState.CANCELLED}
    ),
    NodeState.RETRY_WAIT: frozenset({NodeState.READY, NodeState.FAILED, NodeState.CANCELLED}),
    NodeState.WAITING_EXTERNAL: frozenset(
        {NodeState.RUNNING, NodeState.RETRY_WAIT, NodeState.FAILED, NodeState.CANCELLED}
    ),
    NodeState.WAITING_APPROVAL: frozenset({NodeState.READY, NodeState.FAILED, NodeState.CANCELLED}),
    NodeState.SUCCEEDED: frozenset(),
    NodeState.FAILED: frozenset(),
    NodeState.CANCELLED: frozenset(),
    NodeState.SKIPPED: frozenset(),
}


def validate_transition(
    current: RunState | NodeState, target: RunState | NodeState, expected_version: int
) -> int:
    """Validate an optimistic-lock state transition and return its next version."""
    if expected_version < 0:
        raise MASDomainError("expected_version must be non-negative")
    if type(current) is not type(target):
        raise MASDomainError("state transitions cannot cross run and node state machines")
    transitions = RUN_TRANSITIONS if isinstance(current, RunState) else NODE_TRANSITIONS
    if target not in transitions[current]:
        raise MASDomainError(f"invalid transition: {current} -> {target}")
    return expected_version + 1


class ArtifactPointer(StrictMASModel):
    artifact_id: UUID
    container_path: Annotated[str, Field(pattern=r"^/workspace(?:/[^/][^/]*)*$")]
    media_type: Annotated[str, Field(min_length=1, max_length=255)] = "application/octet-stream"
    schema_version: Annotated[str, Field(min_length=1, max_length=32)] = "1.0"

    @field_validator("container_path")
    @classmethod
    def ensure_container_path_is_safe(cls, value: str) -> str:
        if "/../" in f"{value}/" or value.endswith("/.."):
            raise ValueError("container_path cannot escape /workspace")
        return value


class MASArtifact(StrictMASModel):
    id: UUID = Field(default_factory=uuid4)
    run_id: UUID
    node_key: str | None = None
    logical_name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,127}$")]
    kind: ArtifactKind
    workspace_path: str
    media_type: Annotated[str, Field(min_length=1, max_length=255)]
    size_bytes: Annotated[int, Field(ge=0)]
    sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    schema_version: str = "1.0"
    summary: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    visibility: ArtifactVisibility = ArtifactVisibility.RUN
    state: ArtifactState = ArtifactState.REGISTERED
    storage_class: StorageClass = StorageClass.RUN_LOCAL
    version: Annotated[int, Field(ge=1)] = 1
    reference_count: Annotated[int, Field(ge=0)] = 0
    lease_expires_at: datetime | None = None


class AgentSender(StrictMASModel):
    kind: Annotated[str, Field(pattern=r"^(agent|worker|system)$")]
    id: Annotated[str, Field(min_length=1, max_length=128)]
    attempt_count: Annotated[int, Field(ge=0, le=100)] = 0


class AgentRecipient(StrictMASModel):
    kind: Annotated[str, Field(pattern=r"^(agent|worker|orchestrator|system)$")]
    id: Annotated[str, Field(min_length=1, max_length=128)]


class EventSummary(StrictMASModel):
    message: Annotated[str, Field(max_length=1000)] = ""
    metrics: dict[str, int | float | str | bool] = Field(default_factory=dict)


NODE_EVENT_TYPES = {
    A2AEventType.NODE_READY,
    A2AEventType.NODE_DISPATCHED,
    A2AEventType.NODE_STARTED,
    A2AEventType.NODE_PROGRESSED,
    A2AEventType.ARTIFACT_REGISTERED,
    A2AEventType.ARTIFACT_VALIDATED,
    A2AEventType.NODE_SUCCEEDED,
    A2AEventType.NODE_FAILED,
    A2AEventType.NODE_RETRY_SCHEDULED,
    A2AEventType.NODE_INPUT_REQUIRED,
    A2AEventType.NODE_REWORK_REQUESTED,
}


class A2AEvent(StrictMASModel):
    schema_version: str = "1.0"
    event_id: UUID = Field(default_factory=uuid4)
    event_type: A2AEventType
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    trace_id: Annotated[str, Field(min_length=1, max_length=128)]
    run_id: UUID
    node_key: str | None = None
    sender: AgentSender
    recipient: AgentRecipient
    status: Annotated[str, Field(min_length=1, max_length=64)]
    intent: Annotated[str, Field(max_length=256)] = ""
    context_pointers: dict[str, ArtifactPointer] = Field(default_factory=dict)
    summary: EventSummary = Field(default_factory=EventSummary)
    dedupe_key: Annotated[str, Field(min_length=1, max_length=512)]
    causation_event_id: UUID | None = None
    state_version: Annotated[int, Field(ge=0)] = 0

    @model_validator(mode="after")
    def validate_node_event_contract(self) -> A2AEvent:
        if self.event_type in NODE_EVENT_TYPES and not self.node_key:
            raise ValueError("node events must include node_key")
        if self.node_key is None and self.sender.attempt_count != 0:
            raise ValueError("run-level events must use attempt_count=0")
        if len(self.model_dump_json()) > 64 * 1024:
            raise ValueError("A2A event payload exceeds 64 KiB")
        return self

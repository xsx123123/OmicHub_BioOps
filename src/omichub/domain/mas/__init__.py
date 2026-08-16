"""Multi-agent system domain contracts."""

from omichub.domain.mas.errors import ErrorCategory, RetryDecision, classify_error
from omichub.domain.mas.models import (
    A2AEvent,
    AgentRecipient,
    AgentSender,
    ArtifactPointer,
    ArtifactState,
    ExecutionPlan,
    MASArtifact,
    MASNode,
    NodeState,
    RunState,
)
from omichub.domain.mas.tool_policy import ExecutionPolicy, ToolPreflightRequest
from omichub.domain.mas.workspace import WorkspaceLayout

__all__ = [
    "A2AEvent",
    "AgentRecipient",
    "AgentSender",
    "ArtifactPointer",
    "ArtifactState",
    "ExecutionPlan",
    "ErrorCategory",
    "ExecutionPolicy",
    "MASArtifact",
    "MASNode",
    "NodeState",
    "RunState",
    "RetryDecision",
    "ToolPreflightRequest",
    "WorkspaceLayout",
    "classify_error",
]
from .quality_gate import (
    QCOverrideRequest as QCOverrideRequest,
    QualityGateResult as QualityGateResult,
    QualityGateStatus as QualityGateStatus,
    apply_qc_override as apply_qc_override,
    evaluate_mapping_rate as evaluate_mapping_rate,
)

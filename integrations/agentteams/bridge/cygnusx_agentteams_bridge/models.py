"""Stable Bridge contracts shared by AgentTeams skills and HTTP callers."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

BridgeRole = str
ApprovalAction = Literal["submit_task", "execute_plan", "cancel_task"]
CaseStatus = Literal[
    "queued",
    "received",
    "planning_running",
    "preflight_running",
    "preflight_blocked",
    "waiting_for_correction",
    "planning_failed",
    "approval_pending",
    "approved",
    "executing",
    "execution_failed",
    "quality_running",
    "quality_blocked",
    "remediation_pending",
    "delivery_ready",
    "closed",
    "cancelled",
]
WorkItemStatus = Literal[
    "pending",
    "claimed",
    "running",
    "awaiting_approval",
    "in_progress",  # legacy alias retained for existing clients
    "completed",
    "blocked",
    "failed",
    "skipped",  # cascade-skipped after an unrecoverable upstream failure
    "timeout",  # terminal: lease expired with the retry budget exhausted
    "cancelled",
]


class ContextRef(BaseModel):
    kind: Literal["project", "workspace", "file", "flow", "task", "report", "s3"]
    id: str = Field(min_length=1, max_length=256)
    location: str | None = Field(default=None, max_length=512)
    meta: dict[str, Any] = Field(default_factory=dict)


class PreflightRequest(BaseModel):
    case_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    work_item_id: str | None = Field(default=None, max_length=128)
    flow_id: str = Field(min_length=1, max_length=128)
    sample_sheet: list[dict[str, Any]] = Field(default_factory=list, max_length=10_000)
    comparisons: list[dict[str, Any]] | None = Field(default=None, max_length=1_000)
    context_refs: list[ContextRef] = Field(default_factory=list, max_length=100)
    consultation_summary: str | None = Field(default=None, max_length=1_800)


class Finding(BaseModel):
    code: str
    severity: Literal["error", "warning", "info"]
    message: str
    evidence_refs: list[ContextRef] = Field(default_factory=list)


class PreflightResponse(BaseModel):
    case_id: str
    status: Literal["passed", "blocked"]
    findings: list[Finding]
    next_actions: list[str]


class PreflightInputSnapshot(BaseModel):
    """Bridge-owned input snapshot that must match the subsequent approved submission."""

    flow_id: str
    sample_sheet: list[dict[str, Any]]
    comparisons: list[dict[str, Any]] | None = None
    context_refs: list[ContextRef] = Field(default_factory=list)
    consultation_summary: str | None = None


class TaskSpec(BaseModel):
    flow_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    sample_sheet: list[dict[str, Any]] = Field(default_factory=list, max_length=10_000)
    comparisons: list[dict[str, Any]] | None = Field(default=None, max_length=1_000)
    execution_mode: Literal["local", "cluster"] = "local"
    quality_gate_required: bool = False


class SubmitTaskRequest(BaseModel):
    case_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    work_item_id: str | None = Field(default=None, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=256)
    approval_token: str = Field(min_length=20, max_length=4096)
    task: TaskSpec


class ApprovedSubmission(BaseModel):
    """Bridge-owned, token-free authorization envelope consumed by ``analysis-worker``."""

    approval_id: str = Field(min_length=1, max_length=128)
    expires_at: datetime
    idempotency_key: str = Field(min_length=8, max_length=256)
    task: TaskSpec
    input_snapshot_hash: str = Field(min_length=32, max_length=128)
    prepared_at: datetime
    submission_started_at: datetime | None = None
    consumed_at: datetime | None = None


class QueueApprovedSubmissionRequest(BaseModel):
    """Approve a fixed task snapshot for later execution by the analysis Worker."""

    case_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    work_item_id: str = Field(min_length=1, max_length=128)
    idempotency_key: str = Field(min_length=8, max_length=256)
    approval_token: str = Field(min_length=20, max_length=4096)
    task: TaskSpec


class QueueApprovedSubmissionResponse(BaseModel):
    case_id: str
    work_item_id: str
    approval_id: str
    status: Literal["queued", "idempotent_replay"]
    expires_at: datetime


class TaskReceipt(BaseModel):
    case_id: str
    omic_task_id: str
    status: str
    idempotent_replay: bool = False
    submitted_at: datetime


class ApprovalRequest(BaseModel):
    case_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    action: ApprovalAction
    work_item_id: str | None = Field(default=None, max_length=128)
    flow_id: str | None = Field(default=None, max_length=128)
    task_id: str | None = Field(default=None, max_length=128)
    ttl_seconds: int = Field(default=300, ge=30, le=3_600)


class ApprovalResponse(BaseModel):
    approval_id: str
    token: str
    expires_at: datetime


class ExecuteGeneralPlanRequest(BaseModel):
    case_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    approval_token: str = Field(min_length=20, max_length=4096)


class RetryCaseSubmissionRequest(BaseModel):
    approval_token: str = Field(min_length=20, max_length=4096)


class PlanRevisionRequest(BaseModel):
    expected_plan_hash: str = Field(min_length=64, max_length=64)
    parameters: dict[str, Any]
    reason: str = Field(min_length=3, max_length=512)
    override_revision_limit: bool = False


class PlanRevisionResponse(BaseModel):
    case_id: str
    previous_plan_hash: str
    plan_hash: str
    previous_plan_version: int
    plan_version: int
    revision_count: int
    changed_parameter_keys: list[str]
    replay_work_item_ids: list[str]
    status: CaseStatus


class CaseCancelRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=512)


class CancelTaskRequest(BaseModel):
    case_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    approval_token: str = Field(min_length=20, max_length=4096)
    reason: str = Field(min_length=3, max_length=512)


class EvidenceRequest(BaseModel):
    work_item_id: str = Field(min_length=1, max_length=128)
    event_type: str = Field(min_length=3, max_length=128, pattern=r"^[a-z0-9_.-]+$")
    summary: str = Field(min_length=1, max_length=4_000)
    context_refs: list[ContextRef] = Field(default_factory=list, max_length=100)
    omic_task_id: str | None = Field(default=None, max_length=128)
    skill_name: str | None = Field(default=None, max_length=128)
    payload: dict[str, Any] = Field(default_factory=dict)


# 预留的 Case 级证据 work_item_id：bioops-manager 可用它记录不挂在任何
# 工作项上的 Case 级事件（如房间绑定 room.created、用户发言 room.user_message），
# record_evidence 不再要求存在同名 work item。
CASE_LEVEL_WORK_ITEM_ID = "case"

# 房间级事件流的内部命名空间（会话-工单解耦，Part 2 方案 b）：每个协作室房间
# 对应一条 case_id 形如 ``room-<room_id>`` 的 room_namespace 记录，复用现有
# Case 事件流/MinIO 恢复/SSE/房间镜像链路，但不作为用户 Case 暴露。
ROOM_NAMESPACE_ID_PREFIX = "room-"


def is_room_namespace_case_id(case_id: str) -> bool:
    return case_id.startswith(ROOM_NAMESPACE_ID_PREFIX)


class EvidenceResponse(BaseModel):
    event_id: str
    recorded_at: datetime


class CaseEventResponse(BaseModel):
    case_id: str
    events: list[dict[str, Any]]
    next_cursor: str | None = None


class CaseCreateRequest(BaseModel):
    case_id: str = Field(min_length=3, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    project_ref: ContextRef | None = None
    context_refs: list[ContextRef] = Field(default_factory=list, max_length=100)
    intent: str = Field(min_length=1, max_length=256)
    requester_ref: str = Field(min_length=1, max_length=256)
    team_id: str = Field(default="bioops-delivery", min_length=1, max_length=128)
    origin_consultation_id: str | None = Field(default=None, max_length=256)
    consultation_summary: str | None = Field(default=None, max_length=1_800)
    execution_mode: Literal["local", "cluster_case"] = "cluster_case"
    flow_id: str | None = Field(default=None, min_length=1, max_length=128)
    lead_planner: BridgeRole | None = None
    # 会话-工单解耦（Part 2）：room_namespace 记录是房间级事件流的内部载体，
    # 不进用户 Case 列表/配额/GC；source_case_id 记录"基于上一 Case 继续"的关联引用。
    record_kind: Literal["case", "room_namespace"] = "case"
    source_case_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def _validate_execution_context(self) -> CaseCreateRequest:
        if self.record_kind == "room_namespace":
            if not is_room_namespace_case_id(self.case_id):
                raise ValueError("room_namespace records require a room-<room_id> case_id")
            if self.flow_id or self.lead_planner or self.source_case_id:
                raise ValueError("room_namespace records cannot carry flow/planner/source fields")
            return self
        if self.project_ref is not None and self.project_ref.kind != "project":
            raise ValueError("project_ref must be a project context")
        if self.flow_id and not (self.context_refs or self.project_ref):
            raise ValueError("flow Cases require project_ref or context_refs")
        if not self.flow_id and not (self.context_refs or self.project_ref):
            raise ValueError("general Cases require at least one context_ref")
        return self

class CaseRecord(BaseModel):
    case_id: str
    project_ref: ContextRef | None = None
    context_refs: list[ContextRef] = Field(default_factory=list, max_length=100)
    intent: str
    requester_ref: str
    team_id: str
    origin_consultation_id: str | None = None
    consultation_summary: str | None = None
    execution_mode: Literal["local", "cluster_case"] = "cluster_case"
    flow_id: str | None = None
    lead_planner: BridgeRole | None = None
    record_kind: Literal["case", "room_namespace"] = "case"
    source_case_id: str | None = None
    status: CaseStatus = "received"
    proposed_submission: dict[str, Any] | None = None
    plan_hash: str | None = None
    plan_version: int = Field(default=0, ge=0)
    plan_revision_count: int = Field(default=0, ge=0)
    planning_retry_count: int = Field(default=0, ge=0)
    correction_round_count: int = Field(default=0, ge=0)
    max_correction_rounds: int = Field(default=2, ge=1)
    node_started_at: datetime | None = None
    omic_task_ids: list[str] = Field(default_factory=list)
    task_specs: list[dict[str, Any]] = Field(default_factory=list)
    preflight_input: PreflightInputSnapshot | None = None
    work_items: list[WorkItemRecord] = Field(default_factory=list)
    mas_run_ids: list[str] = Field(default_factory=list)
    quality_decision: str | None = None
    manifest_uri: str | None = None
    created_at: datetime
    updated_at: datetime


class WorkItemRecord(BaseModel):
    work_item_id: str = Field(min_length=1, max_length=128)
    parent_work_item_id: str | None = Field(default=None, max_length=128)
    target: BridgeRole
    objective: str = Field(min_length=1, max_length=1_000)
    skill_name: str = Field(min_length=1, max_length=128)
    context_refs: list[ContextRef] = Field(default_factory=list, max_length=100)
    declared_inputs: list[ContextRef] = Field(default_factory=list, max_length=100)
    declared_outputs: list[ContextRef] = Field(default_factory=list, max_length=100)
    read_only: bool = True
    execution_mode: Literal["readonly_consultation", "workspace_execution"] = (
        "readonly_consultation"
    )
    plan_hash: str | None = Field(default=None, min_length=64, max_length=64)
    plan_version: int = Field(default=0, ge=0)
    approval_required: bool = False
    deadline_seconds: int = Field(default=300, ge=1, le=86_400)
    status: WorkItemStatus = "pending"
    attempt: int = Field(default=0, ge=0, le=100)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff_seconds: int | None = Field(default=None, ge=1, le=86_400)
    lease_owner: str | None = Field(default=None, max_length=128)
    lease_expires_at: datetime | None = None
    retry_not_before: datetime | None = None
    cancelled_at: datetime | None = None
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=256)
    trace_id: str | None = Field(default=None, max_length=128)
    approved_submission: ApprovedSubmission | None = None
    depends_on: list[str] = Field(default_factory=list, max_length=32)
    output_refs: list[ContextRef] = Field(default_factory=list, max_length=100)
    summary: str | None = Field(default=None, max_length=4_000)
    findings: list[Finding] = Field(default_factory=list, max_length=100)
    updated_at: datetime


class WorkItemCreateRequest(BaseModel):
    work_item_id: str = Field(min_length=1, max_length=128)
    parent_work_item_id: str | None = Field(default=None, max_length=128)
    target: BridgeRole
    objective: str = Field(min_length=1, max_length=1_000)
    skill_name: str = Field(min_length=1, max_length=128)
    context_refs: list[ContextRef] = Field(default_factory=list, max_length=100)
    declared_inputs: list[ContextRef] = Field(default_factory=list, max_length=100)
    declared_outputs: list[ContextRef] = Field(default_factory=list, max_length=100)
    read_only: bool = True
    execution_mode: Literal["readonly_consultation", "workspace_execution"] = (
        "readonly_consultation"
    )
    approval_required: bool = False
    deadline_seconds: int = Field(default=300, ge=1, le=86_400)
    max_attempts: int = Field(default=3, ge=1, le=10)
    retry_backoff_seconds: int | None = Field(default=None, ge=1, le=86_400)
    idempotency_key: str | None = Field(default=None, min_length=8, max_length=256)
    depends_on: list[str] = Field(default_factory=list, max_length=32)


class WorkItemUpdateRequest(BaseModel):
    status: WorkItemStatus
    summary: str = Field(default="", max_length=4_000)
    findings: list[Finding] = Field(default_factory=list, max_length=100)
    output_refs: list[ContextRef] = Field(default_factory=list, max_length=100)
    trace_id: str | None = Field(default=None, max_length=128)


class WorkItemHeartbeatRequest(BaseModel):
    trace_id: str | None = Field(default=None, max_length=128)
    summary: str = Field(default="", max_length=1_000)
    worker_id: str | None = Field(default=None, max_length=256)


class ArtifactSourceRef(BaseModel):
    """产物血缘（F1）：Worker 上报产物时携带的上游产物引用。"""

    artifact_id: str = Field(min_length=1, max_length=512)
    relation: Literal["input_to", "derived_from"] = "input_to"
    note: str = Field(default="", max_length=500)


class ReadOnlyExecutionRequest(BaseModel):
    """Worker request for a Bridge-mediated, Gateway-restricted consultation."""

    agent_id: str = Field(min_length=1, max_length=128)
    capability: Literal[
        "interpretation",
        "planning_advice",
        "result_interpretation",
        "qc_advice",
        "project-preflight",
        "quality-gate",
        "delivery-pack",
        "workspace_execution",
    ]
    question: str = Field(min_length=1, max_length=8_000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=50)
    requested_tools: list[str] = Field(default_factory=list, max_length=20)
    trace_id: str | None = Field(default=None, max_length=128)
    execution_mode: Literal["readonly_consultation", "workspace_execution"] = (
        "readonly_consultation"
    )
    # 产物血缘（F1）：workspace_execution 的上游产物引用与执行摘要，
    # 原样透传给平台产物登记路径；None 表示 Worker 未声明。
    source_refs: list[ArtifactSourceRef] | None = Field(default=None, max_length=100)
    execution_summary: str | None = Field(default=None, max_length=2_000)


class ReadOnlyExecutionResult(BaseModel):
    """Fixed Gateway response accepted by the production read-only Worker path."""

    schema_version: str = Field(min_length=1, max_length=32)
    status: Literal["completed", "manual_review", "rejected"]
    conclusion: str = Field(min_length=1, max_length=8_000)
    recommendations: list[str] = Field(default_factory=list, max_length=100)
    evidence_refs: list[str] = Field(default_factory=list, max_length=100)
    risks: list[str] = Field(default_factory=list, max_length=100)
    agent_id: str = Field(min_length=1, max_length=128)
    schema_ver: str = Field(min_length=1, max_length=32)
    duration_ms: int = Field(ge=0)
    token_usage: int = Field(ge=0)
    proposed_submission: dict[str, Any] | None = None
    artifacts: list[dict[str, Any]] = Field(default_factory=list, max_length=100)
    hard_gate: dict[str, Any] | None = None


class WorkerInboxItem(BaseModel):
    """Minimal assignment envelope returned to a single Worker identity."""

    case_id: str
    project_ref: ContextRef | None = None
    context_refs: list[ContextRef] = Field(default_factory=list, max_length=100)
    intent: str
    status: CaseStatus
    omic_task_ids: list[str] = Field(default_factory=list)
    quality_decision: str | None = None
    work_item: WorkItemRecord


class WorkerInboxResponse(BaseModel):
    items: list[WorkerInboxItem]
    total: int


class CaseListResponse(BaseModel):
    items: list[CaseRecord]
    total: int
    next_cursor: str | None = None


class CaseStateUpdate(BaseModel):
    status: CaseStatus
    reason: str = Field(min_length=1, max_length=1_000)
    work_item_id: str | None = Field(default=None, max_length=128)


class QualityGateRequest(BaseModel):
    case_id: str
    work_item_id: str | None = Field(default=None, max_length=128)
    rule_version: str = Field(min_length=1, max_length=128)
    decision: Literal["passed", "warning", "blocked", "manual_review"]
    summary: str = Field(min_length=1, max_length=4_000)
    evidence_refs: list[ContextRef] = Field(default_factory=list, max_length=100)
    artifact_hashes: dict[str, str] = Field(default_factory=dict, max_length=100)
    # 产物血缘（F1）硬约束：上报了 artifact_hashes 就必须携带 source_refs，
    # 缺失由 Bridge 拒绝登记并回写 room.artifact_rejected 审计事件。
    source_refs: list[ArtifactSourceRef] = Field(default_factory=list, max_length=100)
    execution_summary: str = Field(default="", max_length=2_000)
    remediation_request: RemediationRequest | None = None


class RemediationRequest(BaseModel):
    target: Literal["data-steward", "workflow-operator"]
    objective: str = Field(min_length=3, max_length=1_000)
    recommended_changes: list[str] = Field(default_factory=list, max_length=50)


class QualityGateResponse(BaseModel):
    case_id: str
    task_id: str
    decision: Literal["passed", "warning", "blocked", "manual_review"]
    rule_version: str
    summary: str
    evidence_refs: list[ContextRef]
    artifact_hashes: dict[str, str]
    source_refs: list[ArtifactSourceRef]
    execution_summary: str
    recorded_at: datetime


class CaseCloseRequest(BaseModel):
    case_id: str
    quality_decision: Literal["passed", "warning", "manual_review"]
    runbook_ref: ContextRef | None = None
    remediation_summary: str | None = Field(default=None, max_length=2_000)


class CaseCloseResponse(BaseModel):
    case_id: str
    status: Literal["closed"]
    manifest_uri: str
    manifest: dict[str, Any]


class WorkerTokenIssueRequest(BaseModel):
    """Manager-issued, revocable per-Worker token request (M6 credential convergence)."""

    identity: str = Field(min_length=1, max_length=128)
    ttl_seconds: int | None = Field(default=None, ge=60, le=31_536_000)
    note: str = Field(default="", max_length=256)


class WorkerTokenRecord(BaseModel):
    """Stored Worker token metadata; only the SHA-256 hash of the raw token persists."""

    token_id: str
    token_hash: str
    identity: str
    note: str = ""
    created_at: datetime
    expires_at: datetime | None = None
    revoked_at: datetime | None = None

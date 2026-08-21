"""Business guardrails for Bridge operations; no direct database or task-service access."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

from .audit import AuditStore
from .case_store import CaseStore
from .client import GatewayClient, OmicHubClient
from .config import BridgeSettings
from .models import (
    CASE_LEVEL_WORK_ITEM_ID,
    ApprovalRequest,
    ApprovalResponse,
    ApprovedSubmission,
    CancelTaskRequest,
    CaseCancelRequest,
    CaseCloseRequest,
    CaseCloseResponse,
    CaseCreateRequest,
    CaseEventResponse,
    CaseListResponse,
    CaseRecord,
    CaseStateUpdate,
    ContextRef,
    EvidenceRequest,
    EvidenceResponse,
    Finding,
    PlanRevisionRequest,
    PlanRevisionResponse,
    PreflightInputSnapshot,
    PreflightRequest,
    PreflightResponse,
    QualityGateRequest,
    QualityGateResponse,
    QueueApprovedSubmissionRequest,
    QueueApprovedSubmissionResponse,
    ReadOnlyExecutionRequest,
    ReadOnlyExecutionResult,
    RetryCaseSubmissionRequest,
    SubmitTaskRequest,
    TaskReceipt,
    TaskSpec,
    WorkerInboxItem,
    WorkerInboxResponse,
    WorkItemCreateRequest,
    WorkItemHeartbeatRequest,
    WorkItemRecord,
    WorkItemStatus,
    WorkItemUpdateRequest,
)
from .security import ApprovalSigner

# O5 迁移期:标准工作项 target 未在 flow YAML/_shared 声明时走硬编码缺省,每类只警告一次。
_standard_target_fallback_warned: set[str] = set()

# B2 审计伪造面修复（手册阶段 0 修复 2）：/v1/cases/{id}/evidence 写入身份分级。
# 平台身份（主后端固定以 bioops-manager 写房间/Case 事件）可写业务事件；
# 其余身份一律按 Worker 处理：target 绑定 + 有效租约 + 因果锚点 + 命名空间限制。
_PLATFORM_EVIDENCE_IDENTITIES = frozenset({"bioops-manager", "workflow-operator"})
# Worker 身份禁止写入的平台保留命名空间（伪造审批/立项卡/任务提交事件的防线）。
_PLATFORM_RESERVED_EVENT_PREFIXES = (
    "approval.",
    "case.",
    "room.",
    "planning.",
    "general_plan.",
    "omic_task.",
    "work_item.",
    "matrix.",
    "consultation.",
)


def _is_platform_reserved_event_type(event_type: str) -> bool:
    return event_type.startswith(_PLATFORM_RESERVED_EVENT_PREFIXES)


# B1 confirm_token 脱敏（复审清单 B1 闭环）：room.proposal_confirm 立项确认卡
# 在事件流出口（分页/SSE）一律置 confirm_token=None，不再区分 pending/已消费；
# 存活 token 只存主后端房间行 DB 字段，confirm-proposal 端点凭 owner + pending
# 状态原子消费（token 退化为可选的二次校验 nonce，不经事件流分发）。
ROOM_PROPOSAL_CONFIRM_EVENT_TYPE = "room.proposal_confirm"


def _with_confirm_token_redacted(event: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the event with confirm_token nulled at both payload layers."""
    redacted = dict(event)
    payload = dict(event.get("payload")) if isinstance(event.get("payload"), dict) else {}
    if isinstance(payload.get("payload"), dict):
        inner = dict(payload["payload"])
        if "confirm_token" in inner:
            inner["confirm_token"] = None
        payload["payload"] = inner
    if "confirm_token" in payload:
        payload["confirm_token"] = None
    redacted["payload"] = payload
    return redacted


def redact_proposal_confirm_tokens(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Null confirm_token on every room.proposal_confirm card at read exits."""
    return [
        _with_confirm_token_redacted(event)
        if event.get("event_type") == ROOM_PROPOSAL_CONFIRM_EVENT_TYPE
        else event
        for event in events
    ]


class BridgeService:
    _RETRY_BACKOFF_SECONDS = (30, 120, 480)
    _ACTIVE_CASE_STATUSES = {
        "received",
        "planning_running",
        "preflight_running",
        "preflight_blocked",
        "waiting_for_correction",
        "approval_pending",
        "approved",
        "executing",
        "execution_failed",
        "quality_running",
        "quality_blocked",
        "remediation_pending",
        "delivery_ready",
    }
    _ACTIVE_WORK_ITEM_STATUSES = {
        "pending",
        "claimed",
        "running",
        "awaiting_approval",
        "in_progress",
    }
    _SETTLED_WORK_ITEM_STATUSES = {"completed", "blocked", "cancelled", "skipped", "timeout"}
    _TERMINAL_OMIC_TASK_STATUSES = {"success", "failed", "error", "cancelled", "canceled"}
    _GC_CASE_STATUSES = {"cancelled", "execution_failed", "closed"}

    def __init__(
        self,
        settings: BridgeSettings,
        client: OmicHubClient,
        audit: AuditStore,
        cases: CaseStore,
        gateway: GatewayClient | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._audit = audit
        self._cases = cases
        self._gateway = gateway
        self._approval_signer = ApprovalSigner(settings.approval_signing_secret)
        # 每次 inbox 轮询只更新内存中的最新心跳时间，不再写审计事件：
        # 心跳量级（每 Worker 数秒一条）曾把审计 JSONL 灌到 690 万条/1.4GB，
        # 导致删除 Case 全量重写审计文件耗时数十秒、启动加载数分钟。
        self._worker_last_poll: dict[str, datetime] = {}

    async def refresh_capabilities(self) -> dict[str, Any]:
        snapshot = await self._client.get_agentteams_capabilities()
        self._settings.apply_capability_snapshot(snapshot)
        return snapshot

    async def capabilities(self, *, reload: bool = False) -> dict[str, Any]:
        if reload or not self._settings.role_agent_mapping():
            return await self.refresh_capabilities()
        return {
            "allowed_flow_ids": sorted(self._settings.allowed_flows()),
            "flow_agent_map": self._settings.discovered_flow_agent_map,
            "flow_quality_gate_map": self._settings.discovered_flow_quality_gate_map,
            "role_agent_map": self._settings.role_agent_mapping(),
            "worker_profiles": self._settings.discovered_worker_profiles,
        }

    def _external_workers(self) -> set[str]:
        return {*self._settings.role_agent_mapping(), "analysis-worker"}

    def worker_identities(self) -> set[str]:
        return {
            *self._settings.role_agent_mapping(),
            "data-steward",
            "workflow-operator",
            "quality-auditor",
            "delivery-reporter",
        }

    def _workspace_execution_targets(self) -> set[str]:
        """Identities allowed to run workspace_execution, per the capability snapshot.

        Falls back to the original code/viz pair when no snapshot has been applied yet.
        """
        discovered = self._settings.discovered_workspace_execution_identities
        if discovered:
            return set(discovered)
        return {"agent-code", "agent-viz"}

    async def assign_work_item(
        self, case_id: str, request: WorkItemCreateRequest, actor: str
    ) -> WorkItemRecord:
        case = await self._cases.get(case_id)
        active_work_items = sum(
            work_item.status in self._ACTIVE_WORK_ITEM_STATUSES
            or (work_item.status == "failed" and work_item.attempt < work_item.max_attempts)
            for work_item in case.work_items
        )
        if active_work_items >= self._settings.max_active_work_items_per_case:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Active Work Item quota exceeded for Case",
            )
        if request.target not in {*self._external_workers(), "workflow-operator"}:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Invalid work item target"
            )
        if request.execution_mode == "workspace_execution":
            if request.target not in self._workspace_execution_targets():
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Workspace execution is not declared for this target",
                )
            if not request.approval_required and not case.plan_hash:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Workspace execution requires approval_required or a frozen plan",
                )
        elif (
            request.target in {"agent-code", "agent-viz", "agent-scrna", "agent-rnaseq"}
            and not request.read_only
        ):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Professional agent work items must be read-only",
            )
        payload = request.model_dump()
        requested_input_keys = {
            f"{ref.kind}:{ref.id}" for ref in request.declared_inputs
        }
        requested_output_keys = {
            f"{ref.kind}:{ref.id}" for ref in request.declared_outputs
        }
        conflicting_items: list[str] = []
        for existing in case.work_items:
            if existing.status not in self._ACTIVE_WORK_ITEM_STATUSES:
                continue
            existing_input_keys = {f"{ref.kind}:{ref.id}" for ref in existing.declared_inputs}
            existing_output_keys = {f"{ref.kind}:{ref.id}" for ref in existing.declared_outputs}
            if requested_output_keys.intersection(existing_output_keys | existing_input_keys) or (
                requested_input_keys.intersection(existing_output_keys)
            ):
                conflicting_items.append(existing.work_item_id)
        if conflicting_items:
            payload["depends_on"] = list(dict.fromkeys([
                *request.depends_on,
                *conflicting_items,
            ]))
        idempotency_key = payload.pop("idempotency_key", None) or self._work_item_idempotency_key(
            case_id, request
        )
        work_item = WorkItemRecord(
            **payload,
            plan_hash=case.plan_hash if request.execution_mode == "workspace_execution" else None,
            plan_version=case.plan_version if request.execution_mode == "workspace_execution" else 0,
            idempotency_key=idempotency_key,
            updated_at=datetime.now(UTC),
        )
        case = await self._cases.add_work_item(case_id, work_item)
        await self._audit.record(
            case_id=case.case_id,
            actor=actor,
            event_type="work_item.assigned",
            payload={
                "work_item_id": work_item.work_item_id,
                "target": work_item.target,
                "objective": work_item.objective,
                "skill_name": work_item.skill_name,
                "context_refs": [ref.model_dump() for ref in work_item.context_refs],
                "declared_inputs": [ref.model_dump() for ref in work_item.declared_inputs],
                "declared_outputs": [ref.model_dump() for ref in work_item.declared_outputs],
                "serialized_after": conflicting_items,
                "status_line": self._work_item_status_line(work_item, "queued"),
            },
        )
        return work_item

    async def reconcile_approval_timeouts(
        self, actor: str, *, now: datetime | None = None
    ) -> dict[str, int]:
        """Remind stale approvals once and automatically cancel them after seven days."""
        current = now or datetime.now(UTC)
        summary = {"scanned": 0, "reminded": 0, "cancelled": 0}
        for case in await self._cases.list():
            if case.status != "approval_pending":
                continue
            summary["scanned"] += 1
            events = await self._audit.list_events(case.case_id)
            approval_started_at = self._approval_started_at(case, events)
            age = current - approval_started_at
            if age >= timedelta(days=7):
                await self._cases.cancel(case.case_id)
                await self._audit.record(
                    case_id=case.case_id,
                    actor=actor,
                    event_type="case.cancelled",
                    payload={
                        "reason": "approval_timeout_7d",
                        "previous_status": "approval_pending",
                        "approval_started_at": approval_started_at.isoformat(),
                        "automatic": True,
                    },
                )
                summary["cancelled"] += 1
                continue
            already_reminded = any(
                event.get("event_type") == "approval.reminder" for event in events
            )
            if age >= timedelta(hours=24) and not already_reminded:
                await self._audit.record(
                    case_id=case.case_id,
                    actor=actor,
                    event_type="approval.reminder",
                    payload={
                        "approval_started_at": approval_started_at.isoformat(),
                        "age_hours": int(age.total_seconds() // 3600),
                        "auto_cancel_after_days": 7,
                    },
                )
                summary["reminded"] += 1
        return summary

    @staticmethod
    def _approval_started_at(case: CaseRecord, events: list[dict[str, Any]]) -> datetime:
        candidates = [
            event
            for event in events
            if event.get("event_type") == "approval.requested"
            or (
                event.get("event_type") == "case.state_changed"
                and isinstance(event.get("payload"), dict)
                and event["payload"].get("status") == "approval_pending"
            )
        ]
        if not candidates:
            return case.updated_at
        raw = candidates[-1].get("recorded_at")
        if not isinstance(raw, str):
            return case.updated_at
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return case.updated_at
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    async def gc_cases(self, actor: str) -> dict[str, Any]:
        """Delete terminal Cases older than BRIDGE_CASE_GC_DAYS together with their audit events."""
        days = self._settings.case_gc_days
        if days <= 0:
            return {
                "gc_enabled": False,
                "days": days,
                "scanned": 0,
                "deleted_cases": 0,
                "deleted_events": 0,
            }
        cutoff = datetime.now(UTC) - timedelta(days=days)
        summary: dict[str, Any] = {
            "gc_enabled": True,
            "days": days,
            "scanned": 0,
            "deleted_cases": 0,
            "deleted_events": 0,
        }
        for case in await self._cases.list():
            if case.record_kind != "case":
                # 房间命名空间记录承载房间级事件流，生命周期随房间，不参与 Case GC。
                continue
            if case.status not in self._GC_CASE_STATUSES:
                continue
            updated_at = case.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=UTC)
            if updated_at >= cutoff:
                continue
            summary["scanned"] += 1
            deleted_events = await self._audit.delete_events(case.case_id)
            if not await self._cases.delete(case.case_id):
                continue
            summary["deleted_cases"] += 1
            summary["deleted_events"] += deleted_events
        return summary

    async def reconcile_case(self, case_id: str, actor: str) -> CaseRecord:
        """Advance a submitted Case only from observed OmicHub task state.

        Reconciliation creates the next assigned Work Item but never invents a quality decision
        or delivery manifest. It is safe to call repeatedly from a Manager/Controller poller.
        """
        case = await self._cases.get(case_id)
        if case.status == "queued":
            queue_reason = await self._case_queue_reason(case, exclude_case_id=case.case_id)
            if queue_reason is not None:
                return case
            case = await self._cases.transition(case_id, "received")
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="case.dequeued",
                payload={"status": "received"},
            )
        if case.status in {"received", "planning_running"} and not self._existing_work_item_id(
            case, "plan-01"
        ):
            # 聊天式通用 Case（无 flow_id）不进入自动 planning，由房间内 Manager 响应链路处理。
            if not case.flow_id:
                previous_status = case.status
                reason = "chat_case_skips_auto_planning"
                prior_events = await self._audit.list_events(case_id)
                already_recorded = any(
                    event.get("event_type") == "case.reconciled"
                    and isinstance(event.get("payload"), dict)
                    and event["payload"].get("reason") == reason
                    and event["payload"].get("from_status") == previous_status
                    for event in prior_events
                )
                if not already_recorded:
                    await self._audit.record(
                        case_id=case_id,
                        actor=actor,
                        event_type="case.reconciled",
                        payload={
                            "from_status": previous_status,
                            "to_status": previous_status,
                            "reason": reason,
                        },
                    )
                return await self._cases.get(case_id)
            if case.status == "received":
                case = await self._cases.transition(case_id, "planning_running")
            planner = case.lead_planner or self._planner_for_flow(case.flow_id or "")
            await self._ensure_work_item(
                case,
                WorkItemRecord(
                    work_item_id="plan-01",
                    target=planner,
                    objective="形成可执行计划、参数快照、任务依赖与风险说明。",
                    skill_name="planning_advice",
                    context_refs=self._case_context_refs(case)
                    + ([{"kind": "flow", "id": case.flow_id}] if case.flow_id else []),
                    read_only=True,
                    updated_at=datetime.now(UTC),
                ),
                actor,
            )
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="case.reconciled",
                payload={"from_status": "received", "to_status": "planning_running"},
            )
            return await self._cases.get(case_id)
        if case.status == "planning_running":
            elapsed = self._node_elapsed_seconds(case)
            if elapsed is not None and elapsed > self._settings.planning_timeout_seconds:
                await self._audit.record(
                    case_id=case_id,
                    actor=actor,
                    event_type="node_timeout",
                    payload={
                        "node": "planning",
                        "elapsed_seconds": elapsed,
                        "timeout_seconds": self._settings.planning_timeout_seconds,
                        "recommended_actions": ["retry", "revise", "cancel"],
                    },
                )
                return await self._cases.transition(case_id, "waiting_for_correction")
        if case.status != "executing" or not case.omic_task_ids:
            return case

        elapsed = self._node_elapsed_seconds(case)
        if elapsed is not None and elapsed > self._settings.execution_timeout_seconds:
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="node_timeout",
                payload={
                    "node": "execution",
                    "elapsed_seconds": elapsed,
                    "timeout_seconds": self._settings.execution_timeout_seconds,
                    "recommended_actions": ["retry", "view_logs", "cancel"],
                },
            )
            return await self._cases.transition(case_id, "execution_failed")

        task_id = case.omic_task_ids[-1]
        task = await self._client.get_task(task_id)
        task_status = str(task.get("status", "")).lower()
        if task_status == "queued" and self._task_is_stalled(task):
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="omic_task.stalled",
                payload={
                    "omic_task_id": task_id,
                    "status": task_status,
                    "timeout_seconds": self._settings.omic_task_stall_timeout_seconds,
                    "created_at": task.get("created_at"),
                },
            )
            task = await self._client.get_task(task_id)
            task_status = str(task.get("status", "")).lower()
            if task_status == "queued":
                return await self._cases.transition(case_id, "execution_failed")
        if task_status == "success":
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="omic_task.completed",
                payload={"omic_task_id": task_id, "status": task_status},
            )
            flow_id = case.preflight_input.flow_id if case.preflight_input else ""
            interpretation_target = await self._interpretation_target(flow_id)
            quality_dependency = self._existing_work_item_id(case, "submit-01")
            if interpretation_target:
                interpretation = await self._ensure_work_item(
                    case,
                    WorkItemRecord(
                        work_item_id="interpret-01",
                        parent_work_item_id=quality_dependency,
                        target=interpretation_target,
                        objective="解读成功任务的关键结果、证据、限制与后续建议，供独立质控复核。",
                        skill_name="result_interpretation",
                        context_refs=[
                            *self._case_context_refs(case),
                            {"kind": "task", "id": task_id},
                        ],
                        read_only=True,
                        depends_on=[quality_dependency] if quality_dependency else [],
                        updated_at=datetime.now(UTC),
                    ),
                    actor,
                )
                quality_dependency = interpretation.work_item_id
            else:
                await self._audit.record(
                    case_id=case_id,
                    actor=actor,
                    event_type="interpretation.skipped",
                    payload={"flow_id": flow_id, "omic_task_id": task_id},
                )
            case = await self._cases.get(case_id)
            if not self._quality_gate_required(case):
                case = await self._cases.transition(case_id, "delivery_ready")
                await self._audit.record(
                    case_id=case_id,
                    actor=actor,
                    event_type="quality.skipped",
                    payload={
                        "flow_id": flow_id,
                        "omic_task_id": task_id,
                        "reason": "frozen_plan_did_not_require_quality_gate",
                    },
                )
                await self._ensure_work_item(
                    case,
                    WorkItemRecord(
                        work_item_id="delivery-01",
                        parent_work_item_id=quality_dependency,
                        target=self._standard_work_item_target(flow_id, "delivery", "delivery-reporter"),
                        objective="汇总任务产物、解读结论与限制，形成可追溯交付包。",
                        skill_name="delivery-pack",
                        context_refs=[
                            *self._case_context_refs(case),
                            {"kind": "task", "id": task_id},
                        ],
                        read_only=True,
                        depends_on=[quality_dependency] if quality_dependency else [],
                        updated_at=datetime.now(UTC),
                    ),
                    actor,
                )
                return await self._cases.get(case_id)
            case = await self._cases.transition(case_id, "quality_running")
            await self._ensure_work_item(
                case,
                WorkItemRecord(
                    work_item_id="quality-01",
                    parent_work_item_id=quality_dependency,
                    target=self._standard_work_item_target(flow_id, "quality", "quality-auditor"),
                    objective="核对成功任务的 QC、产物完整性和可交付性，提交可追溯质量结论。",
                    skill_name="quality-gate",
                    context_refs=[*self._case_context_refs(case), {"kind": "task", "id": task_id}],
                    read_only=True,
                    depends_on=[quality_dependency] if quality_dependency else [],
                    updated_at=datetime.now(UTC),
                ),
                actor,
            )
            return await self._cases.get(case_id)
        if task_status in {"failed", "error"}:
            case = await self._cases.transition(case_id, "execution_failed")
            error_excerpt = str(task.get("error_message") or "")[-500:]
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="omic_task.failed",
                payload={
                    "omic_task_id": task_id,
                    "status": task_status,
                    "error_excerpt": error_excerpt,
                },
            )
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="case.execution_failed",
                payload={
                    "omic_task_id": task_id,
                    "error_excerpt": error_excerpt,
                    "recommendation": "检查失败日志与输入后，确认重试以复用冻结计划。",
                    "retry_allowed": True,
                },
            )
            return case
        return case

    def _quality_gate_required(self, case: CaseRecord) -> bool:
        proposed_submission = case.proposed_submission
        if isinstance(proposed_submission, dict) and isinstance(
            proposed_submission.get("quality_gate_required"), bool
        ):
            return bool(proposed_submission["quality_gate_required"])
        return self._settings.quality_gate_for_flow(case.flow_id or "")

    def _task_is_stalled(self, task: dict[str, Any]) -> bool:
        queued_since = self._parse_datetime(task.get("updated_at") or task.get("created_at"))
        if queued_since is None:
            return False
        return (datetime.now(UTC) - queued_since).total_seconds() >= (
            self._settings.omic_task_stall_timeout_seconds
        )

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str) and value.strip():
            try:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)

    def _standard_work_item_target(self, flow_id: str, kind: str, legacy_default: str) -> str:
        """O5:标准工作项 target 配置优先;未声明时回落硬编码缺省并打 deprecation 日志。"""
        configured = self._settings.standard_work_item_target(flow_id, kind)
        if configured:
            return configured
        warn_key = f"{flow_id}:{kind}"
        if warn_key not in _standard_target_fallback_warned:
            _standard_target_fallback_warned.add(warn_key)
            logger.warning(
                "standard_work_items 缺省 fallback:flow=%s kind=%s 未在 flow YAML 或 "
                "_shared/policies.yaml 声明 target,沿用硬编码缺省 %s(deprecated,一个版本后移除)",
                flow_id,
                kind,
                legacy_default,
            )
        return legacy_default

    async def _interpretation_target(self, flow_id: str) -> str | None:
        if flow_id not in self._settings.discovered_flow_agent_map:
            await self.refresh_capabilities()
        # O5:flow YAML standard_work_items.interpret 声明优先,否则沿用 flow actor。
        configured = self._settings.standard_work_item_target(flow_id, "interpret")
        if configured:
            return configured
        return self._settings.discovered_flow_agent_map.get(flow_id)

    async def update_work_item(
        self, case_id: str, work_item_id: str, request: WorkItemUpdateRequest, actor: str
    ) -> WorkItemRecord:
        work_item = await self._cases.get_work_item(case_id, work_item_id)
        if actor not in {"bioops-manager", work_item.target}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Identity cannot update this work item",
            )
        if request.status in {"skipped", "timeout"} and actor != "bioops-manager":
            # skipped/timeout 是系统判定态：级联跳过与失联超时只能由 Bridge 状态机产生。
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="skipped/timeout are system-owned terminal statuses",
            )
        if request.status == "pending":
            if actor != "bioops-manager":
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Cannot reset work item to pending",
                )
            # 手动重试：Manager 把失败/超时/被跳过的工作项重置回 pending（重置重试预算）。
            requeued = await self._cases.manager_requeue_work_item(case_id, work_item_id)
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="work_item.manual_retry",
                payload={
                    "work_item_id": work_item_id,
                    "skill_name": work_item.skill_name,
                    "previous_status": work_item.status,
                    "summary": (
                        f"工作项 {work_item_id} 已由 Manager 手动重试，"
                        f"从 {work_item.status} 重置为待派发（重试预算已刷新）。"
                    ),
                },
            )
            await self._auto_reconcile(case_id)
            return requeued
        if actor == "bioops-manager" and request.status == "cancelled":
            # 用户终止：Manager 可强制取消任意非终态工作项（含 Worker 持有租约的运行中项），
            # 依赖它的未启动下游级联跳过，避免静默卡死。
            cancelled = await self._cases.manager_cancel_work_item(case_id, work_item_id)
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="work_item.cancelled",
                payload={
                    "work_item_id": work_item_id,
                    "skill_name": work_item.skill_name,
                    "previous_status": work_item.status,
                    "reason": request.summary or "manual_cancel",
                    "summary": f"工作项 {work_item_id} 已被手动终止。",
                },
            )
            await self._cascade_skip(case_id, cancelled, actor)
            await self._auto_reconcile(case_id)
            return cancelled
        if actor != "bioops-manager" and request.status in {"claimed", "in_progress"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Use the claim endpoint to start a work item",
            )
        if actor != "bioops-manager" and work_item.status not in {
            "claimed",
            "running",
            "awaiting_approval",
            "in_progress",
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Work item must be claimed before completion",
            )
        updated = await self._cases.transition_work_item(
            case_id,
            work_item_id,
            actor if actor != "bioops-manager" else work_item.target,
            request.status,
            summary=request.summary,
            findings=request.findings,
            output_refs=request.output_refs,
            trace_id=request.trace_id,
        )
        if request.status == "failed":
            updated = await self._schedule_work_item_retry(case_id, updated, actor)
        event_type = (
            "skill.finished"
            if request.status == "completed"
            else "skill.failed"
            if request.status == "failed"
            else "skill.status_changed"
        )
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type=event_type,
            payload={
                "work_item_id": work_item_id,
                "skill_name": work_item.skill_name,
                "status": request.status,
                "summary": request.summary,
                "findings": [finding.model_dump() for finding in request.findings],
                "output_refs": [ref.model_dump() for ref in request.output_refs],
                "trace_id": updated.trace_id,
                "status_line": self._work_item_status_line(
                    work_item,
                    "succeeded" if request.status == "completed" else "failed",
                )
                if request.status in {"completed", "failed"}
                else None,
            },
        )
        if request.status == "completed":
            await self._maybe_record_agent_handoff(
                case_id,
                actor=actor,
                completed_work_item=work_item,
                summary=request.summary,
                findings=request.findings,
                output_refs=request.output_refs,
            )
        if request.status == "completed" and work_item.skill_name == "remediation-fix":
            case = await self._cases.get(case_id)
            if case.status == "remediation_pending":
                await self._cases.transition(case_id, "approval_pending")
                await self._audit.record(
                    case_id=case_id,
                    actor="bioops-manager",
                    event_type="remediation.completed",
                    payload={
                        "work_item_id": work_item_id,
                        "completed_by": actor,
                        "summary": request.summary,
                        "next_status": "approval_pending",
                    },
                )
        if request.status in {"completed", "failed"}:
            await self._auto_reconcile(case_id)
        return updated

    async def _maybe_record_agent_handoff(
        self,
        case_id: str,
        *,
        actor: str,
        completed_work_item: WorkItemRecord,
        summary: str,
        findings: list[Finding],
        output_refs: list[ContextRef],
    ) -> None:
        """Emit one structured handoff after an agent's assigned work is complete."""
        if actor == "bioops-manager":
            return
        case = await self._cases.get(case_id)
        assigned = [item for item in case.work_items if item.target == actor]
        if not assigned or not all(item.status == "completed" for item in assigned):
            return
        existing_events = await self._audit.list_events(case_id)
        if any(
            event.get("event_type") == "room.agent_handoff"
            and (event.get("payload") or {}).get("from_agent_id") == actor
            and set((event.get("payload") or {}).get("work_item_ids") or [])
            == {item.work_item_id for item in assigned}
            for event in existing_events
        ):
            return
        risks = [
            finding.message
            for finding in findings
            if getattr(finding, "severity", "") in {"warning", "error"}
        ]
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="room.agent_handoff",
            payload={
                "from_agent_id": actor,
                "to_agent_id": "bioops-manager",
                "work_item_ids": [item.work_item_id for item in assigned],
                "summary": summary or f"{completed_work_item.skill_name} 已完成。",
                "risks": risks,
                "artifact_refs": [ref.model_dump(mode="json") for ref in output_refs],
                "recommended_next_action": "request_user_review",
            },
        )

    async def _auto_reconcile(self, case_id: str) -> None:
        """Best-effort Case advancement after a work item reaches a terminal state.

        Reuses reconcile_case so no new states are invented; never raises into the
        work-item update path and is idempotent for already terminal Cases.
        """
        try:
            case = await self._cases.get(case_id)
            if case.status in {"closed", "cancelled"}:
                return
            if any(not self._work_item_is_settled(item) for item in case.work_items):
                return
            for task_id in case.omic_task_ids:
                try:
                    task = await self._client.get_task(task_id)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "auto-reconcile skipped for case %s: task %s state unavailable",
                        case_id,
                        task_id,
                    )
                    return
                if str(task.get("status", "")).lower() not in self._TERMINAL_OMIC_TASK_STATUSES:
                    return
            await self.reconcile_case(case_id, "bioops-manager")
        except Exception:
            logger.warning("auto-reconcile failed for case %s", case_id, exc_info=True)

    def _work_item_is_settled(self, work_item: WorkItemRecord) -> bool:
        if work_item.status in self._SETTLED_WORK_ITEM_STATUSES:
            return True
        # A failed work item with retry budget left will be requeued, so it is not settled.
        return work_item.status == "failed" and work_item.attempt >= work_item.max_attempts

    def _work_item_status_line(self, work_item: WorkItemRecord, phase: str) -> str | None:
        """按工作项 target 的人格配置取状态播报文案;未配置返回 None。"""
        agent_id = self._settings.role_agent_mapping().get(work_item.target, work_item.target)
        return self._settings.persona_status_line_for(agent_id, phase)

    async def claim_work_item(self, case_id: str, work_item_id: str, actor: str) -> WorkItemRecord:
        case = await self._cases.get(case_id)
        requested = await self._cases.get_work_item(case_id, work_item_id)
        if (
            requested.execution_mode == "workspace_execution"
            and not self._workspace_work_item_is_plan_bound(case, requested)
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Workspace work item is not bound to the frozen plan",
            )
        work_item = await self._cases.claim_work_item(case_id, work_item_id, actor)
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="work_item.claimed",
            payload={
                "work_item_id": work_item.work_item_id,
                "skill_name": work_item.skill_name,
                "lease_seconds": work_item.deadline_seconds,
                "attempt": work_item.attempt,
                "trace_id": work_item.trace_id,
                "status_line": self._work_item_status_line(work_item, "running"),
            },
        )
        return work_item

    async def heartbeat_work_item(
        self,
        case_id: str,
        work_item_id: str,
        request: WorkItemHeartbeatRequest,
        actor: str,
    ) -> WorkItemRecord:
        work_item = await self._cases.heartbeat_work_item(
            case_id, work_item_id, actor, trace_id=request.trace_id
        )
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="worker.heartbeat",
            payload={
                "work_item_id": work_item_id,
                "attempt": work_item.attempt,
                "lease_expires_at": work_item.lease_expires_at,
                "summary": request.summary,
                "trace_id": work_item.trace_id,
                "worker_id": request.worker_id,
            },
        )
        return work_item

    async def execute_readonly_work_item(
        self,
        case_id: str,
        work_item_id: str,
        request: ReadOnlyExecutionRequest,
        actor: str,
    ) -> WorkItemRecord:
        expected_agent_id = self._settings.role_agent_mapping().get(actor)
        if expected_agent_id is None or request.agent_id != expected_agent_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Worker identity is not permitted for this Gateway agent",
            )
        work_item = await self._cases.get_work_item(case_id, work_item_id)
        if actor != work_item.target:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Work item target mismatch"
            )
        if request.execution_mode != work_item.execution_mode:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Work item execution mode mismatch",
            )
        case = await self._cases.get(case_id)
        if work_item.execution_mode == "workspace_execution":
            if work_item.target not in {"agent-code", "agent-viz"}:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Workspace target is not allowed"
                )
            if not case.plan_hash and not (
                work_item.approval_required and work_item.approved_submission is not None
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Workspace execution is not approved",
                )
        elif not work_item.read_only or work_item.approval_required:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only unapproved read-only work items may use Gateway execution",
            )
        if work_item.status == "claimed":
            work_item = await self._cases.transition_work_item(
                case_id,
                work_item_id,
                actor,
                "running",
                trace_id=request.trace_id,
            )
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="work_item.running",
                payload={
                    "work_item_id": work_item_id,
                    "trace_id": work_item.trace_id,
                    "status_line": self._work_item_status_line(work_item, "running"),
                },
            )
        if work_item.status != "running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Work item must be claimed before execution",
            )
        if self._gateway is None or not self._gateway.configured:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Gateway is unavailable"
            )
        await self.heartbeat_work_item(
            case_id,
            work_item_id,
            WorkItemHeartbeatRequest(
                trace_id=request.trace_id, summary="Gateway consultation started"
            ),
            actor,
        )
        renew_task = asyncio.create_task(
            self._renew_work_item_lease(case_id, work_item_id, actor, work_item.deadline_seconds)
        )
        try:
            try:
                result = await self._gateway.consult(
                    {
                        "case_id": case_id,
                        "agent_id": expected_agent_id,
                        "question": request.question,
                        "capability": request.capability,
                        "evidence_refs": request.evidence_refs,
                        "requested_tools": request.requested_tools,
                        "requester_ref": case.requester_ref,
                        "work_item_id": work_item_id,
                        "execution_mode": request.execution_mode,
                    }
                )
                gateway_result = ReadOnlyExecutionResult.model_validate(result)
                if gateway_result.agent_id != request.agent_id:
                    raise ValueError("Gateway response agent does not match the requested agent")
            except Exception as exc:  # noqa: BLE001
                current = await self._cases.get_work_item(case_id, work_item_id)
                if current.attempt != work_item.attempt:
                    # The lease expired mid-consultation and a newer attempt already
                    # reclaimed the item; never overwrite that attempt's state.
                    failed = None
                    conflict = f"Work item reclaimed by attempt {current.attempt}"
                else:
                    conflict = None
                    try:
                        failed = await self._cases.transition_work_item(
                            case_id,
                            work_item_id,
                            actor,
                            "failed",
                            summary=f"Gateway consultation failed: {exc}"[:4000],
                            trace_id=request.trace_id,
                        )
                    except HTTPException as transition_exc:
                        if transition_exc.status_code != status.HTTP_409_CONFLICT:
                            raise
                        failed = None
                        conflict = str(transition_exc.detail)
                if conflict is not None:
                    logger.warning(
                        "work item %s of case %s lost its lease during a failed consultation: %s",
                        work_item_id,
                        case_id,
                        conflict,
                    )
                    await self._audit.record(
                        case_id=case_id,
                        actor=actor,
                        event_type="skill.failed",
                        payload={
                            "work_item_id": work_item_id,
                            "error": str(exc)[:500],
                            "reason": "lease_conflict",
                            "detail": conflict,
                            "trace_id": request.trace_id,
                        },
                    )
                    return current
                await self._audit.record(
                    case_id=case_id,
                    actor=actor,
                    event_type="skill.failed",
                    payload={"work_item_id": work_item_id, "error": str(exc)[:500]},
                )
                assert failed is not None  # conflict is None here, so the transition succeeded
                return await self._schedule_work_item_retry(case_id, failed, actor)
        finally:
            renew_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await renew_task

        status_value = gateway_result.status
        completed = status_value == "completed"
        desired_status: WorkItemStatus = "completed" if completed else "blocked"
        summary = gateway_result.conclusion
        current = await self._cases.get_work_item(case_id, work_item_id)
        updated: WorkItemRecord | None = None
        if current.attempt != work_item.attempt:
            # The lease expired mid-consultation and a newer attempt already
            # reclaimed the item; never overwrite that attempt's state.
            conflict = f"Work item reclaimed by attempt {current.attempt}"
        else:
            conflict = None
            try:
                updated = await self._cases.transition_work_item(
                    case_id,
                    work_item_id,
                    actor,
                    desired_status,
                    summary=summary,
                    trace_id=request.trace_id,
                )
            except HTTPException as exc:
                if exc.status_code != status.HTTP_409_CONFLICT:
                    raise
                conflict = str(exc.detail)
        if conflict is not None:
            logger.warning(
                "work item %s of case %s lost its lease before consultation completion: %s",
                work_item_id,
                case_id,
                conflict,
            )
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="skill.failed",
                payload={
                    "work_item_id": work_item_id,
                    "agent_id": request.agent_id,
                    "capability": request.capability,
                    "gateway_status": status_value,
                    "reason": "lease_conflict",
                    "error": conflict,
                    "trace_id": request.trace_id,
                },
            )
            return current
        assert updated is not None  # conflict is None here, so the transition succeeded
        artifact_refs = self._workspace_artifact_refs(
            case_id,
            work_item_id,
            gateway_result.artifacts,
        )
        if artifact_refs:
            updated = updated.model_copy(update={"output_refs": artifact_refs})
            case = await self._cases.update_work_item(case_id, work_item_id, updated)
            updated = next(
                item for item in case.work_items if item.work_item_id == work_item_id
            )
        if completed and work_item_id == "plan-01":
            await self._accept_plan_result(case_id, gateway_result.proposed_submission, actor)
        elif completed and work_item_id == "preflight-01":
            case = await self._cases.get(case_id)
            if not case.plan_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Preflight completion requires a frozen plan hash",
                )
            if case.status == "preflight_running":
                await self._cases.transition(case_id, "approval_pending")
        if gateway_result.hard_gate:
            hard_gate_event = dict(gateway_result.hard_gate.get("audit_event") or {})
            if hard_gate_event.get("event_type") == "quality.hard_gate":
                await self._audit.record(
                    case_id=case_id,
                    actor=actor,
                    event_type="quality.hard_gate",
                    payload={
                        key: value for key, value in hard_gate_event.items() if key != "event_type"
                    },
                )
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="skill.finished" if completed else "skill.manual_review",
            payload={
                "work_item_id": work_item_id,
                "agent_id": request.agent_id,
                "capability": request.capability,
                "gateway_status": status_value,
                "summary": summary,
                "recommendations": gateway_result.recommendations,
                "evidence_refs": gateway_result.evidence_refs,
                "risks": gateway_result.risks,
                "artifacts": gateway_result.artifacts,
                "hard_gate": gateway_result.hard_gate,
                "trace_id": updated.trace_id,
            },
        )
        if completed and work_item.skill_name not in {"planning_advice", "project-preflight"}:
            await self._audit.record(
                case_id=case_id,
                actor="bioops-manager",
                event_type="manager.review_ready",
                payload={
                    "work_item_id": work_item_id,
                    "worker": actor,
                    "decision": "accepted",
                    "summary": summary,
                    "next_action": "continue_dependencies",
                    "trace_id": updated.trace_id,
                },
            )
        return updated

    async def _renew_work_item_lease(
        self, case_id: str, work_item_id: str, actor: str, deadline_seconds: int
    ) -> None:
        """Renew the lease while a blocking Gateway consultation is in flight.

        Beats at one third of the lease duration so a healthy long consultation
        never times out and gets silently requeued. Renewal uses the store-level
        heartbeat (no audit spam); if the lease is already lost, renewal stops and
        the completion path degrades to a lease_conflict audit event instead of
        a bare 500.
        """
        interval = max(1.0, deadline_seconds / 3)
        while True:
            await asyncio.sleep(interval)
            try:
                await self._cases.heartbeat_work_item(case_id, work_item_id, actor)
            except Exception as exc:
                logger.warning(
                    "lease renewal stopped for work item %s of case %s",
                    work_item_id,
                    case_id,
                    exc_info=True,
                )
                await self._audit.record(
                    case_id=case_id,
                    actor=actor,
                    event_type="worker.lease_renewal_failed",
                    payload={
                        "work_item_id": work_item_id,
                        "error": str(exc)[:500],
                        "deadline_seconds": deadline_seconds,
                    },
                )
                return

    async def _schedule_work_item_retry(
        self, case_id: str, work_item: WorkItemRecord, actor: str
    ) -> WorkItemRecord:
        if work_item.attempt >= work_item.max_attempts:
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="work_item.retry_exhausted",
                payload={
                    "work_item_id": work_item.work_item_id,
                    "attempt": work_item.attempt,
                    "max_attempts": work_item.max_attempts,
                    "options": ["retry", "skip", "terminate"],
                    "status_line": self._work_item_status_line(work_item, "failed"),
                    "summary": (
                        f"工作项 {work_item.work_item_id} 失败且自动重试次数"
                        f"（{work_item.max_attempts} 次）已耗尽；依赖它的下游工作项将被跳过，"
                        "你可以手动重试或终止 Case。"
                    ),
                },
            )
            await self._cascade_skip(case_id, work_item, actor)
            return work_item
        delay_seconds = self._retry_delay_seconds(work_item)
        retry_not_before = datetime.now(UTC) + timedelta(seconds=delay_seconds)
        scheduled = work_item.model_copy(update={"retry_not_before": retry_not_before})
        case = await self._cases.update_work_item(
            case_id, work_item.work_item_id, scheduled
        )
        scheduled = next(
            item for item in case.work_items if item.work_item_id == work_item.work_item_id
        )
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="work_item.retry_scheduled",
            payload={
                "work_item_id": work_item.work_item_id,
                "attempt": work_item.attempt,
                "max_attempts": work_item.max_attempts,
                "delay_seconds": delay_seconds,
                "retry_not_before": retry_not_before.isoformat(),
                "summary": (
                    f"工作项 {work_item.work_item_id} 执行失败，"
                    f"将在 {delay_seconds} 秒后自动重试"
                    f"（第 {work_item.attempt}/{work_item.max_attempts} 次尝试）。"
                ),
            },
        )
        return scheduled

    def _retry_delay_seconds(self, work_item: WorkItemRecord) -> int:
        """Per-item DAG backoff (``retry.backoff_seconds``, exponential) or the default table."""
        base = work_item.retry_backoff_seconds
        if base is not None:
            exponent = max(work_item.attempt - 1, 0)
            return min(base * (2**exponent), 3_600)
        backoff_index = min(
            max(work_item.attempt - 1, 0), len(self._RETRY_BACKOFF_SECONDS) - 1
        )
        return self._RETRY_BACKOFF_SECONDS[backoff_index]

    @staticmethod
    def _workspace_work_item_is_plan_bound(case: CaseRecord, work_item: WorkItemRecord) -> bool:
        if (
            not case.plan_hash
            or work_item.plan_hash != case.plan_hash
            or not isinstance(case.proposed_submission, dict)
        ):
            return False
        parameters = case.proposed_submission.get("parameters")
        planned_items = parameters.get("work_items") if isinstance(parameters, dict) else None
        if not isinstance(planned_items, list):
            return False
        return any(
            isinstance(item, dict)
            and item.get("work_item_id") == work_item.work_item_id
            and item.get("target") == work_item.target
            and item.get("objective") == work_item.objective
            and item.get("skill_name") == work_item.skill_name
            and [str(value) for value in item.get("depends_on") or []] == work_item.depends_on
            for item in planned_items
        )

    @staticmethod
    def _workspace_artifact_refs(
        case_id: str,
        work_item_id: str,
        artifacts: list[dict[str, Any]],
    ) -> list[ContextRef]:
        expected_parts = ("workspace", "agentteams", case_id, work_item_id)
        refs: list[ContextRef] = []
        seen: set[str] = set()
        for artifact in artifacts:
            if not isinstance(artifact, dict) or artifact.get("kind") != "file":
                continue
            raw_path = str(artifact.get("path") or "").strip().replace("\\", "/")
            path = Path(raw_path)
            if not raw_path or path.is_absolute() or ".." in path.parts:
                continue
            parts = path.parts
            if not any(
                tuple(parts[index : index + len(expected_parts)]) == expected_parts
                for index in range(len(parts) - len(expected_parts) + 1)
            ):
                continue
            s3_uri = str(artifact.get("s3_uri") or "").strip()
            ref_location = s3_uri or raw_path
            if ref_location in seen:
                continue
            seen.add(ref_location)
            refs.append(
                ContextRef(
                    kind="s3" if s3_uri else "file",
                    id=ref_location,
                    location=ref_location,
                    meta={
                        "local_path": raw_path,
                        "size_bytes": artifact.get("size_bytes", artifact.get("bytes")),
                        "sha256": artifact.get("sha256"),
                    },
                )
            )
        return refs[:100]

    @staticmethod
    def _case_context_refs(case: CaseRecord) -> list[ContextRef]:
        if case.context_refs:
            return list(case.context_refs)
        return [case.project_ref] if case.project_ref is not None else []

    async def create_case(self, request: CaseCreateRequest, actor: str) -> CaseRecord:
        if request.record_kind == "room_namespace":
            return await self._create_room_namespace(request, actor)
        queue_reason = await self._case_queue_reason(request)
        now = datetime.now(UTC)
        case = await self._cases.create(
            CaseRecord(
                case_id=request.case_id,
                project_ref=request.project_ref,
                context_refs=request.context_refs
                or ([request.project_ref] if request.project_ref else []),
                intent=request.intent,
                requester_ref=request.requester_ref,
                team_id=request.team_id,
                origin_consultation_id=request.origin_consultation_id,
                consultation_summary=request.consultation_summary,
                execution_mode=request.execution_mode,
                flow_id=request.flow_id,
                lead_planner=request.lead_planner,
                record_kind="case",
                source_case_id=request.source_case_id,
                status="queued" if queue_reason else "received",
                created_at=now,
                updated_at=now,
            )
        )
        await self._audit.record(
            case_id=case.case_id,
            actor=actor,
            event_type="case.created",
            payload={
                "project_ref": request.project_ref.model_dump() if request.project_ref else None,
                "context_refs": [ref.model_dump() for ref in request.context_refs],
                "intent": request.intent,
                "execution_mode": request.execution_mode,
                "origin_consultation_id": request.origin_consultation_id,
                "source_case_id": request.source_case_id,
                "queue_reason": queue_reason,
            },
        )
        if queue_reason:
            await self._audit.record(
                case_id=case.case_id,
                actor=actor,
                event_type="case.queued",
                payload={"reason": queue_reason},
            )
        elif request.flow_id or request.lead_planner:
            planner = request.lead_planner or self._planner_for_flow(request.flow_id or "")
            if request.flow_id:
                await self._audit.record(
                    case_id=case.case_id,
                    actor=actor,
                    event_type="case.handoff_proposed",
                    payload={
                        "flow_id": request.flow_id,
                        "lead_planner": planner,
                        "status": "planning_running",
                    },
                )
            case = await self._cases.transition(case.case_id, "planning_running")
            await self._ensure_work_item(
                case,
                WorkItemRecord(
                    work_item_id="plan-01",
                    target=planner,
                    objective="形成可执行计划、参数快照、任务依赖与风险说明。",
                    skill_name="planning_advice",
                    context_refs=self._case_context_refs(case)
                    + ([{"kind": "flow", "id": request.flow_id}] if request.flow_id else []),
                    read_only=True,
                    updated_at=now,
                ),
                actor,
            )
            case = await self._cases.get(case.case_id)
        return case

    async def _create_room_namespace(self, request: CaseCreateRequest, actor: str) -> CaseRecord:
        """Create the internal room-namespace record carrying a room-level event stream.

        会话-工单解耦（Part 2 方案 b）：房间在立项前没有正式 Case，其事件流挂在
        ``room-<room_id>`` 命名空间记录下。命名空间记录不进入用户 Case 列表、
        配额统计与 GC，也不触发排队/规划工作项；事件读写、MinIO 恢复、SSE 与
        房间镜像完全复用现有 Case 链路。
        """
        now = datetime.now(UTC)
        case = await self._cases.create(
            CaseRecord(
                case_id=request.case_id,
                intent=request.intent,
                requester_ref=request.requester_ref,
                team_id=request.team_id,
                execution_mode=request.execution_mode,
                record_kind="room_namespace",
                status="received",
                created_at=now,
                updated_at=now,
            )
        )
        await self._audit.record(
            case_id=case.case_id,
            actor=actor,
            event_type="room.namespace_created",
            payload={"intent": request.intent, "record_kind": "room_namespace"},
        )
        return case

    async def _case_queue_reason(
        self,
        case: CaseCreateRequest | CaseRecord,
        *,
        exclude_case_id: str | None = None,
    ) -> str | None:
        existing = [
            item
            for item in await self._cases.list()
            if item.record_kind == "case"
            and item.case_id != exclude_case_id
            and item.status in self._ACTIVE_CASE_STATUSES
        ]
        requester_active = sum(item.requester_ref == case.requester_ref for item in existing)
        if requester_active >= self._settings.max_active_cases_per_requester:
            return "requester_active_case_quota"
        if case.project_ref is not None:
            project_active = sum(
                item.project_ref is not None and item.project_ref.id == case.project_ref.id
                for item in existing
            )
            if project_active >= self._settings.max_active_cases_per_project:
                return "project_active_case_quota"
        return None

    async def _accept_plan_result(
        self, case_id: str, proposed_submission: dict[str, Any] | None, actor: str
    ) -> None:
        case = await self._cases.get(case_id)
        try:
            if proposed_submission is None:
                raise ValueError("planning consultation omitted proposed_submission")
            if not case.flow_id:
                plan_payload = self._validate_general_plan(proposed_submission)
                plan_hash = self._plan_hash(plan_payload)
                snapshot = PreflightInputSnapshot(
                    flow_id="general",
                    sample_sheet=[],
                    context_refs=self._case_context_refs(case),
                    consultation_summary=case.consultation_summary,
                )
                await self._cases.save_plan(case_id, plan_payload, plan_hash, snapshot)
                await self._cases.transition(case_id, "approval_pending")
                await self._audit.record(
                    case_id=case_id,
                    actor=actor,
                    event_type="planning.frozen",
                    payload={
                        "plan_hash": plan_hash,
                        "kind": "general",
                        "task_count": len(plan_payload["parameters"]["work_items"]),
                        "quality_gate_required": plan_payload["quality_gate_required"],
                    },
                )
                return
            planned_submission = dict(proposed_submission)
            planned_submission.setdefault(
                "quality_gate_required",
                self._settings.quality_gate_for_flow(case.flow_id or ""),
            )
            task = TaskSpec.model_validate(planned_submission)
            if task.flow_id not in self._settings.allowed_flows():
                raise ValueError("planned flow is not allowed")
            if case.flow_id and task.flow_id != case.flow_id:
                raise ValueError("planned flow differs from Case flow")
            if not task.sample_sheet or any(not row.get("sample") for row in task.sample_sheet):
                raise ValueError("planned sample_sheet is missing required sample values")
            if task.comparisons is not None and any(
                not item.get("control") or not item.get("treatment") for item in task.comparisons
            ):
                raise ValueError("planned comparisons are invalid")
        except (ValueError, TypeError) as exc:
            await self._handle_plan_validation_failure(case_id, case, exc, actor)
            return
        plan_payload = task.model_dump(mode="json")
        plan_hash = self._plan_hash(plan_payload)
        snapshot = PreflightInputSnapshot(
            flow_id=task.flow_id,
            sample_sheet=task.sample_sheet,
            comparisons=task.comparisons,
            context_refs=self._case_context_refs(case),
            consultation_summary=case.consultation_summary,
        )
        await self._cases.save_plan(case_id, plan_payload, plan_hash, snapshot)
        await self._cases.transition(case_id, "preflight_running")
        case = await self._cases.get(case_id)
        await self._ensure_work_item(
            case,
            WorkItemRecord(
                work_item_id="preflight-01",
                parent_work_item_id="plan-01",
                target=self._canonical_work_item_target("data-steward"),
                objective="核验冻结计划与真实项目数据、样本和分组是否匹配。",
                skill_name="project-preflight",
                context_refs=[*self._case_context_refs(case), {"kind": "flow", "id": task.flow_id}],
                read_only=True,
                depends_on=["plan-01"],
                updated_at=datetime.now(UTC),
            ),
            actor,
        )
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="planning.frozen",
            payload={
                "plan_hash": plan_hash,
                "flow_id": task.flow_id,
                "quality_gate_required": task.quality_gate_required,
            },
        )

    def _canonical_work_item_target(self, target: str) -> str:
        """BUG-E2E-03：把 legacy 角色别名 target 解析为 canonical worker identity。

        capability snapshot 的 role_agent_map 覆盖 canonical 角色与别名
        （如 data-steward → agent-data）；未登记的 target（如 workflow-operator
        平台内置身份）原样返回。inbox/claim 的精确匹配与租约语义不变。
        """
        resolved = self._settings.role_agent_mapping().get(target)
        if resolved and resolved != target:
            logger.info("work item target %s resolved to canonical identity %s", target, resolved)
            return resolved
        return target

    @staticmethod
    def _parse_missing_fields_from_validation_error(exc: Exception) -> list[str]:
        """从校验错误信息中解析缺失字段，用于修正事件 payload。"""
        message = str(exc)
        if "omitted proposed_submission" in message:
            return ["proposed_submission"]
        if "lacks objective or skill_name" in message:
            return ["objective", "skill_name"]
        if "requires parameters.work_items" in message:
            return ["parameters.work_items"]
        if "must be an object" in message:
            return ["work_item"]
        if "target is not allowed" in message:
            return ["target"]
        if "ids must be unique" in message:
            return ["work_item_id"]
        if "missing required sample values" in message:
            return ["sample_sheet.sample"]
        if "planned comparisons are invalid" in message:
            return ["comparisons.control", "comparisons.treatment"]
        return []

    async def _handle_plan_validation_failure(
        self,
        case_id: str,
        case: CaseRecord,
        exc: Exception,
        actor: str,
        max_attempts: int = 3,
    ) -> None:
        """计划校验失败后的自愈回路：3 次内反馈给 Planner 重试，超限后升级人工介入。"""
        correction_target = "plan-01"
        missing_fields = self._parse_missing_fields_from_validation_error(exc)
        error_message = str(exc)[:500]
        if case.planning_retry_count < max_attempts:
            attempt = case.planning_retry_count + 1
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="correction_started",
                payload={
                    "correction_target": correction_target,
                    "missing_fields": missing_fields,
                    "attempt": attempt,
                    "max_attempts": max_attempts,
                },
            )
            feedback = (
                f"【计划校验反馈，第 {attempt}/{max_attempts} 次重试】"
                f"生成的计划未通过 schema 校验：{error_message}。"
                f"缺失或需修正字段：{missing_fields or '（见错误描述）'}。"
                "输出必须包含完整 proposed_submission；流程型计划至少包含 "
                "flow_id、name、parameters、sample_sheet。"
            )
            # objective 上限 1000 字符，保留原始意图摘要。
            if len(feedback) > 950:
                feedback = feedback[:947] + "..."
            await self._cases.reset_planning_work_item(case_id, correction_target, feedback)
            if case.status != "planning_running":
                await self._cases.transition(case_id, "planning_running")
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="correction_applied",
                payload={
                    "reason": "根据校验错误反馈重新生成计划",
                    "attempt": attempt,
                    "missing_fields": missing_fields,
                    "schema_summary": {
                        "required": ["proposed_submission"],
                        "flow_plan": ["flow_id", "name", "parameters", "sample_sheet"],
                    },
                },
            )
            return
        if case.status == "planning_running":
            await self._cases.transition(case_id, "waiting_for_correction")
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="correction_failed",
            payload={
                "reason": error_message,
                "attempt": case.planning_retry_count,
                "max_attempts": max_attempts,
                "next_actions": ["retry", "revise", "cancel"],
            },
        )
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="planning.validation_failed",
            payload={"error": error_message, "retry_exhausted": True},
        )

    def _validate_general_plan(self, proposed_submission: dict[str, Any]) -> dict[str, Any]:
        parameters = proposed_submission.get("parameters")
        work_items = parameters.get("work_items") if isinstance(parameters, dict) else None
        if not isinstance(work_items, list) or not work_items:
            raise ValueError("general plan requires parameters.work_items")
        expanded: list[dict[str, Any]] = []
        for raw_item in work_items:
            item = dict(raw_item) if isinstance(raw_item, dict) else raw_item
            if not isinstance(item, dict):
                raise ValueError("general plan work item must be an object")
            item["execution_mode"] = str(item.get("execution_mode") or "workspace_execution")
            if item["execution_mode"] != "workspace_execution":
                raise ValueError("general plan work items require workspace_execution")
            fan_out = item.pop("fan_out", None)
            if fan_out is None:
                expanded.append(item)
                continue
            if not isinstance(fan_out, dict) or fan_out.get("merge_strategy", "collect") != "collect":
                raise ValueError("fan_out only supports merge_strategy=collect")
            count = int(fan_out.get("count") or 0)
            if count < 2 or count > 32:
                raise ValueError("fan_out count must be between 2 and 32")
            base_id = str(item.get("work_item_id") or "")
            shard_ids = [f"{base_id}-shard-{index:02d}" for index in range(1, count + 1)]
            for index, shard_id in enumerate(shard_ids, start=1):
                shard = dict(item)
                shard["work_item_id"] = shard_id
                shard["objective"] = f"{item.get('objective', '')}（分片 {index}/{count}）"
                expanded.append(shard)
            expanded.append(
                {
                    **item,
                    "work_item_id": f"{base_id}-merge",
                    "objective": (
                        f"汇总 {count} 个分片产物；使用 artifact_fetch 拉取全部输出后按 collect 策略合并。"
                    ),
                    "depends_on": shard_ids,
                }
            )
        seen_ids: set[str] = set()
        workspace_targets = self._workspace_execution_targets()
        for item in expanded:
            work_item_id = str(item.get("work_item_id") or "")
            target = item.get("target")
            if not work_item_id or work_item_id in seen_ids:
                raise ValueError("general plan work item ids must be unique")
            if target not in workspace_targets:
                raise ValueError("general plan work item target is not allowed")
            if not str(item.get("objective") or "") or not str(item.get("skill_name") or ""):
                raise ValueError("general plan work item lacks objective or skill_name")
            seen_ids.add(work_item_id)
        return {
            "name": str(proposed_submission.get("name") or "general-analysis"),
            "parameters": {"work_items": expanded},
            "quality_gate_required": bool(
                proposed_submission.get("quality_gate_required", False)
            ),
        }

    @staticmethod
    def _planner_for_flow(flow_id: str) -> str:
        normalized = flow_id.lower()
        if "scrna" in normalized:
            return "agent-scrna"
        if "rna" in normalized:
            return "agent-rnaseq"
        return "agent-code"

    @staticmethod
    def _plan_hash(payload: dict[str, Any]) -> str:
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode()).hexdigest()

    async def get_case(self, case_id: str, actor: str) -> CaseRecord:
        case = await self._cases.get(case_id)
        self._require_case_access(case, actor)
        return case

    async def get_manifest(self, case_id: str, actor: str) -> dict[str, Any]:
        case = await self.get_case(case_id, actor)
        if not case.manifest_uri:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manifest not found")
        manifest_path = Path(case.manifest_uri).resolve()
        manifest_root = Path(self._settings.manifest_dir).resolve()
        try:
            manifest_path.relative_to(manifest_root)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Manifest path is invalid"
            ) from exc
        if not manifest_path.is_file():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Manifest not found")
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Manifest is unreadable"
            ) from exc
        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Manifest payload is invalid",
            )
        return payload

    async def get_case_view(self, case_id: str, actor: str) -> dict[str, Any]:
        case = await self.get_case(case_id, actor)
        if actor == "bioops-manager":
            return case.model_dump(mode="json")
        return {
            "case_id": case.case_id,
            "project_ref": case.project_ref.model_dump(mode="json") if case.project_ref else None,
            "context_refs": [ref.model_dump(mode="json") for ref in self._case_context_refs(case)],
            "intent": case.intent,
            "team_id": case.team_id,
            "origin_consultation_id": case.origin_consultation_id,
            "consultation_summary": case.consultation_summary,
            "status": case.status,
            "omic_task_ids": case.omic_task_ids,
            "quality_decision": case.quality_decision,
            "manifest_uri": case.manifest_uri,
            "work_items": [
                work_item.model_dump(mode="json")
                for work_item in case.work_items
                if work_item.target == actor
            ],
            "created_at": case.created_at.isoformat(),
            "updated_at": case.updated_at.isoformat(),
        }

    async def list_worker_inbox(self, actor: str) -> WorkerInboxResponse:
        if actor in self._external_workers():
            self._worker_last_poll[actor] = datetime.now(UTC)
        assignments, sweep = await self._cases.list_assigned_work_items(
            actor, {"pending", "claimed", "running", "in_progress"}
        )
        await self._record_sweep(sweep, actor="bioops-manager")
        items = [
            WorkerInboxItem(
                case_id=case.case_id,
                project_ref=case.project_ref,
                context_refs=self._case_context_refs(case),
                intent=case.intent,
                status=case.status,
                omic_task_ids=case.omic_task_ids,
                quality_decision=case.quality_decision,
                work_item=work_item,
            )
            for case, work_item in assignments
        ]
        return WorkerInboxResponse(items=items, total=len(items))

    async def sweep_work_items(self, actor: str = "bioops-manager") -> dict[str, int]:
        """Watchdog sweep: reclaim lost Workers' leases without waiting for inbox polls."""
        sweep = await self._cases.sweep_expired_work_items()
        await self._record_sweep(sweep, actor=actor)
        return {
            "requeued": len(sweep[0]),
            "timed_out": len(sweep[1]),
            "retry_promoted": len(sweep[2]),
        }

    async def _record_sweep(self, sweep: Any, *, actor: str) -> None:
        """Write timeline/room-visible audit events for one store-level sweep."""
        expired, timed_out, retryable = sweep
        for case_id, expired_item in expired:
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="work_item.lease_expired",
                payload={
                    "work_item_id": expired_item.work_item_id,
                    "skill_name": expired_item.skill_name,
                    "previous_status": expired_item.status,
                    "lease_owner": expired_item.lease_owner,
                    "attempt": expired_item.attempt,
                    "max_attempts": expired_item.max_attempts,
                    "lease_expires_at": (
                        expired_item.lease_expires_at.isoformat()
                        if expired_item.lease_expires_at
                        else None
                    ),
                    "action": "requeued",
                    "trace_id": expired_item.trace_id,
                    "summary": (
                        f"工作项 {expired_item.work_item_id} 的 Worker "
                        f"（{expired_item.lease_owner or expired_item.target}）心跳超时，"
                        f"任务已回收并将重新派发（第 {expired_item.attempt}/"
                        f"{expired_item.max_attempts} 次尝试）。"
                    ),
                },
            )
        for case_id, work_item_id in retryable:
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="work_item.retry_requeued",
                payload={
                    "work_item_id": work_item_id,
                    "action": "requeued",
                    "summary": f"工作项 {work_item_id} 已到重试时间，已重新进入待派发队列。",
                },
            )
        for case_id, timed_out_item in timed_out:
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="work_item.timeout",
                payload={
                    "work_item_id": timed_out_item.work_item_id,
                    "skill_name": timed_out_item.skill_name,
                    "lease_owner": timed_out_item.lease_owner,
                    "attempt": timed_out_item.attempt,
                    "max_attempts": timed_out_item.max_attempts,
                    "trace_id": timed_out_item.trace_id,
                    "summary": (
                        f"工作项 {timed_out_item.work_item_id} 多次失联，"
                        f"重试预算（{timed_out_item.max_attempts} 次）已耗尽，判定超时终止。"
                    ),
                },
            )
            await self._cascade_skip(case_id, timed_out_item, actor)
            await self._auto_reconcile(case_id)

    async def _cascade_skip(self, case_id: str, dead_item: WorkItemRecord, actor: str) -> None:
        """Mark every not-yet-started dependent of a dead work item as skipped, loudly."""
        skipped = await self._cases.skip_dependents(
            case_id,
            dead_item.work_item_id,
            f"上游 {dead_item.work_item_id} 已终止（{dead_item.status}）",
        )
        for skipped_item in skipped:
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="work_item.skipped",
                payload={
                    "work_item_id": skipped_item.work_item_id,
                    "skill_name": skipped_item.skill_name,
                    "target": skipped_item.target,
                    "cause_work_item_id": dead_item.work_item_id,
                    "summary": (
                        f"工作项 {skipped_item.work_item_id} 因上游 "
                        f"{dead_item.work_item_id} 不可恢复而被跳过；"
                        "如需继续，请人工重试上游或终止 Case。"
                    ),
                },
            )

    async def list_cases(
        self,
        requester_ref: str | None = None,
        *,
        case_status: str | None = None,
        project_id: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> CaseListResponse:
        cases = await self._cases.list(requester_ref)
        # 房间命名空间记录是内部事件流载体，不作为用户 Case 暴露。
        cases = [case for case in cases if case.record_kind == "case"]
        if case_status is not None:
            cases = [case for case in cases if case.status == case_status]
        if project_id is not None:
            cases = [
                case for case in cases if case.project_ref and case.project_ref.id == project_id
            ]
        total = len(cases)
        if cursor is not None:
            try:
                start = (
                    next(index for index, case in enumerate(cases) if case.case_id == cursor) + 1
                )
            except StopIteration:
                raise HTTPException(status_code=422, detail="Invalid Case cursor") from None
            cases = cases[start:]
        items = cases[:limit]
        next_cursor = items[-1].case_id if len(cases) > len(items) else None
        return CaseListResponse(items=items, total=total, next_cursor=next_cursor)

    async def update_case_state(
        self, case_id: str, request: CaseStateUpdate, actor: str
    ) -> CaseRecord:
        case = await self._cases.transition(case_id, request.status)
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="case.state_changed",
            payload={
                "status": request.status,
                "reason": request.reason,
                "work_item_id": request.work_item_id,
            },
        )
        return case

    async def get_case_events(
        self, case_id: str, actor: str, *, cursor: str | None = None, limit: int = 100
    ) -> CaseEventResponse:
        case = await self._cases.get(case_id)
        self._require_case_access(case, actor)
        # B1：立项确认卡 confirm_token 在事件流出口一律脱敏（含 pending 卡）。
        events = redact_proposal_confirm_tokens(await self._audit.list_events(case_id))
        if cursor is not None:
            try:
                start = (
                    next(index for index, event in enumerate(events) if event["event_id"] == cursor)
                    + 1
                )
            except StopIteration:
                raise HTTPException(status_code=422, detail="Invalid event cursor") from None
            events = events[start:]
        items = events[:limit]
        next_cursor = items[-1]["event_id"] if len(events) > len(items) else None
        return CaseEventResponse(case_id=case_id, events=items, next_cursor=next_cursor)

    async def stream_case_events(
        self,
        case_id: str,
        actor: str,
        *,
        cursor: str | None = None,
        watch_seconds: int = 60,
    ) -> AsyncIterator[dict[str, Any]]:
        """Native bounded stream of newly recorded Bridge audit events."""
        await self.get_case(case_id, actor)
        next_cursor = cursor
        loop = asyncio.get_running_loop()
        deadline = loop.time() + max(1, watch_seconds)
        while loop.time() < deadline:
            page = await self.get_case_events(case_id, actor, cursor=next_cursor, limit=100)
            for event in page.events:
                yield event
            if page.events:
                next_cursor = page.events[-1]["event_id"]
            await asyncio.sleep(0.1)

    async def metrics(self) -> dict[str, int]:
        return await self._audit.metrics()

    async def worker_health(self) -> dict[str, Any]:
        now = datetime.now(UTC)
        configured_identities = self._settings.identity_secrets()
        external_workers = self._external_workers()
        workers = []
        for worker in sorted(external_workers):
            last_seen = self._worker_last_poll.get(worker)
            age_seconds = int((now - last_seen).total_seconds()) if last_seen else None
            configured = worker in configured_identities
            active = bool(
                configured
                and age_seconds is not None
                and age_seconds <= self._settings.worker_heartbeat_ttl_seconds
            )
            workers.append(
                {
                    "identity": worker,
                    "configured": configured,
                    "active": active,
                    "last_seen_at": last_seen.isoformat() if last_seen else None,
                    "age_seconds": age_seconds,
                }
            )
        return {
            "allowed_flows": sorted(self._settings.allowed_flows()),
            "worker_heartbeat_ttl_seconds": self._settings.worker_heartbeat_ttl_seconds,
            "workers": workers,
        }

    async def list_flows(self) -> dict[str, Any]:
        flows = await self._client.list_flows()
        items = flows.get("items", [])
        if not isinstance(items, list):
            raise HTTPException(status_code=502, detail="OmicHub returned malformed flow list")
        allowed = self._settings.allowed_flows()
        flows["items"] = [
            item for item in items if isinstance(item, dict) and item.get("id") in allowed
        ]
        flows["total"] = len(flows["items"])
        return flows

    async def preflight(self, request: PreflightRequest, actor: str) -> PreflightResponse:
        findings = []
        consultation_summary = " ".join(str(request.consultation_summary or "").split())
        if consultation_summary:
            findings.append(
                (
                    "CONSULTATION_CONTEXT",
                    "info",
                    f"预检已引用会诊纪要：{consultation_summary[:300]}",
                )
            )
        if request.flow_id not in self._settings.allowed_flows():
            findings.append(("FLOW_NOT_ALLOWED", "error", "请求的流程不在 Bridge 白名单中。"))
        if not request.sample_sheet:
            findings.append(("MISSING_SAMPLE_SHEET", "error", "提交前必须提供样本表引用或内容。"))
        elif any(not row.get("sample") for row in request.sample_sheet):
            findings.append(("MISSING_SAMPLE", "error", "样本表存在缺少 sample 字段的记录。"))
        if request.comparisons is not None and any(
            not comparison.get("control") or not comparison.get("treatment")
            for comparison in request.comparisons
        ):
            findings.append(
                ("INVALID_COMPARISON", "error", "comparison 必须同时包含 control 和 treatment。")
            )
        has_errors = any(item[1] == "error" for item in findings)
        response = PreflightResponse(
            case_id=request.case_id,
            status="blocked" if has_errors else "passed",
            findings=[
                {
                    "code": code,
                    "severity": severity,
                    "message": message,
                    "evidence_refs": request.context_refs,
                }
                for code, severity, message in findings
            ],
            next_actions=["request_user_correction"]
            if has_errors
            else ["request_submission_approval"],
        )
        case = await self._cases.get(request.case_id)
        if case.status == "preflight_blocked":
            await self._cases.transition(request.case_id, "waiting_for_correction")
            case = await self._cases.get(request.case_id)
        if case.status in {"received", "waiting_for_correction"}:
            await self._cases.transition(request.case_id, "preflight_running")
        await self._cases.save_preflight_input(
            request.case_id,
            None
            if has_errors
            else PreflightInputSnapshot(
                flow_id=request.flow_id,
                sample_sheet=request.sample_sheet,
                comparisons=request.comparisons,
                context_refs=request.context_refs,
                consultation_summary=request.consultation_summary,
            ),
        )
        if not has_errors and not case.plan_hash:
            if request.flow_id not in self._settings.discovered_flow_quality_gate_map:
                await self.refresh_capabilities()
            legacy_task = TaskSpec(
                flow_id=request.flow_id,
                name=case.intent[:128],
                sample_sheet=request.sample_sheet,
                comparisons=request.comparisons,
                execution_mode="cluster",
                quality_gate_required=self._settings.quality_gate_for_flow(request.flow_id),
            )
            legacy_payload = legacy_task.model_dump(mode="json")
            await self._cases.save_plan(
                request.case_id,
                legacy_payload,
                self._plan_hash(legacy_payload),
                PreflightInputSnapshot(
                    flow_id=request.flow_id,
                    sample_sheet=request.sample_sheet,
                    comparisons=request.comparisons,
                    context_refs=request.context_refs,
                    consultation_summary=request.consultation_summary,
                ),
            )
        await self._cases.transition(
            request.case_id,
            "preflight_blocked" if has_errors else "approval_pending",
        )
        await self._audit.record(
            case_id=request.case_id,
            actor=actor,
            event_type="skill.finished",
            payload={
                "skill_name": "project-preflight",
                "status": response.status,
                "finding_count": len(findings),
                "summary": (
                    "预检已引用会诊纪要并通过。"
                    if consultation_summary and not has_errors
                    else "预检已引用会诊纪要，但仍需修正输入问题。"
                    if consultation_summary
                    else "预检已通过。"
                    if not has_errors
                    else "预检发现需要修正的输入问题。"
                ),
                "findings": response.findings,
            },
        )
        if request.work_item_id:
            await self._update_bound_work_item(
                request.case_id,
                request.work_item_id,
                actor,
                work_item_status="blocked" if has_errors else "completed",
                summary=response.next_actions[0],
                findings=response.findings,
            )
        return response

    async def issue_approval(self, request: ApprovalRequest, actor: str) -> ApprovalResponse:
        case = await self._cases.get(request.case_id)
        if request.action == "submit_task" and case.status not in {
            "approval_pending",
            "execution_failed",
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Task submission approval requires a passed preflight",
            )
        if request.action == "submit_task" and not case.plan_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Task submission approval requires a frozen plan hash",
            )
        if request.action == "submit_task" and (
            case.preflight_input is None or case.preflight_input.flow_id != request.flow_id
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Task submission approval requires a matching preflight input snapshot",
            )
        if request.action == "execute_plan" and (
            case.status != "approval_pending" or case.flow_id or not case.plan_hash
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="General plan execution approval requires a frozen general plan",
            )
        if request.action == "cancel_task" and request.task_id not in case.omic_task_ids:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Task does not belong to the Case",
            )
        token, approval_id, expires_at = self._approval_signer.issue(
            case_id=request.case_id,
            action=request.action,
            work_item_id=request.work_item_id,
            flow_id=request.flow_id,
            task_id=request.task_id,
            plan_hash=case.plan_hash,
            ttl_seconds=request.ttl_seconds,
        )
        await self._audit.record(
            case_id=request.case_id,
            actor=actor,
            event_type="approval.resolved",
            payload={
                "approval_id": approval_id,
                "action": request.action,
                "work_item_id": request.work_item_id,
                "plan_hash": case.plan_hash,
                "expires_at": expires_at.isoformat(),
            },
        )
        return ApprovalResponse(approval_id=approval_id, token=token, expires_at=expires_at)

    async def execute_general_plan(
        self, case_id: str, approval_token: str, actor: str
    ) -> CaseRecord:
        case = await self._cases.get(case_id)
        self._approval_signer.verify(
            approval_token, case_id=case_id, action="execute_plan", plan_hash=case.plan_hash
        )
        if case.status != "approval_pending" or case.flow_id or not case.plan_hash:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="General plan is not ready"
            )
        parameters = (case.proposed_submission or {}).get("parameters")
        work_items = parameters.get("work_items") if isinstance(parameters, dict) else None
        if not isinstance(work_items, list):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Frozen general plan has no task DAG"
            )
        case = await self._cases.transition(case_id, "approved")
        workspace_targets = self._workspace_execution_targets()
        for item in work_items:
            execution_mode = str(item.get("execution_mode") or "workspace_execution")
            target = str(item["target"])
            if execution_mode == "workspace_execution" and target not in workspace_targets:
                # Registry declaration changed after the plan was frozen: degrade the
                # work item to read-only instead of permitting undeclared execution.
                execution_mode = "readonly_consultation"
                await self._audit.record(
                    case_id=case_id,
                    actor=actor,
                    event_type="planning.validation_failed",
                    payload={
                        "error": (
                            f"execution_mode downgraded: {target} does not declare "
                            "workspace_execution"
                        ),
                        "work_item_id": str(item["work_item_id"]),
                        "target": target,
                    },
                )
            retry_decl = item.get("retry") if isinstance(item.get("retry"), dict) else {}
            try:
                max_attempts = min(max(int(retry_decl.get("max_attempts") or 3), 1), 10)
            except (TypeError, ValueError):
                max_attempts = 3
            backoff_seconds: int | None
            try:
                raw_backoff = retry_decl.get("backoff_seconds")
                backoff_seconds = min(max(int(raw_backoff), 1), 86_400) if raw_backoff else None
            except (TypeError, ValueError):
                backoff_seconds = None
            try:
                raw_timeout = item.get("timeout_seconds")
                deadline_seconds = min(max(int(raw_timeout), 1), 86_400) if raw_timeout else 300
            except (TypeError, ValueError):
                deadline_seconds = 300
            await self._ensure_work_item(
                case,
                WorkItemRecord(
                    work_item_id=str(item["work_item_id"]),
                    target=target,
                    objective=str(item["objective"]),
                    skill_name=str(item["skill_name"]),
                    context_refs=self._case_context_refs(case),
                    read_only=execution_mode != "workspace_execution",
                    execution_mode=execution_mode,
                    plan_hash=case.plan_hash,
                    plan_version=case.plan_version,
                    depends_on=[str(value) for value in item.get("depends_on") or []],
                    max_attempts=max_attempts,
                    retry_backoff_seconds=backoff_seconds,
                    deadline_seconds=deadline_seconds,
                    updated_at=datetime.now(UTC),
                ),
                actor,
            )
        case = await self._cases.get(case_id)
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="general_plan.approved",
            payload={"plan_hash": case.plan_hash, "work_item_count": len(work_items)},
        )
        return case

    async def revise_plan(
        self, case_id: str, request: PlanRevisionRequest, actor: str
    ) -> PlanRevisionResponse:
        case = await self._cases.get(case_id)
        self._require_case_access(case, actor)
        if case.status not in {
            "approval_pending",
            "execution_failed",
            "quality_blocked",
            "remediation_pending",
        }:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Case plan cannot be revised in its current status",
            )
        if not case.plan_hash or not isinstance(case.proposed_submission, dict):
            raise HTTPException(status_code=409, detail="Case has no frozen plan")
        if request.expected_plan_hash != case.plan_hash:
            raise HTTPException(status_code=409, detail="Plan hash changed; refresh before editing")
        if case.plan_revision_count >= 5 and not request.override_revision_limit:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "PLAN_REVISION_LIMIT_REACHED",
                    "message": "计划已修订 5 轮，请由用户决定继续修订、更换 lead planner 或取消 Case。",
                    "revision_count": case.plan_revision_count,
                    "options": ["continue_revision", "replace_lead_planner", "cancel_case"],
                },
            )
        current_parameters = case.proposed_submission.get("parameters")
        if not isinstance(current_parameters, dict):
            current_parameters = {}
        revised = dict(case.proposed_submission)
        revised["parameters"] = request.parameters
        if case.flow_id:
            validated = TaskSpec.model_validate(revised).model_dump(mode="json")
        else:
            validated = self._validate_general_plan(revised)
        new_hash = self._plan_hash(validated)
        changed_keys = sorted(
            key
            for key in set(current_parameters) | set(request.parameters)
            if current_parameters.get(key) != request.parameters.get(key)
        )
        if new_hash == case.plan_hash:
            return PlanRevisionResponse(
                case_id=case_id,
                previous_plan_hash=case.plan_hash,
                plan_hash=case.plan_hash,
                previous_plan_version=case.plan_version,
                plan_version=case.plan_version,
                revision_count=case.plan_revision_count,
                changed_parameter_keys=[],
                replay_work_item_ids=[],
                status=case.status,
            )
        replay_ids = self._plan_replay_work_items(case, validated)
        previous_hash = case.plan_hash
        revised_case = await self._cases.revise_plan(case_id, validated, new_hash, replay_ids)
        if revised_case.status != "approval_pending":
            revised_case = await self._cases.transition(case_id, "approval_pending")
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="planning.revised",
            payload={
                "previous_plan_hash": previous_hash,
                "plan_hash": new_hash,
                "previous_plan_version": case.plan_version,
                "plan_version": revised_case.plan_version,
                "revision_count": revised_case.plan_revision_count,
                "changed_parameter_keys": changed_keys,
                "replay_work_item_ids": sorted(replay_ids),
                "reason": request.reason,
            },
        )
        return PlanRevisionResponse(
            case_id=case_id,
            previous_plan_hash=previous_hash,
            plan_hash=new_hash,
            previous_plan_version=case.plan_version,
            plan_version=revised_case.plan_version,
            revision_count=revised_case.plan_revision_count,
            changed_parameter_keys=changed_keys,
            replay_work_item_ids=sorted(replay_ids),
            status=revised_case.status,
        )

    @staticmethod
    def _plan_replay_work_items(case: CaseRecord, revised: dict[str, Any]) -> set[str]:
        if case.flow_id:
            return {"submit-next"}
        old_items = {
            str(item.get("work_item_id")): item
            for item in ((case.proposed_submission or {}).get("parameters") or {}).get("work_items", [])
            if isinstance(item, dict) and item.get("work_item_id")
        }
        new_items = {
            str(item.get("work_item_id")): item
            for item in (revised.get("parameters") or {}).get("work_items", [])
            if isinstance(item, dict) and item.get("work_item_id")
        }
        changed = {
            work_item_id
            for work_item_id in set(old_items) | set(new_items)
            if old_items.get(work_item_id) != new_items.get(work_item_id)
        }
        expanded = set(changed)
        while True:
            dependents = {
                work_item_id
                for work_item_id, item in new_items.items()
                if set(item.get("depends_on") or []) & expanded
            }
            if dependents <= expanded:
                return expanded
            expanded.update(dependents)

    async def submit_task(self, request: SubmitTaskRequest, actor: str) -> TaskReceipt:
        if request.task.flow_id not in self._settings.allowed_flows():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Flow is not allowed")
        case = await self._cases.get(request.case_id)
        self._approval_signer.verify(
            request.approval_token,
            case_id=request.case_id,
            action="submit_task",
            flow_id=request.task.flow_id,
            plan_hash=case.plan_hash,
        )
        if not case.plan_hash or case.proposed_submission is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Approved submission requires a frozen plan hash",
            )
        if case.flow_id and request.task.model_dump(mode="json") != case.proposed_submission:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Task differs from the frozen proposed submission",
            )
        return await self._submit_verified_task(
            case=case,
            work_item_id=request.work_item_id,
            idempotency_key=request.idempotency_key,
            task=request.task,
            actor=actor,
        )

    async def queue_approved_submission(
        self, request: QueueApprovedSubmissionRequest, actor: str
    ) -> QueueApprovedSubmissionResponse:
        if request.task.execution_mode != "cluster":
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Queued analysis submissions must use cluster execution mode",
            )
        if request.task.flow_id not in self._settings.allowed_flows():
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Flow is not allowed")
        case = await self._cases.get(request.case_id)
        claims = self._approval_signer.verify(
            request.approval_token,
            case_id=request.case_id,
            action="submit_task",
            work_item_id=request.work_item_id,
            flow_id=request.task.flow_id,
            plan_hash=case.plan_hash,
        )
        self._validate_task_snapshot(case, request.task)
        work_item = await self._cases.get_work_item(request.case_id, request.work_item_id)
        if (
            work_item.target != "analysis-worker"
            or work_item.read_only
            or not work_item.approval_required
        ):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Approved submissions require an analysis-worker approval-gated Work Item",
            )
        existing = work_item.approved_submission
        if existing is not None:
            if existing.idempotency_key != request.idempotency_key:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Work item already has a different approved submission",
                )
            return QueueApprovedSubmissionResponse(
                case_id=request.case_id,
                work_item_id=request.work_item_id,
                approval_id=existing.approval_id,
                status="idempotent_replay",
                expires_at=existing.expires_at,
            )
        expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
        snapshot = case.preflight_input
        if snapshot is None:  # guarded by _validate_task_snapshot; retained for type narrowing
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Preflight snapshot is missing"
            )
        prepared = ApprovedSubmission(
            approval_id=str(claims["approval_id"]),
            expires_at=expires_at,
            idempotency_key=request.idempotency_key,
            task=request.task,
            input_snapshot_hash=self._snapshot_hash(snapshot),
            prepared_at=datetime.now(UTC),
        )
        await self._cases.update_work_item(
            request.case_id,
            request.work_item_id,
            work_item.model_copy(
                update={"approved_submission": prepared, "updated_at": datetime.now(UTC)}
            ),
        )
        if case.status == "approval_pending":
            await self._cases.transition(request.case_id, "approved")
        await self._audit.record(
            case_id=request.case_id,
            actor=actor,
            event_type="approval.submission_queued",
            payload={
                "work_item_id": request.work_item_id,
                "approval_id": prepared.approval_id,
                "flow_id": request.task.flow_id,
                "idempotency_key": request.idempotency_key,
                "expires_at": prepared.expires_at.isoformat(),
                "plan_hash": case.plan_hash,
            },
        )
        return QueueApprovedSubmissionResponse(
            case_id=request.case_id,
            work_item_id=request.work_item_id,
            approval_id=prepared.approval_id,
            status="queued",
            expires_at=prepared.expires_at,
        )

    async def retry_case_submission(
        self,
        case_id: str,
        request: RetryCaseSubmissionRequest,
        actor: str,
    ) -> QueueApprovedSubmissionResponse:
        case = await self._cases.get(case_id)
        if case.status != "execution_failed":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Only failed Case submissions may be retried",
            )
        previous = next(
            (
                item
                for item in reversed(case.work_items)
                if item.target == "analysis-worker" and item.approved_submission is not None
            ),
            None,
        )
        if previous is None or previous.approved_submission is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Failed Case has no approved submission to retry",
            )
        task = previous.approved_submission.task
        claims = self._approval_signer.verify(
            request.approval_token,
            case_id=case_id,
            action="submit_task",
            flow_id=task.flow_id,
            plan_hash=case.plan_hash,
        )
        self._validate_task_snapshot(case, task)
        version = len(case.task_specs) + 1
        work_item_id = f"submit-{version:02d}"
        idempotency_key = f"{case_id}-submit-v{version}"
        existing = next(
            (item for item in case.work_items if item.work_item_id == work_item_id),
            None,
        )
        if existing is not None and existing.approved_submission is not None:
            approved = existing.approved_submission
            return QueueApprovedSubmissionResponse(
                case_id=case_id,
                work_item_id=work_item_id,
                approval_id=approved.approval_id,
                status="idempotent_replay",
                expires_at=approved.expires_at,
            )
        snapshot = case.preflight_input
        if snapshot is None:  # guarded by _validate_task_snapshot
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Preflight snapshot is missing",
            )
        expires_at = datetime.fromtimestamp(int(claims["exp"]), tz=UTC)
        approved = ApprovedSubmission(
            approval_id=str(claims["approval_id"]),
            expires_at=expires_at,
            idempotency_key=idempotency_key,
            task=task,
            input_snapshot_hash=self._snapshot_hash(snapshot),
            prepared_at=datetime.now(UTC),
        )
        retry_item = WorkItemRecord(
            work_item_id=work_item_id,
            parent_work_item_id=previous.work_item_id,
            target="analysis-worker",
            objective="重试已获人工批准且保持冻结输入不变的 OmicHub 分析任务。",
            skill_name="workflow-submit",
            context_refs=self._case_context_refs(case),
            read_only=False,
            approval_required=True,
            idempotency_key=idempotency_key,
            approved_submission=approved,
            depends_on=[previous.work_item_id],
            updated_at=datetime.now(UTC),
        )
        await self._cases.add_work_item(case_id, retry_item)
        await self._cases.transition(case_id, "remediation_pending")
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="case.retry_queued",
            payload={
                "work_item_id": work_item_id,
                "previous_work_item_id": previous.work_item_id,
                "approval_id": approved.approval_id,
                "flow_id": task.flow_id,
                "idempotency_key": idempotency_key,
                "plan_hash": case.plan_hash,
            },
        )
        return QueueApprovedSubmissionResponse(
            case_id=case_id,
            work_item_id=work_item_id,
            approval_id=approved.approval_id,
            status="queued",
            expires_at=approved.expires_at,
        )

    async def submit_approved_work_item(
        self, case_id: str, work_item_id: str, actor: str
    ) -> TaskReceipt:
        work_item = await self._cases.get_work_item(case_id, work_item_id)
        if actor != "analysis-worker" or work_item.target != actor:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Work item target mismatch"
            )
        approved = work_item.approved_submission
        if approved is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Work item has no approved submission"
            )
        if approved.expires_at <= datetime.now(UTC):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Approved submission has expired"
            )
        if work_item.status == "claimed":
            work_item = await self._cases.transition_work_item(
                case_id, work_item_id, actor, "running", trace_id=work_item.trace_id
            )
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="work_item.running",
                payload={
                    "work_item_id": work_item_id,
                    "trace_id": work_item.trace_id,
                    "status_line": self._work_item_status_line(work_item, "running"),
                },
            )
        if work_item.status != "running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Approved submission Work Item must be claimed before execution",
            )
        work_item = await self._cases.begin_approved_submission(case_id, work_item_id, actor)
        approved = work_item.approved_submission
        if approved is None:  # pragma: no cover - guarded by begin_approved_submission
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Work item has no approved submission"
            )
        case = await self._cases.get(case_id)
        try:
            receipt = await self._submit_verified_task(
                case=case,
                work_item_id=work_item_id,
                idempotency_key=approved.idempotency_key,
                task=approved.task,
                actor=actor,
            )
        except Exception as exc:
            await self._cases.transition_work_item(
                case_id,
                work_item_id,
                actor,
                "failed",
                summary=f"Analysis submission failed: {exc}"[:4000],
            )
            await self._cases.reset_approved_submission_start(case_id, work_item_id, actor)
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="analysis_submission.failed",
                payload={"work_item_id": work_item_id, "error": str(exc)[:500]},
            )
            raise
        completed = await self._cases.get_work_item(case_id, work_item_id)
        completed_approval = completed.approved_submission
        if completed_approval is not None:
            await self._cases.update_work_item(
                case_id,
                work_item_id,
                completed.model_copy(
                    update={
                        "approved_submission": completed_approval.model_copy(
                            update={"consumed_at": datetime.now(UTC)}
                        ),
                        "updated_at": datetime.now(UTC),
                    }
                ),
            )
        return receipt

    async def _submit_verified_task(
        self,
        *,
        case: CaseRecord,
        work_item_id: str | None,
        idempotency_key: str,
        task: TaskSpec,
        actor: str,
    ) -> TaskReceipt:
        self._validate_task_snapshot(case, task)
        prior = await self._audit.get_receipt(idempotency_key)
        if prior is not None:
            return TaskReceipt(**prior).model_copy(update={"idempotent_replay": True})
        task_data = await self._client.submit_task(task.model_dump())
        omic_task_id = str(task_data.get("id", ""))
        if not omic_task_id:
            raise HTTPException(status_code=502, detail="OmicHub submit response has no task ID")
        receipt = TaskReceipt(
            case_id=case.case_id,
            omic_task_id=omic_task_id,
            status=str(task_data.get("status", "submitted")),
            submitted_at=datetime.now(UTC),
        )
        await self._audit.save_receipt(idempotency_key, receipt.model_dump(mode="json"))
        await self._cases.attach_task(case.case_id, omic_task_id, task.model_dump(mode="json"))
        if case.status == "approval_pending":
            await self._cases.transition(case.case_id, "approved")
            await self._cases.transition(case.case_id, "executing")
        elif case.status in {"approved", "remediation_pending"}:
            await self._cases.transition(case.case_id, "executing")
        if case.flow_id:
            await self._audit.record(
                case_id=case.case_id,
                actor=actor,
                event_type="case.handoff_started",
                payload={
                    "flow_id": task.flow_id,
                    "work_item_ids": [work_item_id] if work_item_id else [],
                    "omic_task_id": omic_task_id,
                    "status": "executing",
                },
            )
        await self._audit.record(
            case_id=case.case_id,
            actor=actor,
            event_type="omic_task.submitted",
            payload={
                "omic_task_id": omic_task_id,
                "flow_id": task.flow_id,
                "idempotency_key": idempotency_key,
                "receipt": receipt.model_dump(mode="json"),
            },
        )
        if work_item_id:
            await self._update_bound_work_item(
                case.case_id,
                work_item_id,
                actor,
                work_item_status="completed",
                summary=f"OmicHub task {omic_task_id} submitted",
            )
        return receipt

    @staticmethod
    def _snapshot_hash(snapshot: PreflightInputSnapshot) -> str:
        payload = json.dumps(snapshot.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _validate_task_snapshot(case: CaseRecord, task: TaskSpec) -> None:
        snapshot = case.preflight_input
        if snapshot is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Task submission requires a passed preflight input snapshot",
            )
        if (
            task.flow_id != snapshot.flow_id
            or task.sample_sheet != snapshot.sample_sheet
            or task.comparisons != snapshot.comparisons
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Task input differs from the approved preflight snapshot",
            )

    async def _ensure_work_item(
        self, case: CaseRecord, work_item: WorkItemRecord, actor: str
    ) -> WorkItemRecord:
        ensured, created = await self._cases.ensure_work_item(case.case_id, work_item)
        if created:
            await self._audit.record(
                case_id=case.case_id,
                actor=actor,
                event_type="work_item.assigned",
                payload={
                    "work_item_id": ensured.work_item_id,
                    "target": ensured.target,
                    "objective": ensured.objective,
                    "skill_name": ensured.skill_name,
                    "context_refs": [ref.model_dump() for ref in ensured.context_refs],
                    "status_line": self._work_item_status_line(ensured, "queued"),
                },
            )
        return ensured

    async def get_task(self, task_id: str, actor: str) -> dict[str, Any]:
        case = await self._cases.get_by_task(task_id)
        self._require_case_access(case, actor)
        task = await self._client.get_task(task_id)
        await self._audit.record(
            case_id=case.case_id,
            actor=actor,
            event_type="omic_task.status_changed",
            payload={"omic_task_id": task_id, "status": task.get("status")},
        )
        return task

    async def get_artifacts(self, task_id: str, actor: str) -> dict[str, Any]:
        case = await self._cases.get_by_task(task_id)
        self._require_case_access(case, actor)
        task = await self._client.get_task(task_id)
        result_available = bool(task.get("result_path")) and task.get("status") == "success"
        artifacts = {
            "task_id": task_id,
            "status": task.get("status"),
            "artifacts": [
                {
                    "kind": "task_result",
                    "uri": f"omic://tasks/{task_id}/result",
                    "available": result_available,
                }
            ]
            if result_available
            else [],
        }
        await self._audit.record(
            case_id=case.case_id,
            actor=actor,
            event_type="skill.finished",
            payload={
                "skill_name": "artifact-inspect",
                "omic_task_id": task_id,
                "artifact_count": len(artifacts["artifacts"]),
            },
        )
        return artifacts

    async def quality_gate(
        self, task_id: str, request: QualityGateRequest, actor: str
    ) -> QualityGateResponse:
        case = await self._cases.get_by_task(task_id)
        if case.case_id != request.case_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Case and task mismatch"
            )
        await self._require_bound_work_item_target(
            case.case_id, request.work_item_id, actor, skill_name="quality-gate"
        )
        if case.status == "executing":
            await self._cases.transition(case.case_id, "quality_running")
            case = await self._cases.get(case.case_id)
        if case.status != "quality_running":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Task is not ready for quality gate"
            )
        decision = QualityGateResponse(
            case_id=case.case_id,
            task_id=task_id,
            decision=request.decision,
            rule_version=request.rule_version,
            summary=request.summary,
            evidence_refs=request.evidence_refs,
            artifact_hashes=request.artifact_hashes,
            recorded_at=datetime.now(UTC),
        )
        await self._cases.set_quality(case.case_id, request.decision)
        next_status = (
            "delivery_ready"
            if request.decision in {"passed", "warning", "manual_review"}
            else "quality_blocked"
        )
        await self._cases.transition(case.case_id, next_status)
        await self._audit.record(
            case_id=case.case_id,
            actor=actor,
            event_type="quality.decision",
            payload=decision.model_dump(mode="json"),
        )
        if request.work_item_id:
            await self._update_bound_work_item(
                case.case_id,
                request.work_item_id,
                actor,
                work_item_status="blocked" if request.decision == "blocked" else "completed",
                summary=request.summary,
            )
        if next_status == "delivery_ready":
            flow_id = case.flow_id or (
                case.preflight_input.flow_id if case.preflight_input else ""
            )
            await self._ensure_work_item(
                await self._cases.get(case.case_id),
                WorkItemRecord(
                    work_item_id="delivery-01",
                    parent_work_item_id=self._existing_work_item_id(
                        await self._cases.get(case.case_id), request.work_item_id
                    ),
                    target=self._standard_work_item_target(flow_id, "delivery", "delivery-reporter"),
                    objective="汇总审批、任务、质量与产物证据，生成交付 manifest 并关闭 Case。",
                    skill_name="delivery-pack",
                    context_refs=[*self._case_context_refs(case), {"kind": "task", "id": task_id}],
                    read_only=True,
                    updated_at=datetime.now(UTC),
                ),
                actor,
            )
        else:
            remediation = request.remediation_request
            target = remediation.target if remediation else self._remediation_target(request.summary)
            objective = (
                remediation.objective
                if remediation
                else f"修复质控阻断项并提供可复核证据：{request.summary[:700]}"
            )
            remediation_id = f"remediate-{1 + sum(item.skill_name == 'remediation-fix' for item in case.work_items):02d}"
            await self._cases.transition(case.case_id, "remediation_pending")
            await self._audit.record(
                case_id=case.case_id,
                actor=actor,
                event_type="remediation.requested",
                payload={
                    "work_item_id": remediation_id,
                    "target": target,
                    "objective": objective,
                    "recommended_changes": remediation.recommended_changes if remediation else [],
                    "quality_work_item_id": request.work_item_id,
                    "task_id": task_id,
                },
            )
            await self._ensure_work_item(
                await self._cases.get(case.case_id),
                WorkItemRecord(
                    work_item_id=remediation_id,
                    parent_work_item_id=self._existing_work_item_id(case, request.work_item_id),
                    target=target,
                    objective=objective,
                    skill_name="remediation-fix",
                    context_refs=[*self._case_context_refs(case), {"kind": "task", "id": task_id}],
                    read_only=True,
                    updated_at=datetime.now(UTC),
                ),
                "bioops-manager",
            )
        return decision

    @staticmethod
    def _remediation_target(summary: str) -> str:
        normalized = summary.lower()
        data_markers = ("sample", "metadata", "group", "input", "样本", "分组", "输入", "元数据")
        return "data-steward" if any(marker in normalized for marker in data_markers) else "workflow-operator"

    async def _update_bound_work_item(
        self,
        case_id: str,
        work_item_id: str,
        actor: str,
        *,
        work_item_status: str,
        summary: str,
        findings: list[Any] | None = None,
    ) -> None:
        work_item = await self._cases.get_work_item(case_id, work_item_id)
        if work_item.target != actor:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Work item target mismatch"
            )
        updated = work_item.model_copy(
            update={
                "status": work_item_status,
                "summary": summary,
                "findings": findings or [],
                "updated_at": datetime.now(UTC),
            }
        )
        await self._cases.update_work_item(case_id, work_item_id, updated)
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="skill.finished" if work_item_status == "completed" else "skill.failed",
            payload={
                "work_item_id": work_item_id,
                "skill_name": work_item.skill_name,
                "status": work_item_status,
                "summary": summary,
            },
        )

    async def close_case(self, request: CaseCloseRequest, actor: str) -> CaseCloseResponse:
        case = await self._cases.get(request.case_id)
        await self._require_delivery_target(case, actor)
        if case.status != "delivery_ready":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Case is not delivery-ready"
            )
        if case.quality_decision != request.quality_decision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Quality decision mismatch"
            )
        events = await self._audit.list_events(case.case_id)
        # 汇总各质量门事件提交的产物 MD5（md5 能力在质量门侧计算并随
        # quality.decision 事件落审计），内嵌进交付 manifest 供接收方核验。
        artifact_checksums: dict[str, str] = {}
        for event in events:
            if event.get("event_type") != "quality.decision":
                continue
            payload = event.get("payload")
            if not isinstance(payload, dict):
                continue
            hashes = payload.get("artifact_hashes")
            if not isinstance(hashes, dict):
                continue
            for path, digest in hashes.items():
                artifact_checksums[str(path)] = str(digest)
        task_snapshots: list[dict[str, Any]] = []
        for task_id in case.omic_task_ids:
            try:
                task_snapshots.append(await self._client.get_task(task_id))
            except Exception as exc:
                task_snapshots.append({"id": task_id, "snapshot_error": type(exc).__name__})
        manifest = {
            "schema_version": "1.0",
            "case": case.model_dump(mode="json"),
            "agent_identities": [
                "bioops-manager",
                "data-steward",
                "workflow-operator",
                "quality-auditor",
                "delivery-reporter",
            ],
            "skill_versions": {
                "project-preflight": "1.0",
                "workflow-submit": "1.0",
                "quality-gate": "1.0",
                "delivery-pack": "1.0",
            },
            "input_refs": [ref.model_dump() for ref in self._case_context_refs(case)],
            "task_ids": case.omic_task_ids,
            "task_specs": case.task_specs,
            "omic_task_snapshots": task_snapshots,
            "quality": {"decision": request.quality_decision},
            "artifact_checksums": artifact_checksums,
            "approval_events": [
                event for event in events if event["event_type"].startswith("approval.")
            ],
            "audit_events": events,
            "remediation_summary": request.remediation_summary,
            "runbook_ref": request.runbook_ref.model_dump() if request.runbook_ref else None,
        }
        manifest_dir = Path(self._settings.manifest_dir)
        manifest_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = manifest_dir / f"{case.case_id}.delivery_manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), "utf-8")
        closed = await self._cases.close(case.case_id, str(manifest_path))
        await self._audit.record(
            case_id=case.case_id,
            actor=actor,
            event_type="case.closed",
            payload={"manifest_uri": str(manifest_path)},
        )
        return CaseCloseResponse(
            case_id=closed.case_id,
            status="closed",
            manifest_uri=str(manifest_path),
            manifest=manifest,
        )

    async def cancel_case(self, case_id: str, request: CaseCancelRequest, actor: str) -> CaseRecord:
        case = await self._cases.get(case_id)
        self._require_case_access(case, actor)
        if case.status in {"closed", "cancelled"}:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Case is already terminal"
            )
        reclaimed_work_items = [
            item.work_item_id
            for item in case.work_items
            if item.status not in {"completed", "cancelled"}
        ]
        cancelled = await self._cases.cancel(case_id)
        await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type="case.cancelled",
            payload={
                "reason": request.reason,
                "previous_status": case.status,
                "reclaimed_work_items": reclaimed_work_items,
                "artifacts_retained": True,
            },
        )
        return cancelled

    async def delete_case(
        self, case_id: str, actor: str, reason: str | None = None
    ) -> dict[str, Any]:
        """Delete a Case together with its audit events.

        Non-terminal cases are cancelled first so assigned work items are
        reclaimed before the record disappears; terminal cases are removed
        directly. Artifacts and delivery manifests on disk are retained.
        """
        case = await self._cases.get(case_id)
        self._require_case_access(case, actor)
        cancelled_before_delete = False
        if case.status not in {"closed", "cancelled"}:
            reclaimed_work_items = [
                item.work_item_id
                for item in case.work_items
                if item.status not in {"completed", "cancelled"}
            ]
            await self._cases.cancel(case_id)
            await self._audit.record(
                case_id=case_id,
                actor=actor,
                event_type="case.cancelled",
                payload={
                    "reason": reason or "Case deleted",
                    "previous_status": case.status,
                    "reclaimed_work_items": reclaimed_work_items,
                    "artifacts_retained": True,
                },
            )
            cancelled_before_delete = True
        deleted_events = await self._audit.delete_events(case_id)
        if not await self._cases.delete(case_id):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Case not found"
            )
        return {
            "case_id": case_id,
            "deleted": True,
            "cancelled_before_delete": cancelled_before_delete,
            "deleted_events": deleted_events,
        }

    @staticmethod
    def _existing_work_item_id(case: CaseRecord, work_item_id: str | None) -> str | None:
        if work_item_id and any(item.work_item_id == work_item_id for item in case.work_items):
            return work_item_id
        return None

    @staticmethod
    def _node_elapsed_seconds(case: CaseRecord) -> float | None:
        """Return seconds since the current node started; None if not recorded (legacy Case)."""
        if case.node_started_at is None:
            return None
        return (datetime.now(UTC) - case.node_started_at).total_seconds()

    @staticmethod
    def _work_item_idempotency_key(case_id: str, request: WorkItemCreateRequest) -> str:
        payload = f"{case_id}:{request.work_item_id}:{request.target}:{request.skill_name}:{request.objective}"
        return f"sha256:{hashlib.sha256(payload.encode()).hexdigest()}"

    @staticmethod
    def _require_case_access(case: CaseRecord, actor: str) -> None:
        if actor == "bioops-manager":
            return
        if any(work_item.target == actor for work_item in case.work_items):
            return
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Case is not assigned to this worker identity",
        )

    async def _require_bound_work_item_target(
        self, case_id: str, work_item_id: str | None, actor: str, *, skill_name: str
    ) -> WorkItemRecord:
        """Authorize an endpoint against its exact configured Work Item target.

        Standard work-item targets are flow-configurable. Checking a fixed Bridge role
        at the HTTP boundary would make a valid YAML override unusable; checking the
        bound item keeps the authorization case-scoped and least-privilege instead.
        """
        if not work_item_id:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="work_item_id is required for this operation",
            )
        work_item = await self._cases.get_work_item(case_id, work_item_id)
        if work_item.skill_name != skill_name or work_item.target != actor:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Work item target mismatch",
            )
        return work_item

    async def _require_delivery_target(self, case: CaseRecord, actor: str) -> WorkItemRecord:
        delivery_item = next(
            (item for item in case.work_items if item.skill_name == "delivery-pack"), None
        )
        if delivery_item is None or delivery_item.target != actor:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Case is not assigned to this delivery worker identity",
            )
        return delivery_item

    async def cancel_task(
        self, task_id: str, request: CancelTaskRequest, actor: str
    ) -> dict[str, Any]:
        case = await self._cases.get_by_task(task_id)
        self._require_case_access(case, actor)
        if case.case_id != request.case_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Case and task mismatch"
            )
        self._approval_signer.verify(
            request.approval_token,
            case_id=request.case_id,
            action="cancel_task",
            task_id=task_id,
            plan_hash=case.plan_hash,
        )
        task = await self._client.cancel_task(task_id)
        if case.status not in {"closed", "cancelled"}:
            await self._cases.transition(case.case_id, "cancelled")
        await self._audit.record(
            case_id=request.case_id,
            actor=actor,
            event_type="omic_task.cancelled",
            payload={
                "omic_task_id": task_id,
                "reason": request.reason,
                "status": task.get("status"),
            },
        )
        return task

    async def record_evidence(
        self, case_id: str, request: EvidenceRequest, actor: str
    ) -> EvidenceResponse:
        """Record an evidence event; identity-scoped to close the audit-forgery surface (B2).

        口径（手册阶段 0 修复 2 的落地细化，注释即口径）：
        - 平台身份（bioops-manager / workflow-operator）：允许写业务事件；
          显式携带 ``causation_event_id`` 时强制校验锚点存在于本 Case 事件流，
          悬空引用一律 422。合法的根事件（room.user_message、room.created 等）
          天然无因果锚点，允许缺省——平台身份本身是审计写入的信任根，
          对其强制自锚不增加抗伪造能力。
        - Worker 身份：必须是目标 work item 的 target 且持有有效租约
          （或工作项尚未被他人租用、处于可认领状态）；只能写 Worker 域事件，
          平台保留命名空间（approval.*/room.*/case.*/planning.* 等，见
          ``_PLATFORM_RESERVED_EVENT_PREFIXES``）一律 403，杜绝伪造审批/
          立项卡/任务提交等业务事件；因果锚点强制存在——显式携带时校验存在性，
          缺省时由 Bridge 回填为该工作项最近一条生命周期事件
          （work_item.assigned 必然存在）。
        """
        case = await self._cases.get(case_id)
        inner_payload = request.payload if isinstance(request.payload, dict) else {}
        supplied_anchor = inner_payload.get("causation_event_id")
        if not isinstance(supplied_anchor, str) or not supplied_anchor.strip():
            supplied_anchor = None
        if actor in _PLATFORM_EVIDENCE_IDENTITIES:
            if actor == "bioops-manager" and request.work_item_id == CASE_LEVEL_WORK_ITEM_ID:
                # Case 级事件（房间绑定、用户发言等）不挂在任何工作项上。
                pass
            else:
                await self._cases.get_work_item(case_id, request.work_item_id)
            if supplied_anchor is not None:
                await self._require_existing_event(case_id, supplied_anchor)
        else:
            self._require_case_access(case, actor)
            work_item = await self._cases.get_work_item(case_id, request.work_item_id)
            if work_item.target != actor:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Identity cannot record evidence for this work item",
                )
            if _is_platform_reserved_event_type(request.event_type):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Worker identities cannot record platform-domain evidence events",
                )
            self._require_evidence_lease(work_item, actor)
            events = await self._audit.list_events(case_id)
            if supplied_anchor is not None:
                if not any(str(event.get("event_id")) == supplied_anchor for event in events):
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="causation_event_id does not reference an event in this Case",
                    )
            else:
                derived = self._latest_work_item_event_id(events, request.work_item_id)
                if derived is None:
                    raise HTTPException(
                        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                        detail="Worker evidence requires a causal anchor event in this Case",
                    )
                inner_payload = {**inner_payload, "causation_event_id": derived}
        sanitized_payload = _sanitize_payload(inner_payload, self._settings.max_evidence_bytes)
        event_id, recorded_at = await self._audit.record(
            case_id=case_id,
            actor=actor,
            event_type=request.event_type,
            payload={
                "work_item_id": request.work_item_id,
                "summary": request.summary,
                "context_refs": [item.model_dump() for item in request.context_refs],
                "omic_task_id": request.omic_task_id,
                "skill_name": request.skill_name,
                "payload": sanitized_payload,
            },
        )
        return EvidenceResponse(event_id=event_id, recorded_at=recorded_at)

    async def _require_existing_event(self, case_id: str, event_id: str) -> None:
        events = await self._audit.list_events(case_id)
        if not any(str(event.get("event_id")) == event_id for event in events):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="causation_event_id does not reference an event in this Case",
            )

    @staticmethod
    def _latest_work_item_event_id(
        events: list[dict[str, Any]], work_item_id: str
    ) -> str | None:
        """Latest stream event bound to the work item (assignment always writes one)."""
        for event in reversed(events):
            payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
            if payload.get("work_item_id") == work_item_id and event.get("event_id"):
                return str(event["event_id"])
        return None

    @staticmethod
    def _require_evidence_lease(work_item: WorkItemRecord, actor: str) -> None:
        """Worker evidence requires a live lease, or a claimable item not leased to others."""
        if work_item.lease_owner is not None:
            if work_item.lease_owner != actor or CaseStore._lease_expired(
                work_item, datetime.now(UTC)
            ):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Worker does not hold a valid lease for this work item",
                )
        elif work_item.status not in {"pending", "failed"}:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Work item is not claimable by this worker",
            )


def _sanitize_payload(payload: dict[str, Any], max_bytes: int) -> dict[str, Any]:
    forbidden = {
        "authorization",
        "token",
        "secret",
        "password",
        "api_key",
        "jwt",
        "connection_string",
    }
    cleaned = {
        key: "[redacted]" if key.lower() in forbidden else value for key, value in payload.items()
    }
    if len(str(cleaned).encode()) > max_bytes:
        raise HTTPException(status_code=413, detail="Evidence payload exceeds Bridge size limit")
    return cleaned

"""Small Bridge-owned Case state store; it contains references, never raw omics data."""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status

from .models import (
    CaseRecord,
    CaseStatus,
    PreflightInputSnapshot,
    WorkItemRecord,
    WorkItemStatus,
)
from .shared_state import RedisStateBackend

# Module-level aliases: class-scope annotations below would resolve ``list`` to the
# ``CaseStore.list`` method, so the container types must be named here at module scope.
LeaseExpiredRequeues = list[tuple[str, WorkItemRecord]]  # (case_id, pre-reset snapshot)
AssignedWorkItemsResult = tuple[list[tuple[CaseRecord, WorkItemRecord]], LeaseExpiredRequeues]

_WORK_ITEM_TRANSITIONS: dict[WorkItemStatus, set[WorkItemStatus]] = {
    "pending": {"claimed", "cancelled"},
    "claimed": {"running", "completed", "failed", "awaiting_approval", "blocked", "pending", "cancelled"},
    "running": {"completed", "failed", "awaiting_approval", "blocked", "cancelled", "pending"},
    "awaiting_approval": {"running", "cancelled"},
    "in_progress": {"running", "completed", "failed", "blocked", "cancelled", "pending"},
    "completed": set(),
    "blocked": {"pending", "cancelled"},
    "failed": {"pending", "claimed", "cancelled"},
    "cancelled": set(),
}

_ALLOWED_TRANSITIONS: dict[CaseStatus, set[CaseStatus]] = {
    "queued": {"received", "cancelled"},
    "received": {"planning_running", "preflight_running", "cancelled"},
    "planning_running": {"preflight_running", "approval_pending", "waiting_for_correction", "cancelled"},
    "preflight_running": {"preflight_blocked", "approval_pending", "cancelled"},
    "preflight_blocked": {"waiting_for_correction", "cancelled"},
    "waiting_for_correction": {"planning_running", "preflight_running", "cancelled"},
    "approval_pending": {"approved", "cancelled"},
    "approved": {"executing", "cancelled"},
    "executing": {"quality_running", "delivery_ready", "execution_failed", "cancelled"},
    "execution_failed": {"approval_pending", "remediation_pending", "cancelled"},
    "quality_running": {"delivery_ready", "quality_blocked", "remediation_pending", "cancelled"},
    "quality_blocked": {"approval_pending", "remediation_pending", "cancelled"},
    "remediation_pending": {"approval_pending", "preflight_running", "executing", "quality_running", "cancelled"},
    "delivery_ready": {"closed", "remediation_pending", "cancelled"},
    "closed": set(),
    "cancelled": set(),
}


class _SynchronizedCaseLock:
    """Drop-in async lock that reloads shared state under a distributed lock."""

    def __init__(self, store: CaseStore) -> None:
        self._store = store
        self._contexts: dict[asyncio.Task[Any], Any] = {}

    async def __aenter__(self) -> None:
        context = self._store._synchronized()
        await context.__aenter__()
        task = asyncio.current_task()
        if task is None:  # pragma: no cover - asyncio always supplies a task here
            raise RuntimeError("CaseStore access requires an asyncio task")
        self._contexts[task] = context

    async def __aexit__(self, exc_type: object, exc: object, traceback: object) -> None:
        task = asyncio.current_task()
        if task is None or (context := self._contexts.pop(task, None)) is None:
            raise RuntimeError("CaseStore lock context was lost")
        await context.__aexit__(exc_type, exc, traceback)


class CaseStore:
    def __init__(
        self,
        path: str,
        state_store_url: str = "",
        state_store_key_prefix: str = "omichub:agentteams:cases",
    ) -> None:
        self._path = Path(path)
        self._cases = self._load()
        self._shared_state = (
            RedisStateBackend(state_store_url, state_store_key_prefix) if state_store_url else None
        )
        if self._shared_state is None:
            import logging

            logging.getLogger(__name__).warning(
                "Bridge CaseStore is using local-file fallback; configure BRIDGE_STATE_STORE_URL for production replicas"
            )
        self._local_lock = asyncio.Lock()
        self._lock = _SynchronizedCaseLock(self)

    @asynccontextmanager
    async def _synchronized(self) -> AsyncIterator[None]:
        async with self._local_lock:
            if self._shared_state is None:
                yield
                return
            async with self._shared_state.lock():
                await self._reload_shared_locked()
                yield

    async def _reload_shared_locked(self) -> None:
        if self._shared_state is None:
            return
        raw = await self._shared_state.get_snapshot()
        if not raw:
            self._cases = {}
            return
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Bridge shared CaseStore snapshot is invalid") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError("Bridge shared CaseStore snapshot must be an object")
        self._cases = {
            case_id: CaseRecord.model_validate(value)
            for case_id, value in decoded.items()
            if isinstance(case_id, str) and isinstance(value, dict)
        }

    async def aclose(self) -> None:
        if self._shared_state is not None:
            await self._shared_state.aclose()

    def _load(self) -> dict[str, CaseRecord]:
        if not self._path.exists():
            return {}
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        cases: dict[str, CaseRecord] = {}
        for case_id, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            try:
                cases[str(case_id)] = CaseRecord.model_validate(payload)
            except ValueError:
                continue
        return cases

    async def create(self, case: CaseRecord) -> CaseRecord:
        async with self._lock:
            if case.case_id in self._cases:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Case already exists"
                )
            self._cases[case.case_id] = case
            await self._persist()
            return case

    async def get(self, case_id: str) -> CaseRecord:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            return case

    async def list(self, requester_ref: str | None = None) -> list[CaseRecord]:
        async with self._lock:
            cases = list(self._cases.values())
            if requester_ref is not None:
                cases = [case for case in cases if case.requester_ref == requester_ref]
            return sorted(cases, key=lambda case: case.updated_at, reverse=True)

    async def list_assigned_work_items(
        self, target: str, statuses: set[str]
    ) -> AssignedWorkItemsResult:
        """Return assigned items plus the pre-reset snapshots of lease-expired requeues.

        The second element lets the service layer write audit events for work items
        that were silently reclaimed, so the timeline shows the requeue instead of
        an unexplained duplicate claim.
        """
        async with self._lock:
            expired = self._requeue_expired_locked()
            retryable = self._requeue_retryable_failures_locked()
            if expired or retryable:
                await self._persist()
            assigned = [
                (case, work_item)
                for case in self._cases.values()
                for work_item in case.work_items
                if work_item.target == target and work_item.status in statuses
            ]
            return sorted(assigned, key=lambda item: item[1].updated_at, reverse=True), expired

    async def delete(self, case_id: str) -> bool:
        """Remove a Case from the store; used by Case GC after audit cleanup."""
        async with self._lock:
            if case_id not in self._cases:
                return False
            del self._cases[case_id]
            await self._persist()
            return True

    async def cancel(self, case_id: str) -> CaseRecord:
        """Atomically cancel a Case and reclaim all nonterminal work items."""
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            if "cancelled" not in _ALLOWED_TRANSITIONS[case.status]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Invalid Case transition: {case.status} -> cancelled",
                )
            now = datetime.now(UTC)
            work_items = [
                item
                if item.status in {"completed", "cancelled"}
                else item.model_copy(
                    update={
                        "status": "cancelled",
                        "lease_owner": None,
                        "lease_expires_at": None,
                        "retry_not_before": None,
                        "cancelled_at": now,
                        "updated_at": now,
                    }
                )
                for item in case.work_items
            ]
            cancelled = case.model_copy(
                update={"status": "cancelled", "work_items": work_items, "updated_at": now}
            )
            self._cases[case_id] = cancelled
            await self._persist()
            return cancelled

    async def transition(self, case_id: str, target: CaseStatus) -> CaseRecord:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            if target not in _ALLOWED_TRANSITIONS[case.status]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Invalid Case transition: {case.status} -> {target}",
                )
            now = datetime.now(UTC)
            updated = case.model_copy(
                update={"status": target, "node_started_at": now, "updated_at": now}
            )
            self._cases[case_id] = updated
            await self._persist()
            return updated

    async def attach_task(
        self, case_id: str, task_id: str, task_spec: dict[str, Any] | None = None
    ) -> CaseRecord:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            if task_id not in case.omic_task_ids:
                case = case.model_copy(
                    update={
                        "omic_task_ids": [*case.omic_task_ids, task_id],
                        "task_specs": [*case.task_specs, task_spec]
                        if task_spec
                        else case.task_specs,
                        "updated_at": datetime.now(UTC),
                    }
                )
                self._cases[case_id] = case
                await self._persist()
            return case

    async def save_preflight_input(
        self, case_id: str, snapshot: PreflightInputSnapshot | None
    ) -> CaseRecord:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            updated = case.model_copy(
                update={"preflight_input": snapshot, "updated_at": datetime.now(UTC)}
            )
            self._cases[case_id] = updated
            await self._persist()
            return updated

    async def save_plan(
        self,
        case_id: str,
        proposed_submission: dict[str, Any],
        plan_hash: str,
        snapshot: PreflightInputSnapshot,
    ) -> CaseRecord:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            updated = case.model_copy(
                update={
                    "proposed_submission": proposed_submission,
                    "plan_hash": plan_hash,
                    "plan_version": max(1, case.plan_version + 1),
                    "preflight_input": snapshot,
                    "updated_at": datetime.now(UTC),
                }
            )
            self._cases[case_id] = updated
            await self._persist()
            return updated

    async def revise_plan(
        self,
        case_id: str,
        proposed_submission: dict[str, Any],
        plan_hash: str,
        replay_work_item_ids: set[str],
    ) -> CaseRecord:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            planned_items = {
                str(item.get("work_item_id")): item
                for item in (proposed_submission.get("parameters") or {}).get("work_items", [])
                if isinstance(item, dict) and item.get("work_item_id")
            }
            revised_items = []
            for item in case.work_items:
                if item.execution_mode != "workspace_execution":
                    revised_items.append(item)
                    continue
                updates: dict[str, Any] = {
                    "plan_hash": plan_hash,
                    "plan_version": case.plan_version + 1,
                    "updated_at": datetime.now(UTC),
                }
                planned = planned_items.get(item.work_item_id)
                if planned is not None:
                    updates.update(
                        target=planned["target"],
                        objective=str(planned["objective"]),
                        skill_name=str(planned["skill_name"]),
                        depends_on=[str(value) for value in planned.get("depends_on") or []],
                    )
                if item.work_item_id in replay_work_item_ids:
                    updates.update(
                        status="pending",
                        output_refs=[],
                        summary=None,
                        trace_id=None,
                    )
                revised_items.append(item.model_copy(update=updates))
            updated = case.model_copy(
                update={
                    "proposed_submission": proposed_submission,
                    "plan_hash": plan_hash,
                    "plan_version": case.plan_version + 1,
                    "plan_revision_count": case.plan_revision_count + 1,
                    "work_items": revised_items,
                    "updated_at": datetime.now(UTC),
                }
            )
            self._cases[case_id] = updated
            await self._persist()
            return updated

    async def reset_planning_work_item(
        self,
        case_id: str,
        work_item_id: str,
        objective: str,
    ) -> CaseRecord:
        """Reset a planning work item to pending and bump the planning retry counter.

        Used when schema validation fails so the Planner can reclaim the item with
        corrective feedback in its objective.
        """
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            now = datetime.now(UTC)
            revised_items = []
            for item in case.work_items:
                if item.work_item_id != work_item_id:
                    revised_items.append(item)
                    continue
                revised_items.append(
                    item.model_copy(
                        update={
                            "objective": objective,
                            "status": "pending",
                            "attempt": 0,
                            "lease_owner": None,
                            "lease_expires_at": None,
                            "retry_not_before": None,
                            "summary": None,
                            "trace_id": None,
                            "output_refs": [],
                            "findings": [],
                            "updated_at": now,
                        }
                    )
                )
            updated = case.model_copy(
                update={
                    "planning_retry_count": case.planning_retry_count + 1,
                    "work_items": revised_items,
                    "updated_at": now,
                }
            )
            self._cases[case_id] = updated
            await self._persist()
            return updated

    async def add_work_item(self, case_id: str, work_item: WorkItemRecord) -> CaseRecord:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            if any(item.work_item_id == work_item.work_item_id for item in case.work_items):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Work item already exists"
                )
            if work_item.parent_work_item_id and not any(
                item.work_item_id == work_item.parent_work_item_id for item in case.work_items
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Parent work item not found",
                )
            missing_dependencies = set(work_item.depends_on) - {
                item.work_item_id for item in case.work_items
            }
            if missing_dependencies:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=f"Work item dependencies not found: {sorted(missing_dependencies)}",
                )
            updated = case.model_copy(
                update={
                    "work_items": [*case.work_items, work_item],
                    "updated_at": datetime.now(UTC),
                }
            )
            self._cases[case_id] = updated
            await self._persist()
            return updated

    async def ensure_work_item(
        self, case_id: str, work_item: WorkItemRecord
    ) -> tuple[WorkItemRecord, bool]:
        """Return an existing work item or add it atomically for reconciliation."""
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            for existing in case.work_items:
                if existing.work_item_id == work_item.work_item_id:
                    return existing, False
            if work_item.parent_work_item_id and not any(
                item.work_item_id == work_item.parent_work_item_id for item in case.work_items
            ):
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail="Parent work item not found",
                )
            updated = case.model_copy(
                update={
                    "work_items": [*case.work_items, work_item],
                    "updated_at": datetime.now(UTC),
                }
            )
            self._cases[case_id] = updated
            await self._persist()
            return work_item, True

    async def update_work_item(
        self, case_id: str, work_item_id: str, work_item: WorkItemRecord
    ) -> CaseRecord:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            if not any(item.work_item_id == work_item_id for item in case.work_items):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found"
                )
            updated = case.model_copy(
                update={
                    "work_items": [
                        work_item if item.work_item_id == work_item_id else item
                        for item in case.work_items
                    ],
                    "updated_at": datetime.now(UTC),
                }
            )
            self._cases[case_id] = updated
            await self._persist()
            return updated

    async def begin_approved_submission(
        self, case_id: str, work_item_id: str, target: str
    ) -> WorkItemRecord:
        """Atomically reserve a prepared submission before an outbound task request."""
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            work_item = next(
                (item for item in case.work_items if item.work_item_id == work_item_id), None
            )
            if work_item is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
            if work_item.target != target or work_item.lease_owner != target:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Work item lease owner mismatch")
            if work_item.status != "running" or self._lease_expired(work_item, datetime.now(UTC)):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Work item is not running")
            approved = work_item.approved_submission
            if approved is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Work item has no approved submission")
            if approved.consumed_at is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approved submission was already consumed")
            if approved.submission_started_at is not None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Approved submission is already running")
            now = datetime.now(UTC)
            updated_item = work_item.model_copy(
                update={
                    "approved_submission": approved.model_copy(update={"submission_started_at": now}),
                    "updated_at": now,
                }
            )
            self._cases[case_id] = case.model_copy(
                update={
                    "work_items": [
                        updated_item if item.work_item_id == work_item_id else item
                        for item in case.work_items
                    ],
                    "updated_at": now,
                }
            )
            await self._persist()
            return updated_item

    async def reset_approved_submission_start(
        self, case_id: str, work_item_id: str, target: str
    ) -> WorkItemRecord:
        """Allow a failed submission attempt to be retried after its Work Item is requeued."""
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            work_item = next(
                (item for item in case.work_items if item.work_item_id == work_item_id), None
            )
            if work_item is None or work_item.target != target:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
            approved = work_item.approved_submission
            if approved is None:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Work item has no approved submission")
            now = datetime.now(UTC)
            updated_item = work_item.model_copy(
                update={
                    "approved_submission": approved.model_copy(update={"submission_started_at": None}),
                    "updated_at": now,
                }
            )
            self._cases[case_id] = case.model_copy(
                update={
                    "work_items": [
                        updated_item if item.work_item_id == work_item_id else item
                        for item in case.work_items
                    ],
                    "updated_at": now,
                }
            )
            await self._persist()
            return updated_item

    async def claim_work_item(self, case_id: str, work_item_id: str, target: str) -> WorkItemRecord:
        """Atomically claim a pending assignment, reclaiming only an expired lease."""
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            work_item = next(
                (item for item in case.work_items if item.work_item_id == work_item_id), None
            )
            if work_item is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found"
                )
            if work_item.target != target:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN, detail="Work item target mismatch"
                )
            now = datetime.now(UTC)
            dependency_statuses = {
                item.work_item_id: item.status for item in case.work_items
            }
            unmet_dependencies = [
                dependency
                for dependency in work_item.depends_on
                if dependency_statuses.get(dependency) != "completed"
            ]
            if unmet_dependencies:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Work item dependencies are not completed: {unmet_dependencies}",
                )
            lease_expired = self._lease_expired(work_item, now)
            retryable_failure = work_item.status == "failed" and work_item.attempt < work_item.max_attempts
            if (
                retryable_failure
                and work_item.retry_not_before is not None
                and work_item.retry_not_before > now
            ):
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Work item retry is not ready before {work_item.retry_not_before.isoformat()}",
                )
            if work_item.status != "pending" and not lease_expired and not retryable_failure:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Work item is already claimed or completed",
                )
            if work_item.status == "failed" and work_item.attempt >= work_item.max_attempts:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Work item retry budget is exhausted",
                )
            claimed = work_item.model_copy(
                update={
                    "status": "claimed",
                    "attempt": work_item.attempt + 1,
                    "lease_owner": target,
                    "lease_expires_at": _lease_expiry(now, work_item.deadline_seconds),
                    "retry_not_before": None,
                    "updated_at": now,
                }
            )
            updated_case = case.model_copy(
                update={
                    "work_items": [
                        claimed if item.work_item_id == work_item_id else item
                        for item in case.work_items
                    ],
                    "updated_at": now,
                }
            )
            self._cases[case_id] = updated_case
            await self._persist()
            return claimed

    async def transition_work_item(
        self,
        case_id: str,
        work_item_id: str,
        target: str,
        desired_status: WorkItemStatus,
        *,
        summary: str = "",
        findings: list[Any] | None = None,
        output_refs: list[Any] | None = None,
        trace_id: str | None = None,
    ) -> WorkItemRecord:
        """Transition a claimed item while enforcing owner, lease, and terminal-state rules."""
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            work_item = next(
                (item for item in case.work_items if item.work_item_id == work_item_id), None
            )
            if work_item is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
            if work_item.target != target:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Work item target mismatch")
            if work_item.lease_owner not in {None, target}:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Work item lease owner mismatch")
            now = datetime.now(UTC)
            if work_item.status in {"claimed", "running", "in_progress", "awaiting_approval"} and self._lease_expired(work_item, now):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Work item lease has expired")
            if desired_status not in _WORK_ITEM_TRANSITIONS[work_item.status]:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"Invalid Work Item transition: {work_item.status} -> {desired_status}",
                )
            terminal = desired_status in {"completed", "failed", "blocked", "cancelled"}
            updated_item = work_item.model_copy(
                update={
                    "status": desired_status,
                    "summary": summary or work_item.summary,
                    "findings": findings if findings is not None else work_item.findings,
                    "output_refs": output_refs if output_refs is not None else work_item.output_refs,
                    "trace_id": trace_id or work_item.trace_id,
                    "lease_owner": None if terminal else target,
                    "lease_expires_at": None
                    if terminal
                    else _lease_expiry(now, work_item.deadline_seconds),
                    "updated_at": now,
                }
            )
            self._cases[case_id] = case.model_copy(
                update={
                    "work_items": [
                        updated_item if item.work_item_id == work_item_id else item
                        for item in case.work_items
                    ],
                    "updated_at": now,
                }
            )
            await self._persist()
            return updated_item

    async def heartbeat_work_item(
        self, case_id: str, work_item_id: str, target: str, *, trace_id: str | None = None
    ) -> WorkItemRecord:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            work_item = next(
                (item for item in case.work_items if item.work_item_id == work_item_id), None
            )
            if work_item is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")
            if work_item.target != target or work_item.lease_owner != target:
                raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Work item lease owner mismatch")
            now = datetime.now(UTC)
            if self._lease_expired(work_item, now):
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Work item lease has expired")
            if work_item.status not in {"claimed", "running", "in_progress", "awaiting_approval"}:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Work item is not active")
            updated_item = work_item.model_copy(
                update={
                    "lease_expires_at": _lease_expiry(now, work_item.deadline_seconds),
                    "trace_id": trace_id or work_item.trace_id,
                    "updated_at": now,
                }
            )
            self._cases[case_id] = case.model_copy(
                update={
                    "work_items": [
                        updated_item if item.work_item_id == work_item_id else item
                        for item in case.work_items
                    ],
                    "updated_at": now,
                }
            )
            await self._persist()
            return updated_item

    def _requeue_expired_locked(self) -> LeaseExpiredRequeues:
        now = datetime.now(UTC)
        requeued: LeaseExpiredRequeues = []
        for case_id, case in list(self._cases.items()):
            changed = False
            work_items: list[WorkItemRecord] = []
            for item in case.work_items:
                if item.status in {"claimed", "running", "in_progress"} and self._lease_expired(item, now):
                    requeued.append((case_id, item))
                    work_items.append(
                        item.model_copy(
                            update={
                                "status": "pending",
                                "lease_owner": None,
                                "lease_expires_at": None,
                                "updated_at": now,
                            }
                        )
                    )
                    changed = True
                else:
                    work_items.append(item)
            if changed:
                self._cases[case_id] = case.model_copy(
                    update={"work_items": work_items, "updated_at": now}
                )
        return requeued

    def _requeue_retryable_failures_locked(self) -> list[tuple[str, str]]:
        now = datetime.now(UTC)
        requeued: list[tuple[str, str]] = []
        for case_id, case in list(self._cases.items()):
            changed = False
            work_items: list[WorkItemRecord] = []
            for item in case.work_items:
                retry_ready = (
                    item.status == "failed"
                    and item.attempt < item.max_attempts
                    and (item.retry_not_before is None or item.retry_not_before <= now)
                )
                if retry_ready:
                    work_items.append(
                        item.model_copy(
                            update={
                                "status": "pending",
                                "lease_owner": None,
                                "lease_expires_at": None,
                                "retry_not_before": None,
                                "updated_at": now,
                            }
                        )
                    )
                    requeued.append((case_id, item.work_item_id))
                    changed = True
                else:
                    work_items.append(item)
            if changed:
                self._cases[case_id] = case.model_copy(
                    update={"work_items": work_items, "updated_at": now}
                )
        return requeued

    @staticmethod
    def _lease_expired(work_item: WorkItemRecord, now: datetime) -> bool:
        expiry = work_item.lease_expires_at
        if expiry is None:
            return (now - work_item.updated_at).total_seconds() >= work_item.deadline_seconds
        return expiry <= now

    async def get_work_item(self, case_id: str, work_item_id: str) -> WorkItemRecord:
        case = await self.get(case_id)
        for item in case.work_items:
            if item.work_item_id == work_item_id:
                return item
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Work item not found")

    async def get_by_task(self, task_id: str) -> CaseRecord:
        async with self._lock:
            for case in self._cases.values():
                if task_id in case.omic_task_ids:
                    return case
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Task is not linked to a Case"
            )

    async def set_quality(self, case_id: str, decision: str) -> CaseRecord:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            case = case.model_copy(
                update={"quality_decision": decision, "updated_at": datetime.now(UTC)}
            )
            self._cases[case_id] = case
            await self._persist()
            return case

    async def close(self, case_id: str, manifest_uri: str) -> CaseRecord:
        async with self._lock:
            case = self._cases.get(case_id)
            if case is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Case not found")
            if case.status != "delivery_ready":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT, detail="Case is not ready to close"
                )
            updated = case.model_copy(
                update={
                    "status": "closed",
                    "manifest_uri": manifest_uri,
                    "updated_at": datetime.now(UTC),
                }
            )
            self._cases[case_id] = updated
            await self._persist()
            return updated

    async def _persist(self) -> None:
        encoded = json.dumps(
            {case_id: case.model_dump(mode="json") for case_id, case in self._cases.items()},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        if self._shared_state is not None:
            await self._shared_state.set_snapshot(encoded)
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_suffix(f"{self._path.suffix}.{os.getpid()}.tmp")
        try:
            temporary.write_text(encoded, encoding="utf-8")
            os.replace(temporary, self._path)
        finally:
            temporary.unlink(missing_ok=True)


def _lease_expiry(now: datetime, deadline_seconds: int) -> datetime:
    from datetime import timedelta

    return now + timedelta(seconds=deadline_seconds)

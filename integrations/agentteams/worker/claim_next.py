#!/usr/bin/env python3
"""Claim one Bridge-assigned Work Item for an external AgentTeams Worker.

The command is intentionally controller-agnostic. A Worker runtime invokes it before asking an
LLM to execute a skill; stdout is a small JSON envelope and never contains Bridge credentials or
Bridge-private Case fields.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Callable
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

UrlOpen = Callable[[Request], Any]


def request_json(
    url: str,
    headers: dict[str, str],
    *,
    method: str,
    opener: UrlOpen,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    request_headers = dict(headers)
    data = None
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=request_headers, method=method)
    with opener(request) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("Bridge returned a non-object response")
    return payload


def assignment_envelope(pending: dict[str, Any], work_item: dict[str, Any]) -> dict[str, Any]:
    """Keep stdout limited to the documented Worker assignment contract."""
    return {
        "case_id": pending.get("case_id"),
        "project_ref": pending.get("project_ref"),
        "intent": pending.get("intent"),
        "status": pending.get("status"),
        "omic_task_ids": pending.get("omic_task_ids", []),
        "quality_decision": pending.get("quality_decision"),
        "work_item": work_item,
    }


def claim_next(
    bridge_url: str,
    identity: str,
    token: str,
    *,
    dry_run: bool = False,
    opener: UrlOpen = urlopen,
) -> dict[str, Any]:
    base_url = bridge_url.rstrip("/")
    headers = {"X-Bridge-Identity": identity, "X-Bridge-Token": token}
    inbox = request_json(f"{base_url}/work-items/assigned", headers, method="GET", opener=opener)
    items = inbox.get("items", [])
    if not isinstance(items, list):
        raise RuntimeError("Bridge returned malformed Worker inbox")
    pending = next(
        (
            item
            for item in items
            if isinstance(item, dict)
            and isinstance(item.get("work_item"), dict)
            and item["work_item"].get("status") == "pending"
        ),
        None,
    )
    if pending is None:
        return {"assignment": None}

    case_id = pending.get("case_id")
    work_item = pending["work_item"]
    work_item_id = work_item.get("work_item_id")
    if not isinstance(case_id, str) or not isinstance(work_item_id, str):
        raise RuntimeError("Bridge returned malformed Work Item identity")
    if dry_run:
        return {"assignment": assignment_envelope(pending, work_item), "claimed": False}

    claimed = request_json(
        f"{base_url}/cases/{case_id}/work-items/{work_item_id}/claim",
        headers,
        method="POST",
        opener=opener,
    )
    return {
        "assignment": {
            **assignment_envelope(pending, claimed),
        },
        "claimed": True,
    }


def complete_work_item(
    bridge_url: str,
    identity: str,
    token: str,
    assignment: dict[str, Any],
    summary: str,
    *,
    opener: UrlOpen = urlopen,
) -> dict[str, Any]:
    """Mark an already claimed, read-only assignment completed."""
    case_id = assignment.get("case_id")
    work_item = assignment.get("work_item")
    if not isinstance(case_id, str) or not isinstance(work_item, dict):
        raise RuntimeError("Bridge returned malformed claimed assignment")
    work_item_id = work_item.get("work_item_id")
    if not isinstance(work_item_id, str):
        raise RuntimeError("Bridge returned malformed Work Item identity")
    return request_json(
        f"{bridge_url.rstrip('/')}/cases/{case_id}/work-items/{work_item_id}",
        {"X-Bridge-Identity": identity, "X-Bridge-Token": token},
        method="POST",
        opener=opener,
        payload={"status": "completed", "summary": summary},
    )


def heartbeat_work_item(
    bridge_url: str,
    identity: str,
    token: str,
    assignment: dict[str, Any],
    *,
    summary: str = "",
    trace_id: str | None = None,
    worker_id: str | None = None,
    opener: UrlOpen = urlopen,
) -> dict[str, Any]:
    case_id, work_item_id = _assignment_identity(assignment)
    payload: dict[str, Any] = {"summary": summary}
    if trace_id:
        payload["trace_id"] = trace_id
    pod_name = worker_id or os.environ.get("AGENTTEAMS_POD_NAME") or os.environ.get("HOSTNAME")
    if pod_name:
        payload["worker_id"] = pod_name
    return request_json(
        f"{bridge_url.rstrip('/')}/cases/{case_id}/work-items/{work_item_id}/heartbeat",
        {"X-Bridge-Identity": identity, "X-Bridge-Token": token},
        method="POST",
        opener=opener,
        payload=payload,
    )


def record_work_item_failure(
    bridge_url: str,
    identity: str,
    token: str,
    assignment: dict[str, Any],
    *,
    error: str,
    trace_id: str | None = None,
    opener: UrlOpen = urlopen,
) -> dict[str, Any]:
    """Persist a worker preflight failure before the lease watchdog can reclaim it."""
    case_id, work_item_id = _assignment_identity(assignment)
    return request_json(
        f"{bridge_url.rstrip('/')}/cases/{case_id}/evidence",
        {"X-Bridge-Identity": identity, "X-Bridge-Token": token},
        method="POST",
        opener=opener,
        payload={
            "work_item_id": work_item_id,
            "event_type": "worker.preflight_failed",
            "summary": "Worker 前置校验失败",
            "payload": {"error": error[:1_000], "trace_id": trace_id},
        },
    )


def execute_readonly_work_item(
    bridge_url: str,
    identity: str,
    token: str,
    assignment: dict[str, Any],
    *,
    agent_id: str,
    capability: str,
    question: str,
    evidence_refs: list[str] | None = None,
    requested_tools: list[str] | None = None,
    execution_mode: str = "readonly_consultation",
    trace_id: str | None = None,
    source_refs: list[dict[str, str]] | None = None,
    execution_summary: str | None = None,
    opener: UrlOpen = urlopen,
) -> dict[str, Any]:
    case_id, work_item_id = _assignment_identity(assignment)
    payload: dict[str, Any] = {
        "agent_id": agent_id,
        "capability": capability,
        "question": question,
        "evidence_refs": evidence_refs or [],
        "requested_tools": requested_tools or [],
        "execution_mode": execution_mode,
    }
    if trace_id:
        payload["trace_id"] = trace_id
    # 产物血缘（F1）：workspace_execution 声明的上游产物引用与执行摘要；
    # 仅在调用方显式提供时携带（None = 未声明）。
    if source_refs is not None:
        payload["source_refs"] = source_refs
    if execution_summary is not None:
        payload["execution_summary"] = execution_summary
    return request_json(
        f"{bridge_url.rstrip('/')}/cases/{case_id}/work-items/{work_item_id}/execute-readonly",
        {"X-Bridge-Identity": identity, "X-Bridge-Token": token},
        method="POST",
        opener=opener,
        payload=payload,
    )


def submit_approved_work_item(
    bridge_url: str,
    identity: str,
    token: str,
    assignment: dict[str, Any],
    *,
    opener: UrlOpen = urlopen,
) -> dict[str, Any]:
    """Ask Bridge to execute the token-free approved submission bound to this Work Item."""
    case_id, work_item_id = _assignment_identity(assignment)
    return request_json(
        f"{bridge_url.rstrip('/')}/cases/{case_id}/work-items/{work_item_id}/submit-approved",
        {"X-Bridge-Identity": identity, "X-Bridge-Token": token},
        method="POST",
        opener=opener,
    )


def submit_quality_gate(
    bridge_url: str,
    identity: str,
    token: str,
    assignment: dict[str, Any],
    *,
    task_id: str,
    decision: str,
    summary: str,
    evidence_refs: list[dict[str, str]] | None = None,
    artifact_hashes: dict[str, str] | None = None,
    source_refs: list[dict[str, str]] | None = None,
    execution_summary: str | None = None,
    remediation_request: dict[str, Any] | None = None,
    opener: UrlOpen = urlopen,
) -> dict[str, Any]:
    case_id, work_item_id = _assignment_identity(assignment)
    payload: dict[str, Any] = {
        "case_id": case_id,
        "work_item_id": work_item_id,
        "rule_version": "agentteams-quality-v1",
        "decision": decision,
        "summary": summary,
        "evidence_refs": evidence_refs or [{"kind": "task", "id": task_id}],
        "artifact_hashes": artifact_hashes or {},
        "remediation_request": remediation_request,
    }
    # 产物血缘（F1）：上报 artifact_hashes 时必须同时携带 source_refs，
    # 缺失会被 Bridge 拒绝登记并回写 room.artifact_rejected 审计事件。
    if source_refs is not None:
        payload["source_refs"] = source_refs
    if execution_summary is not None:
        payload["execution_summary"] = execution_summary
    return request_json(
        f"{bridge_url.rstrip('/')}/tasks/{task_id}/quality-gate",
        {"X-Bridge-Identity": identity, "X-Bridge-Token": token},
        method="POST",
        opener=opener,
        payload=payload,
    )


def close_case(
    bridge_url: str,
    identity: str,
    token: str,
    assignment: dict[str, Any],
    *,
    quality_decision: str,
    remediation_summary: str,
    opener: UrlOpen = urlopen,
) -> dict[str, Any]:
    case_id, _ = _assignment_identity(assignment)
    return request_json(
        f"{bridge_url.rstrip('/')}/cases/{case_id}/close",
        {"X-Bridge-Identity": identity, "X-Bridge-Token": token},
        method="POST",
        opener=opener,
        payload={
            "case_id": case_id,
            "quality_decision": quality_decision,
            "remediation_summary": remediation_summary,
        },
    )


def record_evidence(
    bridge_url: str,
    identity: str,
    token: str,
    assignment: dict[str, Any],
    *,
    event_type: str,
    summary: str,
    context_refs: list[dict[str, str]] | None = None,
    omic_task_id: str | None = None,
    skill_name: str | None = None,
    payload: dict[str, Any] | None = None,
    opener: UrlOpen = urlopen,
) -> dict[str, Any]:
    case_id, work_item_id = _assignment_identity(assignment)
    return request_json(
        f"{bridge_url.rstrip('/')}/cases/{case_id}/evidence",
        {"X-Bridge-Identity": identity, "X-Bridge-Token": token},
        method="POST",
        opener=opener,
        payload={
            "work_item_id": work_item_id,
            "event_type": event_type,
            "summary": summary,
            "context_refs": context_refs or [],
            "omic_task_id": omic_task_id,
            "skill_name": skill_name,
            "payload": payload or {},
        },
    )


def _assignment_identity(assignment: dict[str, Any]) -> tuple[str, str]:
    case_id = assignment.get("case_id")
    work_item = assignment.get("work_item")
    if not isinstance(case_id, str) or not isinstance(work_item, dict):
        raise RuntimeError("Bridge returned malformed claimed assignment")
    work_item_id = work_item.get("work_item_id")
    if not isinstance(work_item_id, str):
        raise RuntimeError("Bridge returned malformed Work Item identity")
    return case_id, work_item_id


def main() -> int:
    parser = argparse.ArgumentParser(description="Claim one assigned CygnusX AgentTeams Work Item")
    parser.add_argument("--bridge-url", default=os.environ.get("AGENTTEAMS_BRIDGE_BASE_URL", ""))
    parser.add_argument("--identity", default=os.environ.get("AGENTTEAMS_WORKER_IDENTITY", ""))
    parser.add_argument("--token", default=os.environ.get("AGENTTEAMS_BRIDGE_TOKEN", ""))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.bridge_url or not args.identity or not args.token:
        parser.error("Bridge URL, Worker identity, and Bridge token are required")
    try:
        result = claim_next(
            args.bridge_url,
            args.identity,
            args.token,
            dry_run=args.dry_run,
        )
    except HTTPError as exc:
        print(f"Bridge request failed with HTTP {exc.code}", file=sys.stderr)
        return 2
    except (URLError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"Bridge worker claim failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

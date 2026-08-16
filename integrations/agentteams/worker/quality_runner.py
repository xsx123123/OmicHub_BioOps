#!/usr/bin/env python3
"""Quality Worker backed by the real OmicHub agent-qc consultation."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError

from claim_next import (
    claim_next,
    execute_readonly_work_item,
    heartbeat_work_item,
    submit_quality_gate,
)


@dataclass(frozen=True)
class QualityWorkerConfig:
    bridge_url: str
    token: str
    poll_seconds: float


def load_config(environ: dict[str, str] | None = None) -> QualityWorkerConfig:
    values = os.environ if environ is None else environ
    bridge_url = values.get("AGENTTEAMS_BRIDGE_BASE_URL", "").strip()
    token = values.get("AGENTTEAMS_BRIDGE_TOKEN", "").strip()
    if values.get("AGENTTEAMS_WORKER_IDENTITY", "quality-auditor") != "quality-auditor":
        raise ValueError("Quality runtime requires the quality-auditor identity")
    if not bridge_url or not token:
        raise ValueError("Bridge URL and quality-auditor token are required")
    return QualityWorkerConfig(
        bridge_url,
        token,
        max(float(values.get("AGENTTEAMS_WORKER_POLL_SECONDS", "5")), 1.0),
    )


def _task_id(assignment: dict[str, Any]) -> str:
    work_item = assignment.get("work_item")
    if not isinstance(work_item, dict):
        raise RuntimeError("Bridge returned malformed quality Work Item")
    for reference in work_item.get("context_refs") or []:
        if (
            isinstance(reference, dict)
            and reference.get("kind") == "task"
            and isinstance(reference.get("id"), str)
        ):
            return reference["id"]
    raise RuntimeError("Quality Work Item does not contain a task reference")


def _decision(result: dict[str, Any]) -> tuple[str, str]:
    summary = str(result.get("summary") or "").strip()
    if result.get("status") != "completed":
        return "manual_review", summary or "质控会诊失败，必须人工复核。"
    marker = summary.splitlines()[0].strip().upper() if summary else ""
    mapping = {"PASSED": "passed", "WARNING": "warning", "BLOCKED": "blocked"}
    return mapping.get(marker, "manual_review"), summary or "质控会诊未返回结论，必须人工复核。"


def run_once(config: QualityWorkerConfig) -> dict[str, Any]:
    identity = "quality-auditor"
    preview = claim_next(config.bridge_url, identity, config.token, dry_run=True)
    if preview.get("assignment") is None:
        return {"action": "idle", "identity": identity}
    claimed = claim_next(config.bridge_url, identity, config.token)
    assignment = claimed.get("assignment")
    if assignment is None:
        return {"action": "claim_raced", "identity": identity}
    task_id = _task_id(assignment)
    trace_id = uuid.uuid4().hex
    heartbeat_work_item(
        config.bridge_url,
        identity,
        config.token,
        assignment,
        summary="agent-qc consultation started.",
        trace_id=trace_id,
    )
    result = execute_readonly_work_item(
        config.bridge_url,
        identity,
        config.token,
        assignment,
        agent_id="agent-qc",
        capability="quality-gate",
        question="独立检查任务证据、质量指标、产物完整性与风险。结论首行必须仅为 PASSED、WARNING 或 BLOCKED。",
        evidence_refs=[f"task:{task_id}"],
        trace_id=trace_id,
    )
    decision, summary = _decision(result)
    recommendations = [
        str(item) for item in result.get("recommendations", []) if isinstance(item, str)
    ]
    normalized = f"{summary} {' '.join(recommendations)}".lower()
    remediation_request = None
    if decision == "blocked":
        target = (
            "data-steward"
            if any(marker in normalized for marker in ("sample", "metadata", "group", "input", "样本", "分组", "输入", "元数据"))
            else "workflow-operator"
        )
        remediation_request = {
            "target": target,
            "objective": f"修复质控阻断项并补充复核证据：{summary[:700]}",
            "recommended_changes": recommendations[:50],
        }
    gate = submit_quality_gate(
        config.bridge_url,
        identity,
        config.token,
        assignment,
        task_id=task_id,
        decision=decision,
        summary=summary,
        remediation_request=remediation_request,
    )
    return {
        "action": decision,
        "identity": identity,
        "case_id": assignment["case_id"],
        "task_id": task_id,
        "status": gate.get("decision"),
    }


def main() -> int:
    try:
        config = load_config()
    except ValueError as exc:
        print(f"quality worker configuration failed: {exc}", flush=True)
        return 2
    while True:
        try:
            print(json.dumps(run_once(config), ensure_ascii=False, separators=(",", ":")), flush=True)
        except (HTTPError, URLError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"quality worker failed: {exc}", flush=True)
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

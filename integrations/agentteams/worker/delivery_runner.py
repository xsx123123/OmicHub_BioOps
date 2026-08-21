#!/usr/bin/env python3
"""Delivery Worker backed by the real OmicHub agent-delivery consultation."""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError

from claim_next import claim_next, close_case, execute_readonly_work_item, heartbeat_work_item


@dataclass(frozen=True)
class DeliveryWorkerConfig:
    bridge_url: str
    token: str
    poll_seconds: float


def load_config(environ: dict[str, str] | None = None) -> DeliveryWorkerConfig:
    values = os.environ if environ is None else environ
    bridge_url = values.get("AGENTTEAMS_BRIDGE_BASE_URL", "").strip()
    token = values.get("AGENTTEAMS_BRIDGE_TOKEN", "").strip()
    if values.get("AGENTTEAMS_WORKER_IDENTITY", "delivery-reporter") != "delivery-reporter":
        raise ValueError("Delivery runtime requires the delivery-reporter identity")
    if not bridge_url or not token:
        raise ValueError("Bridge URL and delivery-reporter token are required")
    return DeliveryWorkerConfig(
        bridge_url,
        token,
        max(float(values.get("AGENTTEAMS_WORKER_POLL_SECONDS", "5")), 1.0),
    )


def _task_id(assignment: dict[str, Any]) -> str | None:
    work_item = assignment.get("work_item")
    if not isinstance(work_item, dict):
        raise RuntimeError("Bridge returned malformed delivery Work Item")
    for reference in work_item.get("context_refs") or []:
        if (
            isinstance(reference, dict)
            and reference.get("kind") == "task"
            and isinstance(reference.get("id"), str)
        ):
            return reference["id"]
    return None


def backoff_seconds(poll_seconds: float, consecutive_failures: int) -> float:
    """指数退避：poll_seconds * 2^consecutive_failures，封顶 5 分钟。"""
    return min(poll_seconds * (2 ** max(consecutive_failures, 0)), 300.0)


def run_once(config: DeliveryWorkerConfig) -> dict[str, Any]:
    identity = "delivery-reporter"
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
        summary="agent-delivery consultation started.",
        trace_id=trace_id,
    )
    evidence_refs = [f"task:{task_id}"] if task_id else []
    result = execute_readonly_work_item(
        config.bridge_url,
        identity,
        config.token,
        assignment,
        agent_id="agent-delivery",
        capability="delivery-pack",
        question="汇总交付清单、产物引用、运行说明、已知风险和复现步骤。不得遗漏风险披露。"
        "无人值守自动交付只产出 delivery-summary.md 与 checksums.md5 标准交付，"
        "不生成 HTML 报告，不调用 ask_user。",
        evidence_refs=evidence_refs,
        trace_id=trace_id,
    )
    summary = str(result.get("summary") or "").strip()
    if result.get("status") != "completed" or not summary:
        return {
            "action": "manual_review",
            "identity": identity,
            "case_id": assignment["case_id"],
            "task_id": task_id,
            "status": result.get("status"),
        }
    quality_decision = str(assignment.get("quality_decision") or "").strip().lower()
    if quality_decision not in {"passed", "warning", "manual_review"}:
        return {
            "action": "manual_review",
            "identity": identity,
            "case_id": assignment["case_id"],
            "task_id": task_id,
            "reason": "missing_or_invalid_quality_decision",
        }
    closed = close_case(
        config.bridge_url,
        identity,
        config.token,
        assignment,
        quality_decision=quality_decision,
        remediation_summary=summary,
    )
    return {
        "action": "closed",
        "identity": identity,
        "case_id": assignment["case_id"],
        "task_id": task_id,
        "status": closed.get("status"),
        "manifest_uri": closed.get("manifest_uri"),
    }


def main() -> int:
    try:
        config = load_config()
    except ValueError as exc:
        print(f"delivery worker configuration failed: {exc}", flush=True)
        return 2
    consecutive_failures = 0
    while True:
        try:
            print(json.dumps(run_once(config), ensure_ascii=False, separators=(",", ":")), flush=True)
            consecutive_failures = 0
            delay = config.poll_seconds
        except (HTTPError, URLError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"delivery worker failed: {exc}", flush=True)
            delay = backoff_seconds(config.poll_seconds, consecutive_failures)
            consecutive_failures += 1
        time.sleep(delay)


if __name__ == "__main__":
    raise SystemExit(main())

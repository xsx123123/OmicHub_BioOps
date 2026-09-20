#!/usr/bin/env python3
"""Run repeatable AgentTeams Bridge demos against a separately deployed environment.

This driver never reads CygnusX data volumes or credentials.  It calls the public Bridge API
with the six service identities supplied through environment variables.  The default modes stop
after preflight; workflow submission requires an explicit staging-only approval opt-in.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4


@dataclass(frozen=True)
class Identity:
    name: str
    token: str


class BridgeDemo:
    def __init__(self, base_url: str, identities: dict[str, Identity]) -> None:
        self.base_url = base_url.rstrip("/")
        self.identities = identities

    def request(
        self,
        method: str,
        path: str,
        identity: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        request = Request(
            f"{self.base_url}{path}",
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Bridge-Identity": self.identities[identity].name,
                "X-Bridge-Token": self.identities[identity].token,
            },
        )
        try:
            with urlopen(request, timeout=20) as response:  # noqa: S310 - URL is operator supplied.
                decoded = json.loads(response.read().decode())
        except HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"{method} {path} failed with {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"Cannot reach Bridge at {self.base_url}: {exc.reason}") from exc
        if not isinstance(decoded, dict):
            raise RuntimeError(f"{method} {path} returned an invalid JSON object")
        return decoded


def required_identity(role: str) -> Identity:
    token = os.environ.get(f"DEMO_{role.upper().replace('-', '_')}_TOKEN", "").strip()
    if not token or token.startswith("replace-"):
        raise RuntimeError(f"Missing DEMO_{role.upper().replace('-', '_')}_TOKEN")
    return Identity(name=role, token=token)


def create_case(demo: BridgeDemo, project_id: str, intent: str) -> str:
    case_id = f"bioops_demo_{uuid4().hex[:16]}"
    demo.request(
        "POST",
        "/v1/cases",
        "bioops-manager",
        {
            "case_id": case_id,
            "project_ref": {"kind": "project", "id": project_id},
            "intent": intent,
            "requester_ref": "agentteams-demo-operator",
        },
    )
    demo.request(
        "POST",
        f"/v1/cases/{case_id}/work-items",
        "bioops-manager",
        {
            "work_item_id": "preflight-01",
            "target": "data-steward",
            "objective": "Validate RNA-seq example inputs before workflow approval.",
            "skill_name": "project-preflight",
            "context_refs": [{"kind": "project", "id": project_id}],
        },
    )
    return case_id


def run_preflight(
    demo: BridgeDemo,
    case_id: str,
    project_id: str,
    *,
    blocked: bool,
    flow_id: str = "rna_seq",
    sample_sheet: list[dict[str, Any]] | None = None,
    comparisons: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    preflight_sample_sheet = (
        [] if blocked else sample_sheet or [{"sample": "DEMO_S01", "group": "control"}]
    )
    result = demo.request(
        "POST",
        f"/v1/projects/{project_id}/preflight",
        "data-steward",
        {
            "case_id": case_id,
            "work_item_id": "preflight-01",
            "flow_id": flow_id,
            "sample_sheet": preflight_sample_sheet,
            "comparisons": comparisons,
            "context_refs": [{"kind": "project", "id": project_id}],
        },
    )
    expected = "blocked" if blocked else "passed"
    if result.get("status") != expected:
        raise RuntimeError(f"Expected preflight {expected}, got {result.get('status')!r}")
    return result


def wait_for_task(demo: BridgeDemo, task_id: str, timeout_seconds: int) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        task = demo.request("GET", f"/v1/tasks/{task_id}", "workflow-operator")
        if task.get("status") in {"success", "failed", "cancelled"}:
            return task
        time.sleep(5)
    raise RuntimeError(f"Task {task_id} did not reach a terminal state within {timeout_seconds}s")


def run_staging_success(
    demo: BridgeDemo, case_id: str, task_payload: dict[str, Any], timeout: int
) -> None:
    if task_payload.get("flow_id") != "rna_seq":
        raise RuntimeError("The demo Bridge allowlist currently permits only flow_id=rna_seq")
    if not isinstance(task_payload.get("sample_sheet"), list) or not task_payload["sample_sheet"]:
        raise RuntimeError(
            "--task-json must include a non-empty sample_sheet for the preflight snapshot"
        )
    approval = demo.request(
        "POST",
        "/v1/approvals",
        "approval-authority",
        {"case_id": case_id, "action": "submit_task", "flow_id": "rna_seq"},
    )
    demo.request(
        "POST",
        f"/v1/cases/{case_id}/work-items",
        "bioops-manager",
        {
            "work_item_id": "submit-01",
            "target": "workflow-operator",
            "objective": "Submit the approved RNA-seq workflow through CygnusX.",
            "skill_name": "workflow-submit",
            "approval_required": True,
        },
    )
    receipt = demo.request(
        "POST",
        "/v1/tasks",
        "workflow-operator",
        {
            "case_id": case_id,
            "work_item_id": "submit-01",
            "idempotency_key": f"{case_id}-submit-v1",
            "approval_token": approval["token"],
            "task": task_payload,
        },
    )
    task_id = receipt.get("omic_task_id") or receipt.get("task_id")
    if not isinstance(task_id, str):
        raise RuntimeError("Bridge submission receipt did not include an CygnusX task ID")
    task = wait_for_task(demo, task_id, timeout)
    if task.get("status") != "success":
        raise RuntimeError(f"Submitted task ended as {task.get('status')!r}; inspect Case evidence")
    reconciled = demo.request("POST", f"/v1/cases/{case_id}/reconcile", "bioops-manager")
    interpretation = next(
        (
            item
            for item in reconciled.get("work_items", [])
            if isinstance(item, dict) and item.get("work_item_id") == "interpret-01"
        ),
        None,
    )
    if interpretation is None:
        raise RuntimeError("Task success did not create the required interpretation Work Item")
    demo.request(
        "POST",
        f"/v1/cases/{case_id}/work-items/interpret-01/claim",
        "agent-rnaseq",
    )
    interpretation_result = demo.request(
        "POST",
        f"/v1/cases/{case_id}/work-items/interpret-01/execute-readonly",
        "agent-rnaseq",
        {
            "agent_id": "agent-rnaseq",
            "capability": "result_interpretation",
            "question": "解读该 RNA-seq 任务的关键结果、证据、限制与后续建议。",
            "evidence_refs": [f"task:{task_id}"],
            "requested_tools": [],
        },
    )
    if interpretation_result.get("status") != "completed":
        raise RuntimeError("Interpretation Work Item did not complete")
    demo.request(
        "POST",
        f"/v1/cases/{case_id}/work-items",
        "bioops-manager",
        {
            "work_item_id": "quality-01",
            "target": "quality-auditor",
            "objective": "Verify task evidence and complete the quality gate.",
            "skill_name": "quality-gate",
        },
    )
    demo.request(
        "POST",
        f"/v1/tasks/{task_id}/quality-gate",
        "quality-auditor",
        {
            "case_id": case_id,
            "work_item_id": "quality-01",
            "rule_version": "demo-rna-qc-1.0",
            "decision": "passed",
            "summary": "Staging demonstration completed after the real task reached success.",
            "evidence_refs": [{"kind": "task", "id": task_id}],
            "artifact_hashes": {},
        },
    )
    manifest = demo.request(
        "POST",
        f"/v1/cases/{case_id}/close",
        "delivery-reporter",
        {"case_id": case_id, "quality_decision": "passed"},
    )
    print(
        json.dumps(
            {"case_id": case_id, "task_id": task_id, "manifest": manifest}, ensure_ascii=False
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("preflight-success", "preflight-blocked", "staging-success"),
        required=True,
    )
    parser.add_argument(
        "--project-id",
        required=True,
        help="Existing demo project reference; never a filesystem path",
    )
    parser.add_argument(
        "--task-json",
        type=Path,
        help="TaskSubmitRequest-compatible JSON required by staging-success",
    )
    parser.add_argument("--timeout-seconds", type=int, default=7200)
    parser.add_argument(
        "--allow-automated-demo-approval",
        action="store_true",
        help="Required only for staging-success; prohibited for production approval demonstrations.",
    )
    args = parser.parse_args()
    if args.mode == "staging-success" and (
        not args.allow_automated_demo_approval or not args.task_json
    ):
        parser.error("staging-success requires --task-json and --allow-automated-demo-approval")
    base_url = os.environ.get("DEMO_BRIDGE_URL", "").strip()
    if not base_url:
        parser.error("DEMO_BRIDGE_URL is required")
    roles = ["bioops-manager", "data-steward"]
    if args.mode == "staging-success":
        roles.extend(
            [
                "approval-authority",
                "workflow-operator",
                "quality-auditor",
                "delivery-reporter",
                "agent-rnaseq",
            ]
        )
    try:
        demo = BridgeDemo(base_url, {role: required_identity(role) for role in roles})
        case_id = create_case(
            demo, args.project_id, f"{args.mode}-{datetime.now(UTC).date().isoformat()}"
        )
        if args.mode != "staging-success":
            result = run_preflight(
                demo, case_id, args.project_id, blocked=args.mode == "preflight-blocked"
            )
            print(json.dumps({"case_id": case_id, "preflight": result}, ensure_ascii=False))
            return 0
        task_payload = json.loads(args.task_json.read_text(encoding="utf-8"))
        if not isinstance(task_payload, dict):
            raise RuntimeError("--task-json must contain a JSON object")
        result = run_preflight(
            demo,
            case_id,
            args.project_id,
            blocked=False,
            flow_id=str(task_payload.get("flow_id", "")),
            sample_sheet=task_payload.get("sample_sheet"),
            comparisons=task_payload.get("comparisons"),
        )
        if result.get("status") != "passed":
            raise RuntimeError(
                "Staging task input did not pass preflight; task submission was not attempted"
            )
        run_staging_success(demo, case_id, task_payload, args.timeout_seconds)
        return 0
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"demo failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

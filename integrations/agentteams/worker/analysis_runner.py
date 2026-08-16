#!/usr/bin/env python3
"""Run approval-gated analysis submissions through the Bridge-owned authorization envelope."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError

from claim_next import claim_next, heartbeat_work_item, submit_approved_work_item


@dataclass(frozen=True)
class AnalysisWorkerConfig:
    bridge_url: str
    token: str
    poll_seconds: float


def load_config(environ: dict[str, str] | None = None) -> AnalysisWorkerConfig:
    values = os.environ if environ is None else environ
    bridge_url = values.get("AGENTTEAMS_BRIDGE_BASE_URL", "").strip()
    token = values.get("AGENTTEAMS_BRIDGE_TOKEN", "").strip()
    if values.get("AGENTTEAMS_WORKER_IDENTITY", "analysis-worker") != "analysis-worker":
        raise ValueError("Analysis runtime requires the analysis-worker identity")
    if not bridge_url or not token:
        raise ValueError("Bridge URL and analysis-worker token are required")
    return AnalysisWorkerConfig(
        bridge_url=bridge_url,
        token=token,
        poll_seconds=max(float(values.get("AGENTTEAMS_WORKER_POLL_SECONDS", "5")), 1.0),
    )


def run_once(config: AnalysisWorkerConfig) -> dict[str, Any]:
    identity = "analysis-worker"
    preview = claim_next(config.bridge_url, identity, config.token, dry_run=True)
    if preview.get("assignment") is None:
        return {"action": "idle", "identity": identity}
    claimed = claim_next(config.bridge_url, identity, config.token)
    assignment = claimed.get("assignment")
    if assignment is None:
        return {"action": "claim_raced", "identity": identity}
    heartbeat_work_item(
        config.bridge_url,
        identity,
        config.token,
        assignment,
        summary="Approved analysis submission started.",
    )
    receipt = submit_approved_work_item(config.bridge_url, identity, config.token, assignment)
    return {
        "action": "submitted",
        "identity": identity,
        "case_id": assignment["case_id"],
        "work_item_id": assignment["work_item"]["work_item_id"],
        "task_id": receipt.get("omic_task_id"),
        "status": receipt.get("status"),
    }


def main() -> int:
    try:
        config = load_config()
    except ValueError as exc:
        print(f"analysis worker configuration failed: {exc}", flush=True)
        return 2
    while True:
        try:
            print(json.dumps(run_once(config), ensure_ascii=False, separators=(",", ":")), flush=True)
        except (HTTPError, URLError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"analysis worker failed: {exc}", flush=True)
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run a constrained, opt-in AgentTeams Worker polling loop.

This runner is for controlled Bridge acceptance exercises.  It never completes a work item unless
the explicit demo switch is enabled, the Case ID has the configured acceptance prefix, and the
assigned work item is read-only.  Production Workers should invoke their own skill runtime after
claiming an assignment instead of enabling this auto-complete mode.
"""

from __future__ import annotations

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError

from claim_next import claim_next, complete_work_item


@dataclass(frozen=True)
class WorkerConfig:
    bridge_url: str
    identity: str
    token: str
    poll_seconds: float
    auto_complete_demo: bool
    acceptance_case_prefix: str
    max_concurrent: int = 2


def _as_bool(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _identity_token(identity: str, identities: str) -> str:
    for entry in identities.split(","):
        configured_identity, separator, token = entry.partition(":")
        if separator and configured_identity.strip() == identity:
            return token.strip()
    return ""


def load_config(environ: dict[str, str] | None = None) -> WorkerConfig:
    values = os.environ if environ is None else environ
    identity = values.get("AGENTTEAMS_WORKER_IDENTITY", "").strip()
    token = values.get("AGENTTEAMS_BRIDGE_TOKEN", "").strip() or _identity_token(
        identity, values.get("BRIDGE_IDENTITIES", "")
    )
    bridge_url = values.get("AGENTTEAMS_BRIDGE_BASE_URL", "").strip()
    if not bridge_url or not identity or not token:
        raise ValueError("Bridge URL, Worker identity, and Bridge token are required")
    return WorkerConfig(
        bridge_url=bridge_url,
        identity=identity,
        token=token,
        poll_seconds=max(float(values.get("AGENTTEAMS_WORKER_POLL_SECONDS", "5")), 1.0),
        auto_complete_demo=_as_bool(values.get("AGENTTEAMS_WORKER_AUTOCOMPLETE_DEMO", "false")),
        acceptance_case_prefix=values.get(
            "AGENTTEAMS_WORKER_ACCEPT_CASE_PREFIX", "agentteams-acceptance-"
        ),
        max_concurrent=max(1, min(int(values.get("AGENTTEAMS_WORKER_MAX_CONCURRENT", "2")), 16)),
    )


def run_once(config: WorkerConfig) -> dict[str, Any]:
    preview = claim_next(config.bridge_url, config.identity, config.token, dry_run=True)
    assignment = preview.get("assignment")
    if assignment is None:
        return {"action": "idle", "identity": config.identity}
    case_id = assignment.get("case_id")
    work_item = assignment.get("work_item")
    eligible = (
        config.auto_complete_demo
        and isinstance(case_id, str)
        and case_id.startswith(config.acceptance_case_prefix)
        and isinstance(work_item, dict)
        and work_item.get("read_only") is True
    )
    if not eligible:
        return {"action": "awaiting_skill_runtime", "identity": config.identity, "case_id": case_id}

    claimed = claim_next(config.bridge_url, config.identity, config.token)
    claimed_assignment = claimed.get("assignment")
    if claimed_assignment is None:
        return {"action": "claim_raced", "identity": config.identity, "case_id": case_id}
    completed = complete_work_item(
        config.bridge_url,
        config.identity,
        config.token,
        claimed_assignment,
        "Controlled AgentTeams acceptance worker completed its read-only assignment.",
    )
    return {
        "action": "completed",
        "identity": config.identity,
        "case_id": claimed_assignment["case_id"],
        "work_item_id": completed["work_item_id"],
    }


def run_batch_once(config: WorkerConfig) -> list[dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=config.max_concurrent) as pool:
        results = list(pool.map(lambda _index: run_once(config), range(config.max_concurrent)))
    return [result for result in results if result.get("action") != "idle"] or [results[0]]


def main() -> int:
    try:
        config = load_config()
    except (TypeError, ValueError) as exc:
        print(f"worker configuration failed: {exc}")
        return 2
    while True:
        try:
            print(json.dumps(run_batch_once(config), ensure_ascii=False, separators=(",", ":")), flush=True)
        except (HTTPError, URLError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"worker poll failed: {exc}", flush=True)
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

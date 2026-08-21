#!/usr/bin/env python3
"""Export one AgentTeams Case through read-only Bridge endpoints.

This program only issues HTTP GET requests. It stores every response verbatim
alongside a normalized event table so a later investigation can distinguish
source records from interpretations.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


TABLE_COLUMNS = (
    "event_id",
    "recorded_at",
    "business_at",
    "event_type",
    "actor",
    "case_status",
    "work_item_id",
    "target",
    "attempt",
    "lease_expires_at",
    "trace_id",
    "context_refs",
    "payload_summary",
    "frontend_message_id",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def get_json(base_url: str, token: str, path: str, query: dict[str, str] | None = None) -> Any:
    suffix = f"?{urlencode(query)}" if query else ""
    request = Request(
        f"{base_url.rstrip('/')}{path}{suffix}",
        headers={"X-Bridge-Token": token, "Accept": "application/json"},
        method="GET",
    )
    with urlopen(request, timeout=20) as response:  # noqa: S310 -- URL supplied explicitly by operator.
        return json.loads(response.read().decode("utf-8"))


def payload_summary(payload: dict[str, Any]) -> str:
    for key in ("summary", "reason", "error", "conclusion", "label"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value[:1000]
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)[:1000]


def first_string(mapping: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = mapping.get(key)
        if value is not None:
            return str(value)
    return ""


def normalize_event(event: dict[str, Any], case: dict[str, Any]) -> dict[str, str]:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return {
        "event_id": first_string(event, "event_id"),
        "recorded_at": first_string(event, "recorded_at"),
        "business_at": first_string(payload, "business_at", "occurred_at", "created_at", "timestamp"),
        "event_type": first_string(event, "event_type"),
        "actor": first_string(event, "actor"),
        "case_status": first_string(payload, "case_status", "status") or first_string(case, "status"),
        "work_item_id": first_string(payload, "work_item_id"),
        "target": first_string(payload, "target", "worker_id", "agent_id"),
        "attempt": first_string(payload, "attempt"),
        "lease_expires_at": first_string(payload, "lease_expires_at"),
        "trace_id": first_string(payload, "trace_id"),
        "context_refs": json.dumps(payload.get("context_refs", []), ensure_ascii=False, default=str),
        "payload_summary": payload_summary(payload),
        "frontend_message_id": first_string(payload, "matrix_event_id", "frontend_message_id", "message_id"),
    }


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_table(path: Path, rows: list[dict[str, str]]) -> None:
    lines = [" | ".join(TABLE_COLUMNS), " | ".join("---" for _ in TABLE_COLUMNS)]
    for row in rows:
        lines.append(" | ".join(row[column].replace("\n", " ").replace("|", "\\|") for column in TABLE_COLUMNS))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only AgentTeams Case evidence export")
    parser.add_argument("--bridge-url", required=True)
    parser.add_argument("--bridge-token", required=True)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()

    output_dir = arguments.output_dir / arguments.case_id
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "collected_at": utc_now(),
        "case_id": arguments.case_id,
        "bridge_url": arguments.bridge_url,
        "method": "GET only",
        "endpoints": [],
    }
    responses: dict[str, Any] = {}
    requests = {
        "case.json": f"/v1/cases/{arguments.case_id}",
        "events.json": f"/v1/cases/{arguments.case_id}/events",
        "manifest.json": f"/v1/cases/{arguments.case_id}/manifest",
    }
    try:
        for filename, path in requests.items():
            query = {"limit": "10000"} if filename == "events.json" else None
            responses[filename] = get_json(arguments.bridge_url, arguments.bridge_token, path, query)
            write_json(output_dir / filename, responses[filename])
            manifest["endpoints"].append({"path": path, "result": "saved"})

        case = responses["case.json"] if isinstance(responses["case.json"], dict) else {}
        task_ids = case.get("omic_task_ids", []) if isinstance(case.get("omic_task_ids"), list) else []
        task_exports: dict[str, dict[str, Any]] = {}
        for task_id in (str(item) for item in task_ids if item):
            task_dir = output_dir / "tasks" / task_id
            task_dir.mkdir(parents=True, exist_ok=True)
            task_exports[task_id] = {}
            for filename, path in {
                "task.json": f"/v1/tasks/{task_id}",
                "events.json": f"/v1/tasks/{task_id}/events",
                "artifacts.json": f"/v1/tasks/{task_id}/artifacts",
            }.items():
                query = {"limit": "10000"} if filename == "events.json" else None
                task_exports[task_id][filename] = get_json(
                    arguments.bridge_url, arguments.bridge_token, path, query
                )
                write_json(task_dir / filename, task_exports[task_id][filename])
                manifest["endpoints"].append({"path": path, "result": "saved"})
        responses["task_exports"] = task_exports
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
        manifest["error"] = f"{type(error).__name__}: {error}"
        write_json(output_dir / "collection-manifest.json", manifest)
        print(manifest["error"], file=sys.stderr)
        return 2

    case = responses["case.json"] if isinstance(responses["case.json"], dict) else {}
    event_response = responses["events.json"] if isinstance(responses["events.json"], dict) else {}
    events = list(event_response.get("events", []))
    for task_export in responses.get("task_exports", {}).values():
        task_event_response = task_export.get("events.json", {})
        if isinstance(task_event_response, dict):
            events.extend(task_event_response.get("events", []))
    rows = [normalize_event(event, case) for event in events if isinstance(event, dict)]
    write_table(output_dir / "event-table.md", rows)
    manifest["event_count"] = len(rows)
    write_json(output_dir / "collection-manifest.json", manifest)
    print(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

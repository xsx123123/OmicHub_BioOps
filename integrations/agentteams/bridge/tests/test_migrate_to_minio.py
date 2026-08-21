"""Tests for the one-shot local-JSON -> MinIO migration tool."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from omichub_agentteams_bridge.migrate_to_minio import (
    MigrationReport,
    _read_local_cases,
    _read_local_events,
    main,
    migrate_local_to_minio,
    reconcile,
)
from test_minio_persistence import FakeMinioClient, make_event, make_storage  # noqa: F401


def write_legacy_files(tmp_path: Path) -> tuple[Path, Path, dict[str, dict[str, Any]]]:
    now = datetime.now(UTC).isoformat()
    cases = {
        "case-a": {
            "case_id": "case-a",
            "project_ref": {"kind": "project", "id": "project-1"},
            "intent": "legacy",
            "requester_ref": "user-1",
            "team_id": "bioops-delivery",
            "status": "closed",
            "created_at": now,
            "updated_at": now,
        }
    }
    case_path = tmp_path / "cases.json"
    case_path.write_text(json.dumps(cases), encoding="utf-8")
    audit_path = tmp_path / "audit.jsonl"
    lines = [
        json.dumps(make_event("case-a", "case.created", "evt-a-1")),
        json.dumps(make_event("case-a", "case.closed", "evt-a-2")),
        json.dumps(make_event("case-b", "case.created", "evt-b-1")),
        "{broken-json",  # 坏行：与本地 _load 的容错口径一致，跳过并计数
    ]
    audit_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return case_path, audit_path, cases


@pytest.mark.asyncio
async def test_migration_writes_minio_and_reconciles(tmp_path: Path) -> None:
    case_path, audit_path, cases = write_legacy_files(tmp_path)
    client = FakeMinioClient()
    storage = make_storage(client)

    report = await migrate_local_to_minio(storage, case_path, audit_path)

    assert report.balanced
    assert report.cases_migrated == 1
    assert report.events_migrated == 3
    assert report.skipped_local_lines == 1
    assert report.per_case == {
        "case-a": {"local": 2, "minio": 2},
        "case-b": {"local": 1, "minio": 1},
    }
    # 事件流与快照都进了 MinIO，且原样保留 event_id
    events = storage.read_events("case-a")
    assert [event["event_id"] for event in events] == ["evt-a-1", "evt-a-2"]
    envelope = storage.read_snapshot("case-a")
    assert envelope is not None
    assert envelope["case"] == cases["case-a"]
    assert envelope["last_event_id"] == "evt-a-2"
    # 旧文件不被删除（人工归档）
    assert case_path.exists() and audit_path.exists()


def test_reconcile_reports_mismatch(tmp_path: Path) -> None:
    case_path, audit_path, _ = write_legacy_files(tmp_path)
    report = MigrationReport()
    local_cases = _read_local_cases(case_path)
    local_events = _read_local_events(audit_path, report)
    # MinIO 里只有 case-a 的一条事件 → 逐 case 对账必须不平
    client = FakeMinioClient()
    storage = make_storage(client)
    client.objects["cases/case-a/events/audit.jsonl"] = (
        json.dumps(make_event("case-a", "case.created", "evt-a-1")) + "\n"
    ).encode()

    reconcile(storage, local_cases, local_events, report)

    assert not report.balanced
    assert any("case-a" in item for item in report.mismatches)
    assert any("case-b" in item for item in report.mismatches)
    assert any("snapshot missing" in item for item in report.mismatches)


def test_main_exits_nonzero_without_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    for variable in (
        "BRIDGE_MINIO_ENDPOINT",
        "BRIDGE_MINIO_ACCESS_KEY",
        "BRIDGE_MINIO_SECRET_KEY",
    ):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.delenv("BRIDGE_ENVIRONMENT", raising=False)
    assert main(["--case-store-path", "x", "--audit-log-path", "y"]) == 2

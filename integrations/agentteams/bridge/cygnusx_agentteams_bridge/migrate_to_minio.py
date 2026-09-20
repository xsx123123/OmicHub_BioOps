"""One-shot migration of legacy local Bridge state (JSON/JSONL files) into MinIO.

用法：

    python -m cygnusx_agentteams_bridge.migrate_to_minio \
        --case-store-path /var/lib/cygnusx-agentteams-bridge/cases.json \
        --audit-log-path /var/lib/cygnusx-agentteams-bridge/audit.jsonl

MinIO 连接参数默认读 BRIDGE_MINIO_* 环境变量（与 BridgeSettings 同口径），
CLI 参数可覆盖。迁移后逐 Case 对账（MinIO 事件数 == 本地事件数、快照齐全），
不平则以非零码退出。旧本地文件绝不删除，请人工归档。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .config import BridgeSettings
from .minio_store import MinioBridgeStorage

logger = logging.getLogger(__name__)


@dataclass
class MigrationReport:
    cases_migrated: int = 0
    events_migrated: int = 0
    skipped_local_lines: int = 0
    per_case: dict[str, dict[str, int]] = field(default_factory=dict)
    mismatches: list[str] = field(default_factory=list)

    @property
    def balanced(self) -> bool:
        return not self.mismatches

    def render(self) -> str:
        lines = [
            f"cases migrated: {self.cases_migrated}",
            f"events migrated: {self.events_migrated}",
            f"skipped corrupt local lines: {self.skipped_local_lines}",
            "per-case reconciliation:",
        ]
        for case_id in sorted(self.per_case):
            counts = self.per_case[case_id]
            status = "OK" if counts["local"] == counts["minio"] else "MISMATCH"
            lines.append(
                f"  {case_id}: local={counts['local']} minio={counts['minio']} [{status}]"
            )
        if self.mismatches:
            lines.append("mismatches:")
            lines.extend(f"  {item}" for item in self.mismatches)
        lines.append(f"result: {'BALANCED' if self.balanced else 'UNBALANCED'}")
        return "\n".join(lines)


def _read_local_cases(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        logger.warning("local case store file does not exist: %s", path)
        return {}
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise RuntimeError(f"local case store file must contain an object: {path}")
    return {str(k): v for k, v in raw.items() if isinstance(v, dict)}


def _read_local_events(path: Path, report: MigrationReport) -> dict[str, list[dict[str, Any]]]:
    events: dict[str, list[dict[str, Any]]] = {}
    if not path.exists():
        logger.warning("local audit log file does not exist: %s", path)
        return events
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            report.skipped_local_lines += 1
            continue
        if not isinstance(event, dict) or not isinstance(event.get("case_id"), str):
            report.skipped_local_lines += 1
            continue
        events.setdefault(event["case_id"], []).append(event)
    return events


def reconcile(
    storage: MinioBridgeStorage,
    local_cases: dict[str, dict[str, Any]],
    local_events: dict[str, list[dict[str, Any]]],
    report: MigrationReport,
) -> MigrationReport:
    """Per-case reconciliation between MinIO and the legacy local files."""
    for case_id in sorted(set(local_cases) | set(local_events)):
        local_count = len(local_events.get(case_id, []))
        minio_count = len(storage.read_events(case_id))
        report.per_case[case_id] = {"local": local_count, "minio": minio_count}
        if local_count != minio_count:
            report.mismatches.append(
                f"case {case_id}: local {local_count} event(s) != MinIO {minio_count} event(s)"
            )
        if case_id in local_cases and storage.read_snapshot(case_id) is None:
            report.mismatches.append(f"case {case_id}: snapshot missing in MinIO")
    return report


async def migrate_local_to_minio(
    storage: MinioBridgeStorage,
    case_store_path: str | Path,
    audit_log_path: str | Path,
) -> MigrationReport:
    """Migrate legacy local state into MinIO and reconcile; never deletes local files."""
    report = MigrationReport()
    local_cases = _read_local_cases(Path(case_store_path))
    local_events = _read_local_events(Path(audit_log_path), report)

    # 先事件后快照：快照 envelope 内嵌的 last_event_id 必须指向已落盘的最后一条事件。
    for case_id, events in local_events.items():
        for event in events:
            await storage.append_event(case_id, event)
        report.events_migrated += len(events)
    for case_id, payload in local_cases.items():
        storage.write_snapshot(case_id, payload)
        report.cases_migrated += 1

    reconcile(storage, local_cases, local_events, report)
    return report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Migrate legacy Bridge local state into MinIO")
    parser.add_argument("--case-store-path", default=None, help="legacy case snapshot JSON path")
    parser.add_argument("--audit-log-path", default=None, help="legacy audit JSONL path")
    parser.add_argument("--minio-endpoint", default=None)
    parser.add_argument("--minio-access-key", default=None)
    parser.add_argument("--minio-secret-key", default=None)
    parser.add_argument("--minio-bucket", default=None)
    parser.add_argument("--minio-secure", action="store_true", default=None)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    args = _build_parser().parse_args(argv)
    settings = BridgeSettings()

    endpoint = args.minio_endpoint or settings.minio_endpoint
    if not endpoint:
        print("error: MinIO endpoint is required (BRIDGE_MINIO_ENDPOINT or --minio-endpoint)")
        return 2
    storage = MinioBridgeStorage(
        endpoint,
        args.minio_access_key or settings.minio_access_key,
        args.minio_secret_key or settings.minio_secret_key,
        args.minio_bucket or settings.minio_bucket,
        bool(args.minio_secure) or settings.minio_secure,
    )
    report = asyncio.run(
        migrate_local_to_minio(
            storage,
            args.case_store_path or settings.case_store_path,
            args.audit_log_path or settings.audit_log_path,
        )
    )
    print(report.render())
    if not report.balanced:
        print("reconciliation FAILED; do not switch traffic. Local files were left untouched.")
        return 1
    print("migration complete. Local files were left untouched; archive them manually:")
    print(f"  {args.case_store_path or settings.case_store_path}")
    print(f"  {args.audit_log_path or settings.audit_log_path}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

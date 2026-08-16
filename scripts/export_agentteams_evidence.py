#!/usr/bin/env python3
"""导出一个 AgentTeams Case 的完整审计证据包到本地目录。

数据全部来自现有 Bridge API（Case、事件、任务、产物、Manifest、指标），不新建存储，
也不修改任何写入路径。输出结构对齐 docs/competition/2026-agentteams-bioops/04_Demo验证与审计证据.md §4.1。

用法：
    uv run python scripts/export_agentteams_evidence.py \
        --case-id <case_id> \
        --output-dir ./evidence

环境：
    需要能访问 OmicHub 数据库以读取 Bridge 运行时配置（URL 与 manager token）。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from omichub.application.services.agentteams_bridge_settings_service import (
    AgentTeamsBridgeSettingsService,
)
from omichub.application.services.agentteams_service import AgentTeamsService
from omichub.core.config import get_settings
from omichub.infrastructure.database.session import close_db, get_session_factory
from sqlalchemy.ext.asyncio import AsyncSession


REPO_ROOT = Path(__file__).resolve().parents[1]


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _ndjson_lines(items: list[dict[str, Any]]) -> str:
    return "".join(json.dumps(item, ensure_ascii=False, default=str) + "\n" for item in items)


def _safe_write(path: Path, payload: dict[str, Any] | list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, list):
        path.write_text(_ndjson_lines(payload), encoding="utf-8")
    else:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


async def _get_service(db: AsyncSession) -> AgentTeamsService:
    settings = get_settings()
    bridge_config = await AgentTeamsBridgeSettingsService(db, settings).get_runtime_config()
    return AgentTeamsService(settings, bridge_config)


async def export_case_evidence(
    case_id: str,
    output_dir: Path,
    db: AsyncSession | None = None,
    service: AgentTeamsService | None = None,
) -> Path:
    if service is None:
        if db is None:
            raise ValueError("必须提供 db 或 service 之一")
        service = await _get_service(db)
    if not service.available:
        raise RuntimeError("AgentTeams Bridge 未配置或已禁用")

    # 1. Case 基本信息（manager 身份直接读取，不校验 requester_ref）
    case = await service.admin_get_case(case_id)
    public_case = service._public_case(case)

    # 2. Case 审计事件
    events_response = await service._request(
        f"/v1/cases/{case_id}/events", params={"limit": 10000}
    )
    events = events_response.get("events") or []

    # 3. Manifest（如果已生成）
    manifest: dict[str, Any] | None = None
    try:
        manifest = await service._request(f"/v1/cases/{case_id}/manifest")
    except Exception:
        manifest = None

    # 4. 任务级详情 / 事件 / 产物
    task_details: list[dict[str, Any]] = []
    task_events: list[dict[str, Any]] = []
    artifact_manifests: list[dict[str, Any]] = []
    for task_id in case.get("omic_task_ids") or []:
        try:
            task = await service._request(f"/v1/tasks/{task_id}")
            task_details.append(task)
        except Exception as exc:
            task_details.append({"task_id": task_id, "error": str(exc)})
        try:
            events_resp = await service._request(
                f"/v1/tasks/{task_id}/events", params={"limit": 10000}
            )
            for event in events_resp.get("events") or []:
                event["task_id"] = task_id
                task_events.append(event)
        except Exception as exc:
            task_events.append({"task_id": task_id, "error": str(exc)})
        try:
            artifacts = await service._request(f"/v1/tasks/{task_id}/artifacts")
            artifact_manifests.append({"task_id": task_id, **artifacts})
        except Exception as exc:
            artifact_manifests.append({"task_id": task_id, "error": str(exc)})

    # 5. Bridge 指标（作为可观测性摘要的一部分）
    try:
        metrics = await service._request("/v1/metrics")
    except Exception as exc:
        metrics = {"error": str(exc)}

    # 6. 按证据包结构拆分
    case_summary = {
        **public_case,
        "exported_at": _now_iso(),
        "task_count": len(case.get("omic_task_ids") or []),
    }
    approvals = [ev for ev in events if str(ev.get("event_type", "")).startswith("approval.")]
    preflight_reports = [
        ev
        for ev in events
        if ev.get("event_type") == "skill.finished"
        and (ev.get("payload") or {}).get("skill_name") == "project-preflight"
    ]
    quality_decision_event = next(
        (ev for ev in events if ev.get("event_type") == "quality.decision"), None
    )
    quality_decision = {
        "case_id": case_id,
        "quality_decision": case.get("quality_decision"),
        "quality_decision_event": quality_decision_event,
        "recorded_at": _now_iso(),
    }

    observability_summary = {
        "case_id": case_id,
        "exported_at": _now_iso(),
        "bridge_metrics": metrics,
        "event_counts": {
            "case_events": len(events),
            "task_events": len(task_events),
            "approval_events": len(approvals),
            "quality_events": 1 if quality_decision_event else 0,
        },
    }

    # 7. 写入 9 个文件
    base = output_dir / f"case/{case_id}"
    _safe_write(base / "case-summary.json", case_summary)
    _safe_write(base / "approvals.json", {"case_id": case_id, "count": len(approvals), "events": approvals})
    _safe_write(
        base / "preflight-report.json",
        {"case_id": case_id, "count": len(preflight_reports), "events": preflight_reports},
    )
    _safe_write(base / "task-events.ndjson", task_events)
    _safe_write(
        base / "artifact-manifest.json",
        {"case_id": case_id, "count": len(artifact_manifests), "artifacts": artifact_manifests},
    )
    _safe_write(base / "quality-decision.json", quality_decision)
    _safe_write(base / "evidence-events.ndjson", events)
    _safe_write(
        base / "delivery-manifest.json",
        manifest or {"case_id": case_id, "note": "Manifest 尚未生成或读取失败"},
    )
    _safe_write(base / "observability-summary.json", observability_summary)

    return base


async def main() -> None:
    parser = argparse.ArgumentParser(description="导出 AgentTeams Case 审计证据包")
    parser.add_argument("--case-id", required=True, help="Case ID")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "evidence",
        help="输出目录（默认 ./evidence）",
    )
    args = parser.parse_args()

    async with get_session_factory()() as db:
        try:
            base = await export_case_evidence(args.case_id, args.output_dir, db)
            print(f"证据包已导出: {base}")
        finally:
            await close_db()


if __name__ == "__main__":
    asyncio.run(main())

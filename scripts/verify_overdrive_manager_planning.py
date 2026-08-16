#!/usr/bin/env python3
"""Verify live Overdrive Manager planning evidence from Postgres and Redis."""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from omichub.application.services.overdrive_planning_telemetry_service import (
    OverdrivePlanningTelemetryService,
)
from omichub.infrastructure.database.models.chat import ChatMessageModel
from omichub.infrastructure.database.models.overdrive import OverdriveRunModel
from omichub.infrastructure.database.session import create_unpooled_engine
from sqlalchemy import select

_ALLOWED_MODES = {"llm", "llm_repaired", "rule_merge", "rule_override", "rule_preflight"}
_FORBIDDEN_SPEECH = (
    "已按系统发育领域契约固定执行链",
    "我会按任务所需的最小专家集合直接处理",
    "已确认这是已有系统发育树的处理与美化任务",
)


@dataclass(frozen=True)
class SessionEvidence:
    session_id: str
    passed: bool
    errors: list[str]
    planning_mode: str
    latency_ms: float | None
    run_id: str
    task_ids: list[str]
    shard_design: bool


def _as_dict(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _task_ids(tasks: Sequence[Mapping[str, Any]]) -> list[str]:
    return [str(item.get("task_id") or "") for item in tasks if item.get("task_id")]


def _depends_transitively(
    downstream_id: str, upstream_ids: set[str], tasks: Sequence[Mapping[str, Any]]
) -> bool:
    by_id = {str(item.get("task_id") or ""): item for item in tasks}
    pending = list(by_id.get(downstream_id, {}).get("depends_on") or [])
    seen: set[str] = set()
    while pending:
        dependency = str(pending.pop())
        if dependency in upstream_ids:
            return True
        if dependency in seen:
            continue
        seen.add(dependency)
        pending.extend(by_id.get(dependency, {}).get("depends_on") or [])
    return False


def evaluate_session(
    session_id: str,
    messages: Sequence[Mapping[str, Any]],
    run: Mapping[str, Any] | None,
    *,
    minimum_latency_ms: float,
    require_phylo_anchors: bool,
    require_shards: bool,
) -> SessionEvidence:
    errors: list[str] = []
    planning_message: Mapping[str, Any] | None = None
    user_message: Mapping[str, Any] | None = None
    latest_user: Mapping[str, Any] | None = None
    for message in messages:
        role = str(message.get("role") or "")
        if role == "user":
            latest_user = message
            continue
        metadata = _as_dict(message.get("metadata_json"))
        if role == "assistant" and metadata.get("planning_mode"):
            planning_message = message
            user_message = latest_user
    if planning_message is None:
        errors.append("未找到带 planning_mode 的 Manager 助手消息")

    planning_mode = ""
    latency_ms: float | None = None
    if planning_message is not None:
        metadata = _as_dict(planning_message.get("metadata_json"))
        planning_mode = str(metadata.get("planning_mode") or "")
        if planning_mode not in _ALLOWED_MODES:
            errors.append(f"非法 planning_mode: {planning_mode or '<empty>'}")
        content = str(planning_message.get("content") or "")
        for forbidden in _FORBIDDEN_SPEECH:
            if forbidden in content:
                errors.append(f"命中禁用模板话术: {forbidden}")
        if user_message is None:
            errors.append("规划消息之前未找到用户消息")
        else:
            user_created = user_message.get("created_at")
            assistant_created = planning_message.get("created_at")
            if isinstance(user_created, datetime) and isinstance(assistant_created, datetime):
                latency_ms = (assistant_created - user_created).total_seconds() * 1000
                if latency_ms < minimum_latency_ms:
                    errors.append(
                        f"用户到 Manager 回复仅 {latency_ms:.1f}ms，低于 {minimum_latency_ms:.1f}ms"
                    )
            else:
                errors.append("消息 created_at 缺失或类型无效")

    run_payload = _as_dict(run)
    run_id = str(run_payload.get("run_id") or "")
    raw_tasks = run_payload.get("tasks")
    tasks = [dict(item) for item in raw_tasks if isinstance(item, Mapping)] if isinstance(raw_tasks, list) else []
    task_ids = _task_ids(tasks)
    shard_ids = {task_id for task_id in task_ids if task_id.startswith("tnpd-homolog-search-")}
    homolog_ids = shard_ids or ({"tnpd-homolog-search"} if "tnpd-homolog-search" in task_ids else set())
    if require_phylo_anchors:
        if not homolog_ids:
            errors.append("计划缺少 tnpd-homolog-search 锚点或其 shard")
        if "tnpd-phylogeny" not in task_ids:
            errors.append("计划缺少 tnpd-phylogeny 锚点")
        elif homolog_ids and not _depends_transitively("tnpd-phylogeny", homolog_ids, tasks):
            errors.append("tnpd-phylogeny 未依赖 homolog-search 锚点/shard")
    serialized_tasks = json.dumps(tasks, ensure_ascii=False).lower()
    shard_design = len(shard_ids) >= 2 or any(
        marker in serialized_tasks for marker in ("shard", "分片", "批次", "并行")
    )
    if require_shards and not shard_design:
        errors.append("大规模计划未检测到分片/批次/并行设计")

    return SessionEvidence(
        session_id=session_id,
        passed=not errors,
        errors=errors,
        planning_mode=planning_mode,
        latency_ms=latency_ms,
        run_id=run_id,
        task_ids=task_ids,
        shard_design=shard_design,
    )


async def _load_session(session_id: str) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    engine = create_unpooled_engine()
    try:
        async with engine.connect() as connection:
            message_rows = (
                await connection.execute(
                    select(
                        ChatMessageModel.role,
                        ChatMessageModel.content,
                        ChatMessageModel.metadata_json,
                        ChatMessageModel.created_at,
                    )
                    .where(ChatMessageModel.session_id == session_id)
                    .order_by(ChatMessageModel.created_at)
                )
            ).mappings().all()
            run_row = (
                await connection.execute(
                    select(
                        OverdriveRunModel.run_id,
                        OverdriveRunModel.tasks,
                        OverdriveRunModel.updated_at,
                    )
                    .where(OverdriveRunModel.session_id == session_id)
                    .order_by(OverdriveRunModel.updated_at.desc())
                    .limit(1)
                )
            ).mappings().first()
            return [dict(row) for row in message_rows], dict(run_row) if run_row else None
    finally:
        await engine.dispose()


async def _run(args: argparse.Namespace) -> int:
    sharded_sessions = set(args.sharded_session_id or [])
    evidence: list[SessionEvidence] = []
    for session_id in args.session_id:
        messages, run = await _load_session(session_id)
        evidence.append(
            evaluate_session(
                session_id,
                messages,
                run,
                minimum_latency_ms=args.minimum_latency_ms,
                require_phylo_anchors=not args.skip_phylo_anchors,
                require_shards=session_id in sharded_sessions,
            )
        )
    telemetry: dict[str, Any] = {}
    if args.check_redis:
        telemetry = await OverdrivePlanningTelemetryService().summary(days=args.redis_days)
        if not any(key.startswith("overdrive_planning_total:") for key in telemetry):
            evidence.append(
                SessionEvidence(
                    session_id="<redis>",
                    passed=False,
                    errors=["Redis 中未查询到 overdrive_planning_total mode 分布"],
                    planning_mode="",
                    latency_ms=None,
                    run_id="",
                    task_ids=[],
                    shard_design=False,
                )
            )
        if int(telemetry.get("overdrive_llm_speech_overridden_total") or 0) != 0:
            evidence.append(
                SessionEvidence(
                    session_id="<redis>",
                    passed=False,
                    errors=["overdrive_llm_speech_overridden_total 非 0"],
                    planning_mode="",
                    latency_ms=None,
                    run_id="",
                    task_ids=[],
                    shard_design=False,
                )
            )
    payload = {
        "passed": all(item.passed for item in evidence),
        "sessions": [item.__dict__ for item in evidence],
        "telemetry": telemetry,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0 if payload["passed"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session-id", action="append", required=True)
    parser.add_argument("--sharded-session-id", action="append", default=[])
    parser.add_argument("--minimum-latency-ms", type=float, default=100.0)
    parser.add_argument("--skip-phylo-anchors", action="store_true")
    parser.add_argument("--check-redis", action="store_true")
    parser.add_argument("--redis-days", type=int, default=1)
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())

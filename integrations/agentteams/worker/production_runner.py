#!/usr/bin/env python3
"""Run a production read-only AgentTeams Worker pool without exposing Gateway credentials.

Each pool replica holds the Bridge tokens for its configured expert identities. Every claim and
execution still uses the matching role credential. The Bridge owns the Gateway Manager token,
validates state/lease/role, and persists the result before returning.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from claim_next import (
    claim_next,
    execute_readonly_work_item,
    heartbeat_work_item,
    record_work_item_failure,
)

_EVIDENCE_TOOLS = [
    "task_result_summary",
    "task_file_preview",
    "workspace_file_preview",
    "workspace_read_file",
    "task_compare_metrics",
    "rule_threshold_lookup",
]


@dataclass(frozen=True)
class ProductionWorkerConfig:
    bridge_url: str
    identity: str
    token: str
    poll_seconds: float
    max_concurrent: int = 2


@dataclass(frozen=True)
class ProductionWorkerPoolConfig:
    workers: tuple[ProductionWorkerConfig, ...]
    poll_seconds: float
    max_concurrent: int = 4


def _identity_token(identity: str, identities: str) -> str:
    for entry in identities.split(","):
        configured_identity, separator, token = entry.partition(":")
        if separator and configured_identity.strip() == identity:
            return token.strip()
    return ""


def _identity_token_env(identity: str) -> str:
    return f"AGENTTEAMS_{identity.upper().replace('-', '_')}_TOKEN"


def load_config(environ: dict[str, str] | None = None) -> ProductionWorkerConfig:
    values = os.environ if environ is None else environ
    identity = values.get("AGENTTEAMS_WORKER_IDENTITY", "").strip()
    token = values.get("AGENTTEAMS_BRIDGE_TOKEN", "").strip() or _identity_token(
        identity, values.get("BRIDGE_IDENTITIES", "")
    )
    bridge_url = values.get("AGENTTEAMS_BRIDGE_BASE_URL", "").strip()
    if not bridge_url or not identity or not token:
        raise ValueError("Bridge URL, Worker identity, and Bridge token are required")
    return ProductionWorkerConfig(
        bridge_url=bridge_url,
        identity=identity,
        token=token,
        poll_seconds=max(float(values.get("AGENTTEAMS_WORKER_POLL_SECONDS", "5")), 1.0),
        max_concurrent=max(1, min(int(values.get("AGENTTEAMS_WORKER_MAX_CONCURRENT", "2")), 16)),
    )


def load_pool_config(environ: dict[str, str] | None = None) -> ProductionWorkerPoolConfig:
    values = os.environ if environ is None else environ
    bridge_url = values.get("AGENTTEAMS_BRIDGE_BASE_URL", "").strip()
    identities = tuple(
        dict.fromkeys(
            identity.strip()
            for identity in values.get(
                "AGENTTEAMS_WORKER_IDENTITIES",
                values.get("AGENTTEAMS_WORKER_IDENTITY", ""),
            ).split(",")
            if identity.strip()
        )
    )
    if not bridge_url or not identities:
        raise ValueError("Bridge URL and at least one Worker identity are required")
    shared_identity_tokens = values.get("BRIDGE_IDENTITIES", "")
    workers: list[ProductionWorkerConfig] = []
    missing_tokens: list[str] = []
    poll_seconds = max(float(values.get("AGENTTEAMS_WORKER_POLL_SECONDS", "5")), 1.0)
    for identity in identities:
        token = (
            values.get(_identity_token_env(identity), "").strip()
            or _identity_token(identity, shared_identity_tokens)
            or (
                values.get("AGENTTEAMS_BRIDGE_TOKEN", "").strip()
                if len(identities) == 1
                else ""
            )
        )
        if not token:
            missing_tokens.append(identity)
            continue
        workers.append(
            ProductionWorkerConfig(
                bridge_url=bridge_url,
                identity=identity,
                token=token,
                poll_seconds=poll_seconds,
                max_concurrent=1,
            )
        )
    if missing_tokens:
        raise ValueError(f"Bridge tokens are required for: {', '.join(missing_tokens)}")
    return ProductionWorkerPoolConfig(
        workers=tuple(workers),
        poll_seconds=poll_seconds,
        max_concurrent=max(
            1, min(int(values.get("AGENTTEAMS_WORKER_MAX_CONCURRENT", "4")), 32)
        ),
    )


def load_worker_profile(config: ProductionWorkerConfig) -> tuple[str, str, tuple[str, ...]]:
    request = Request(
        f"{config.bridge_url.rstrip('/')}/capabilities",
        headers={"X-Bridge-Identity": config.identity, "X-Bridge-Token": config.token},
    )
    with urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    profiles = payload.get("worker_profiles") if isinstance(payload, dict) else None
    profile = profiles.get(config.identity) if isinstance(profiles, dict) else None
    if not isinstance(profile, dict):
        raise ValueError(f"Production runtime does not support identity: {config.identity}")
    agent_id = str(profile.get("agent_id") or "").strip()
    capability = str(profile.get("capability") or "").strip()
    if not agent_id or not capability:
        raise ValueError(f"Bridge returned malformed worker profile: {config.identity}")
    return agent_id, capability, _execution_modes_for(payload, config.identity)


def _execution_modes_for(payload: dict[str, Any], identity: str) -> tuple[str, ...]:
    """Resolve the registry-declared execution modes for an identity.

    ``agent_capabilities`` is keyed by canonical role; alias identities (e.g. data-steward)
    resolve through the snapshot's ``role_aliases`` mapping first.
    """
    capabilities = payload.get("agent_capabilities") if isinstance(payload, dict) else None
    if not isinstance(capabilities, dict):
        return ()
    entry = capabilities.get(identity)
    if not isinstance(entry, dict):
        aliases = payload.get("role_aliases")
        canonical = aliases.get(identity) if isinstance(aliases, dict) else None
        entry = capabilities.get(str(canonical)) if canonical else None
    if not isinstance(entry, dict):
        return ()
    modes = entry.get("execution_modes")
    if not isinstance(modes, list):
        return ()
    return tuple(str(mode) for mode in modes)


def _question(assignment: dict[str, Any]) -> str:
    work_item = assignment.get("work_item")
    if not isinstance(work_item, dict):
        raise RuntimeError("Bridge returned malformed Work Item")
    objective = str(work_item.get("objective") or "")
    refs = work_item.get("context_refs") or []
    execution_mode = str(work_item.get("execution_mode") or "readonly_consultation")
    prefix = (
        "请在 Bridge 指定的受控工作目录中执行任务并登记所有产物；不得修改数据库或提交工作流。\n"
        if execution_mode == "workspace_execution"
        else "请仅基于以下受控任务给出简洁、可核验的只读专业建议；不要执行任务、修改文件、提交工作流或承诺后续操作。\n"
    )
    return prefix + f"任务：{objective}\n逻辑上下文引用：{json.dumps(refs, ensure_ascii=False)}"


def _evidence_refs(assignment: dict[str, Any]) -> list[str]:
    work_item = assignment.get("work_item")
    refs = work_item.get("context_refs") if isinstance(work_item, dict) else []
    result: list[str] = []
    for ref in refs if isinstance(refs, list) else []:
        if not isinstance(ref, dict):
            continue
        kind = str(ref.get("kind") or "").strip()
        ref_id = str(ref.get("id") or "").strip()
        location = str(ref.get("location") or "").strip()
        if kind == "task" and ref_id:
            result.append(f"task:{ref_id}")
        elif kind in {"file", "workspace"} and (location or ref_id):
            value = location or ref_id
            try:
                uuid.UUID(value)
            except ValueError:
                # 已经是工作区相对路径（包含 projects/、inbox/ 或 Worker work 相对路径）。
                result.append(value)
            else:
                # 历史 UUID 只能由平台兼容层映射；未映射值显式标记为不可读，
                # 不再伪造 file:// URI 让预览器把它误判为普通路径。
                result.append(f"legacy-file:{value}")
        elif kind == "s3" and (location or ref_id):
            result.append(location or ref_id)
    return list(dict.fromkeys(result))


def run_once(config: ProductionWorkerConfig) -> dict[str, Any]:
    preview = claim_next(config.bridge_url, config.identity, config.token, dry_run=True)
    if preview.get("assignment") is None:
        return {"action": "idle", "identity": config.identity}

    preview_assignment = preview["assignment"]
    trace_id = uuid.uuid4().hex
    try:
        agent_id, capability, execution_modes = load_worker_profile(config)
    except (HTTPError, URLError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        try:
            record_work_item_failure(
                config.bridge_url,
                config.identity,
                config.token,
                preview_assignment,
                error=str(exc),
                trace_id=trace_id,
            )
        except (HTTPError, URLError, RuntimeError, ValueError, json.JSONDecodeError):
            pass
        raise

    claimed = claim_next(config.bridge_url, config.identity, config.token)
    assignment = claimed.get("assignment")
    if assignment is None:
        return {"action": "claim_raced", "identity": config.identity}

    heartbeat_work_item(
        config.bridge_url,
        config.identity,
        config.token,
        assignment,
        summary="Worker claimed assignment; preflight started.",
        trace_id=trace_id,
    )
    execution_mode = str(assignment["work_item"].get("execution_mode") or "readonly_consultation")
    if execution_mode == "workspace_execution":
        if "workspace_execution" not in execution_modes:
            raise RuntimeError(
                f"Workspace execution is not declared for identity: {config.identity}"
            )
        capability = "workspace_execution"
    heartbeat_work_item(
        config.bridge_url,
        config.identity,
        config.token,
        assignment,
        summary="Production read-only worker started Gateway consultation.",
        trace_id=trace_id,
    )
    result = execute_readonly_work_item(
        config.bridge_url,
        config.identity,
        config.token,
        assignment,
        agent_id=agent_id,
        capability=capability,
        question=_question(assignment),
        evidence_refs=_evidence_refs(assignment),
        requested_tools=_EVIDENCE_TOOLS,
        execution_mode=execution_mode,
        trace_id=trace_id,
    )
    work_item = result.get("work_item_id") or assignment["work_item"]["work_item_id"]
    return {
        "action": "completed" if result.get("status") == "completed" else "manual_review",
        "identity": config.identity,
        "case_id": assignment["case_id"],
        "work_item_id": work_item,
        "status": result.get("status"),
        "trace_id": trace_id,
    }


def run_batch_once(config: ProductionWorkerConfig) -> list[dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=config.max_concurrent) as pool:
        results = list(pool.map(lambda _index: run_once(config), range(config.max_concurrent)))
    return [result for result in results if result.get("action") != "idle"] or [results[0]]


def run_pool_once(config: ProductionWorkerPoolConfig) -> list[dict[str, Any]]:
    with ThreadPoolExecutor(max_workers=min(config.max_concurrent, len(config.workers))) as pool:
        results = list(pool.map(run_once, config.workers))
    return [result for result in results if result.get("action") != "idle"] or [results[0]]


def main() -> int:
    try:
        config = load_pool_config()
    except (TypeError, ValueError) as exc:
        print(f"production worker configuration failed: {exc}", flush=True)
        return 2
    while True:
        try:
            print(
                json.dumps(run_pool_once(config), ensure_ascii=False, separators=(",", ":")), flush=True
            )
        except (HTTPError, URLError, RuntimeError, json.JSONDecodeError) as exc:
            print(f"production worker execution failed: {exc}", flush=True)
        time.sleep(config.poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())

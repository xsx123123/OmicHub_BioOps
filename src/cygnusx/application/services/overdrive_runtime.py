"""超频调度的文件状态机、预算与共享产物运行时。"""

from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from cygnusx.core.config import get_settings
from cygnusx.infrastructure.studio.manager import studio_sandbox_manager

_DEFAULT_LIMITS: dict[str, Any] = {
    "summary_chars": 1500,
    "upstream_context_chars": 8000,
    "task_instruction_chars": 20000,
    "max_tasks_per_session": 12,
    "max_parallel_per_wave": 4,
    "chain_wall_timeout_minutes": 45,
    "stall_threshold_seconds": 120,
    "max_intake_rounds": 3,
    "max_repair_rounds": 1,
    "planning": {"max_revision_rounds": 3},
    "research": {
        "source_timeout_seconds": 20,
        "model_timeout_seconds": 45,
        "max_evidence_items_per_source": 8,
        "wall_timeout_seconds": 75,
    },
    "manager_review": {
        "rule_fast_path": True,
        "max_tokens": 1200,
        "timeout_seconds": 30,
    },
    "default_retry": {"max_attempts": 2, "backoff_seconds": 30},
    "default_timeout_seconds": 1800,
    "agents": {},
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def load_overdrive_limits(agent_id: str | None = None) -> dict[str, Any]:
    path = Path(__file__).resolve().parents[4] / "data" / "ai" / "_overdrive_limits.yaml"
    limits = deepcopy(_DEFAULT_LIMITS)
    if path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(loaded, dict):
            limits.update(loaded)
    overrides = (limits.get("agents") or {}).get(agent_id or "", {})
    if isinstance(overrides, dict):
        limits.update(overrides)
    return limits


def overdrive_root(session_id: str) -> Path:
    workspace = studio_sandbox_manager.workspace_dir(session_id)
    try:
        studio_sandbox_manager.ensure_workspace_dirs(workspace)
    except OSError:
        workspace = Path(get_settings().storage_path) / "studio" / session_id
        try:
            studio_sandbox_manager.ensure_workspace_dirs(workspace)
        except OSError:
            workspace = Path("/tmp/cygnusx-overdrive-workspaces") / session_id
            studio_sandbox_manager.ensure_workspace_dirs(workspace)
    return workspace / "output" / "overdrive" / session_id


def relative_overdrive_root(session_id: str) -> str:
    return f"output/overdrive/{session_id}"


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(content, encoding="utf-8")
    os.replace(temporary, path)


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    _atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n")


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def normalize_retry(value: Any, limits: dict[str, Any]) -> dict[str, int]:
    configured = value if isinstance(value, dict) else {}
    defaults = limits.get("default_retry") or {}
    return {
        "max_attempts": max(1, min(5, int(configured.get("max_attempts") or defaults.get("max_attempts") or 2))),
        "backoff_seconds": max(0, min(300, int(configured.get("backoff_seconds") or defaults.get("backoff_seconds") or 30))),
    }


def normalize_contract_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return list(dict.fromkeys(str(item).strip() for item in value if str(item).strip()))[:20]


def infer_contract_dependencies(assignments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    producers: dict[str, list[str]] = {}
    for assignment in assignments:
        for output in assignment.get("produces_outputs") or []:
            producers.setdefault(output, []).append(assignment["task_id"])
    for assignment in assignments:
        dependencies = list(assignment.get("depends_on") or [])
        for required_input in assignment.get("accepts_inputs") or []:
            candidates = [
                task_id
                for task_id in producers.get(required_input, [])
                if task_id != assignment["task_id"]
            ]
            if len(candidates) == 1 and candidates[0] not in dependencies:
                dependencies.append(candidates[0])
        assignment["depends_on"] = dependencies
    return assignments


def assignment_waves(
    assignments: list[dict[str, Any]], *, max_parallel: int
) -> tuple[list[list[dict[str, Any]]], list[str]]:
    remaining = list(assignments)
    completed: set[str] = set()
    waves: list[list[dict[str, Any]]] = []
    warnings: list[str] = []
    while remaining:
        ready = [
            item for item in remaining if set(item.get("depends_on") or []).issubset(completed)
        ]
        if not ready:
            blocked = ", ".join(item["task_id"] for item in remaining)
            warnings.append(f"检测到循环依赖，已按原顺序拆分：{blocked}")
            ready = [remaining[0]]
        ready.sort(key=lambda item: {"high": 0, "normal": 1, "low": 2}.get(item.get("priority"), 1))
        for offset in range(0, len(ready), max(1, max_parallel)):
            waves.append(ready[offset : offset + max(1, max_parallel)])
        ready_ids = {item["task_id"] for item in ready}
        completed.update(ready_ids)
        remaining = [item for item in remaining if item["task_id"] not in ready_ids]
    return waves, warnings


class OverdriveManifest:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.root = overdrive_root(session_id)
        self.path = self.root / "manifest.json"
        self.control_path = self.root / "control.json"

    def load(self) -> dict[str, Any]:
        return read_json(self.path)

    def initialize(
        self, *, run_id: str, request: str, assignments: list[dict[str, Any]]
    ) -> dict[str, Any]:
        existing = self.load()
        resume_requested = existing.get("request") == request or any(
            marker in request.lower() for marker in ("继续上次", "恢复上次", "resume")
        )
        if (
            resume_requested
            and existing.get("status") in {"running", "paused"}
            and existing.get("tasks")
        ):
            changed = False
            for task in existing["tasks"]:
                if task.get("status") == "running":
                    task["status"] = "ready"
                    task["error_summary"] = "服务中断后恢复，任务将重新执行"
                    changed = True
            if changed:
                existing["updated_at"] = utc_now()
                atomic_write_json(self.path, existing)
            return existing
        tasks = []
        relative_root = relative_overdrive_root(self.session_id)
        for assignment in assignments:
            task_id = assignment["task_id"]
            task_root = f"{relative_root}/tasks/{task_id}"
            tasks.append(
                {
                    **assignment,
                    "status": "pending",
                    "attempt": 0,
                    "artifacts": {
                        "result": f"{task_root}/result.md",
                        "summary": f"{task_root}/summary.md",
                        "progress": f"{task_root}/progress.log",
                    },
                    "error_summary": "",
                    "started_at": None,
                    "finished_at": None,
                    "last_event_at": None,
                }
            )
        payload = {
            "version": 1,
            "session_id": self.session_id,
            "run_id": run_id,
            "request": request,
            "status": "running",
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "tasks": tasks,
        }
        atomic_write_json(self.path, payload)
        atomic_write_json(self.control_path, {"action": "run", "updated_at": utc_now()})
        return payload

    def update_task(self, task_id: str, status: str, **fields: Any) -> dict[str, Any]:
        manifest = self.load()
        for task in manifest.get("tasks") or []:
            if task.get("task_id") != task_id:
                continue
            task["status"] = status
            task.update(fields)
            if status == "running" and not task.get("started_at"):
                task["started_at"] = utc_now()
            if status in {"succeeded", "failed", "skipped"}:
                task["finished_at"] = utc_now()
            task["last_event_at"] = utc_now()
            break
        manifest["updated_at"] = utc_now()
        atomic_write_json(self.path, manifest)
        return manifest

    def set_status(self, status: str) -> dict[str, Any]:
        manifest = self.load()
        manifest["status"] = status
        manifest["updated_at"] = utc_now()
        atomic_write_json(self.path, manifest)
        return manifest

    def write_artifacts(self, task_id: str, result: str, summary_chars: int) -> dict[str, str]:
        task_root = self.root / "tasks" / task_id
        summary = extract_summary(result, summary_chars)
        _atomic_write(task_root / "result.md", result.rstrip() + "\n")
        _atomic_write(task_root / "summary.md", summary.rstrip() + "\n")
        self.append_progress(task_id, "产出已原子落盘")
        return {
            "result": f"{relative_overdrive_root(self.session_id)}/tasks/{task_id}/result.md",
            "summary": f"{relative_overdrive_root(self.session_id)}/tasks/{task_id}/summary.md",
            "progress": f"{relative_overdrive_root(self.session_id)}/tasks/{task_id}/progress.log",
        }

    def append_progress(self, task_id: str, message: str) -> None:
        path = self.root / "tasks" / task_id / "progress.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(f"{utc_now()} {message}\n")

    def progress_tail(self, task_id: str, lines: int = 50) -> str:
        path = self.root / "tasks" / task_id / "progress.log"
        if not path.exists():
            return ""
        return "\n".join(path.read_text(encoding="utf-8").splitlines()[-lines:])

    def read_summary(self, task_id: str, limit: int) -> str:
        path = self.root / "tasks" / task_id / "summary.md"
        return path.read_text(encoding="utf-8")[:limit] if path.exists() else ""

    def control(self) -> dict[str, Any]:
        return read_json(self.control_path)

    def write_control(self, action: str, *, task_id: str = "", directive: str = "") -> dict[str, Any]:
        payload = {
            "action": action,
            "task_id": task_id,
            "directive": directive,
            "updated_at": utc_now(),
        }
        atomic_write_json(self.control_path, payload)
        return payload

    def consume_directive(self) -> str:
        control = self.control()
        directive = str(control.get("directive") or "").strip()
        if directive:
            control["directive"] = ""
            control["updated_at"] = utc_now()
            atomic_write_json(self.control_path, control)
        return directive


def extract_summary(result: str, limit: int) -> str:
    text = result.strip()
    match = re.search(r"(?:^|\n)#{1,3}\s*(?:执行)?摘要\s*\n(.+?)(?=\n#{1,3}\s|\Z)", text, re.S)
    return (match.group(1).strip() if match else text)[: max(1, limit)]


def build_upstream_context(
    manifest: OverdriveManifest,
    dependency_ids: list[str],
    *,
    summary_chars: int,
    total_chars: int,
) -> str:
    if not dependency_ids:
        return ""
    sections = []
    paths = []
    for task_id in dependency_ids:
        summary = manifest.read_summary(task_id, summary_chars) or "上游未提供摘要，请检查 manifest 状态。"
        sections.append(f"【{task_id}】\n{summary}")
        paths.append(
            f"- {task_id} 完整产物: {relative_overdrive_root(manifest.session_id)}/tasks/{task_id}/result.md"
        )
    content = (
        "## 上游产物摘要（必读）\n"
        + "\n\n".join(sections)
        + "\n\n## 上游产物位置（按需读取）\n"
        + "\n".join(paths)
        + f"\n- 产物清单与状态: {relative_overdrive_root(manifest.session_id)}/manifest.json\n\n"
        "必须基于上游产物继续工作；需要细节时用 workspace_read 读取完整产物，不得忽略依赖重新回答。"
    )
    return content[: max(1, total_chars)]

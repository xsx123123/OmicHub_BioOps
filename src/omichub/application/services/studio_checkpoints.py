"""OmicStudio 工作区 Git 检查点。"""

from __future__ import annotations

import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from omichub.infrastructure.mcp.presets import _BINARY_ONLY_SUFFIXES
from omichub.infrastructure.studio.manager import studio_sandbox_manager

_MAX_CHECKPOINTS = 20
_MAX_TRACKED_BYTES = 10 * 1024 * 1024
_CHECKPOINT_REF_PREFIX = "refs/studio-checkpoints/"
_GITIGNORE = "\n".join(
    (
        "input/",
        "# Files larger than 10MB are excluded by the Studio checkpoint filter.",
        ".env",
        "*.key",
        "*.pem",
        "secrets/",
        *(f"*{suffix}" for suffix in sorted(_BINARY_ONLY_SUFFIXES)),
        "",
    )
)


def _run(workspace: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=workspace, text=True, capture_output=True, check=False
    )


def ensure_checkpoint_repository(session_id: str) -> Path:
    workspace = studio_sandbox_manager.workspace_dir(session_id)
    workspace.mkdir(parents=True, exist_ok=True)
    if not (workspace / ".git").exists():
        _run(workspace, "init", "-q")
    if not _run(workspace, "config", "user.email").stdout.strip():
        _run(workspace, "config", "user.email", "studio@omichub.local")
    if not _run(workspace, "config", "user.name").stdout.strip():
        _run(workspace, "config", "user.name", "OmicHub Studio")
    gitignore = workspace / ".gitignore"
    existing_ignore = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
    missing_rules = [rule for rule in _GITIGNORE.splitlines() if rule and rule not in existing_ignore]
    if missing_rules:
        prefix = "" if not existing_ignore or existing_ignore.endswith("\n") else "\n"
        gitignore.write_text(existing_ignore + prefix + "\n".join(missing_rules) + "\n", encoding="utf-8")
    return workspace


def _skip_large_files(workspace: Path) -> list[str]:
    skipped: list[str] = []
    for path in workspace.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            if path.stat().st_size > _MAX_TRACKED_BYTES:
                skipped.append(path.relative_to(workspace).as_posix())
        except OSError:
            continue
    return skipped


def _checkpoint_rows(workspace: Path) -> list[tuple[str, str, str, str]]:
    result = _run(
        workspace,
        "for-each-ref",
        "--sort=-refname",
        "--format=%(objectname)%09%(creatordate:iso-strict)%09%(subject)%09%(refname)",
        _CHECKPOINT_REF_PREFIX,
    )
    rows: list[tuple[str, str, str, str]] = []
    for line in result.stdout.splitlines():
        parts = line.split("\t", 3)
        if len(parts) == 4:
            rows.append((parts[0], parts[1], parts[2], parts[3]))
    return rows


def create_checkpoint(session_id: str, tool_call_id: str = "") -> dict[str, Any]:
    workspace = ensure_checkpoint_repository(session_id)
    skipped = _skip_large_files(workspace)
    if skipped:
        exclude = workspace / ".git" / "info" / "exclude"
        existing = exclude.read_text(encoding="utf-8") if exclude.exists() else ""
        additions = "\n".join(skipped) + "\n"
        if additions not in existing:
            exclude.write_text(existing + additions, encoding="utf-8")
    added = _run(workspace, "add", "-A")
    if added.returncode != 0:
        raise RuntimeError(added.stderr.strip() or "无法暂存工作区检查点")
    tree = _run(workspace, "write-tree")
    if tree.returncode != 0:
        raise RuntimeError(tree.stderr.strip() or "无法创建工作区快照")
    timestamp = datetime.now(UTC).isoformat(timespec="microseconds")
    message = f"studio checkpoint {tool_call_id or 'manual'} {timestamp}"
    committed = _run(workspace, "commit-tree", tree.stdout.strip(), "-m", message)
    if committed.returncode != 0:
        raise RuntimeError(committed.stderr.strip() or "无法创建工作区检查点")
    checkpoint_id = committed.stdout.strip()
    ref_name = f"{_CHECKPOINT_REF_PREFIX}{timestamp.replace(':', '').replace('+', '_')}-{checkpoint_id[:12]}"
    updated = _run(workspace, "update-ref", ref_name, checkpoint_id)
    if updated.returncode != 0:
        raise RuntimeError(updated.stderr.strip() or "无法登记工作区检查点")
    _prune_checkpoints(workspace)
    changed = _run(workspace, "show", "--format=", "--name-only", "--no-renames", checkpoint_id)
    files = [line for line in changed.stdout.splitlines() if line.strip()]
    return {
        "checkpoint_id": checkpoint_id,
        "created_at": timestamp,
        "tool_call_id": tool_call_id,
        "changed_files": len(files),
        "skipped": skipped,
    }


def _prune_checkpoints(workspace: Path) -> None:
    for _, _, _, ref_name in _checkpoint_rows(workspace)[_MAX_CHECKPOINTS:]:
        _run(workspace, "update-ref", "-d", ref_name)


def list_checkpoints(session_id: str) -> list[dict[str, Any]]:
    workspace = ensure_checkpoint_repository(session_id)
    checkpoints = []
    for checkpoint_id, created_at, message, _ in _checkpoint_rows(workspace)[:_MAX_CHECKPOINTS]:
        files = _run(workspace, "show", "--format=", "--name-only", checkpoint_id)
        checkpoints.append(
            {
                "checkpoint_id": checkpoint_id,
                "created_at": created_at,
                "message": message,
                "tool_call_id": message.split(" ", 3)[2] if message.startswith("studio checkpoint ") else "",
                "changed_files": len([item for item in files.stdout.splitlines() if item.strip()]),
            }
        )
    return checkpoints


def restore_checkpoint(session_id: str, checkpoint_id: str) -> dict[str, Any]:
    create_checkpoint(session_id, "restore-before")
    workspace = ensure_checkpoint_repository(session_id)
    result = _run(workspace, "reset", "--hard", checkpoint_id)
    if result.returncode != 0:
        raise ValueError(result.stderr.strip() or "检查点不存在")
    return {"checkpoint_id": checkpoint_id, "restored": True}

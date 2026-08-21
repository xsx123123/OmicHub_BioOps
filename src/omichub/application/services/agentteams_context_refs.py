"""Preflight validation for AgentTeams context references."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

SUPPORTED_URI_SCHEMES = frozenset({"s3"})


@dataclass(frozen=True)
class ContextRefCheck:
    ref: dict[str, Any]
    category: str
    readable: bool
    reason: str


def _value(ref: dict[str, Any]) -> str:
    for key in ("location", "path", "uri", "id"):
        value = ref.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def check_context_ref(
    ref: dict[str, Any], *, workspace_root: Path | None = None
) -> ContextRefCheck:
    """Classify one ref without dereferencing remote resources."""
    raw = _value(ref)
    parsed = urlparse(raw)
    if parsed.scheme:
        if parsed.scheme in SUPPORTED_URI_SCHEMES:
            return ContextRefCheck(ref, "uri", True, f"{parsed.scheme} URI 有专用产物解析工具")
        return ContextRefCheck(ref, "unreadable", False, f"不支持的 URI 协议: {parsed.scheme}")

    if not raw:
        return ContextRefCheck(ref, "unreadable", False, "未提供可解析的逻辑引用")

    path = PurePosixPath(raw.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts:
        return ContextRefCheck(ref, "unreadable", False, "工作区路径必须是安全的相对路径")
    if ref.get("kind") not in {"workspace", "file", "project", "path"}:
        return ContextRefCheck(ref, "unreadable", False, "未注册的逻辑引用类型")

    if workspace_root is not None:
        candidate = (workspace_root / Path(*path.parts)).resolve()
        try:
            candidate.relative_to(workspace_root.resolve())
        except ValueError:
            return ContextRefCheck(ref, "unreadable", False, "工作区路径越界")
        if not candidate.exists():
            return ContextRefCheck(ref, "unreadable", False, "路径不存在")
        if not candidate.is_file():
            return ContextRefCheck(ref, "unreadable", False, "路径是目录，不是普通文件")
    return ContextRefCheck(ref, "workspace", True, "工作区相对路径")


def check_context_refs(
    refs: list[dict[str, Any]], *, workspace_root: Path | None = None
) -> list[ContextRefCheck]:
    return [check_context_ref(ref, workspace_root=workspace_root) for ref in refs]

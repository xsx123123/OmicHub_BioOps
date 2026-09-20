"""Controlled Session workspace references for files, uploads, and user directories."""

from __future__ import annotations

import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.studio_context_service import import_datahub_file
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import BusinessError, NotFoundError, CygnusXError
from cygnusx.infrastructure.database.models.chat import ChatSessionModel
from cygnusx.infrastructure.database.models.file import DirectoryModel
from cygnusx.infrastructure.storage import get_path_factory
from cygnusx.infrastructure.studio.manager import studio_sandbox_manager
from cygnusx.infrastructure.studio.workspace import link_platform_directory

_UPLOAD_REF_RE = re.compile(r"^upload://[a-fA-F0-9]{16,128}$")


@dataclass(frozen=True)
class WorkspaceResourceRef:
    kind: Literal["file", "upload", "directory"]
    resource_id: str
    resource_ref: str


@dataclass(frozen=True)
class WorkspaceDirectoryManifest:
    resource_ref: str
    sandbox_path: str
    recursive: bool
    file_count: int
    total_size_bytes: int
    snapshot_at: str
    entries: list[dict[str, Any]]
    truncated: bool
    next_cursor: str | None
    status: str = "ready"

    def summary(self) -> dict[str, Any]:
        data = asdict(self)
        data.pop("entries", None)
        return data


def parse_workspace_resource_ref(ref: str) -> WorkspaceResourceRef:
    """Normalize and validate a controlled workspace reference exactly once."""
    value = str(ref or "").strip()
    if value.startswith("file://") or value.startswith("directory://"):
        scheme, raw_id = value.split("://", 1)
        try:
            resource_id = str(uuid.UUID(raw_id))
        except ValueError as exc:
            raise BusinessError("工作区资源引用格式非法") from exc
        kind = "directory" if scheme == "directory" else "file"
        return WorkspaceResourceRef(kind=kind, resource_id=resource_id, resource_ref=f"{scheme}://{resource_id}")
    if _UPLOAD_REF_RE.fullmatch(value):
        return WorkspaceResourceRef(kind="upload", resource_id=value.removeprefix("upload://"), resource_ref=value)
    raise BusinessError("仅支持 file://、upload:// 和 directory:// 受控引用")


def _directory_physical_path(user_root: Path, directory: DirectoryModel) -> Path:
    """Map the legacy directory model to its local storage location without path escape."""
    rel = Path(directory.path)
    if rel.is_absolute() or ".." in rel.parts or not directory.path.strip("/"):
        raise BusinessError("目录路径异常")
    candidates = [user_root / rel]
    if rel.parts[0] == "inbox":
        candidates.append(user_root / rel)
    else:
        candidates.append(user_root / "inbox" / rel)
    root_real = user_root.resolve()
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        if resolved != root_real and root_real in resolved.parents and resolved.is_dir():
            return resolved
    raise NotFoundError("目录不存在或不可访问")


async def validate_workspace_resource_owner(
    user_id: str,
    ref: str,
    db: AsyncSession,
) -> WorkspaceResourceRef:
    """Verify a controlled reference is owned by the active user before workspace use."""
    parsed = parse_workspace_resource_ref(ref)
    if parsed.kind != "directory":
        return parsed
    try:
        owner_id = uuid.UUID(str(user_id))
        directory_id = uuid.UUID(parsed.resource_id)
    except ValueError as exc:
        raise BusinessError("目录引用格式非法") from exc
    directory = await db.scalar(
        select(DirectoryModel).where(
            DirectoryModel.id == directory_id,
            DirectoryModel.user_id == owner_id,
        )
    )
    if directory is None:
        raise NotFoundError("目录不存在或无权访问")
    if directory.is_system:
        raise BusinessError("系统根目录不能作为工作区引用，请选择其中的具体数据目录")
    _directory_physical_path(get_path_factory().user_root(str(user_id)), directory)
    return parsed


def _build_directory_manifest(
    directory: Path,
    *,
    resource_ref: str,
    sandbox_path: str,
    recursive: bool,
) -> WorkspaceDirectoryManifest:
    settings = get_settings()
    max_files = settings.workspace_directory_max_files
    max_total_bytes = settings.workspace_directory_max_total_bytes
    page_size = settings.workspace_directory_manifest_page_size
    deadline = time.monotonic() + settings.workspace_directory_scan_timeout_seconds
    entries: list[dict[str, Any]] = []
    file_count = 0
    total_size = 0
    truncated = False
    status = "ready"
    stack = [directory]
    root_real = directory.resolve()
    while stack:
        current = stack.pop()
        try:
            children = sorted(os.scandir(current), key=lambda item: item.name.casefold())
        except OSError:
            continue
        for entry in children:
            if time.monotonic() > deadline:
                truncated, status = True, "scan_timeout"
                stack.clear()
                break
            try:
                if entry.is_symlink():
                    continue
                rel = Path(entry.path).relative_to(root_real).as_posix()
                if entry.is_dir(follow_symlinks=False):
                    if len(entries) < page_size:
                        entries.append({"path": rel + "/", "type": "directory"})
                    else:
                        truncated = True
                    if recursive:
                        stack.append(Path(entry.path))
                    continue
                if not entry.is_file(follow_symlinks=False):
                    continue
                size = entry.stat(follow_symlinks=False).st_size
            except OSError:
                continue
            file_count += 1
            total_size += size
            if len(entries) < page_size:
                entries.append({"path": rel, "type": "file", "size": size})
            else:
                truncated = True
            if file_count >= max_files:
                truncated, status = True, "file_limit"
                stack.clear()
                break
            if total_size > max_total_bytes:
                truncated, status = True, "size_limit"
                stack.clear()
                break
    next_cursor = str(len(entries)) if truncated else None
    return WorkspaceDirectoryManifest(
        resource_ref=resource_ref,
        sandbox_path=sandbox_path,
        recursive=recursive,
        file_count=file_count,
        total_size_bytes=total_size,
        snapshot_at=datetime.now(UTC).isoformat(),
        entries=entries,
        truncated=truncated,
        next_cursor=next_cursor,
        status=status,
    )


async def link_session_workspace_refs(
    user_id: str,
    session_id: str,
    refs: list[str],
    db: AsyncSession,
) -> tuple[dict[str, str], dict[str, dict[str, Any]], dict[str, str]]:
    """Idempotently introduce controlled references into one Session workspace.

    Returns ``(paths, manifests, errors)``.  Every ref is checked independently so a
    bad attachment cannot prevent valid user-selected inputs from being introduced.
    """
    session = await db.scalar(
        select(ChatSessionModel).where(
            ChatSessionModel.session_id == session_id,
            ChatSessionModel.user_id == str(user_id),
        )
    )
    if session is None:
        raise NotFoundError("会话不存在或无权访问")

    paths: dict[str, str] = {}
    manifests: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}
    existing = dict(session.sandbox_meta or {})
    existing_refs = {
        str(item.get("resource_ref")): item
        for item in existing.get("workspace_resources", [])
        if isinstance(item, dict) and item.get("resource_ref")
    }
    for raw_ref in dict.fromkeys(str(value or "").strip() for value in refs):
        if not raw_ref:
            continue
        try:
            parsed = await validate_workspace_resource_owner(user_id, raw_ref, db)
            if parsed.kind != "directory":
                payload = await import_datahub_file(
                    user_id=user_id,
                    session_id=session_id,
                    file_id=parsed.resource_ref,
                    name=None,
                    db=db,
                    idempotent=True,
                )
                paths[parsed.resource_ref] = payload["sandbox_path"]
                existing_refs.setdefault(
                    parsed.resource_ref,
                    {
                        "resource_ref": parsed.resource_ref,
                        "resource_type": parsed.kind,
                        "permission": "read",
                        "sandbox_path": payload["sandbox_path"],
                    },
                )
                continue

            directory = await db.get(DirectoryModel, uuid.UUID(parsed.resource_id))
            if directory is None:
                raise NotFoundError("目录不存在或无权访问")
            physical = _directory_physical_path(get_path_factory().user_root(str(user_id)), directory)
            workspace = studio_sandbox_manager.workspace_dir(session_id)
            studio_sandbox_manager.ensure_workspace_dirs(workspace)
            # The container mounts users/{user_id} at /data/platform, so the target is relative to it.
            mount_rel = physical.relative_to(get_path_factory().user_root(str(user_id)).resolve()).as_posix()
            link_name = link_platform_directory(workspace, mount_rel, directory.name, idempotent=True)
            sandbox_path = f"/workspace/input/{link_name}/"
            manifest = _build_directory_manifest(
                physical,
                resource_ref=parsed.resource_ref,
                sandbox_path=sandbox_path,
                recursive=True,
            )
            paths[parsed.resource_ref] = sandbox_path
            manifests[parsed.resource_ref] = asdict(manifest)
            existing_refs[parsed.resource_ref] = {
                "resource_ref": parsed.resource_ref,
                "resource_type": "directory",
                "permission": "read",
                "recursive": True,
                "sandbox_path": sandbox_path,
                "manifest_summary": manifest.summary(),
            }
        except CygnusXError as exc:
            errors[raw_ref] = exc.detail
        except Exception as exc:  # noqa: BLE001
            logger.warning("工作区资源引入失败 ref={}: {}", raw_ref, exc)
            errors[raw_ref] = "资源引入失败"
    existing["workspace_resources"] = list(existing_refs.values())
    session.sandbox_meta = existing
    await db.flush()
    return paths, manifests, errors

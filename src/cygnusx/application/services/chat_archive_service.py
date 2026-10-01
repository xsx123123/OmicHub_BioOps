"""普通 AI 助手会话的分析运行归档。

聊天沙盒仍保持轻量执行契约，但每个会话现在拥有一个可持续更新的 run 目录。
归档格式复用 project_archive_service，避免 Studio、超频协作和普通助手产生三套
不可互操作的 README/environment/manifest 格式。
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.project_archive_service import (
    ArchivedFile,
    ProjectInfo,
    archive_run,
    collect_environment,
    md5_stream,
    sha256_stream,
)
from cygnusx.core.config import get_settings
from cygnusx.infrastructure.database.models.chat import ChatMessageModel, ChatSessionModel
from cygnusx.infrastructure.database.models.project import ProjectModel
from cygnusx.infrastructure.storage import get_path_factory
from cygnusx.infrastructure.storage.file_registry import FileRegistry
from cygnusx.domain.file.value_objects import FileSource


CHAT_ARCHIVE_KEY = "analysis_archive"
CHAT_ARCHIVE_SCHEMA_VERSION = 1


@dataclass
class ChatArchiveContext:
    session: ChatSessionModel
    project: ProjectInfo
    run_dir: Path
    metadata: dict[str, Any]


def _safe_relpath(value: str) -> str | None:
    path = PurePosixPath(str(value or ""))
    if not path.parts or path.is_absolute() or ".." in path.parts:
        return None
    return path.as_posix()


async def _project_for_session(
    db: AsyncSession, user_id: str, session: ChatSessionModel
) -> ProjectInfo:
    project_id = str(session.project_id or "").strip()
    if project_id:
        try:
            model = await db.get(ProjectModel, UUID(project_id))
        except (ValueError, TypeError):
            model = None
        if model is not None and str(model.user_id) == user_id:
            return ProjectInfo(
                name=model.name,
                slug=model.slug,
                description=model.description or "",
                customer=str(getattr(model, "customer", "") or ""),
                created_at=model.created_at.isoformat() if model.created_at else "",
            )
    title = str(session.title or "").strip() or f"chat-{session.session_id[:8]}"
    return ProjectInfo(name=f"AI助手-{title}")


async def ensure_chat_archive(
    db: AsyncSession, user_id: str, session_id: str
) -> ChatArchiveContext | None:
    """为会话创建或恢复唯一的分析 run 目录，并写回 sandbox_meta。"""
    session = await db.scalar(
        select(ChatSessionModel).where(ChatSessionModel.session_id == str(session_id))
    )
    if session is None or str(session.user_id) != str(user_id):
        return None
    factory = get_path_factory()
    project = await _project_for_session(db, str(user_id), session)
    marker = (session.sandbox_meta or {}).get(CHAT_ARCHIVE_KEY)
    run_dir: Path | None = None
    if isinstance(marker, dict):
        run_relative = _safe_relpath(str(marker.get("run_directory") or ""))
        if run_relative:
            candidate = factory.data_root / run_relative
            if factory.is_within_root(candidate) and candidate.is_dir():
                run_dir = candidate
    if run_dir is None:
        run_dir = factory.create_project_run_dir(
            str(user_id), project.name, f"chat-{str(session_id)[:8]}"
        )
    run_relative = factory.relative_to_root(run_dir)
    metadata = dict(marker) if isinstance(marker, dict) else {}
    metadata.update(
        {
            "schema_version": CHAT_ARCHIVE_SCHEMA_VERSION,
            "project_slug": project.slug,
            "run_name": run_dir.name,
            "run_directory": run_relative,
            "readme": f"{run_relative}/README.md",
            "environment": f"{run_relative}/environment.json",
            "manifest": f"{run_relative}/manifest.json",
            "updated_at": datetime.now(UTC).isoformat(),
        }
    )
    session.sandbox_meta = {**(session.sandbox_meta or {}), CHAT_ARCHIVE_KEY: metadata}
    return ChatArchiveContext(session=session, project=project, run_dir=run_dir, metadata=metadata)


async def _session_summary(db: AsyncSession, session_id: str, execution_count: int) -> str:
    result = await db.execute(
        select(ChatMessageModel)
        .where(ChatMessageModel.session_id == str(session_id))
        .order_by(ChatMessageModel.created_at)
    )
    messages = list(result.scalars().all())
    lines = [
        f"本 README 由 AI 助手会话 `{session_id}` 自动维护。",
        f"当前已记录 {len(messages)} 条消息，完成 {execution_count} 次代码执行。",
        "",
        "### 会话消息摘要",
    ]
    selected = [message for message in messages if message.role in {"user", "assistant"}][-12:]
    if not selected:
        lines.append("- （暂无已持久化消息）")
    else:
        for message in selected:
            text = " ".join(str(message.content or "").split())
            if len(text) > 240:
                text = text[:237] + "..."
            text = text.replace("|", "\\|") or "（空）"
            lines.append(f"- **{message.role}**: {text}")
    return "\n".join(lines)


def _copy_into_run(src: Path, run_dir: Path, relative: str, subdir: str) -> Path | None:
    safe = _safe_relpath(relative)
    if not safe or not src.is_file():
        return None
    destination = run_dir / subdir / safe
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.resolve().relative_to((run_dir / subdir).resolve())
        shutil.copy2(src, destination)
    except (OSError, ValueError):
        return None
    return destination


def _scan_archived_outputs(run_dir: Path) -> list[ArchivedFile]:
    """返回 run/output 下的完整产物清单，避免后续执行覆盖历史 manifest。"""
    output_dir = run_dir / "output"
    if not output_dir.is_dir():
        return []
    entries: list[ArchivedFile] = []
    for path in sorted(p for p in output_dir.rglob("*") if p.is_file()):
        relative = path.relative_to(run_dir).as_posix()
        entries.append(
            ArchivedFile(
                name=path.name,
                relative_path=relative,
                size=path.stat().st_size,
                md5=md5_stream(path),
                sha256=sha256_stream(path),
            )
        )
    return entries


async def archive_chat_execution(
    db: AsyncSession,
    context: ChatArchiveContext,
    *,
    sandbox_session_id: str,
    language: str,
    code: str,
    artifacts: list[dict[str, Any]],
    input_files: list[dict[str, Any]],
    stdout: str,
    stderr: str,
    success: bool,
    observed_software: dict[str, str] | None = None,
) -> dict[str, Any]:
    """归档一次执行，并刷新当前会话 README。失败不会阻断聊天结果。"""
    try:
        metadata = context.metadata
        execution_count = int(metadata.get("execution_count") or 0) + 1
        ext = {"python": ".py", "r": ".R", "bash": ".sh"}.get(language, ".txt")
        code_path = context.run_dir / "work" / f"execution-{execution_count:04d}{ext}"
        code_path.parent.mkdir(parents=True, exist_ok=True)
        code_path.write_text(code, encoding="utf-8")

        archived: list[ArchivedFile] = []
        for item in artifacts:
            rel = _safe_relpath(str(item.get("path") or ""))
            if not rel:
                continue
            source = (
                get_path_factory().workspace_dir(str(context.session.user_id))
                / "chat-output"
                / str(sandbox_session_id)
                / "output"
                / rel
            )
            copied = _copy_into_run(source, context.run_dir, rel, "output")
            if copied is None:
                continue
            archived.append(
                ArchivedFile(
                    name=copied.name,
                    relative_path=f"output/{rel}",
                    size=copied.stat().st_size,
                    md5=md5_stream(copied),
                    sha256=sha256_stream(copied),
                )
            )

        for item in input_files:
            source_raw = str(item.get("source") or "")
            source = Path(source_raw)
            _copy_into_run(source, context.run_dir, str(item.get("name") or source.name), "input")

        archived = _scan_archived_outputs(context.run_dir)
        settings = get_settings()
        environment = collect_environment(
            image=str(getattr(settings, "sandbox_image", "") or ""),
            flow_id="chat",
            flow_name="AI助手会话",
        )
        runtime = environment.setdefault("runtime", {})
        runtime["resources"] = {
            "cpu": getattr(settings, "sandbox_default_cpu", ""),
            "memory": getattr(settings, "sandbox_default_memory", ""),
            "pids": getattr(settings, "sandbox_pids_limit", ""),
        }
        runtime["network_policy"] = (
            "none" if getattr(settings, "sandbox_network_isolated", True) else "default"
        )
        runtime["container_user"] = str(getattr(settings, "sandbox_container_user", "") or "")
        if observed_software:
            runtime["observed_software"] = dict(observed_software)
            if observed_software.get("python"):
                environment.setdefault("python", {})["version"] = observed_software["python"]
        summary = await _session_summary(db, str(context.session.session_id), execution_count)
        if stdout.strip() or stderr.strip():
            tail = " ".join((stdout or stderr).split())
            summary += f"\n\n### 最近一次执行\n\n{tail[:1000]}"
        metadata["execution_count"] = execution_count
        await archive_run(
            user_id=str(context.session.user_id),
            project=context.project,
            run_dir=context.run_dir,
            analysis_type="AI助手聊天分析",
            status="completed" if success else "failed",
            summary=summary,
            environment=environment,
            artifacts=archived,
        )

        # README、环境快照和 manifest 也进入统一文件索引，后续会话管理可按 file_id 下载。
        # 先把整批文档收集出来，再一次性写入 metadata，避免返回的文档列表不完整。
        document_files: list[dict[str, Any]] = []
        try:
            registry = FileRegistry(db)
            for name in ("README.md", "environment.json", "manifest.json"):
                path = context.run_dir / name
                if path.is_file():
                    record = await registry.register(
                        UUID(str(context.session.user_id)),
                        path,
                        source=FileSource.CHAT_SANDBOX,
                        directory=context.metadata["run_directory"],
                    )
                    relative = get_path_factory().relative_to_root(path)
                    document_files.append(
                        {
                            "path": relative,
                            "name": name,
                            "size": path.stat().st_size,
                            "file_id": str(record.id),
                            "url": f"/api/v1/files/{record.id}/download",
                        }
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("[ChatArchive] 文档注册失败（归档仍保留）: {}", exc)

        metadata.update(
            {
                "execution_count": execution_count,
                "artifact_count": len(archived),
                "last_status": "completed" if success else "failed",
                "environment_summary": {
                    "image": runtime.get("image", ""),
                    "profile": runtime.get("profile", ""),
                    "resources": runtime.get("resources", {}),
                    "software_count": len(
                        runtime.get("observed_software") or runtime.get("software") or {}
                    ),
                },
                "updated_at": datetime.now(UTC).isoformat(),
            }
        )
        context.session.sandbox_meta = {
            **(context.session.sandbox_meta or {}),
            CHAT_ARCHIVE_KEY: metadata,
        }
        await db.commit()
        return {
            **metadata,
            "documents": {
                "readme": metadata["readme"],
                "environment": metadata["environment"],
                "manifest": metadata["manifest"],
            },
            "document_files": document_files,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("[ChatArchive] 会话归档失败（聊天结果不受影响）: {}", exc)
        return {}

#!/usr/bin/env python3
"""Import cloud operations notes and attachments into the cloud knowledge base."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote

from cygnusx.application.services.knowledge_asset_service import KnowledgeAssetService
from cygnusx.application.services.knowledge_index_service import KnowledgeIndexService
from cygnusx.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from cygnusx.infrastructure.database.models.knowledge_chunk import KbChunkModel
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
from cygnusx.infrastructure.database.models.knowledge_editor import DocEditorModel
from cygnusx.infrastructure.database.models.knowledge_revision import DocRevisionModel
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.session import get_engine, get_session_factory
from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table
from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
CLOUD_DIR = DOCS_ROOT / "knowledge" / "cloud"
KNOWLEDGE_BASE_ID = "cloud"
KNOWLEDGE_BASE_NAME = "云计算与平台运维知识库"
SEARCHABLE_SUFFIXES = frozenset(
    {
        ".pdf",
        ".docx",
        ".pptx",
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".gif",
        ".bmp",
        ".tif",
        ".tiff",
        ".svg",
    }
)
_LINK_RE = re.compile(r'(!?\[[^\]]*\]\()(?:<([^>]+)>|([^\s)]+))(\s+"[^"]*")?\)')
_FENCED_CODE_RE = re.compile(r"(^```.*?^```\s*$|^~~~.*?^~~~\s*$)", re.MULTILINE | re.DOTALL)
console = Console()


def configure_cli_logging() -> None:
    """Keep knowledge imports readable even when APP_DEBUG enables SQL echo."""
    get_engine().echo = False
    for logger_name in ("sqlalchemy.engine", "sqlalchemy.pool", "sqlalchemy.dialects"):
        logging.getLogger(logger_name).setLevel(logging.WARNING)


def create_progress() -> Progress:
    return Progress(
        SpinnerColumn(),
        TextColumn("[cyan]{task.description}[/cyan]"),
        BarColumn(bar_width=28),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    )


def render_summary(
    *,
    dry_run: bool,
    markdown: int,
    added: int,
    updated: int,
    unchanged: int,
    searchable_assets: int,
    rewritten: int,
    missing: int,
) -> None:
    table = Table(
        title="Cloud 知识库预览" if dry_run else "Cloud 知识库同步完成",
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("知识库", style="bold")
    table.add_column("Markdown", justify="right")
    table.add_column("新增", justify="right", style="green")
    table.add_column("更新", justify="right", style="yellow")
    table.add_column("未变化", justify="right", style="dim")
    table.add_column("可索引附件", justify="right", style="cyan")
    table.add_column("链接重写", justify="right")
    table.add_column("缺失", justify="right", style="red" if missing else "green")
    table.add_row(
        KNOWLEDGE_BASE_ID,
        str(markdown),
        str(added),
        str(updated),
        str(unchanged),
        str(searchable_assets),
        str(rewritten),
        str(missing),
    )
    console.print(table)


def render_validation(markdown: int, assets: int, missing: int, uncovered: int) -> None:
    table = Table(title="Cloud 知识源检查", header_style="bold cyan")
    table.add_column("Markdown", justify="right")
    table.add_column("可索引附件", justify="right")
    table.add_column("缺失链接", justify="right")
    table.add_column("未覆盖附件", justify="right")
    table.add_row(str(markdown), str(assets), str(missing), str(uncovered))
    console.print(table)


def discover_markdown_files(root: Path = CLOUD_DIR) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if path.is_file())


async def resolve_admin_user_id(
    session: object, admin_user_id: uuid.UUID | None, *, auto_admin: bool
) -> uuid.UUID:
    if admin_user_id is not None:
        return admin_user_id
    if not auto_admin:
        raise ValueError("必须提供 --admin-user-id 或 --auto-admin")
    result = await session.execute(
        select(UserModel.id)
        .where(UserModel.role == "admin")
        .order_by(UserModel.created_at.asc())
        .limit(1)
    )
    resolved = result.scalar_one_or_none()
    if resolved is None:
        raise ValueError("数据库中不存在 role='admin' 的用户，无法自动选择管理员")
    return resolved


def rewrite_links(
    content: str, source_file: Path, docs_root: Path = DOCS_ROOT
) -> tuple[str, int, int]:
    rewritten = 0
    missing = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal rewritten, missing
        prefix, angle_target, bare_target, title_part = match.groups()
        target = unquote(angle_target or bare_target or "")
        if target.startswith(("#", "http://", "https://", "mailto:", "data:", "/")):
            return match.group(0)
        resolved = (source_file.parent / target).resolve()
        try:
            relative = resolved.relative_to(docs_root.resolve())
        except ValueError:
            return match.group(0)
        if not resolved.exists():
            missing += 1
            return match.group(0)
        url = "/docs-static/" + "/".join(quote(part) for part in relative.parts)
        rewritten += 1
        return f"{prefix}{url}{title_part or ''})"

    parts = _FENCED_CODE_RE.split(content)
    for index in range(0, len(parts), 2):
        parts[index] = _LINK_RE.sub(replace, parts[index])
    return "".join(parts), rewritten, missing


def searchable_asset_inventory(root: Path = CLOUD_DIR) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SEARCHABLE_SUFFIXES
    )


def document_id(relative_path: Path) -> str:
    if relative_path == Path("README.md"):
        return "cloud-resource-catalog"
    if relative_path == Path("Cloud.md"):
        return "cloud-overview"
    digest = hashlib.md5(relative_path.as_posix().encode("utf-8")).hexdigest()[:12]  # noqa: S324
    return f"cloud-{digest}"


def title_and_category(path: Path, content: str) -> tuple[str, str]:
    title = path.stem
    for line in content.splitlines():
        if line.strip().startswith("# "):
            title = line.strip()[2:].strip() or title
            break
    relative = path.relative_to(CLOUD_DIR)
    category = relative.parts[0] if len(relative.parts) > 1 else "云计算与平台运维"
    return title[:200], category


def validate_sources() -> tuple[int, int, int, int]:
    service = KnowledgeAssetService()
    covered: set[Path] = set()
    missing_links = 0
    for markdown in discover_markdown_files():
        content = markdown.read_text(encoding="utf-8")
        _rewritten, _count, missing = rewrite_links(content, markdown, DOCS_ROOT)
        missing_links += missing
        covered.update(
            path
            for path, _label in service._referenced_assets(
                content, markdown.resolve(), include_unreferenced_assets=True
            )
        )
    assets = set(searchable_asset_inventory())
    return len(discover_markdown_files()), len(assets), missing_links, len(assets - covered)


async def import_cloud_knowledge(
    admin_user_id: uuid.UUID | None, *, dry_run: bool = False, auto_admin: bool = False
) -> None:
    markdown_files = discover_markdown_files()
    configure_cli_logging()
    factory = get_session_factory()
    async with factory() as session:
        admin_user_id = await resolve_admin_user_id(session, admin_user_id, auto_admin=auto_admin)
        user = await session.get(UserModel, admin_user_id)
        if user is None:
            raise ValueError(f"admin_user_id {admin_user_id} 不存在")
        user_name = user.nickname or user.username

        knowledge_base = await session.get(KnowledgeBaseModel, KNOWLEDGE_BASE_ID)
        if not dry_run:
            if knowledge_base is None:
                knowledge_base = KnowledgeBaseModel(
                    id=KNOWLEDGE_BASE_ID,
                    show_in_lab=False,
                )
                session.add(knowledge_base)
            knowledge_base.name = KNOWLEDGE_BASE_NAME
            knowledge_base.description = (
                "云计算、CygnusX 平台运维、存储、网络、容器仓库、Terraform 与 Slurm 资料"
            )
            knowledge_base.ai_searchable = True
            knowledge_base.is_enabled = True

        added = updated = unchanged = rewritten_total = missing_total = 0
        with create_progress() as progress:
            task = progress.add_task("准备同步 Cloud 文档", total=len(markdown_files))
            for markdown in markdown_files:
                relative = markdown.relative_to(CLOUD_DIR)
                display_path = relative.as_posix()
                progress.update(task, description=f"同步 Cloud · {display_path[-52:]}")
                try:
                    doc_id = document_id(relative)
                    raw = markdown.read_text(encoding="utf-8")
                    content, rewritten, missing = rewrite_links(raw, markdown, DOCS_ROOT)
                    rewritten_total += rewritten
                    missing_total += missing
                    document = (
                        await session.execute(
                            select(KbDocumentModel).where(KbDocumentModel.doc_id == doc_id)
                        )
                    ).scalar_one_or_none()
                    revision = (
                        await session.get(DocRevisionModel, document.current_rev)
                        if document is not None and document.current_rev
                        else None
                    )
                    changed = revision is None or revision.content != content
                    if dry_run:
                        added += document is None
                        updated += document is not None and changed
                        unchanged += document is not None and not changed
                        continue

                    title, category = title_and_category(markdown, content)
                    if document is None:
                        document = KbDocumentModel(
                            doc_id=doc_id,
                            title=title,
                            category=category,
                            file_path=str(markdown),
                            status=1,
                            created_by=admin_user_id,
                            kb_id=KNOWLEDGE_BASE_ID,
                        )
                        session.add(document)
                        await session.flush()
                        added += 1
                    else:
                        document.title = title
                        document.category = category
                        document.file_path = str(markdown)
                        document.status = 1
                        document.kb_id = KNOWLEDGE_BASE_ID
                        updated += int(changed)
                        unchanged += int(not changed)

                    if changed:
                        if revision is not None:
                            revision.status = 4
                        revision = DocRevisionModel(
                            document_id=document.id,
                            content=content,
                            edit_summary=f"同步 {markdown.relative_to(REPO_ROOT)}",
                            edited_by=admin_user_id,
                            status=1,
                        )
                        session.add(revision)
                        await session.flush()
                        document.current_rev = revision.id
                        document.pending_rev = None

                    editor = (
                        await session.execute(
                            select(DocEditorModel).where(
                                DocEditorModel.document_id == document.id,
                                DocEditorModel.user_id == admin_user_id,
                            )
                        )
                    ).scalar_one_or_none()
                    if editor is None:
                        session.add(
                            DocEditorModel(
                                document_id=document.id,
                                user_id=admin_user_id,
                                user_name=user_name,
                                edit_count=1,
                            )
                        )
                    elif changed:
                        editor.user_name = user_name
                        editor.edit_count += 1
                        editor.last_edit = datetime.now(UTC)

                    chunk_count = (
                        await session.execute(
                            select(func.count())
                            .select_from(KbChunkModel)
                            .where(KbChunkModel.document_id == doc_id)
                        )
                    ).scalar_one()
                    if changed or not chunk_count:
                        await KnowledgeIndexService(session).index_document(document, content)
                finally:
                    progress.advance(task)

        if not dry_run:
            await session.commit()
        render_summary(
            dry_run=dry_run,
            markdown=len(markdown_files),
            added=added,
            updated=updated,
            unchanged=unchanged,
            searchable_assets=len(searchable_asset_inventory()),
            rewritten=rewritten_total,
            missing=missing_total,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 Cloud 目录到平台知识库")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--admin-user-id", help="管理员用户 UUID")
    group.add_argument("--auto-admin", action="store_true", help="自动选择最早创建的管理员")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--validate-sources", action="store_true")
    args = parser.parse_args()
    if args.validate_sources:
        markdown, assets, missing, uncovered = validate_sources()
        render_validation(markdown, assets, missing, uncovered)
        raise SystemExit(1 if missing or uncovered else 0)
    if not args.admin_user_id and not args.auto_admin:
        parser.error("必须提供 --admin-user-id、--auto-admin 或 --validate-sources")
    asyncio.run(
        import_cloud_knowledge(
            uuid.UUID(args.admin_user_id) if args.admin_user_id else None,
            dry_run=args.dry_run,
            auto_admin=args.auto_admin,
        )
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Import all QC notes and their PDF/image assets into a searchable knowledge base."""

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

from omichub.application.services.knowledge_index_service import KnowledgeIndexService
from omichub.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from omichub.infrastructure.database.models.knowledge_chunk import KbChunkModel
from omichub.infrastructure.database.models.knowledge_document import KbDocumentModel
from omichub.infrastructure.database.models.knowledge_editor import DocEditorModel
from omichub.infrastructure.database.models.knowledge_revision import DocRevisionModel
from omichub.infrastructure.database.models.user import UserModel
from omichub.infrastructure.database.session import get_engine, get_session_factory
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
QC_DIR = DOCS_ROOT / "knowledge" / "qc"
KNOWLEDGE_BASE_ID = "qc"
KNOWLEDGE_BASE_NAME = "测序与生信质量控制知识库"
DOCUMENT_ID_OVERRIDES = {
    Path("README.md"): "qc-resource-catalog",
    Path("Raw data QC.md"): "qc-raw-data",
    Path("Quality control & preprocessing.md"): "qc-preprocessing",
    Path("FastQC.md"): "qc-fastqc",
    Path("fastp.md"): "qc-fastp",
    Path("multiqc.md"): "qc-multiqc",
}
DOCUMENT_CATEGORIES = {
    Path("README.md"): "QC 资源目录",
    Path("Raw data QC.md"): "原始测序质控",
    Path("Quality control & preprocessing.md"): "质控与预处理",
    Path("FastQC.md"): "原始测序质控",
    Path("fastp.md"): "质控与预处理",
    Path("multiqc.md"): "跨样本质量汇总",
}
SEARCHABLE_ASSET_SUFFIXES = frozenset(
    {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff", ".svg"}
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
    attachments: int,
    searchable_assets: int,
    rewritten: int,
    missing: int,
) -> None:
    table = Table(
        title="QC 知识库预览" if dry_run else "QC 知识库同步完成",
        header_style="bold cyan",
        show_lines=False,
    )
    table.add_column("知识库", style="bold")
    table.add_column("Markdown", justify="right")
    table.add_column("新增", justify="right", style="green")
    table.add_column("更新", justify="right", style="yellow")
    table.add_column("未变化", justify="right", style="dim")
    table.add_column("附件", justify="right")
    table.add_column("可索引", justify="right", style="cyan")
    table.add_column("链接重写", justify="right")
    table.add_column("缺失", justify="right", style="red" if missing else "green")
    table.add_row(
        KNOWLEDGE_BASE_ID,
        str(markdown),
        str(added),
        str(updated),
        str(unchanged),
        str(attachments),
        str(searchable_assets),
        str(rewritten),
        str(missing),
    )
    console.print(table)


def render_validation(markdown: int, assets: int, missing: int, uncovered: int) -> None:
    table = Table(title="QC 知识源检查", header_style="bold cyan")
    table.add_column("Markdown", justify="right")
    table.add_column("可索引附件", justify="right")
    table.add_column("缺失链接", justify="right")
    table.add_column("未覆盖附件", justify="right")
    table.add_row(str(markdown), str(assets), str(missing), str(uncovered))
    console.print(table)


def discover_markdown_files(root: Path = QC_DIR) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def document_id(relative_path: Path) -> str:
    override = DOCUMENT_ID_OVERRIDES.get(relative_path)
    if override:
        return override
    digest = hashlib.md5(relative_path.as_posix().encode("utf-8")).hexdigest()[:12]  # noqa: S324
    return f"qc-{digest}"


def extract_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()[:200] or fallback
    return fallback


def document_category(relative_path: Path) -> str:
    override = DOCUMENT_CATEGORIES.get(relative_path)
    if override:
        return override
    if len(relative_path.parts) > 1:
        return relative_path.parts[0]
    return "QC 工具与数据格式"


def rewrite_links(
    content: str, source_file: Path, docs_root: Path = DOCS_ROOT
) -> tuple[str, int, int]:
    """Rewrite existing relative attachments to the mounted ``/docs-static`` path."""
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


def attachment_inventory(root: Path = QC_DIR) -> list[Path]:
    return sorted(
        path for path in root.rglob("*") if path.is_file() and path.suffix.lower() != ".md"
    )


def searchable_asset_inventory(root: Path = QC_DIR) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SEARCHABLE_ASSET_SUFFIXES
    )


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


def validate_sources() -> tuple[int, int, int, int]:
    from omichub.application.services.knowledge_asset_service import KnowledgeAssetService

    markdown_files = discover_markdown_files()
    service = KnowledgeAssetService()
    covered: set[Path] = set()
    missing_links = 0
    rewritten_links = 0
    for markdown_file in markdown_files:
        raw_content = markdown_file.read_text(encoding="utf-8")
        _content, rewritten, missing = rewrite_links(raw_content, markdown_file)
        rewritten_links += rewritten
        missing_links += missing
        covered.update(
            path
            for path, _label in service._referenced_assets(
                raw_content,
                markdown_file.resolve(),
                include_unreferenced_assets=True,
            )
        )
    searchable_assets = set(searchable_asset_inventory())
    uncovered_assets = len(searchable_assets - covered)
    return len(markdown_files), len(searchable_assets), missing_links, uncovered_assets


async def import_qc_knowledge(
    admin_user_id: uuid.UUID | None,
    *,
    dry_run: bool = False,
    auto_admin: bool = False,
) -> None:
    markdown_files = discover_markdown_files()
    if not markdown_files:
        raise FileNotFoundError(f"QC Markdown 不存在: {QC_DIR}")

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
                "测序平台、FASTQ/FAST5、FastQC、fastp、MultiQC、污染、比对覆盖、"
                "变异与常用生物信息文件格式的质量控制资料"
            )
            knowledge_base.ai_searchable = True
            knowledge_base.is_enabled = True

        added = updated = unchanged = total_rewritten = total_missing = 0
        with create_progress() as progress:
            task = progress.add_task("准备同步 QC 文档", total=len(markdown_files))
            for markdown_file in markdown_files:
                relative_path = markdown_file.relative_to(QC_DIR)
                display_path = relative_path.as_posix()
                progress.update(task, description=f"同步 QC · {display_path[-56:]}")
                try:
                    doc_id = document_id(relative_path)
                    raw_content = markdown_file.read_text(encoding="utf-8")
                    content, rewritten_links, missing_links = rewrite_links(
                        raw_content, markdown_file
                    )
                    total_rewritten += rewritten_links
                    total_missing += missing_links

                    document = (
                        await session.execute(
                            select(KbDocumentModel).where(KbDocumentModel.doc_id == doc_id)
                        )
                    ).scalar_one_or_none()
                    current_revision = (
                        await session.get(DocRevisionModel, document.current_rev)
                        if document is not None and document.current_rev is not None
                        else None
                    )
                    changed = current_revision is None or current_revision.content != content
                    if dry_run:
                        if document is None:
                            added += 1
                        elif changed:
                            updated += 1
                        else:
                            unchanged += 1
                        continue

                    title = extract_title(content, markdown_file.stem)
                    if document is None:
                        document = KbDocumentModel(
                            doc_id=doc_id,
                            title=title,
                            category=document_category(relative_path),
                            file_path=str(markdown_file),
                            status=1,
                            created_by=admin_user_id,
                            kb_id=KNOWLEDGE_BASE_ID,
                        )
                        session.add(document)
                        await session.flush()
                        added += 1
                    else:
                        document.title = title
                        document.category = document_category(relative_path)
                        document.file_path = str(markdown_file)
                        document.status = 1
                        document.kb_id = KNOWLEDGE_BASE_ID
                        if changed:
                            updated += 1
                        else:
                            unchanged += 1

                    if changed:
                        if current_revision is not None:
                            current_revision.status = 4
                        revision = DocRevisionModel(
                            document_id=document.id,
                            content=content,
                            edit_summary=f"同步 {markdown_file.relative_to(REPO_ROOT)}",
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

        attachments = attachment_inventory()
        searchable_assets = searchable_asset_inventory()
        if not dry_run:
            await session.commit()
        render_summary(
            dry_run=dry_run,
            markdown=len(markdown_files),
            added=added,
            updated=updated,
            unchanged=unchanged,
            attachments=len(attachments),
            searchable_assets=len(searchable_assets),
            rewritten=total_rewritten,
            missing=total_missing,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 QC 目录到平台知识库")
    admin_group = parser.add_mutually_exclusive_group()
    admin_group.add_argument("--admin-user-id", help="管理员用户 UUID")
    admin_group.add_argument(
        "--auto-admin",
        action="store_true",
        help="自动使用数据库中最早创建的管理员用户",
    )
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写数据库")
    parser.add_argument(
        "--validate-sources",
        action="store_true",
        help="只检查 Markdown、附件链接和图片/PDF 覆盖，不连接数据库",
    )
    args = parser.parse_args()
    if args.validate_sources:
        markdown_count, asset_count, missing_links, uncovered_assets = validate_sources()
        render_validation(markdown_count, asset_count, missing_links, uncovered_assets)
        if missing_links or uncovered_assets:
            raise SystemExit(1)
        return
    if not args.admin_user_id and not args.auto_admin:
        parser.error("必须提供 --admin-user-id、--auto-admin 或 --validate-sources")
    asyncio.run(
        import_qc_knowledge(
            uuid.UUID(args.admin_user_id) if args.admin_user_id else None,
            dry_run=args.dry_run,
            auto_admin=args.auto_admin,
        )
    )


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""将知识库 Markdown 源内容同步到数据库。

场景：
    知识库服务以数据库为权威源。一旦某篇文档被网页端编辑过，它就会被导入到数据库中。
    此后直接修改 `docs/knowledge/` 或已登记 Markdown 集合（如 `wiki/`）中的文件，网页端不会自动
    热重载，因为读取的是数据库内容。本脚本用于把文件系统的最新内容同步回数据库，实现
    "文件修改 → 网页生效"。

用法示例：
    source .venv/bin/activate
    python scripts/sync_knowledge_from_files.py \
        --meta-yaml docs/knowledge/meta.yaml \
        --admin-user-id 00000000-0000-0000-0000-000000000001

Docker 部署环境：
    docker exec cygnusx-web python scripts/sync_knowledge_from_files.py \
        --meta-yaml docs/knowledge/meta.yaml \
        --auto-admin
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import re
import uuid
from pathlib import Path
from typing import Any

import yaml
from cygnusx.application.services.knowledge_index_service import KnowledgeIndexService
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
from cygnusx.infrastructure.database.models.knowledge_editor import DocEditorModel
from cygnusx.infrastructure.database.models.knowledge_revision import DocRevisionModel
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.session import get_engine, get_session_factory
from rich.console import Console
from rich.table import Table
from rich.theme import Theme
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# 抑制 SQLAlchemy 引擎日志输出，避免同步时打印大量 SQL
logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.pool").setLevel(logging.WARNING)
logging.getLogger("sqlalchemy.dialects").setLevel(logging.WARNING)

# Rich 控制台主题
custom_theme = Theme(
    {
        "info": "cyan",
        "success": "green",
        "warning": "yellow",
        "error": "red bold",
        "title": "bold blue",
    }
)
console = Console(theme=custom_theme)


def _document_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            return match.group(1)
    return fallback


def _collection_document_id(prefix: str, relative_path: Path) -> str:
    source = relative_path.with_suffix("").as_posix().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", source).strip("-") or "document"
    digest = hashlib.sha1(relative_path.as_posix().encode("utf-8")).hexdigest()[:10]
    return f"{prefix}-{slug[:48].rstrip('-')}-{digest}"


def expand_knowledge_items(meta: dict[str, Any], section_dir: Path) -> list[dict[str, Any]]:
    """展开显式文档和受控 Markdown 集合。"""
    items = [dict(item) for item in meta.get("items", []) if isinstance(item, dict)]
    for collection in meta.get("collections", []):
        if not isinstance(collection, dict):
            logging.getLogger(__name__).warning("忽略非对象知识库集合配置: %r", collection)
            continue

        source_dir_value = str(collection.get("source_dir") or "").strip()
        prefix = str(collection.get("id_prefix") or "").strip()
        if not source_dir_value or not prefix:
            logging.getLogger(__name__).warning("知识库集合缺少 source_dir 或 id_prefix: %r", collection)
            continue

        source_dir = (section_dir / source_dir_value).resolve()
        if not source_dir.is_dir():
            logging.getLogger(__name__).warning("知识库集合目录不存在: %s", source_dir)
            continue

        include = str(collection.get("include") or "**/*.md")
        exclude = [str(pattern) for pattern in collection.get("exclude", [])]
        category = str(collection.get("category") or "未分类")
        title_prefix = str(collection.get("title_prefix") or "")
        for source_path in sorted(source_dir.glob(include)):
            if not source_path.is_file():
                continue
            relative_path = source_path.relative_to(source_dir)
            if any(relative_path.match(pattern) for pattern in exclude):
                continue

            content = source_path.read_text(encoding="utf-8")
            title = _document_title(content, source_path.stem)
            items.append(
                {
                    "id": _collection_document_id(prefix, relative_path),
                    "title": f"{title_prefix}{title}",
                    "category": category,
                    "source_file": str(source_path),
                }
            )
    return items


async def resolve_admin_user_id(
    session: AsyncSession, admin_user_id: uuid.UUID | None, auto_admin: bool
) -> uuid.UUID:
    """解析最终使用的管理员用户 ID。"""
    if admin_user_id is not None:
        return admin_user_id

    if not auto_admin:
        raise ValueError("必须提供 --admin-user-id 或 --auto-admin")

    result = await session.execute(
        select(UserModel.id).where(UserModel.role == "admin").order_by(UserModel.created_at.asc()).limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ValueError("数据库中不存在 role='admin' 的用户，无法自动选择管理员")
    return row


async def sync(
    meta_yaml_path: Path,
    actor_user_id: uuid.UUID | None,
    session: AsyncSession,
    auto_admin: bool = False,
    *,
    index_documents: bool = True,
) -> tuple[int, int, int]:
    """执行同步，返回 (更新的文档数, 新建的文档数, 跳过的文档数)。"""
    section_dir = meta_yaml_path.parent

    actor_user_id = await resolve_admin_user_id(session, actor_user_id, auto_admin)

    user_result = await session.execute(
        select(UserModel.username, UserModel.nickname).where(UserModel.id == actor_user_id)
    )
    user_row = user_result.one_or_none()
    if user_row is None:
        raise ValueError(f"actor_user_id {actor_user_id} 不存在")
    actor_name = user_row.nickname or user_row.username

    with open(meta_yaml_path, encoding="utf-8") as f:
        meta = yaml.safe_load(f) or {}

    updated = 0
    created = 0
    skipped = 0
    results: list[tuple[str, str, str]] = []
    indexer = KnowledgeIndexService(session)

    for item in expand_knowledge_items(meta, section_dir):
        doc_id = item.get("id")
        title = item.get("title")
        category = item.get("category") or "未分类"
        md_file = item.get("source_file") or item.get("file")
        if not doc_id or not title or not md_file:
            results.append(("[warning]跳过[/warning]", doc_id or "?", "条目缺少 id/title/file"))
            skipped += 1
            continue

        file_path = section_dir / md_file
        if not file_path.exists():
            results.append(("[error]缺失[/error]", doc_id, f"文件不存在: {md_file}"))
            skipped += 1
            continue

        content = file_path.read_text(encoding="utf-8")

        # 查询数据库中是否已存在
        doc_result = await session.execute(
            select(KbDocumentModel).where(KbDocumentModel.doc_id == doc_id)
        )
        document = doc_result.scalar_one_or_none()

        if document is None:
            # 新建文档 + 初始版本
            document = KbDocumentModel(
                doc_id=doc_id,
                title=title,
                category=category,
                file_path=str(file_path),
                status=1,
                created_by=actor_user_id,
                kb_id="lab",
            )
            session.add(document)
            await session.flush()

            revision = DocRevisionModel(
                document_id=document.id,
                content=content,
                edit_summary="从文件系统同步导入",
                edited_by=actor_user_id,
                status=1,
            )
            session.add(revision)
            await session.flush()

            document.current_rev = revision.id
            if index_documents:
                await indexer.index_document(document, content, include_unreferenced_assets=True)

            editor = DocEditorModel(
                document_id=document.id,
                user_id=actor_user_id,
                user_name=actor_name,
                edit_count=1,
            )
            session.add(editor)

            created += 1
            results.append(("[success]新建[/success]", doc_id, title))
        else:
            # 同步 title / category
            document.title = title
            document.category = category
            document.kb_id = "lab"

            # 只有当内容发生变化时才创建新版本
            current_revision = await session.get(DocRevisionModel, document.current_rev)
            if current_revision is not None and current_revision.content == content:
                results.append(("[info]无变化[/info]", doc_id, title))
                continue

            # 归档旧版本
            if current_revision is not None:
                current_revision.status = 4  # 已归档

            revision = DocRevisionModel(
                document_id=document.id,
                content=content,
                edit_summary="从文件系统同步更新",
                edited_by=actor_user_id,
                status=1,
            )
            session.add(revision)
            await session.flush()

            document.current_rev = revision.id
            document.status = 1
            if index_documents:
                await indexer.index_document(document, content, include_unreferenced_assets=True)

            # 更新编辑者统计
            editor_result = await session.execute(
                select(DocEditorModel).where(
                    DocEditorModel.document_id == document.id,
                    DocEditorModel.user_id == actor_user_id,
                )
            )
            editor = editor_result.scalar_one_or_none()
            if editor is None:
                editor = DocEditorModel(
                    document_id=document.id,
                    user_id=actor_user_id,
                    user_name=actor_name,
                    edit_count=1,
                )
                session.add(editor)
            else:
                editor.edit_count += 1
                editor.user_name = actor_name

            updated += 1
            results.append(("[success]更新[/success]", doc_id, title))

    await session.commit()

    # 输出结果表格
    table = Table(title="知识库同步结果", show_header=True, header_style="bold magenta")
    table.add_column("状态", style="bold", width=10)
    table.add_column("文档 ID", style="dim", width=32)
    table.add_column("标题", style="bold")

    for status, doc_id, title in results:
        table.add_row(status, doc_id, title)

    console.print(table)

    return updated, created, skipped


async def main() -> None:
    parser = argparse.ArgumentParser(description="将知识库 Markdown 文件同步到数据库")
    parser.add_argument(
        "--meta-yaml",
        type=Path,
        default=Path("docs/knowledge/meta.yaml"),
        help="知识库 meta.yaml 路径",
    )
    parser.add_argument(
        "--admin-user-id",
        type=str,
        default=None,
        help="用于标记同步版本创建者的用户 UUID（与 --auto-admin 二选一）",
    )
    parser.add_argument(
        "--auto-admin",
        action="store_true",
        help="自动选择数据库中最早创建的管理员用户作为同步者",
    )
    args = parser.parse_args()

    if not args.meta_yaml.exists():
        console.print(f"[error]meta.yaml 不存在: {args.meta_yaml}[/error]")
        raise SystemExit(1)

    admin_user_id = uuid.UUID(args.admin_user_id) if args.admin_user_id else None

    # 关闭 SQLAlchemy echo，避免打印 SQL（即使 APP_DEBUG=true）
    engine = get_engine()
    engine.echo = False

    factory = get_session_factory()
    async with factory() as session:
        updated, created, skipped = await sync(
            args.meta_yaml, admin_user_id, session, auto_admin=args.auto_admin
        )

    summary = Table.grid(padding=(0, 2))
    summary.add_row(
        "[title]同步完成[/title]",
        f"[success]更新 {updated} 篇[/success]",
        f"[info]新建 {created} 篇[/info]",
        f"[warning]跳过 {skipped} 篇[/warning]",
    )
    console.print(summary)


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""Import the curated RNA-seq overview into the searchable RNA-seq knowledge base."""

from __future__ import annotations

import argparse
import asyncio
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote

from omichub.application.services.knowledge_index_service import KnowledgeIndexService
from omichub.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from omichub.infrastructure.database.models.knowledge_chunk import KbChunkModel
from omichub.infrastructure.database.models.knowledge_document import KbDocumentModel
from omichub.infrastructure.database.models.knowledge_editor import DocEditorModel
from omichub.infrastructure.database.models.knowledge_revision import DocRevisionModel
from omichub.infrastructure.database.models.user import UserModel
from omichub.infrastructure.database.session import get_session_factory
from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
SOURCE_FILE = DOCS_ROOT / "knowledge" / "rna-seq" / "RNA-seq.md"
KNOWLEDGE_BASE_ID = "rnaseq"
DOCUMENT_ID = "rnaseq-overview"
DOCUMENT_TITLE = "RNA-seq 原理、实验与分析流程"
DOCUMENT_CATEGORY = "RNA-seq 基础与全流程"
_LINK_RE = re.compile(r'(!?\[[^\]]*\]\()(?:<([^>]+)>|([^\s)]+))(\s+"[^"]*")?\)')


def rewrite_links(content: str, source_file: Path = SOURCE_FILE) -> tuple[str, int, int]:
    """Rewrite existing relative attachments to the mounted ``/docs-static`` path."""
    rewritten = 0
    missing = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal rewritten, missing
        prefix, angle_target, bare_target, title_part = match.groups()
        target = angle_target or bare_target or ""
        if target.startswith(("#", "http://", "https://", "mailto:", "data:", "/")):
            return match.group(0)
        candidates = [
            (source_file.parent / target).resolve(),
            (source_file.parent / Path(target).name).resolve(),
        ]
        resolved = next((candidate for candidate in candidates if candidate.exists()), candidates[0])
        try:
            relative = resolved.relative_to(DOCS_ROOT.resolve())
        except ValueError:
            return match.group(0)
        if not resolved.exists():
            missing += 1
            return match.group(0)
        url = "/docs-static/" + "/".join(quote(part) for part in relative.parts)
        rewritten += 1
        return f"{prefix}{url}{title_part or ''})"

    return _LINK_RE.sub(replace, content), rewritten, missing


async def import_rnaseq_knowledge(admin_user_id: uuid.UUID, *, dry_run: bool = False) -> None:
    if not SOURCE_FILE.is_file():
        raise FileNotFoundError(f"RNA-seq 文档不存在: {SOURCE_FILE}")

    raw_content = SOURCE_FILE.read_text(encoding="utf-8")
    content, rewritten_links, missing_links = rewrite_links(raw_content)
    factory = get_session_factory()
    async with factory() as session:
        user = await session.get(UserModel, admin_user_id)
        if user is None:
            raise ValueError(f"admin_user_id {admin_user_id} 不存在")
        user_name = user.nickname or user.username

        knowledge_base = await session.get(KnowledgeBaseModel, KNOWLEDGE_BASE_ID)
        document = (
            await session.execute(
                select(KbDocumentModel).where(KbDocumentModel.doc_id == DOCUMENT_ID)
            )
        ).scalar_one_or_none()
        current_revision = (
            await session.get(DocRevisionModel, document.current_rev)
            if document is not None and document.current_rev is not None
            else None
        )
        changed = current_revision is None or current_revision.content != content

        if dry_run:
            action = "更新" if document is not None and changed else "新增" if document is None else "跳过"
            print(
                f"[预览] {action}知识库={KNOWLEDGE_BASE_ID} 文档={DOCUMENT_ID} "
                f"字符={len(content)} 链接重写={rewritten_links} 缺失={missing_links}"
            )
            return

        if knowledge_base is None:
            knowledge_base = KnowledgeBaseModel(id=KNOWLEDGE_BASE_ID)
            session.add(knowledge_base)
        knowledge_base.name = "RNA-seq 知识库"
        knowledge_base.description = "Bulk RNA-seq 原理、实验设计、建库技术与分析流程资料"
        knowledge_base.show_in_lab = False
        knowledge_base.ai_searchable = True
        knowledge_base.is_enabled = True

        if document is None:
            document = KbDocumentModel(
                doc_id=DOCUMENT_ID,
                title=DOCUMENT_TITLE,
                category=DOCUMENT_CATEGORY,
                file_path=str(SOURCE_FILE),
                status=1,
                created_by=admin_user_id,
                kb_id=KNOWLEDGE_BASE_ID,
            )
            session.add(document)
            await session.flush()
        else:
            document.title = DOCUMENT_TITLE
            document.category = DOCUMENT_CATEGORY
            document.file_path = str(SOURCE_FILE)
            document.status = 1
            document.kb_id = KNOWLEDGE_BASE_ID

        if changed:
            if current_revision is not None:
                current_revision.status = 4
            revision = DocRevisionModel(
                document_id=document.id,
                content=content,
                edit_summary="同步 docs/knowledge/rna-seq/RNA-seq.md",
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
                select(func.count()).select_from(KbChunkModel).where(
                    KbChunkModel.document_id == DOCUMENT_ID
                )
            )
        ).scalar_one()
        if changed or not chunk_count:
            await KnowledgeIndexService(session).index_document(document, content)

        await session.commit()
        action = "已更新" if changed and current_revision is not None else "已导入" if changed else "已确认"
        print(
            f"{action}: knowledge_base={KNOWLEDGE_BASE_ID} document={DOCUMENT_ID} "
            f"links={rewritten_links} missing={missing_links}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 RNA-seq Markdown 到平台知识库")
    parser.add_argument("--admin-user-id", required=True, help="管理员用户 UUID")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写数据库")
    args = parser.parse_args()
    asyncio.run(import_rnaseq_knowledge(uuid.UUID(args.admin_user_id), dry_run=args.dry_run))


if __name__ == "__main__":
    main()

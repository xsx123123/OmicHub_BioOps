#!/usr/bin/env python3
"""Import all ATAC-seq Markdown notes into the searchable ATAC-seq knowledge base."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, unquote

from cygnusx.application.services.knowledge_index_service import KnowledgeIndexService
from cygnusx.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from cygnusx.infrastructure.database.models.knowledge_chunk import KbChunkModel
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
from cygnusx.infrastructure.database.models.knowledge_editor import DocEditorModel
from cygnusx.infrastructure.database.models.knowledge_revision import DocRevisionModel
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.session import get_session_factory
from sqlalchemy import func, select

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCS_ROOT = REPO_ROOT / "docs"
ATACSEQ_DIR = DOCS_ROOT / "knowledge" / "atac-seq"
KNOWLEDGE_BASE_ID = "atacseq"
KNOWLEDGE_BASE_NAME = "ATAC-seq 知识库"
DOCUMENT_ID_OVERRIDES = {
    Path("ATAC-seq.md"): "atacseq-overview",
    Path("Chromatin Accessibility.md"): "atacseq-chromatin-accessibility",
    Path("README.md"): "atacseq-resource-catalog",
}
DOCUMENT_CATEGORIES = {
    Path("ATAC-seq.md"): "ATAC-seq 原理与全流程",
    Path("Chromatin Accessibility.md"): "染色质开放性基础",
    Path("README.md"): "ATAC-seq 资源目录",
}
_LINK_RE = re.compile(r'(!?\[[^\]]*\]\()(?:<([^>]+)>|([^\s)]+))(\s+"[^"]*")?\)')


def discover_markdown_files(root: Path = ATACSEQ_DIR) -> list[Path]:
    return sorted(path for path in root.rglob("*.md") if path.is_file())


def document_id(relative_path: Path) -> str:
    override = DOCUMENT_ID_OVERRIDES.get(relative_path)
    if override:
        return override
    digest = hashlib.md5(relative_path.as_posix().encode("utf-8")).hexdigest()[:12]  # noqa: S324
    return f"atacseq-{digest}"


def extract_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()[:200] or fallback
    return fallback


def document_category(relative_path: Path) -> str:
    return DOCUMENT_CATEGORIES.get(relative_path, relative_path.parts[0] if len(relative_path.parts) > 1 else "ATAC-seq")


def rewrite_links(content: str, source_file: Path, docs_root: Path = DOCS_ROOT) -> tuple[str, int, int]:
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

    return _LINK_RE.sub(replace, content), rewritten, missing


def attachment_inventory(root: Path = ATACSEQ_DIR) -> list[Path]:
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() != ".md")


async def import_atacseq_knowledge(admin_user_id: uuid.UUID, *, dry_run: bool = False) -> None:
    markdown_files = discover_markdown_files()
    if not markdown_files:
        raise FileNotFoundError(f"ATAC-seq Markdown 不存在: {ATACSEQ_DIR}")

    factory = get_session_factory()
    async with factory() as session:
        user = await session.get(UserModel, admin_user_id)
        if user is None:
            raise ValueError(f"admin_user_id {admin_user_id} 不存在")
        user_name = user.nickname or user.username

        knowledge_base = await session.get(KnowledgeBaseModel, KNOWLEDGE_BASE_ID)
        if not dry_run:
            if knowledge_base is None:
                knowledge_base = KnowledgeBaseModel(id=KNOWLEDGE_BASE_ID)
                session.add(knowledge_base)
            knowledge_base.name = KNOWLEDGE_BASE_NAME
            knowledge_base.description = "ATAC-seq、染色质开放性、建库、质控、峰识别与调控分析资料"
            knowledge_base.show_in_lab = False
            knowledge_base.ai_searchable = True
            knowledge_base.is_enabled = True

        added = updated = unchanged = total_rewritten = total_missing = 0
        for markdown_file in markdown_files:
            relative_path = markdown_file.relative_to(ATACSEQ_DIR)
            doc_id = document_id(relative_path)
            raw_content = markdown_file.read_text(encoding="utf-8")
            content, rewritten_links, missing_links = rewrite_links(raw_content, markdown_file)
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
                    select(func.count()).select_from(KbChunkModel).where(
                        KbChunkModel.document_id == doc_id
                    )
                )
            ).scalar_one()
            if changed or not chunk_count:
                await KnowledgeIndexService(session).index_document(document, content)

        attachments = attachment_inventory()
        if dry_run:
            print(
                f"[预览] knowledge_base={KNOWLEDGE_BASE_ID} markdown={len(markdown_files)} "
                f"新增={added} 更新={updated} 跳过={unchanged} attachments={len(attachments)} "
                f"链接重写={total_rewritten} 缺失={total_missing}"
            )
            return

        await session.commit()
        print(
            f"已同步: knowledge_base={KNOWLEDGE_BASE_ID} markdown={len(markdown_files)} "
            f"新增={added} 更新={updated} 未变化={unchanged} attachments={len(attachments)} "
            f"links={total_rewritten} missing={total_missing}"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 ATAC-seq 目录到平台知识库")
    parser.add_argument("--admin-user-id", required=True, help="管理员用户 UUID")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写数据库")
    args = parser.parse_args()
    asyncio.run(import_atacseq_knowledge(uuid.UUID(args.admin_user_id), dry_run=args.dry_run))


if __name__ == "__main__":
    main()

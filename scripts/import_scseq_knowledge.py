#!/usr/bin/env python3
"""单细胞笔记批量导入知识库

将 docs/knowledge/sc-seq/ 下的 Markdown 笔记导入知识库（kb_documents + doc_revisions）：
- 遍历所有 .md，doc_id 取相对路径的稳定哈希（幂等，可重复执行）；
- 标题取首个 H1，分类取顶层目录名；
- 正文中的相对图片/附件链接（image/xxx、file/xxx 等）重写为 /docs-static/ 绝对 URL
  （main.py 已将 docs/ 挂载为 /docs-static），保证 DocReader 能渲染图片；
- 原始文件不动，重写后的内容只写入 DB 修订；
- 附件（PDF/图片/R/数据文件）保留在磁盘；PDF 和图片会由索引服务提取可检索内容，
  同时保留 /docs-static 链接供回答引用。

用法:
    source .venv/bin/activate
    POSTGRES_PASSWORD=cygnusx_dev_password \
        python scripts/import_scseq_knowledge.py \
        --admin-user-id cb79a200-b2ca-441f-9a42-d3417fbfa89d [--dry-run]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import re
import uuid
from pathlib import Path
from urllib.parse import quote

from cygnusx.application.services.knowledge_index_service import KnowledgeIndexService
from cygnusx.infrastructure.database.models.knowledge_base import KnowledgeBaseModel
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
from cygnusx.infrastructure.database.models.knowledge_editor import DocEditorModel
from cygnusx.infrastructure.database.models.knowledge_revision import DocRevisionModel
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.infrastructure.database.session import get_session_factory
from sqlalchemy import select

SCSEQ_DIR = Path("docs/knowledge/sc-seq")
DOCS_ROOT = Path("docs")
ROOT_CATEGORY = "单细胞总览"

# 行内链接/图片：[text](target "title")、[text](<target 含空格> "title")、![alt](target)
_LINK_RE = re.compile(r'(!?\[[^\]]*\]\()(?:<([^>]+)>|([^\s)]+))(\s+"[^"]*")?\)')


def _rewrite_links(content: str, md_file: Path, stats: dict[str, int]) -> str:
    """相对链接重写为 /docs-static/ 绝对 URL；锚点/外链/不存在的目标保持原样"""

    def _sub(m: re.Match[str]) -> str:
        prefix, angle_target, bare_target, title_part = m.groups()
        target = angle_target or bare_target or ""
        if target.startswith(("#", "http://", "https://", "mailto:", "data:", "/")):
            return m.group(0)
        resolved = (md_file.parent / target).resolve()
        try:
            rel_to_docs = resolved.relative_to(DOCS_ROOT.resolve())
        except ValueError:
            return m.group(0)
        if not resolved.exists():
            stats["missing"] += 1
            return m.group(0)
        url = "/docs-static/" + "/".join(quote(seg) for seg in rel_to_docs.parts)
        stats["rewritten"] += 1
        return f"{prefix}{url}{title_part or ''})"

    return _LINK_RE.sub(_sub, content)


def _extract_title(content: str, fallback: str) -> str:
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("# "):
            return line[2:].strip()[:200] or fallback
    return fallback


def _doc_id(rel_path: Path) -> str:
    digest = hashlib.md5(str(rel_path).encode("utf-8")).hexdigest()[:12]  # noqa: S324
    return f"scseq-{digest}"


async def import_notes(admin_user_id: uuid.UUID, dry_run: bool) -> None:
    md_files = sorted(SCSEQ_DIR.rglob("*.md"))
    print(f"发现 {len(md_files)} 篇 Markdown 笔记")

    factory = get_session_factory()
    async with factory() as session:
        user_row = (
            await session.execute(
                select(UserModel.username, UserModel.nickname).where(
                    UserModel.id == admin_user_id
                )
            )
        ).one_or_none()
        if user_row is None:
            raise ValueError(f"admin_user_id {admin_user_id} 不存在")
        admin_name = user_row.nickname or user_row.username

        existing = set(
            (await session.execute(select(KbDocumentModel.doc_id))).scalars().all()
        )

        # 确保单细胞知识库存在（迁移会预置；库被删过时这里兜底重建）
        kb = await session.get(KnowledgeBaseModel, "scseq")
        if kb is None:
            session.add(
                KnowledgeBaseModel(
                    id="scseq",
                    name="单细胞知识库",
                    description="单细胞测序教程与笔记（仅供 AI 检索，不在实验室知识库页展示）",
                    show_in_lab=False,
                    ai_searchable=True,
                )
            )
            await session.flush()

        stats = {"rewritten": 0, "missing": 0}
        imported = skipped = 0
        indexer = KnowledgeIndexService(session)
        for md_file in md_files:
            rel_path = md_file.relative_to(SCSEQ_DIR)
            doc_id = _doc_id(rel_path)
            if doc_id in existing:
                skipped += 1
                continue

            content = md_file.read_text(encoding="utf-8")
            title = _extract_title(content, md_file.stem)
            category = rel_path.parts[0] if len(rel_path.parts) > 1 else ROOT_CATEGORY
            rewritten = _rewrite_links(content, md_file, stats)

            if dry_run:
                imported += 1
                print(f"[预览] {doc_id} | {category} | {title} | {len(rewritten)} 字符")
                continue

            document = KbDocumentModel(
                doc_id=doc_id,
                title=title,
                category=category,
                file_path=str(md_file),
                status=1,
                created_by=admin_user_id,
                kb_id="scseq",
            )
            session.add(document)
            await session.flush()

            revision = DocRevisionModel(
                document_id=document.id,
                content=rewritten,
                edit_summary="单细胞笔记导入",
                edited_by=admin_user_id,
                status=1,
            )
            session.add(revision)
            await session.flush()
            document.current_rev = revision.id
            await indexer.index_document(document, rewritten, include_unreferenced_assets=True)

            session.add(
                DocEditorModel(
                    document_id=document.id,
                    user_id=admin_user_id,
                    user_name=admin_name,
                    edit_count=1,
                )
            )
            imported += 1

        if not dry_run:
            await session.commit()

        mode = "预览" if dry_run else "导入"
        print(
            f"{mode}完成：新增 {imported} 篇，跳过已存在 {skipped} 篇；"
            f"链接重写 {stats['rewritten']} 处，目标缺失保留原样 {stats['missing']} 处"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="导入 docs/knowledge/sc-seq 单细胞笔记到知识库")
    parser.add_argument("--admin-user-id", type=str, required=True, help="管理员用户 UUID")
    parser.add_argument("--dry-run", action="store_true", help="只预览不写库")
    args = parser.parse_args()

    if not SCSEQ_DIR.exists():
        raise FileNotFoundError(f"目录不存在: {SCSEQ_DIR}")

    asyncio.run(import_notes(uuid.UUID(args.admin_user_id), args.dry_run))


if __name__ == "__main__":
    main()

"""知识库审核服务

封装文档版本的 approve / reject 流程，包含数据库状态更新、文件系统双写、
audit log 记录。所有方法均在调用方提供的数据库会话内执行。
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from pathlib import Path

import yaml
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.exceptions import ValidationError
from cygnusx.infrastructure.database.models.knowledge_audit_log import DocAuditLogModel
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
from cygnusx.infrastructure.database.models.knowledge_revision import DocRevisionModel


class KnowledgeAuditService:
    """知识库审核服务"""

    def __init__(self, docs_root: Path | str | None = None):
        self._root = Path(docs_root) if docs_root else Path("docs").resolve()

    async def approve(
        self,
        db: AsyncSession,
        document: KbDocumentModel,
        revision: DocRevisionModel,
        actor_id: uuid.UUID,
        actor_name: str,
        reason: str | None = None,
    ) -> None:
        """通过审核：发布 revision 内容，并原子写入文件系统。"""
        # 1. 发布版本
        revision.status = 1

        # 2. 更新文档主表
        document.current_rev = revision.id
        document.pending_rev = None
        document.status = 1

        # 3. 原子写入 .md 文件
        await self._write_md_file(document.file_path, revision.content)

        # 4. 确保文档条目出现在 meta.yaml（新文档追加，已有文档同步标题/分类）
        await self._ensure_meta_entry(document)

        # 5. 记录审核日志
        log = DocAuditLogModel(
            document_id=document.id,
            revision_id=revision.id,
            action="approve",
            actor_id=actor_id,
            actor_name=actor_name,
            reason=reason,
            created_at=datetime.now(UTC),
        )
        db.add(log)

    async def reject(
        self,
        db: AsyncSession,
        document: KbDocumentModel,
        revision: DocRevisionModel,
        actor_id: uuid.UUID,
        actor_name: str,
        reason: str | None = None,
    ) -> None:
        """拒绝审核：仅更新数据库状态，不写文件系统。"""
        if not reason:
            raise ValidationError("拒绝审核时必须填写原因")

        revision.status = 3  # 已拒绝
        document.pending_rev = None
        # document.status 保持原值

        log = DocAuditLogModel(
            document_id=document.id,
            revision_id=revision.id,
            action="reject",
            actor_id=actor_id,
            actor_name=actor_name,
            reason=reason,
            created_at=datetime.now(UTC),
        )
        db.add(log)

    async def _write_md_file(self, file_path: str, content: str) -> None:
        """原子写入 Markdown 文件。"""
        path = Path(file_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)

    async def _ensure_meta_entry(self, document: KbDocumentModel) -> None:
        """确保文档条目出现在 docs/knowledge/meta.yaml 中。

        - 新文档：追加条目
        - 已有文档：同步 title / category，保持 file 不变
        """
        meta_path = self._root / "knowledge" / "meta.yaml"
        if not meta_path.exists():
            return

        with meta_path.open(encoding="utf-8") as f:
            meta = yaml.safe_load(f) or {}

        items = meta.get("items", [])
        section_dir = self._root / "knowledge"
        try:
            rel_path = Path(document.file_path).relative_to(section_dir).as_posix()
        except ValueError:
            rel_path = Path(document.file_path).name

        existing = next((item for item in items if item.get("id") == document.doc_id), None)
        if existing is None:
            items.append(
                {
                    "id": document.doc_id,
                    "title": document.title,
                    "category": document.category,
                    "file": rel_path,
                }
            )
        else:
            existing["title"] = document.title
            existing["category"] = document.category
            # 如 file 路径未设置或已变化，也同步更新
            if not existing.get("file"):
                existing["file"] = rel_path

        meta["items"] = items

        tmp_path = meta_path.with_suffix(meta_path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
        tmp_path.replace(meta_path)

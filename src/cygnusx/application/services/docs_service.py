"""知识库应用服务 —— 数据库权威源 + 文件系统双写。"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, overload

import anyio
import yaml
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.knowledge_audit_service import KnowledgeAuditService
from cygnusx.application.services.knowledge_index_service import KnowledgeIndexService
from cygnusx.application.services.knowledge_issue_service import KnowledgeIssueService
from cygnusx.core.exceptions import AuthorizationError, NotFoundError, ValidationError
from cygnusx.infrastructure.database.models.knowledge_audit_log import DocAuditLogModel
from cygnusx.infrastructure.database.models.knowledge_document import KbDocumentModel
from cygnusx.infrastructure.database.models.knowledge_editor import DocEditorModel
from cygnusx.infrastructure.database.models.knowledge_revision import DocRevisionModel
from cygnusx.infrastructure.database.models.user import UserModel

_DOCS_ROOT = Path("docs").resolve()
_DOC_ID_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class DocsService:
    """文档与知识库服务（数据库为权威源）。"""

    def __init__(
        self,
        docs_root: Path | str | None = None,
        audit_service: KnowledgeAuditService | None = None,
        issue_service: KnowledgeIssueService | None = None,
    ):
        self._root = Path(docs_root) if docs_root else _DOCS_ROOT
        self._audit = audit_service or KnowledgeAuditService(self._root)
        self._issue = issue_service or KnowledgeIssueService()

    # ------------------------------------------------------------------
    # 读取
    # ------------------------------------------------------------------
    async def list_knowledge(self, db: AsyncSession) -> dict[str, Any]:
        """获取实验室知识库导航列表（按 category 聚合）。

        数据库是目录权威源，仅展示所属知识库标记为 show_in_lab 的文档。
        """
        from cygnusx.infrastructure.database.models.knowledge_base import (
            KnowledgeBaseModel,
        )

        result = await db.execute(
            select(KbDocumentModel)
            .join(
                KnowledgeBaseModel, KbDocumentModel.kb_id == KnowledgeBaseModel.id
            )
            .where(
                KnowledgeBaseModel.show_in_lab.is_(True),
                KnowledgeBaseModel.is_enabled.is_(True),
            )
            .order_by(KbDocumentModel.category, KbDocumentModel.title)
        )
        file_config = self._load_nav_config("knowledge", "meta.yaml")
        items = [
            {
                "id": doc.doc_id,
                "title": doc.title,
                "category": doc.category,
                "status": self._status_name(doc.status),
            }
            for doc in result.scalars().all()
        ]

        return {
            "title": file_config.get("title", "实验室知识库"),
            "items": items,
        }

    async def get_knowledge_doc(
        self, db: AsyncSession, doc_id: str, current_user_id: uuid.UUID | None = None
    ) -> dict[str, Any]:
        """获取指定知识库文档当前生效版本。

        数据库优先；数据库未导入时 fallback 读取文件系统。
        对管理员或 pending 版本提交者，额外返回 pendingRevision。
        """
        document = await self._get_document_by_doc_id(db, doc_id, raise_not_found=False)

        if document is not None:
            from cygnusx.infrastructure.database.models.knowledge_base import (
                KnowledgeBaseModel,
            )

            visible_base_id = (
                await db.execute(
                    select(KnowledgeBaseModel.id).where(
                        KnowledgeBaseModel.id == document.kb_id,
                        KnowledgeBaseModel.show_in_lab.is_(True),
                        KnowledgeBaseModel.is_enabled.is_(True),
                    )
                )
            ).scalar_one_or_none()
            if visible_base_id is None:
                raise NotFoundError(f"文档 '{doc_id}' 不存在")

            if document.status != 1:
                # 非已发布文档：仅管理员和创建者可见
                if current_user_id is None:
                    raise NotFoundError(f"文档 '{doc_id}' 不存在")
                if not await self._is_admin(db, current_user_id) and document.created_by != current_user_id:
                    raise NotFoundError(f"文档 '{doc_id}' 不存在")

            current_revision = await self._get_revision(db, document.current_rev)
            content = current_revision.content if current_revision else ""

            editors = await self.get_doc_editors(db, document.id)
            issues = await self._issue.list_by_document(db, document.id)

            data: dict[str, Any] = {
                "id": document.doc_id,
                "title": document.title,
                "category": document.category,
                "status": self._status_name(document.status),
                "content": content,
                "currentRevision": self._revision_info(current_revision),
                "editors": editors,
                "issues": issues,
            }

            if document.pending_rev and (
                await self._is_admin(db, current_user_id)
                if current_user_id
                else False
                or document.pending_revision
                and document.pending_revision.edited_by == current_user_id
            ):
                pending_revision = await self._get_revision(db, document.pending_rev)
                data["pendingRevision"] = self._revision_info(pending_revision)

            return data

        # Fallback：数据库没有该文档时，尝试从文件系统读取
        file_doc = self._load_doc("knowledge", "meta.yaml", doc_id)
        return {
            "id": file_doc["id"],
            "title": file_doc["title"],
            "category": file_doc.get("category") or "未分类",
            "status": "published",
            "content": file_doc["content"],
            "currentRevision": None,
            "pendingRevision": None,
            "editors": [],
            "issues": [],
        }

    async def get_doc_history(self, db: AsyncSession, doc_id: str) -> list[dict[str, Any]]:
        """获取文档版本历史。"""
        document = await self._get_document_by_doc_id(db, doc_id)
        result = await db.execute(
            select(DocRevisionModel)
            .where(DocRevisionModel.document_id == document.id)
            .order_by(DocRevisionModel.created_at.desc())
        )
        return [
            info
            for rev in result.scalars().all()
            if (info := self._revision_info(rev)) is not None
        ]

    async def get_doc_editors(
        self, db: AsyncSession, document_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """获取文档编辑者列表，按最后编辑时间倒序。"""
        result = await db.execute(
            select(DocEditorModel)
            .where(DocEditorModel.document_id == document_id)
            .order_by(DocEditorModel.last_edit.desc())
        )
        return [
            {
                "userName": editor.user_name,
                "editCount": editor.edit_count,
                "lastEdit": editor.last_edit.isoformat() if editor.last_edit else None,
            }
            for editor in result.scalars().all()
        ]

    async def get_audit_logs(
        self, db: AsyncSession, doc_id: str
    ) -> list[dict[str, Any]]:
        """获取文档审核日志。"""
        document = await self._get_document_by_doc_id(db, doc_id)
        result = await db.execute(
            select(DocAuditLogModel)
            .where(DocAuditLogModel.document_id == document.id)
            .order_by(DocAuditLogModel.created_at.desc())
        )
        return [
            {
                "id": str(log.id),
                "action": log.action,
                "actorName": log.actor_name,
                "reason": log.reason,
                "createdAt": log.created_at.isoformat() if log.created_at else None,
            }
            for log in result.scalars().all()
        ]

    # ------------------------------------------------------------------
    # 写入
    # ------------------------------------------------------------------
    async def create_knowledge_doc(
        self,
        db: AsyncSession,
        payload: dict[str, Any],
        current_user_id: uuid.UUID,
        is_admin: bool,
    ) -> dict[str, Any]:
        """新建知识库文档。"""
        doc_id = payload.get("docId", "").strip()
        title = payload.get("title", "").strip()
        category = (payload.get("category") or "未分类").strip()
        project_id = str(payload.get("projectId") or "").strip() or None
        content = payload.get("content", "")
        edit_summary = (payload.get("editSummary") or "新建文档").strip()

        if not doc_id or not _DOC_ID_PATTERN.match(doc_id):
            raise ValidationError("文档ID只能包含小写字母、数字和连字符")
        if not title:
            raise ValidationError("标题不能为空")
        if not content:
            raise ValidationError("正文不能为空")

        existing = await self._get_document_by_doc_id(db, doc_id, raise_not_found=False)
        if existing is not None:
            raise ValidationError(f"文档ID '{doc_id}' 已存在")

        # 计算文件路径
        section_dir = self._root / "knowledge"
        md_filename = f"{doc_id}.md"
        file_path = section_dir / md_filename

        status = 1 if is_admin else 2

        document = KbDocumentModel(
            doc_id=doc_id,
            kb_id="lab",
            project_id=project_id,
            title=title,
            category=category,
            file_path=str(file_path),
            status=status,
            created_by=current_user_id,
        )
        db.add(document)
        await db.flush()

        revision = DocRevisionModel(
            document_id=document.id,
            content=content,
            edit_summary=edit_summary,
            edited_by=current_user_id,
            status=status,
        )
        db.add(revision)
        await db.flush()

        user_name = await self._get_user_name(db, current_user_id)
        await self._upsert_editor(db, document.id, current_user_id, user_name)
        await self._record_submit_log(
            db, document.id, revision.id, current_user_id, user_name, edit_summary
        )

        if is_admin:
            document.current_rev = revision.id
            await KnowledgeIndexService(db).index_document(document, content)
            await self._write_md_file(file_path, content)
            await self._ensure_meta_entry(document)
        else:
            document.pending_rev = revision.id

        return {
            "id": document.doc_id,
            "docId": document.doc_id,
            "title": document.title,
            "status": self._status_name(document.status),
            "revisionId": str(revision.id),
            "message": "文档已发布" if is_admin else "文档已提交，等待管理员审核",
        }

    async def update_knowledge_doc(
        self,
        db: AsyncSession,
        doc_id: str,
        payload: dict[str, Any],
        current_user_id: uuid.UUID,
        is_admin: bool,
    ) -> dict[str, Any]:
        """提交知识库文档编辑。"""
        content = payload.get("content", "")
        edit_summary = (payload.get("editSummary") or "更新文档").strip()

        if not content:
            raise ValidationError("正文不能为空")

        document = await self._ensure_db_document(db, doc_id, current_user_id)

        # 普通用户只能编辑已发布文档，且不能覆盖他人的待审核版本
        if not is_admin:
            if document.status != 1:
                raise AuthorizationError("当前文档不可编辑")
            if (
                document.pending_rev
                and document.pending_revision
                and document.pending_revision.edited_by != current_user_id
            ):
                raise AuthorizationError("该文档有他人提交的版本正在审核中")

        # 若有 pending_rev 且是本人提交的，可继续覆盖
        if (
            document.pending_rev
            and (not document.pending_revision or document.pending_revision.edited_by != current_user_id)
            and not is_admin
        ):
            raise AuthorizationError("该文档已有待审核版本")

        status = 1 if is_admin else 2

        revision = DocRevisionModel(
            document_id=document.id,
            content=content,
            edit_summary=edit_summary,
            edited_by=current_user_id,
            status=status,
        )
        db.add(revision)
        await db.flush()

        user_name = await self._get_user_name(db, current_user_id)
        await self._upsert_editor(db, document.id, current_user_id, user_name)
        await self._record_submit_log(
            db, document.id, revision.id, current_user_id, user_name, edit_summary
        )

        if is_admin:
            # 管理员直接发布；旧 current_rev 标记为归档
            if document.current_rev:
                old_rev = await self._get_revision(db, document.current_rev)
                if old_rev:
                    old_rev.status = 4  # 已归档
            document.current_rev = revision.id
            document.pending_rev = None
            document.status = 1
            await KnowledgeIndexService(db).index_document(document, content)
            await self._write_md_file(Path(document.file_path), content)
        else:
            # 普通用户：覆盖 pending_rev
            if document.pending_rev:
                old_pending = await self._get_revision(db, document.pending_rev)
                if old_pending:
                    old_pending.status = 3  # 旧的 pending 被拒绝（覆盖）
            document.pending_rev = revision.id
            document.status = 2

        return {
            "revisionId": str(revision.id),
            "status": self._status_name(document.status),
            "message": "文档已更新" if is_admin else "修改已提交，等待管理员审核通过后生效",
        }

    async def delete_knowledge_doc(
        self,
        db: AsyncSession,
        doc_id: str,
        current_user_id: uuid.UUID,
        is_admin: bool,
    ) -> dict[str, str]:
        """删除知识库文档（管理员或创建者本人）。"""
        if not is_admin:
            raise AuthorizationError("仅管理员可删除文档")

        document = await self._get_document_by_doc_id(db, doc_id, raise_not_found=False)

        if document is not None:
            # 删除关联数据（revision/editor/issue/audit_log 由 FK ondelete 级联）
            await db.delete(document)

        # 同时清理文件系统镜像（无论数据库是否有记录）
        file_path = anyio.Path(self._root / "knowledge" / f"{doc_id}.md")
        if await file_path.exists():
            await file_path.unlink()
        await self._remove_meta_entry(doc_id)

        return {"message": "文档已删除"}

    async def audit_knowledge_doc(
        self,
        db: AsyncSession,
        doc_id: str,
        action: str,
        reason: str | None,
        actor_id: uuid.UUID,
        actor_name: str,
    ) -> dict[str, Any]:
        """管理员审核文档。"""
        document = await self._get_document_by_doc_id(db, doc_id)
        if not document.pending_rev:
            raise ValidationError("该文档没有待审核版本")

        revision = await self._get_revision(db, document.pending_rev)
        if revision is None:
            raise NotFoundError("待审核版本不存在")

        if action == "approve":
            await self._audit.approve(db, document, revision, actor_id, actor_name, reason)
            await KnowledgeIndexService(db).index_document(document, revision.content)
        elif action == "reject":
            await self._audit.reject(db, document, revision, actor_id, actor_name, reason)
        else:
            raise ValidationError("审核动作必须是 approve 或 reject")

        return {
            "docId": document.doc_id,
            "status": self._status_name(document.status),
            "message": "审核已通过" if action == "approve" else "审核已拒绝",
        }

    async def list_pending_docs(self, db: AsyncSession) -> list[dict[str, Any]]:
        """获取待审核文档列表（管理员用）。"""
        result = await db.execute(
            select(KbDocumentModel)
            .where(KbDocumentModel.status == 2)
            .order_by(KbDocumentModel.updated_at.desc())
        )
        docs = result.scalars().all()
        pending_list = []
        for doc in docs:
            pending = doc.pending_revision
            submitter_name = None
            if pending:
                submitter_name = await self._get_user_name(db, pending.edited_by)
            pending_list.append(
                {
                    "id": doc.doc_id,
                    "title": doc.title,
                    "category": doc.category,
                    "submitter": submitter_name,
                    "editSummary": pending.edit_summary if pending else None,
                    "createdAt": pending.created_at.isoformat()
                    if pending and pending.created_at
                    else None,
                }
            )
        return pending_list

    # ------------------------------------------------------------------
    # Issue
    # ------------------------------------------------------------------
    async def get_issues(self, db: AsyncSession, doc_id: str) -> list[dict[str, Any]]:
        document = await self._get_document_by_doc_id(db, doc_id)
        return await self._issue.list_by_document(db, document.id)

    async def create_issue(
        self,
        db: AsyncSession,
        doc_id: str,
        user_id: uuid.UUID,
        user_name: str,
        content: str,
        reply_to: uuid.UUID | None = None,
    ) -> dict[str, Any]:
        if not content or not content.strip():
            raise ValidationError("留言内容不能为空")
        document = await self._get_document_by_doc_id(db, doc_id)
        issue = await self._issue.create(db, document.id, user_id, user_name, content.strip(), reply_to)
        return {
            "id": str(issue.id),
            "userName": issue.user_name,
            "content": issue.content,
            "status": issue.status,
            "createdAt": issue.created_at.isoformat() if issue.created_at else None,
        }

    async def delete_issue(
        self,
        db: AsyncSession,
        issue_id: uuid.UUID,
        user_id: uuid.UUID,
        is_admin: bool,
    ) -> None:
        await self._issue.delete(db, issue_id, user_id, is_admin)

    async def resolve_issue(self, db: AsyncSession, issue_id: uuid.UUID) -> None:
        await self._issue.resolve(db, issue_id)

    # ------------------------------------------------------------------
    # 辅助方法
    # ------------------------------------------------------------------
    @overload
    async def _get_document_by_doc_id(
        self,
        db: AsyncSession,
        doc_id: str,
        raise_not_found: Literal[True] = True,
    ) -> KbDocumentModel: ...

    @overload
    async def _get_document_by_doc_id(
        self,
        db: AsyncSession,
        doc_id: str,
        raise_not_found: Literal[False],
    ) -> KbDocumentModel | None: ...

    async def _get_document_by_doc_id(
        self,
        db: AsyncSession,
        doc_id: str,
        raise_not_found: bool = True,
    ) -> KbDocumentModel | None:
        result = await db.execute(
            select(KbDocumentModel).where(KbDocumentModel.doc_id == doc_id)
        )
        document = result.scalar_one_or_none()
        if document is None and raise_not_found:
            raise NotFoundError(f"文档 '{doc_id}' 不存在")
        return document

    async def _get_revision(
        self, db: AsyncSession, revision_id: uuid.UUID | None
    ) -> DocRevisionModel | None:
        if revision_id is None:
            return None
        return await db.get(DocRevisionModel, revision_id)

    async def _get_user_name(
        self, db: AsyncSession, user_id: uuid.UUID | None
    ) -> str:
        if user_id is None:
            return "未知用户"
        user = await db.get(UserModel, user_id)
        if user is None:
            return "未知用户"
        return user.nickname or user.username

    async def _is_admin(self, db: AsyncSession, user_id: uuid.UUID | None) -> bool:
        if user_id is None:
            return False
        result = await db.execute(select(UserModel.role).where(UserModel.id == user_id))
        role = result.scalar_one_or_none()
        return role == "admin"

    async def _upsert_editor(
        self,
        db: AsyncSession,
        document_id: uuid.UUID,
        user_id: uuid.UUID,
        user_name: str,
    ) -> None:
        now = datetime.now(UTC)
        stmt = (
            insert(DocEditorModel)
            .values(
                document_id=document_id,
                user_id=user_id,
                user_name=user_name,
                edit_count=1,
                first_edit=now,
                last_edit=now,
            )
            .on_conflict_do_update(
                index_elements=["document_id", "user_id"],
                set_={
                    "user_name": user_name,
                    "edit_count": DocEditorModel.edit_count + 1,
                    "last_edit": now,
                },
            )
        )
        await db.execute(stmt)

    async def _record_submit_log(
        self,
        db: AsyncSession,
        document_id: uuid.UUID,
        revision_id: uuid.UUID,
        actor_id: uuid.UUID,
        actor_name: str,
        reason: str | None,
    ) -> None:
        log = DocAuditLogModel(
            document_id=document_id,
            revision_id=revision_id,
            action="submit",
            actor_id=actor_id,
            actor_name=actor_name,
            reason=reason,
            created_at=datetime.now(UTC),
        )
        db.add(log)

    async def _write_md_file(self, file_path: Path, content: str) -> None:
        file_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = file_path.with_suffix(file_path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(file_path)

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
            if not existing.get("file"):
                existing["file"] = rel_path

        meta["items"] = items

        tmp_path = meta_path.with_suffix(meta_path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
        tmp_path.replace(meta_path)

    async def _remove_meta_entry(self, doc_id: str) -> None:
        """从 docs/knowledge/meta.yaml 中移除指定文档条目。"""
        meta_path = self._root / "knowledge" / "meta.yaml"
        if not meta_path.exists():
            return

        with meta_path.open(encoding="utf-8") as f:
            meta = yaml.safe_load(f) or {}

        items = meta.get("items", [])
        new_items = [item for item in items if item.get("id") != doc_id]
        if len(new_items) == len(items):
            return

        meta["items"] = new_items
        tmp_path = meta_path.with_suffix(meta_path.suffix + ".tmp")
        with tmp_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(meta, f, allow_unicode=True, sort_keys=False)
        tmp_path.replace(meta_path)

    async def _ensure_db_document(
        self,
        db: AsyncSession,
        doc_id: str,
        current_user_id: uuid.UUID,
    ) -> KbDocumentModel:
        """确保文件系统中存在的文档在数据库中也有记录。

        用于编辑/删除仅存在于 meta.yaml 中的文档时，先自动导入数据库。
        """
        document = await self._get_document_by_doc_id(db, doc_id, raise_not_found=False)
        if document is not None:
            return document

        file_doc = self._load_doc("knowledge", "meta.yaml", doc_id)
        section_dir = self._root / "knowledge"
        file_path = section_dir / f"{doc_id}.md"
        if not file_path.exists():
            raise NotFoundError(f"文档文件不存在: {file_path}")

        user_name = await self._get_user_name(db, current_user_id)

        document = KbDocumentModel(
            doc_id=doc_id,
            title=file_doc["title"],
            category=file_doc.get("category") or "未分类",
            file_path=str(file_path),
            status=1,
            created_by=current_user_id,
        )
        db.add(document)
        await db.flush()

        revision = DocRevisionModel(
            document_id=document.id,
            content=file_doc["content"],
            edit_summary="从文件系统自动导入",
            edited_by=current_user_id,
            status=1,
        )
        db.add(revision)
        await db.flush()

        document.current_rev = revision.id
        await self._upsert_editor(db, document.id, current_user_id, user_name)
        await self._record_submit_log(
            db, document.id, revision.id, current_user_id, user_name, "从文件系统自动导入"
        )
        return document

    @staticmethod
    def _revision_info(revision: DocRevisionModel | None) -> dict[str, Any] | None:
        if revision is None:
            return None
        return {
            "id": str(revision.id),
            "editedBy": str(revision.edited_by),
            "editSummary": revision.edit_summary,
            "status": revision.status,
            "createdAt": revision.created_at.isoformat() if revision.created_at else None,
        }

    @staticmethod
    def _status_name(status: int) -> str:
        return {1: "published", 2: "pending", 3: "rejected"}.get(status, "unknown")

    # ------------------------------------------------------------------
    # 文档中心（保持原有同步文件系统行为）
    # ------------------------------------------------------------------
    def list_docs(self) -> dict[str, Any]:
        """获取文档中心导航列表"""
        return self._load_nav_config("docs", "nav.yaml")

    def get_doc(self, doc_id: str) -> dict[str, Any]:
        """获取指定文档内容"""
        return self._load_doc("docs", "nav.yaml", doc_id)

    async def get_doc_editors_by_doc_id(
        self, db: AsyncSession, doc_id: str
    ) -> list[dict[str, Any]]:
        """根据 doc_id 获取编辑者列表。"""
        document = await self._get_document_by_doc_id(db, doc_id)
        return await self.get_doc_editors(db, document.id)

    def _load_nav_config(self, section: str, filename: str) -> dict[str, Any]:
        config_path = self._root / section / filename
        if not config_path.exists():
            raise NotFoundError(f"{section} 导航配置不存在")
        with config_path.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}
        return {
            "title": config.get("title", section),
            "items": [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "category": item.get("category"),
                }
                for item in config.get("items", [])
                if item.get("id") and item.get("title")
            ],
        }

    def _load_doc(self, section: str, filename: str, doc_id: str) -> dict[str, Any]:
        doc_path, target = self._resolve_doc_path(section, filename, doc_id)
        if not doc_path.exists():
            raise NotFoundError(f"文档文件不存在: {doc_path.name}")
        content = doc_path.read_text(encoding="utf-8")
        return {
            "id": doc_id,
            "title": target.get("title", doc_id),
            "category": target.get("category", "未分类"),
            "content": content,
        }

    def _resolve_doc_path(
        self, section: str, filename: str, doc_id: str
    ) -> tuple[Path, dict[str, Any]]:
        """根据 doc_id 解析出磁盘路径与导航条目，含路径遍历防护。"""
        config_path = self._root / section / filename
        if not config_path.exists():
            raise NotFoundError(f"{section} 导航配置不存在")

        with config_path.open("r", encoding="utf-8") as f:
            config = yaml.safe_load(f) or {}

        items = config.get("items", [])
        target = next((item for item in items if item.get("id") == doc_id), None)
        if target is None:
            raise NotFoundError(f"文档 '{doc_id}' 不存在")

        file_name = target.get("file")
        if not file_name:
            raise NotFoundError(f"文档 '{doc_id}' 未配置文件")

        doc_path = self._root / section / file_name
        section_dir = (self._root / section).resolve()
        try:
            doc_path.resolve().relative_to(section_dir)
        except ValueError as exc:
            raise NotFoundError(f"非法文档路径: {file_name}") from exc

        return doc_path, target

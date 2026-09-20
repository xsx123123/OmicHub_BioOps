"""知识库 Issue 留言服务"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.core.exceptions import AuthorizationError, NotFoundError
from cygnusx.infrastructure.database.models.knowledge_issue import KbIssueModel


class KnowledgeIssueService:
    """知识库 Issue 留言服务"""

    async def list_by_document(
        self, db: AsyncSession, document_id: uuid.UUID
    ) -> list[dict[str, Any]]:
        """获取文档下的 Issue 列表，按顶层 + 回复树形组织。"""
        result = await db.execute(
            select(KbIssueModel)
            .where(KbIssueModel.document_id == document_id)
            .order_by(KbIssueModel.created_at.asc())
        )
        issues = result.scalars().all()

        top_level: list[KbIssueModel] = []
        replies_map: dict[uuid.UUID, list[KbIssueModel]] = {}
        for issue in issues:
            if issue.reply_to is None:
                top_level.append(issue)
            else:
                replies_map.setdefault(issue.reply_to, []).append(issue)

        return [
            self._serialize_issue(issue, replies_map.get(issue.id, []))
            for issue in top_level
        ]

    async def create(
        self,
        db: AsyncSession,
        document_id: uuid.UUID,
        user_id: uuid.UUID,
        user_name: str,
        content: str,
        reply_to: uuid.UUID | None = None,
    ) -> KbIssueModel:
        """创建 Issue 或回复。"""
        if reply_to is not None:
            parent_result = await db.execute(
                select(KbIssueModel).where(
                    KbIssueModel.id == reply_to,
                    KbIssueModel.document_id == document_id,
                    KbIssueModel.reply_to.is_(None),
                )
            )
            if parent_result.scalar_one_or_none() is None:
                raise NotFoundError("回复的 Issue 不存在")

        issue = KbIssueModel(
            document_id=document_id,
            user_id=user_id,
            user_name=user_name,
            content=content,
            reply_to=reply_to,
            status=0,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db.add(issue)
        await db.flush()
        return issue

    async def delete(
        self,
        db: AsyncSession,
        issue_id: uuid.UUID,
        user_id: uuid.UUID,
        is_admin: bool,
    ) -> None:
        """删除 Issue（本人或管理员）。"""
        issue = await db.get(KbIssueModel, issue_id)
        if issue is None:
            raise NotFoundError("Issue 不存在")
        if not is_admin and issue.user_id != user_id:
            raise AuthorizationError("无权删除他人留言")
        await db.delete(issue)

    async def resolve(
        self,
        db: AsyncSession,
        issue_id: uuid.UUID,
    ) -> None:
        """管理员将 Issue 标记为已解决。"""
        issue = await db.get(KbIssueModel, issue_id)
        if issue is None:
            raise NotFoundError("Issue 不存在")
        issue.status = 1
        issue.updated_at = datetime.now(UTC)

    @staticmethod
    def _serialize_issue(issue: KbIssueModel, replies: list[KbIssueModel]) -> dict[str, Any]:
        return {
            "id": str(issue.id),
            "userName": issue.user_name,
            "content": issue.content,
            "status": issue.status,
            "createdAt": issue.created_at.isoformat() if issue.created_at else None,
            "replies": [
                {
                    "id": str(reply.id),
                    "userName": reply.user_name,
                    "content": reply.content,
                    "status": reply.status,
                    "createdAt": reply.created_at.isoformat() if reply.created_at else None,
                }
                for reply in replies
            ],
        }

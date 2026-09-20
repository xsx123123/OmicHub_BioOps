"""文档与知识库 API"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Annotated, Any

import anyio
from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.application.services.docs_service import DocsService
from cygnusx.core.exceptions import ValidationError
from cygnusx.infrastructure.database.models.user import UserModel
from cygnusx.middleware.rbac import require_admin

router = APIRouter()


# ------------------------------------------------------------------
# Pydantic 请求模型
# ------------------------------------------------------------------
class DocContentUpdate(BaseModel):
    """文档正文更新请求"""

    model_config = ConfigDict(populate_by_name=True)

    content: str = Field(description="新的 Markdown 正文")
    edit_summary: str | None = Field(
        default=None, alias="editSummary", description="编辑摘要/变更说明"
    )


class DocCreateRequest(BaseModel):
    """新建文档请求"""

    model_config = ConfigDict(populate_by_name=True)

    doc_id: str = Field(alias="docId", description="URL 标识，只能包含小写字母、数字和连字符")
    title: str = Field(description="文档标题")
    category: str = Field(description="分类")
    content: str = Field(description="Markdown 正文")
    edit_summary: str | None = Field(
        default=None, alias="editSummary", description="编辑摘要"
    )


class DocAuditRequest(BaseModel):
    """文档审核请求"""

    action: str = Field(description="approve 或 reject")
    reason: str | None = Field(default=None, description="审核意见/拒绝原因")


class IssueCreateRequest(BaseModel):
    """Issue 留言请求"""

    model_config = ConfigDict(populate_by_name=True)

    content: str = Field(description="留言内容")
    reply_to: str | None = Field(
        default=None, alias="replyTo", description="回复哪个 issue 的 UUID"
    )


# ------------------------------------------------------------------
# 依赖/工具
# ------------------------------------------------------------------
async def _is_admin(db: AsyncSession, user_id: str) -> bool:
    """实时校验当前用户是否为管理员。"""
    result = await db.execute(select(UserModel.role).where(UserModel.id == uuid.UUID(user_id)))
    role = result.scalar_one_or_none()
    return role == "admin"


async def _current_user_name(db: AsyncSession, user_id: str) -> str:
    user = await db.get(UserModel, uuid.UUID(user_id))
    if user is None:
        return "未知用户"
    return user.nickname or user.username


# ------------------------------------------------------------------
# 知识库接口
# ------------------------------------------------------------------
@router.get("/knowledge", tags=["Docs"])
async def list_knowledge(db: DbSession) -> dict[str, Any]:
    """获取实验室知识库导航列表。"""
    service = DocsService()
    return await service.list_knowledge(db)


@router.get("/knowledge/{doc_id}", tags=["Docs"])
async def get_knowledge_doc(
    doc_id: str,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> dict[str, Any]:
    """获取指定知识库文档内容。"""
    service = DocsService()
    user_uuid = uuid.UUID(current_user_id)
    return await service.get_knowledge_doc(db, doc_id, user_uuid)


@router.post("/knowledge", tags=["Docs"], summary="新建知识库文档")
async def create_knowledge_doc(
    payload: DocCreateRequest,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> dict[str, Any]:
    """新建知识库文档。管理员直接发布，普通用户进入待审核。"""
    service = DocsService()
    is_admin = await _is_admin(db, current_user_id)
    return await service.create_knowledge_doc(
        db, payload.model_dump(by_alias=True), uuid.UUID(current_user_id), is_admin
    )


@router.put("/knowledge/{doc_id}", tags=["Docs"], summary="提交知识库文档编辑")
async def save_knowledge_doc(
    doc_id: str,
    payload: DocContentUpdate,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> dict[str, Any]:
    """提交知识库文档编辑。管理员直接发布，普通用户进入待审核。"""
    service = DocsService()
    is_admin = await _is_admin(db, current_user_id)
    return await service.update_knowledge_doc(
        db,
        doc_id,
        payload.model_dump(by_alias=True),
        uuid.UUID(current_user_id),
        is_admin,
    )


@router.delete("/knowledge/{doc_id}", tags=["Docs"], summary="删除知识库文档")
async def delete_knowledge_doc(
    doc_id: str,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> dict[str, str]:
    """删除知识库文档（管理员或创建者本人）。"""
    service = DocsService()
    is_admin = await _is_admin(db, current_user_id)
    return await service.delete_knowledge_doc(
        db, doc_id, uuid.UUID(current_user_id), is_admin
    )


@router.get("/knowledge/{doc_id}/history", tags=["Docs"])
async def get_knowledge_doc_history(
    doc_id: str,
    db: DbSession,
) -> list[dict[str, Any]]:
    """获取文档版本历史。"""
    service = DocsService()
    return await service.get_doc_history(db, doc_id)


@router.get("/knowledge/{doc_id}/editors", tags=["Docs"])
async def get_knowledge_doc_editors(
    doc_id: str,
    db: DbSession,
) -> list[dict[str, Any]]:
    """获取文档编辑者列表。"""
    service = DocsService()
    return await service.get_doc_editors_by_doc_id(db, doc_id)


@router.get("/knowledge/audit/pending", tags=["Docs"])
async def list_pending_docs(
    db: DbSession,
    _admin: Annotated[None, Depends(require_admin)],
) -> list[dict[str, Any]]:
    """获取待审核文档列表（管理员）。"""
    service = DocsService()
    return await service.list_pending_docs(db)


@router.post("/knowledge/{doc_id}/audit", tags=["Docs"])
async def audit_knowledge_doc(
    doc_id: str,
    payload: DocAuditRequest,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> dict[str, Any]:
    """审核知识库文档（管理员）。"""
    service = DocsService()
    actor_name = await _current_user_name(db, current_user_id)
    return await service.audit_knowledge_doc(
        db,
        doc_id,
        payload.action,
        payload.reason,
        uuid.UUID(current_user_id),
        actor_name,
    )


@router.get("/knowledge/{doc_id}/audit", tags=["Docs"])
async def get_knowledge_audit_logs(
    doc_id: str,
    db: DbSession,
) -> list[dict[str, Any]]:
    """获取文档审核日志。"""
    service = DocsService()
    return await service.get_audit_logs(db, doc_id)


@router.get("/knowledge/{doc_id}/issues", tags=["Docs"])
async def get_knowledge_issues(
    doc_id: str,
    db: DbSession,
) -> list[dict[str, Any]]:
    """获取文档 Issue 列表。"""
    service = DocsService()
    return await service.get_issues(db, doc_id)


@router.post("/knowledge/{doc_id}/issues", tags=["Docs"])
async def create_knowledge_issue(
    doc_id: str,
    payload: IssueCreateRequest,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> dict[str, Any]:
    """发表 Issue 或回复。"""
    service = DocsService()
    user_name = await _current_user_name(db, current_user_id)
    reply_to = uuid.UUID(payload.reply_to) if payload.reply_to else None
    return await service.create_issue(
        db,
        doc_id,
        uuid.UUID(current_user_id),
        user_name,
        payload.content,
        reply_to,
    )


@router.delete("/knowledge/issues/{issue_id}", tags=["Docs"])
async def delete_knowledge_issue(
    issue_id: str,
    db: DbSession,
    current_user_id: CurrentUserId,
) -> dict[str, str]:
    """删除 Issue（本人或管理员）。"""
    service = DocsService()
    is_admin = await _is_admin(db, current_user_id)
    await service.delete_issue(db, uuid.UUID(issue_id), uuid.UUID(current_user_id), is_admin)
    return {"message": "删除成功"}


@router.post("/knowledge/issues/{issue_id}/resolve", tags=["Docs"])
async def resolve_knowledge_issue(
    issue_id: str,
    db: DbSession,
    _admin: Annotated[None, Depends(require_admin)],
) -> dict[str, str]:
    """将 Issue 标记为已解决（管理员）。"""
    service = DocsService()
    await service.resolve_issue(db, uuid.UUID(issue_id))
    return {"message": "已标记为已解决"}


# ------------------------------------------------------------------
# 图片上传
# ------------------------------------------------------------------
_ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}
_MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/knowledge/upload", tags=["Docs"], summary="上传知识库图片")
async def upload_knowledge_image(
    file: Annotated[UploadFile, File(description="图片文件")],
) -> dict[str, str]:
    """上传知识库配图，保存到 docs/knowledge/figure，返回可引用的静态 URL。

    普通用户在编辑器中插入图片也需要此接口，故不再限制仅管理员。
    """
    if not file.filename:
        raise ValidationError("未提供文件名")

    ext = Path(file.filename).suffix.lower()
    if ext not in _ALLOWED_IMAGE_EXTS:
        raise ValidationError(f"不支持的图片格式: {ext}")

    content = await file.read()
    if len(content) > _MAX_IMAGE_SIZE:
        raise ValidationError("图片大小不能超过 10MB")

    upload_dir = anyio.Path("docs/knowledge/figure")
    await upload_dir.mkdir(parents=True, exist_ok=True)

    filename = f"{uuid.uuid4().hex}{ext}"
    dest = upload_dir / filename
    await dest.write_bytes(content)

    return {"url": f"/docs-static/knowledge/figure/{filename}", "filename": filename}


# ------------------------------------------------------------------
# 文档中心接口（保持原有行为）
# ------------------------------------------------------------------
@router.get("/docs", tags=["Docs"])
async def list_docs() -> dict[str, Any]:
    """获取文档中心导航列表"""
    service = DocsService()
    return service.list_docs()


@router.get("/docs/{doc_id}", tags=["Docs"])
async def get_doc(doc_id: str) -> dict[str, Any]:
    """获取指定文档内容"""
    service = DocsService()
    return service.get_doc(doc_id)

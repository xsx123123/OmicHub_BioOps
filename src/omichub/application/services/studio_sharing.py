"""Studio 会话分享与可复现打印报告。"""

from __future__ import annotations

import hashlib
import html
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.schemas.studio import (
    SharedStudioMessageDTO,
    SharedStudioSessionDTO,
)
from omichub.core.exceptions import NotFoundError
from omichub.infrastructure.database.models.chat import ChatMessageModel, ChatSessionModel
from omichub.infrastructure.storage import get_path_factory, get_storage_backend
from omichub.infrastructure.studio.manager import studio_sandbox_manager
from omichub.infrastructure.studio.paths import relative_workspace_path
from omichub.infrastructure.studio.workspace import OUTPUT_DIR


def share_token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def create_share(session: ChatSessionModel, expires_hours: int) -> tuple[str, datetime]:
    token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires_at = now + timedelta(hours=expires_hours)
    session.share_token_hash = share_token_hash(token)
    session.shared_at = now
    session.share_expires_at = expires_at
    return token, expires_at


def revoke_share(session: ChatSessionModel) -> None:
    session.share_token_hash = None
    session.share_expires_at = None
    session.shared_at = None


def share_is_active(session: ChatSessionModel, now: datetime | None = None) -> bool:
    now = now or datetime.now(UTC)
    expires_at = session.share_expires_at
    return bool(
        session.share_token_hash
        and expires_at is not None
        and _as_utc(expires_at) > _as_utc(now)
    )


async def get_shared_session(db: AsyncSession, token: str) -> ChatSessionModel:
    if len(token) < 32 or len(token) > 128:
        raise NotFoundError("分享链接不存在或已失效")
    result = await db.execute(
        select(ChatSessionModel).where(
            ChatSessionModel.share_token_hash == share_token_hash(token),
            ChatSessionModel.mode == "studio",
            ChatSessionModel.status == "active",
        )
    )
    session = result.scalar_one_or_none()
    if session is None or not share_is_active(session):
        raise NotFoundError("分享链接不存在或已失效")
    return session


async def build_shared_snapshot(
    db: AsyncSession, session: ChatSessionModel
) -> SharedStudioSessionDTO:
    result = await db.execute(
        select(ChatMessageModel)
        .where(ChatMessageModel.session_id == session.session_id)
        .order_by(ChatMessageModel.created_at)
    )
    messages = [
        SharedStudioMessageDTO(
            role=message.role,
            content=message.content,
            created_at=message.created_at,
        )
        for message in result.scalars().all()
        if message.role in {"user", "assistant"} and message.content
    ]
    workspace = studio_sandbox_manager.workspace_dir(session.session_id)
    factory = get_path_factory()
    backend = get_storage_backend()
    workspace_info = await backend.stat(factory.relative_to_root(workspace))
    if workspace_info is None or not workspace_info.get("is_dir"):
        artifacts: list[dict[str, Any]] = []
    else:
        out_rel = factory.relative_to_root(workspace / OUTPUT_DIR)
        entries = await backend.list(out_rel, recursive=True)
        artifacts = [
            {
                "path": relative_workspace_path(factory.data_root / entry["path"], workspace),
                "size": entry["size"],
                "mtime": entry["mtime"],
            }
            for entry in entries
            if entry["type"] == "file"
        ]
    return SharedStudioSessionDTO(
        title=session.title,
        agent_id=session.agent_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        expires_at=_as_utc(session.share_expires_at or datetime.now(UTC)),
        messages=messages,
        artifacts=artifacts,
    )


def render_printable_report(snapshot: SharedStudioSessionDTO) -> str:
    """生成无脚本、打印友好的自包含 HTML；浏览器打印即得到 PDF。"""
    title = html.escape(snapshot.title)
    message_html = []
    for message in snapshot.messages:
        role = "用户" if message.role == "user" else "AI 助手"
        content = html.escape(message.content).replace("\n", "<br>")
        created_at = html.escape(_as_utc(message.created_at).isoformat())
        message_html.append(
            f'<section class="message {message.role}"><header>{role}<time>{created_at}</time>'
            f'</header><div class="content">{content}</div></section>'
        )
    artifact_html = "".join(
        f"<li><code>{html.escape(str(item.get('path', '')))}</code> "
        f"<span>{int(item.get('size', 0))} bytes</span></li>"
        for item in snapshot.artifacts
    ) or "<li>无登记产物</li>"
    return f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>{title} - OmicStudio</title>
<style>
@page {{ size: A4; margin: 18mm; }}
body {{ font-family: -apple-system,BlinkMacSystemFont,"Segoe UI","Noto Sans CJK SC",sans-serif; color:#172033; line-height:1.65; max-width:900px; margin:32px auto; padding:0 24px; }}
h1 {{ margin-bottom:4px; }} .meta {{ color:#667085; font-size:12px; margin-bottom:28px; }}
.message {{ break-inside:avoid; border:1px solid #e4e7ec; border-radius:10px; margin:14px 0; overflow:hidden; }}
.message header {{ display:flex; justify-content:space-between; gap:16px; padding:9px 12px; background:#f8fafc; font-weight:600; }}
.message time {{ color:#667085; font-weight:400; font-size:11px; }}
.content {{ padding:12px; white-space:normal; overflow-wrap:anywhere; }}
code {{ background:#f2f4f7; padding:2px 5px; border-radius:4px; }}
@media print {{ body {{ margin:0; max-width:none; padding:0; }} .no-print {{ display:none; }} }}
</style></head><body>
<button class="no-print" onclick="window.print()">打印 / 保存为 PDF</button>
<h1>{title}</h1><div class="meta">Agent: {html.escape(snapshot.agent_id or "-")} · 创建于 {_as_utc(snapshot.created_at).isoformat()} · 导出于 {datetime.now(UTC).isoformat()}</div>
<h2>对话记录</h2>{''.join(message_html) or '<p>无对话记录</p>'}
<h2>工作区产物</h2><ul>{artifact_html}</ul>
</body></html>"""


def resolve_shared_artifact(session: ChatSessionModel, relative_path: str) -> Path:
    workspace = studio_sandbox_manager.workspace_dir(session.session_id)
    candidate = (workspace / relative_path.lstrip("/")).resolve()
    output_root = (workspace / "output").resolve()
    if candidate == output_root or output_root not in candidate.parents or not candidate.is_file():
        raise NotFoundError("分享产物不存在")
    return candidate


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)

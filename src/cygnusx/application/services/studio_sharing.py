"""Studio 会话分享与可复现打印报告。"""

from __future__ import annotations

import hashlib
import html
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.studio import (
    SharedStudioMessageDTO,
    SharedStudioSessionDTO,
)

# R4（WP3 任务 4）分享载荷大小护栏：复用 WP0 的 200KB 截断逻辑
# （_cap_tool_invocation_payload_detail），被截断处带截断标记字段
# （payload_truncated / original_bytes / truncation_note），前端按"已截断"显式提示。
from cygnusx.application.services.chat.utils import _cap_tool_invocation_payload_detail
from cygnusx.core.exceptions import NotFoundError
from cygnusx.infrastructure.database.models.chat import ChatMessageModel, ChatSessionModel
from cygnusx.infrastructure.storage import get_path_factory, get_storage_backend
from cygnusx.infrastructure.studio.manager import studio_sandbox_manager
from cygnusx.infrastructure.studio.paths import relative_workspace_path
from cygnusx.infrastructure.studio.workspace import OUTPUT_DIR


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
            # R4：补执行历史摘要，被分享方看到完整工具执行过程（截断护栏见下）
            metadata_json=_share_message_metadata(message.metadata_json or {}),
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
        checksums = await _artifact_checksums(db, session)
        artifacts = [
            {
                "path": relative_workspace_path(factory.data_root / entry["path"], workspace),
                "size": entry["size"],
                "mtime": entry["mtime"],
                # R4：产物 sha256 取 WP2 落 file_records 的 checksum 列（登记时实测），
                # 无登记记录为 None
                "sha256": checksums.get((str(entry["path"]).split("/")[-1], entry["size"])),
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


# 分享快照中透出的 metadata_json 键白名单（其余键可能含隐私/内部状态，不外泄）
_SHARED_METADATA_KEYS = ("tool_invocations", "timeline", "usage")


def _share_message_metadata(metadata_json: dict[str, Any]) -> dict[str, Any] | None:
    """从消息 metadata_json 提取可分享的执行历史摘要（白名单键 + 截断护栏）。

    tool_invocations 信封（tool_name/arguments/result/payload_hash/截断标记）
    原样透出——落库时已过一次 200KB 护栏，这里对快照载荷再做一次兜底截断。
    """
    shared: dict[str, Any] = {}
    for key in _SHARED_METADATA_KEYS:
        value = metadata_json.get(key)
        if not value:
            continue
        capped, truncation = _cap_tool_invocation_payload_detail(value)
        shared[key] = capped
        if truncation:
            shared[f"{key}_truncation"] = truncation
    return shared or None


async def _artifact_checksums(
    db: AsyncSession, session: ChatSessionModel
) -> dict[tuple[str, int], str]:
    """WP2 产物登记的 file_records.checksum 索引：(original_name, size) -> sha256。

    登记时 checksum 为 dest 落盘文件实测 sha256，与 workspace 产物同源同尺寸；
    查不到（未登记/远程后端未实测）的条目不进索引，快照中 sha256=None。
    """
    try:
        from cygnusx.infrastructure.database.models.file import FileRecordModel

        user_uuid = uuid.UUID(str(session.user_id))
    except (ValueError, AttributeError, TypeError, ImportError):
        return {}
    try:
        result = await db.execute(
            select(FileRecordModel).where(
                FileRecordModel.user_id == user_uuid,
                FileRecordModel.source == "studio",
                FileRecordModel.checksum != "",
            )
        )
        indexed: dict[tuple[str, int], str] = {}
        for record in result.scalars().all():
            indexed[(record.original_name, int(record.size))] = record.checksum
        return indexed
    except Exception:  # noqa: BLE001 - 分享快照尽力而为，checksum 缺失不阻断
        return {}


def _tool_card_html(message: SharedStudioMessageDTO) -> str:
    """R4：单条消息的工具卡摘要 HTML（代码 + 关键输出摘要行），全部转义。"""
    invocations = (message.metadata_json or {}).get("tool_invocations")
    if not isinstance(invocations, list) or not invocations:
        return ""
    cards: list[str] = []
    for invocation in invocations:
        if not isinstance(invocation, dict):
            continue
        name = html.escape(str(invocation.get("tool_name") or "tool"))
        status = "成功" if invocation.get("success") else "失败"
        args = invocation.get("arguments")
        arg_text = ""
        if isinstance(args, dict):
            # 代码卡取 code，文件类工具取 path，其余序列化截短
            arg_text = str(args.get("code") or args.get("path") or args)[:400]
        arg_html = html.escape(arg_text).replace("\n", "<br>") if arg_text else ""
        result_text = html.escape(str(invocation.get("result") or "")[:300])
        badges = ""
        if invocation.get("result_truncation") or invocation.get("ui_payload_truncation"):
            badges = '<span class="trunc">已截断</span>'
        cards.append(
            f'<div class="tool-card"><header><code>{name}</code>'
            f'<span class="{"ok" if invocation.get("success") else "fail"}">{status}</span>'
            f"{badges}</header>"
            + (f'<pre class="args">{arg_html}</pre>' if arg_html else "")
            + (f'<div class="result">{result_text}</div>' if result_text else "")
            + "</div>"
        )
    if not cards:
        return ""
    return f'<div class="tools">{"".join(cards)}</div>'


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
            f'</header><div class="content">{content}</div>'
            f"{_tool_card_html(message)}</section>"
        )
    artifact_html = "".join(
        f"<li><code>{html.escape(str(item.get('path', '')))}</code> "
        f"<span>{int(item.get('size', 0))} bytes"
        + (
            f" · sha256:{html.escape(str(item.get('sha256'))[:16])}…"
            if item.get("sha256")
            else ""
        )
        + "</span></li>"
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
.tools {{ border-top:1px dashed #e4e7ec; padding:8px 12px; display:grid; gap:8px; }}
.tool-card {{ border:1px solid #eef1f4; border-radius:8px; padding:8px 10px; font-size:12px; }}
.tool-card header {{ display:flex; gap:10px; align-items:center; padding:0; background:none; }}
.tool-card .ok {{ color:#12805c; }} .tool-card .fail {{ color:#c03221; }}
.tool-card .trunc {{ color:#b54708; }}
.tool-card pre {{ background:#f8fafc; border-radius:6px; padding:8px; overflow-x:auto; white-space:pre-wrap; margin:6px 0 0; }}
.tool-card .result {{ color:#475467; margin-top:6px; overflow-wrap:anywhere; }}
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

"""只读导出指定聊天会话的消息、路由元数据与 Agent 交接事件。"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from cygnusx.infrastructure.database.models.chat import (
    ChatHandoffEventModel,
    ChatMessageModel,
    ChatSessionModel,
    CollaborationDegradationEventModel,
)
from cygnusx.infrastructure.database.session import close_db, get_session_factory
from sqlalchemy import select


def _text(value: str, *, full_content: bool, preview_chars: int) -> str:
    content = value or ""
    if full_content or len(content) <= preview_chars:
        return content
    return f"{content[:preview_chars]}…[truncated {len(content) - preview_chars} chars]"


async def inspect_session(
    session_id: str,
    *,
    full_content: bool = False,
    preview_chars: int = 500,
) -> dict[str, Any] | None:
    factory = get_session_factory()
    async with factory() as db:
        session = (
            await db.execute(
                select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
            )
        ).scalar_one_or_none()
        if session is None:
            return None

        messages = list(
            (
                await db.execute(
                    select(ChatMessageModel)
                    .where(ChatMessageModel.session_id == session_id)
                    .order_by(ChatMessageModel.created_at)
                )
            )
            .scalars()
            .all()
        )
        handoffs = list(
            (
                await db.execute(
                    select(ChatHandoffEventModel)
                    .where(ChatHandoffEventModel.session_id == session_id)
                    .order_by(ChatHandoffEventModel.created_at)
                )
            )
            .scalars()
            .all()
        )
        degradations = list(
            (
                await db.execute(
                    select(CollaborationDegradationEventModel)
                    .where(CollaborationDegradationEventModel.session_id == session_id)
                    .order_by(CollaborationDegradationEventModel.created_at)
                )
            )
            .scalars()
            .all()
        )

        return {
            "session": {
                "session_id": session.session_id,
                "user_id": session.user_id,
                "agent_id": session.agent_id,
                "assistant_id": session.assistant_id,
                "title": session.title,
                "mode": session.mode,
                "status": session.status,
                "message_count": session.message_count,
                "created_at": session.created_at,
                "updated_at": session.updated_at,
                "sandbox_meta": session.sandbox_meta,
            },
            "messages": [
                {
                    "message_id": message.message_id,
                    "role": message.role,
                    "status": message.status,
                    "content": _text(
                        message.content,
                        full_content=full_content,
                        preview_chars=preview_chars,
                    ),
                    "metadata": message.metadata_json,
                    "created_at": message.created_at,
                }
                for message in messages
            ],
            "handoffs": [
                {
                    "source_agent_id": event.source_agent_id,
                    "target_agent_id": event.target_agent_id,
                    "reason": event.reason,
                    "handoff_summary": _text(
                        event.handoff_summary,
                        full_content=full_content,
                        preview_chars=preview_chars,
                    ),
                    "user_intent": event.user_intent,
                    "artifacts": event.artifacts,
                    "constraints": event.constraints,
                    "hop_index": event.hop_index,
                    "created_at": event.created_at,
                }
                for event in handoffs
            ],
            "collaboration_degradations": [
                {
                    "message_id": event.message_id,
                    "intent": event.intent,
                    "reason": event.reason,
                    "created_at": event.created_at,
                }
                for event in degradations
            ],
        }


async def _run(args: argparse.Namespace) -> int:
    try:
        payload = await inspect_session(
            args.session_id,
            full_content=args.full_content,
            preview_chars=args.preview_chars,
        )
        if payload is None:
            print(f"session not found: {args.session_id}")
            return 2
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, default=str)
        if args.output:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(f"{rendered}\n", encoding="utf-8")
            print(output)
        else:
            print(rendered)
        return 0
    finally:
        await close_db()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session_id", help="chat_sessions.session_id")
    parser.add_argument(
        "--full-content",
        action="store_true",
        help="输出完整消息正文；默认每条仅显示前 500 字符",
    )
    parser.add_argument(
        "--preview-chars",
        type=int,
        default=500,
        help="未启用 --full-content 时的单条正文预览长度",
    )
    parser.add_argument("--output", help="可选 JSON 输出文件")
    args = parser.parse_args()
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()

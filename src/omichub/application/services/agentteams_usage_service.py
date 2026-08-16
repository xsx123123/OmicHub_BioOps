"""AgentTeams 协作室 LLM token 用量落库与饼干扣费。

把会诊（AgentConsultationService.run_consultation）产生的 token 用量写入
chat_sessions/chat_messages：合成会话使用 ``session_id=f"agentteams:{case_id}"``、
``mode="agentteams"``、``status="system"``——聊天会话列表只查 ``status=="active"``
因此不会对用户可见，而 stats_service.user_ai_token_usage 的聚合不看 status/mode，
用量统计页自动覆盖；同时按 ai_token_cookie_rate 费率扣减饼干
（CookieService.spend_ai_tokens 以 message_id 为幂等键防重，余额不足按可用余额封顶）。

事务边界：HTTP 会诊端点经 get_db 在请求末尾 commit；Celery 房间响应任务
（_respond_to_room_message）不 commit，故本函数在写入后自行 commit。
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.application.services.cookie_service import CookieService
from omichub.application.services.agentteams_title import derive_agentteams_case_title
from omichub.core.config import get_settings
from omichub.infrastructure.ai_provider.openai_compatible import normalize_token_usage
from omichub.infrastructure.database.models.chat import ChatMessageModel, ChatSessionModel

if TYPE_CHECKING:
    from omichub.application.services.agentteams_service import AgentTeamsService

_SESSION_TITLE_FALLBACK = "协作室会话"
_MESSAGE_CONTENT_MAX_CHARS = 2_000


async def record_consultation_usage(
    db: AsyncSession,
    *,
    case_id: str,
    agent_id: str,
    requester_ref: str,
    usage: dict[str, Any] | None,
    conclusion: str,
    model_config: Any,
    agentteams_service: AgentTeamsService | None = None,
    message_id: str | None = None,
) -> str | None:
    """记录一次协作室会诊的 token 用量并按费率扣饼干。

    返回写入的消息 ID；用量为空/total<=0 或 requester_ref 非合法 UUID 时跳过返回 None。
    调用方负责整体 try/except（本函数不吞异常，失败语义由调用方降级为日志）。
    """
    normalized = normalize_token_usage(usage)
    if normalized is None:
        return None
    total = int(normalized.get("total_tokens") or 0)
    if total <= 0:
        return None
    try:
        user_uuid = UUID(str(requester_ref))
    except (ValueError, AttributeError, TypeError):
        return None

    session_id = f"agentteams:{case_id}"[:50]
    message_id = message_id or f"at:{uuid4().hex}"

    result = await db.execute(
        select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
    )
    session = result.scalar_one_or_none()
    if session is None:
        title = await _resolve_session_title(agentteams_service, case_id, requester_ref)
        session = ChatSessionModel(
            session_id=session_id,
            user_id=str(user_uuid),
            title=title,
            status="system",
            mode="agentteams",
            model_id=model_config.id,
            message_count=0,
            total_tokens=0,
        )
        try:
            async with db.begin_nested():
                db.add(session)
                await db.flush()
        except IntegrityError:
            # 同一 Case 并发会诊：另一事务已创建合成会话，回滚到保存点后重读
            result = await db.execute(
                select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
            )
            session = result.scalar_one_or_none()
            if session is None:
                raise

    message = ChatMessageModel(
        session_id=session.session_id,
        message_id=message_id,
        role="assistant",
        content=(conclusion or "")[:_MESSAGE_CONTENT_MAX_CHARS],
        metadata_json={
            "usage": {
                "prompt_tokens": normalized["prompt_tokens"],
                "completion_tokens": normalized["completion_tokens"],
                "total_tokens": total,
            },
            "source": "agentteams",
            "case_id": case_id,
            "agent_id": agent_id,
            "provider": str(getattr(model_config, "name", "") or ""),
            "model": str(getattr(model_config, "model", "") or ""),
        },
        status="complete",
    )
    db.add(message)
    session.total_tokens = int(session.total_tokens or 0) + total
    session.message_count = int(session.message_count or 0) + 1
    session.last_message_at = datetime.now(UTC)
    await db.flush()

    if get_settings().enable_cookie_system:
        await CookieService(db).spend_ai_tokens(
            user_id=user_uuid, tokens=total, source_id=message_id
        )
    await db.commit()
    return message_id


async def _resolve_session_title(
    agentteams_service: AgentTeamsService | None, case_id: str, requester_ref: str
) -> str:
    """合成会话标题优先取 Case intent（仅创建时取一次）；失败用兜底文案。"""
    if agentteams_service is not None:
        try:
            case = await agentteams_service.get_case(case_id, requester_ref)
            intent = str((case or {}).get("intent") or "").strip()
            if intent:
                return f"协作室 · {derive_agentteams_case_title(intent)}"
        except Exception as exc:  # noqa: BLE001 - 标题只是展示用途，失败不阻断
            logger.bind(case_id=case_id).warning(
                "AgentTeams usage session title fallback: {}", exc
            )
    return _SESSION_TITLE_FALLBACK


__all__ = ["record_consultation_usage"]

"""长期记忆的低优先级异步维护任务。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import re
from typing import Any

from celery import shared_task
from sqlalchemy import select


def _conversation_text(messages: list[Any], *, limit: int = 8_000) -> str:
    """将会话压缩为可发送给摘要模型的纯文本，并避免把工具元数据送出。"""
    lines: list[str] = []
    used = 0
    for message in messages[-30:]:
        role = str(getattr(message, "role", ""))
        content = str(getattr(message, "content", "")).strip()
        if role not in {"user", "assistant"} or not content:
            continue
        line = f"{role}: {content}"
        remaining = limit - used
        if remaining <= 0:
            break
        lines.append(line[:remaining])
        used += len(line)
    return "\n".join(lines)


def _summary_content(response: dict[str, Any]) -> str:
    choices = response.get("choices") if isinstance(response, dict) else None
    if not isinstance(choices, list) or not choices:
        return ""
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = str(message.get("content", "")).strip()
    return re.sub(r"\s+", " ", content)[:200]


_FACT_EXTRACTION_PROMPT = """从以下对话增量中抽取值得跨会话保留的事实。

只抽取：
- 用户明确陈述的持久偏好（工具、流程、格式、语言）
- 项目级事实（数据集、样本量、分组、分析目标）
- 用户做出的重要决定及其原因

不抽取：
- 一次性操作指令
- 寒暄、过程性对话
- 任何密钥/凭据/隐私信息

每条事实要求：
- content：<=200 字符，自包含，禁止代词指代
- scope：profile / preference / project / summary 之一
- keywords：最多 8 个

无值得保留的内容时返回空数组。以 JSON 数组返回，不要输出其他内容。

对话：
{messages}
"""


def _extract_json_array(response: dict[str, Any]) -> list[dict[str, Any]]:
    choices = response.get("choices") if isinstance(response, dict) else None
    if not isinstance(choices, list) or not choices:
        return []
    message = choices[0].get("message", {}) if isinstance(choices[0], dict) else {}
    content = str(message.get("content", "")).strip()
    try:
        value = json.loads(content)
    except (TypeError, ValueError):
        return []
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


@shared_task(name="omichub.infrastructure.celery_app.tasks.memory.migrate_legacy_memories")
def migrate_legacy_memories() -> dict[str, int | str]:
    """Copy active legacy memories into v2 without deleting source rows."""
    return asyncio.run(_migrate_legacy_memories())


async def _migrate_legacy_memories() -> dict[str, int | str]:
    from omichub.infrastructure.database.models.agent_memory import (
        AgentMemoryModel,
        MemoryBlockModel,
        MemoryFactModel,
    )
    from omichub.infrastructure.database.session import get_session_factory

    imported = 0
    blocks_updated = 0
    async with get_session_factory()() as session:
        legacy_rows = list(
            (
                await session.scalars(
                    select(AgentMemoryModel)
                    .where(AgentMemoryModel.status == "active")
                    .order_by(AgentMemoryModel.created_at.asc())
                )
            ).all()
        )
        for legacy in legacy_rows:
            user_id = str(legacy.user_id)
            agent_id = str(legacy.agent_id or "")
            content_hash = hashlib.sha256(legacy.content.encode("utf-8")).hexdigest()
            existing = await session.scalar(
                select(MemoryFactModel.id).where(
                    MemoryFactModel.user_id == user_id,
                    MemoryFactModel.agent_id == agent_id,
                    MemoryFactModel.content_hash == content_hash,
                )
            )
            if existing is not None:
                continue
            scope = legacy.scope if legacy.scope in {"profile", "preference", "project", "summary"} else "summary"
            session.add(
                MemoryFactModel(
                    user_id=user_id,
                    agent_id=agent_id,
                    scope=scope,
                    content=legacy.content[:300],
                    content_hash=content_hash,
                    keywords=legacy.keywords or [],
                    embedding=legacy.embedding,
                    embedding_model=legacy.embedding_model,
                    source_session_id=legacy.source_session,
                    confidence=legacy.confidence,
                )
            )
            imported += 1
            if scope in {"profile", "preference"}:
                block_name = "profile" if scope == "profile" else "preferences"
                char_limit = 1500 if block_name == "profile" else 2000
                block = await session.scalar(
                    select(MemoryBlockModel).where(
                        MemoryBlockModel.user_id == user_id,
                        MemoryBlockModel.agent_id == agent_id,
                        MemoryBlockModel.block_name == block_name,
                    )
                )
                if block is None:
                    block = MemoryBlockModel(
                        user_id=user_id,
                        agent_id=agent_id,
                        block_name=block_name,
                        char_limit=char_limit,
                    )
                    session.add(block)
                    await session.flush()
                if legacy.content not in block.content:
                    suffix = "更多历史偏好见事实库"
                    separator = "\n" if block.content else ""
                    candidate = f"{block.content}{separator}- {legacy.content}"
                    if len(candidate) > char_limit:
                        candidate = candidate[: max(0, char_limit - len(suffix) - 1)].rstrip() + "\n" + suffix
                    block.content = candidate[:char_limit]
                    blocks_updated += 1
        await session.commit()
    return {"status": "completed", "imported": imported, "blocks_updated": blocks_updated}


@shared_task(name="omichub.infrastructure.celery_app.tasks.memory.backfill_embeddings")
def backfill_embeddings(limit: int = 100) -> dict[str, int | str]:
    """为启用语义召回前产生的历史记忆补齐向量；由运维按需触发。"""
    return asyncio.run(_backfill_embeddings(limit))


async def _backfill_embeddings(limit: int) -> dict[str, int | str]:
    from omichub.application.services.agent_memory_service import AgentMemoryService
    from omichub.core.config import get_settings
    from omichub.infrastructure.database.models.agent_memory import AgentMemoryModel
    from omichub.infrastructure.database.session import get_session_factory

    settings = get_settings()
    if not (
        settings.agent_memory_semantic_retrieval_enabled
        and settings.agent_memory_embedding_model.strip()
    ):
        return {"status": "disabled", "updated": 0}
    async with get_session_factory()() as session:
        rows = list(
            (await session.scalars(
                select(AgentMemoryModel)
                .where(
                    AgentMemoryModel.status == "active",
                    AgentMemoryModel.embedding.is_(None),
                )
                .order_by(AgentMemoryModel.updated_at.asc())
                .limit(max(1, min(limit, 500)))
            )).all()
        )
        service = AgentMemoryService(session)
        for memory in rows:
            await service._populate_embedding(memory)
        await session.commit()
        return {"status": "completed", "updated": len(rows)}


@shared_task(name="omichub.infrastructure.celery_app.tasks.memory.settle_session_memory")
def settle_session_memory(session_id: str) -> dict[str, Any]:
    """增量抽取事实并写入 memory_facts。"""
    return asyncio.run(_settle_session_memory(session_id))


async def _settle_session_memory(session_id: str) -> dict[str, Any]:
    return await _settle_session_memory_v2(session_id)


async def _settle_session_memory_v2(session_id: str) -> dict[str, Any]:
    """Extract only the new message interval and persist it idempotently."""
    from omichub.core.config import get_settings
    from omichub.infrastructure.database.models.agent_memory import MemoryFactModel, MemorySettlementModel
    from omichub.infrastructure.database.models.chat import ChatMessageModel, ChatSessionModel
    from omichub.infrastructure.database.session import get_session_factory
    from omichub.infrastructure.memory.fact_store import MemoryFactCreate, PostgresFactStore
    from omichub.application.services.agent_memory_service import AgentMemoryService

    settings = get_settings()
    async with get_session_factory()() as session:
        chat_session = await session.scalar(
            select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
        )
        if chat_session is None:
            return {"status": "missing"}
        query = (
            select(ChatMessageModel)
            .where(ChatMessageModel.session_id == session_id)
            .order_by(ChatMessageModel.created_at.asc())
        )
        messages = list((await session.scalars(query)).all())
        start_index = 0
        if chat_session.last_settled_message_id:
            for index, message in enumerate(messages):
                if message.message_id == chat_session.last_settled_message_id:
                    start_index = index + 1
                    break
        new_messages = messages[start_index:]
        if len(new_messages) < max(1, settings.memory_settle_min_new_messages):
            return {"status": "too_short", "new_messages": len(new_messages)}
        start_id = new_messages[0].message_id
        end_id = new_messages[-1].message_id
        range_key = f"{session_id}:{start_id}:{end_id}"
        if await session.scalar(
            select(MemorySettlementModel.id).where(MemorySettlementModel.range_key == range_key)
        ):
            return {"status": "already_settled", "range_key": range_key}
        owner = (chat_session.user_id, chat_session.agent_id or "")
        payload = _conversation_text(new_messages)

    try:
        from omichub.infrastructure.ai_provider.litellm_provider import LiteLLMProvider

        response = await LiteLLMProvider().chat(
            [{"role": "user", "content": _FACT_EXTRACTION_PROMPT.format(messages=payload)}],
            model=settings.memory_extraction_model,
            temperature=0.1,
        )
        extracted = _extract_json_array(response)
    except Exception:
        extracted = []

    async with get_session_factory()() as session:
        settlement = MemorySettlementModel(
            range_key=range_key,
            session_id=session_id,
            start_message_id=start_id,
            end_message_id=end_id,
        )
        session.add(settlement)
        await session.flush()
        store = PostgresFactStore(session)
        memory_service = AgentMemoryService(session)
        written = 0
        for item in extracted:
            content = str(item.get("content") or "").strip()[:200]
            scope = str(item.get("scope") or "summary").strip()
            if not content or scope not in {"profile", "preference", "project", "summary"}:
                continue
            keywords = [str(value)[:40] for value in item.get("keywords", []) if str(value).strip()][:8]
            try:
                embedding = await memory_service._embed(content)
                new_fact = MemoryFactCreate(
                    user_id=owner[0],
                    agent_id=owner[1],
                    scope=scope,
                    content=content,
                    keywords=keywords,
                    embedding=embedding or None,
                    source_session_id=session_id,
                    source_message_ids=[message.message_id for message in new_messages],
                )
                similar = await store.search(owner[0], owner[1], embedding, limit=1) if embedding else []
                if similar and _looks_like_replacement(content, similar[0].content):
                    await store.supersede(similar[0].id, new_fact)
                elif not similar or _fact_distance_is_distinct(similar[0].similarity):
                    await store.insert(new_fact)
                else:
                    await store.insert(new_fact)
                written += 1
            except Exception:
                await session.rollback()
                return {"status": "error", "detail": "事实写入失败"}
        chat_session = await session.scalar(
            select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
        )
        chat_session.last_settled_message_id = end_id
        await session.commit()
        return {"status": "settled", "facts": written, "processed_messages": len(new_messages)}


def _looks_like_replacement(new_content: str, old_content: str) -> bool:
    return any(marker in new_content for marker in ("改成", "改为", "不再", "以后别", "换成"))


def _fact_distance_is_distinct(similarity: float | None) -> bool:
    return similarity is None or similarity < 0.85

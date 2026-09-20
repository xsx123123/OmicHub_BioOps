"""Chat 路由候选的后台观测辅助。"""

from __future__ import annotations

import time

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.database.models.agent import AgentTemplateModel

_CUSTOM_AGENT_REGISTRY_WARN_INTERVAL_SECONDS = 300.0
_custom_agent_registry_warned_at = 0.0


async def warn_custom_agents_missing_from_registry(
    db: AsyncSession, registered_ids: set[str]
) -> list[str]:
    """报告未进入路由注册表快照的活跃自建 Agent。"""
    global _custom_agent_registry_warned_at
    now = time.monotonic()
    if now - _custom_agent_registry_warned_at < _CUSTOM_AGENT_REGISTRY_WARN_INTERVAL_SECONDS:
        return []
    _custom_agent_registry_warned_at = now
    try:
        result = await db.execute(
            select(AgentTemplateModel.agent_id).where(
                AgentTemplateModel.is_active == True,  # noqa: E712
                AgentTemplateModel.is_builtin == False,  # noqa: E712
            )
        )
        missing = sorted(
            str(agent_id)
            for (agent_id,) in result.all()
            if agent_id and str(agent_id) not in registered_ids
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("自建 agent 注册表比对失败（忽略）: {}", exc)
        return []
    if missing:
        logger.warning(
            "chat 路由候选不含以下 DB 自建 agent（将静默回落通用助手）: {}",
            ",".join(missing),
        )
    return missing

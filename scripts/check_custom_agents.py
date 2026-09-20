#!/usr/bin/env python3
"""上线前盘点：生产 DB 中的自建（非种子）Agent 清单（只读）。

背景（《协作室框架文档v3复审问题清单.md》C2）：chat 路由候选只来自注册表
快照（data/ai YAML），POST /api/v1/admin/agents 创建的自建 agent 只写 DB，
不进入路由候选，会被静默回落通用助手。上线前执行本脚本确认生产是否存在
自建 agent 并评估影响；存在时退出码 1（供检查清单卡点），不存在退出码 0。

只读：仅 SELECT agent_templates，不写任何表。

运行方式：
    uv run python scripts/check_custom_agents.py
"""

from __future__ import annotations

import asyncio
import sys

from cygnusx.core.config import get_settings
from cygnusx.infrastructure.database.models.agent import AgentTemplateModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


async def fetch_custom_agents(session: AsyncSession) -> list[tuple[str, str, bool]]:
    """返回自建 agent 的 (agent_id, name, is_active) 清单（is_builtin=False）。

    抽出为独立函数以便单测用 mock session 注入，不依赖真实数据库。
    """
    result = await session.execute(
        select(
            AgentTemplateModel.agent_id,
            AgentTemplateModel.name,
            AgentTemplateModel.is_active,
        )
        .where(AgentTemplateModel.is_builtin == False)  # noqa: E712
        .order_by(AgentTemplateModel.created_at)
    )
    return [(str(agent_id), str(name), bool(is_active)) for agent_id, name, is_active in result.all()]


async def _collect() -> list[tuple[str, str, bool]]:
    engine = create_async_engine(get_settings().database_url)
    try:
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
        async with session_factory() as session:
            return await fetch_custom_agents(session)
    finally:
        await engine.dispose()


def main() -> int:
    agents = asyncio.run(_collect())
    if not agents:
        print("✅ 数据库中不存在自建（非种子）Agent，路由候选与 DB 一致。")
        return 0
    print(f"⚠️  检测到 {len(agents)} 个自建 Agent（不进 chat 路由候选，将静默回落通用助手）：")
    for agent_id, name, is_active in agents:
        state = "active" if is_active else "inactive"
        print(f"   - {agent_id}（{name}，{state}）")
    print("请评估是否需要在 data/ai YAML 注册表补登，或通知属主该 agent 不再可路由。")
    return 1


if __name__ == "__main__":
    sys.exit(main())

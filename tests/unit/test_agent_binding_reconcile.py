"""内置 Agent 绑定重建（清除陈旧 MCP ID）行为测试。

核心断言：ensure_builtin_agents 对内置 Agent 以 YAML 声明集合重建 mcp_ids，
历史残留（外部 ensmbl/go-server、已失效的旧 platform 随机 ID、conda 全局注入）
一律清除，仅保留声明集合 + 核心 builtin 预设（cygnusx-tools / platform）。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from cygnusx.application.services.agent_service import AgentService
from cygnusx.infrastructure.database.models.agent import AgentTemplateModel
from cygnusx.infrastructure.mcp.conda_meta_preset import CONDA_META_MCP_SERVER_ID
from cygnusx.infrastructure.mcp.presets import (
    CYGNUSX_PLATFORM_SERVER_ID,
    CYGNUSX_TOOLS_SERVER_ID,
)

# 历史漂移场景里的陈旧 ID
_STALE_ENSMBL = "9f3a3546-e7d6-4a59-9c61-206ca2e471c7"
_STALE_GO = "15bb9689-f2c9-4d31-aaa3-4f79514e7f92"
_STALE_PIPELINES = "7375dd58-4c5f-59f9-ab27-a407bb961ee8"
_STALE_OLD_PLATFORM = "d4bbaf4d-e831-4571-b86f-b6e5093ea21b"
_STALE_OLD_CONDA = "73d0f808-9b74-5933-be24-22f686ff86d1"

_DECLARED_RNASEQ = [
    str(CYGNUSX_TOOLS_SERVER_ID),
    str(CYGNUSX_PLATFORM_SERVER_ID),
    _STALE_PIPELINES,
    _STALE_ENSMBL,
    _STALE_GO,
]


def _service_with(existing: AgentTemplateModel) -> AgentService:
    db = AsyncMock()
    provider_result = MagicMock()
    provider_result.scalars.return_value.all.return_value = []
    db.execute.return_value = provider_result
    service = AgentService(db)
    service.get_agent = AsyncMock(return_value=existing)
    service._ensure_configured_marketplace_skills = AsyncMock()
    return service


@pytest.mark.asyncio
async def test_builtin_agent_drops_stale_mcp_ids(monkeypatch):
    existing = AgentTemplateModel(
        agent_id="agent-rnaseq",
        name="RNA-seq 分析师",
        is_builtin=True,
        system_prompt="旧提示词",
        description="",
        temperature=0.7,
        is_active=True,
        # 历史漂移：携带旧 platform 随机 ID、conda 全局注入、且声明外残留 ensmbl/go
        mcp_ids=[
            _STALE_OLD_PLATFORM,
            _STALE_OLD_CONDA,
            str(CYGNUSX_TOOLS_SERVER_ID),
            _STALE_PIPELINES,
            _STALE_ENSMBL,
            _STALE_GO,
        ],
        skill_ids=["rnaflow", "stale-skill"],
        features={},
    )
    monkeypatch.setattr(
        "cygnusx.application.services.agent_service.load_agent_configs",
        lambda: [
            {
                "agent_id": "agent-rnaseq",
                "mcp_ids": _DECLARED_RNASEQ,
                "skill_ids": ["rnaflow"],
                "features": {},
            }
        ],
    )
    service = _service_with(existing)
    await service.ensure_builtin_agents()

    result = [str(v) for v in existing.mcp_ids]
    assert _STALE_OLD_PLATFORM not in result, "旧 platform 随机 ID 应被清除"
    assert _STALE_OLD_CONDA not in result, "全局注入的 conda 应被清除"
    assert _STALE_ENSMBL in result, "声明集合内的 ensmbl 应保留"
    assert _STALE_GO in result, "声明集合内的 go-server 应保留"
    assert str(CYGNUSX_PLATFORM_SERVER_ID) in result, "核心 platform 预设应保留"
    assert str(CYGNUSX_TOOLS_SERVER_ID) in result, "核心 cygnusx-tools 预设应保留"
    # 声明集合的确定性常量 ID 应顶替旧随机 ID
    assert CONDA_META_MCP_SERVER_ID not in result
    # skill 同样以声明为准
    assert existing.skill_ids == ["rnaflow"]

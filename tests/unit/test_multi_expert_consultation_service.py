"""多专家并行会诊的无网络服务测试。"""

from collections.abc import AsyncIterator
from types import SimpleNamespace

import pytest

from omichub.application.services.multi_expert_consultation_service import (
    MultiExpertConsultationService,
)
from omichub.infrastructure.ai_provider.openai_compatible import ChatChunk


class AgentServiceStub:
    async def assemble_context(self, agent_id: str):
        return SimpleNamespace(
            agent=SimpleNamespace(agent_id=agent_id, name=f"{agent_id} 专家"),
            model_config=SimpleNamespace(),
            system_prompt="专家系统提示",
        )


@pytest.mark.asyncio
async def test_collect_runs_experts_and_ignores_failed_opinion(monkeypatch) -> None:
    async def fake_stream(**kwargs) -> AsyncIterator[ChatChunk]:
        if kwargs["config"] is None:
            raise RuntimeError("missing config")
        yield ChatChunk(type="text", content="建议先检查输入数据质量。")

    monkeypatch.setattr(
        "omichub.application.services.multi_expert_consultation_service.provider_manager.chat_stream",
        fake_stream,
    )
    service = MultiExpertConsultationService(AgentServiceStub())

    opinions = await service.collect(["agent-rnaseq", "agent-viz"], "请分析这个项目")

    assert [item["agent_id"] for item in opinions] == ["agent-rnaseq", "agent-viz"]
    assert "多专家会诊意见" in service.render_prompt_context(opinions)

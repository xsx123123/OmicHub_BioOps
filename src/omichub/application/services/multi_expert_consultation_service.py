"""受开关控制的只读多专家并行会诊。"""

from __future__ import annotations

import asyncio
from typing import Any

from omichub.infrastructure.ai_provider.openai_compatible import provider_manager


class MultiExpertConsultationService:
    """并行收集专家意见；任一专家失败不影响其余意见或主链路回答。"""

    def __init__(self, agent_service: Any) -> None:
        self._agent_service = agent_service

    async def collect(
        self, agent_ids: list[str], user_text: str, user_id: str | None = None
    ) -> list[dict[str, str]]:
        contexts = await asyncio.gather(
            *(self._agent_service.assemble_context(agent_id, user_id=user_id) for agent_id in agent_ids),
            return_exceptions=True,
        )
        tasks = [
            self._collect_one(context, user_text)
            for context in contexts
            if not isinstance(context, Exception) and context is not None
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return [result for result in results if isinstance(result, dict)]

    @staticmethod
    async def _collect_one(context: Any, user_text: str) -> dict[str, str] | None:
        model_config = getattr(context, "model_config", None)
        agent = getattr(context, "agent", None)
        if model_config is None or agent is None:
            return None
        text = ""
        try:
            async for chunk in provider_manager.chat_stream(
                config=model_config,
                messages=[{"role": "user", "content": user_text}],
                system_prompt=(
                    f"{getattr(context, 'system_prompt', '')}\n\n"
                    "你正在参与多专家会诊。仅从自己的专业角度给主助手一份简洁、"
                    "可核验的建议；不要调用工具、不要向用户承诺执行任务，控制在 300 字内。"
                ),
                temperature=0.2,
                max_tokens=400,
                tools=None,
                deep_thinking=False,
            ):
                if chunk.type == "text":
                    text += chunk.content
        except Exception:
            return None
        text = text.strip()
        if not text:
            return None
        return {
            "agent_id": str(getattr(agent, "agent_id", "")),
            "name": str(getattr(agent, "name", "专家")),
            "opinion": text[:1200],
        }

    @staticmethod
    def render_prompt_context(opinions: list[dict[str, str]]) -> str:
        if not opinions:
            return ""
        lines = ["## 多专家会诊意见（仅供综合，需自行核验）"]
        lines.extend(f"- {item['name']}：{item['opinion']}" for item in opinions)
        return "\n".join(lines)

    @staticmethod
    def summarize(opinions: list[dict[str, str]]) -> str:
        """Return a conclusion-only handoff summary safe to prefill into a Case."""
        if not opinions:
            return ""
        lines = ["会诊纪要（仅含专家结论，不含原始工具轨迹）："]
        lines.extend(f"- {item['name']}：{item['opinion'][:360]}" for item in opinions)
        return "\n".join(lines)[:1800]

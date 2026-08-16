"""受控 Agent Handoff：白名单校验、交接包与会话审计。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from omichub.core.exceptions import BusinessError, NotFoundError
from omichub.infrastructure.database.models.agent import AgentTemplateModel
from omichub.infrastructure.database.models.chat import ChatHandoffEventModel, ChatSessionModel
from omichub.infrastructure.database.session import get_session_factory

HANDOFF_TOOL_NAME = "transfer_to_agent"
MAX_HANDOFF_PACKET_BYTES = 2400
DEFAULT_MAX_HOPS = 10
MAX_HOPS_CEILING = 10


def extract_handoff_directive(result: Any) -> dict[str, Any] | None:
    """兼容 ToolBridge 与 builtin MCP 两层结果信封，提取交接指令。"""
    candidate = result
    if isinstance(candidate, dict):
        candidate = candidate.get("result", candidate)
    if isinstance(candidate, dict):
        candidate = candidate.get("llm_payload", candidate)
    directive = candidate.get("handoff") if isinstance(candidate, dict) else None
    return dict(directive) if isinstance(directive, dict) else None


class AgentHandoffService:
    """Handoff 的服务端策略层；实际上下文切换由 ChatService 执行。"""

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def prepare_handoff(
        self,
        *,
        user_id: str,
        session_id: str,
        source_agent_id: str,
        target_agent_id: str,
        reason: str,
        handoff_summary: str,
        user_intent: str,
        artifacts: list[str] | None = None,
        constraints: list[str] | None = None,
    ) -> dict[str, Any]:
        """验证转交请求，生成预算受限的 packet，但不立即写事件。"""
        session = await self._db.scalar(
            select(ChatSessionModel).where(
                ChatSessionModel.session_id == session_id,
                ChatSessionModel.user_id == user_id,
                ChatSessionModel.status == "active",
            )
        )
        if session is None:
            raise NotFoundError("会话不存在或无权执行转交")

        source = await self._db.scalar(
            select(AgentTemplateModel).where(
                AgentTemplateModel.agent_id == source_agent_id,
                AgentTemplateModel.is_active == True,  # noqa: E712
            )
        )
        if source is None:
            raise BusinessError("当前 Agent 不可用，无法转交")
        target = await self._db.scalar(
            select(AgentTemplateModel).where(
                AgentTemplateModel.agent_id == target_agent_id,
                AgentTemplateModel.is_active == True,  # noqa: E712
            )
        )
        if target is None:
            raise BusinessError("目标 Agent 不存在或已停用")
        if target_agent_id == source_agent_id:
            raise BusinessError("不能转交给当前 Agent")

        handoff_config = dict((source.features or {}).get("handoff") or {})
        allowed_targets = {str(item) for item in handoff_config.get("allowed_targets", [])}
        allow_all_active_targets = "*" in allowed_targets
        if not allow_all_active_targets and target_agent_id not in allowed_targets:
            raise BusinessError("目标 Agent 不在当前 Agent 的转交白名单中")
        if allow_all_active_targets and (target.features or {}).get("router"):
            raise BusinessError("不能转交给路由 Agent")
        max_hops = self._parse_max_hops(handoff_config.get("max_hops_per_session"))

        history = list(
            (
                await self._db.scalars(
                    select(ChatHandoffEventModel)
                    .where(ChatHandoffEventModel.session_id == session_id)
                    .order_by(ChatHandoffEventModel.hop_index)
                )
            ).all()
        )
        next_hop = len(history) + 1
        if next_hop > max_hops:
            raise BusinessError(f"本会话最多允许 {max_hops} 次转交")

        normalized_reason = self._normalize_text(reason, "转交原因", 320)
        if (
            any(event.source_agent_id == target_agent_id for event in history)
            and len(normalized_reason) < 16
        ):
            raise BusinessError("回转交必须在转交原因中说明新增信息")

        normalized_artifacts = self._normalize_artifacts(artifacts)
        normalized_constraints = self._normalize_list(constraints, "约束", 8, 180)
        packet = self._build_packet(
            source_name=source.name,
            reason=normalized_reason,
            user_intent=self._normalize_text(user_intent, "用户原始诉求", 500),
            handoff_summary=self._normalize_text(handoff_summary, "已完成工作摘要", 1000),
            artifacts=normalized_artifacts,
            constraints=normalized_constraints,
        )
        return {
            "source_agent_id": source_agent_id,
            "source_agent_name": source.name,
            "target_agent_id": target_agent_id,
            "target_agent_name": target.name,
            "reason": normalized_reason,
            "handoff_summary": self._normalize_text(handoff_summary, "已完成工作摘要", 1000),
            "user_intent": self._normalize_text(user_intent, "用户原始诉求", 500),
            "artifacts": normalized_artifacts,
            "constraints": normalized_constraints,
            "hop_index": next_hop,
            "packet": packet,
        }

    async def record_handoff(
        self, *, user_id: str, session_id: str, directive: dict[str, Any]
    ) -> ChatHandoffEventModel:
        """在 ChatService 成功接受指令后持久化，形成用户可追溯审计。"""
        event = ChatHandoffEventModel(
            session_id=session_id,
            user_id=user_id,
            source_agent_id=str(directive["source_agent_id"]),
            target_agent_id=str(directive["target_agent_id"]),
            reason=str(directive["reason"]),
            handoff_summary=str(directive["handoff_summary"]),
            user_intent=str(directive["user_intent"]),
            artifacts=list(directive.get("artifacts") or []),
            constraints=list(directive.get("constraints") or []),
            hop_index=int(directive["hop_index"]),
        )
        self._db.add(event)
        await self._db.flush()
        return event

    @staticmethod
    async def record_handoff_anchor(
        *, user_id: str, session_id: str, directive: dict[str, Any]
    ) -> ChatHandoffEventModel:
        """使用独立事务持久化交接审计，避免流式请求中断回滚已发生的转交。"""
        event = ChatHandoffEventModel(
            session_id=session_id,
            user_id=user_id,
            source_agent_id=str(directive["source_agent_id"]),
            target_agent_id=str(directive["target_agent_id"]),
            reason=str(directive["reason"]),
            handoff_summary=str(directive["handoff_summary"]),
            user_intent=str(directive["user_intent"]),
            artifacts=list(directive.get("artifacts") or []),
            constraints=list(directive.get("constraints") or []),
            hop_index=int(directive["hop_index"]),
        )
        async with get_session_factory()() as db:
            db.add(event)
            await db.commit()
        return event

    @staticmethod
    def _parse_max_hops(value: Any) -> int:
        try:
            parsed = int(value or DEFAULT_MAX_HOPS)
        except (TypeError, ValueError):
            parsed = DEFAULT_MAX_HOPS
        return min(max(parsed, 1), MAX_HOPS_CEILING)

    @staticmethod
    def _normalize_text(value: str, label: str, limit: int) -> str:
        normalized = str(value or "").strip()
        if not normalized:
            raise BusinessError(f"{label}不能为空")
        if len(normalized) > limit:
            raise BusinessError(f"{label}不能超过 {limit} 个字符")
        return normalized

    @classmethod
    def _normalize_list(
        cls, values: list[str] | None, label: str, limit: int, item_limit: int
    ) -> list[str]:
        normalized: list[str] = []
        for value in values or []:
            item = str(value).strip()
            if not item:
                continue
            if len(item) > item_limit:
                raise BusinessError(f"{label}单项不能超过 {item_limit} 个字符")
            if item not in normalized:
                normalized.append(item)
        if len(normalized) > limit:
            raise BusinessError(f"{label}最多 {limit} 项")
        return normalized

    @classmethod
    def _normalize_artifacts(cls, values: list[str] | None) -> list[str]:
        artifacts = cls._normalize_list(values, "产物", 8, 300)
        for path in artifacts:
            if path.startswith("/") or ".." in path.split("/"):
                raise BusinessError("产物路径必须是用户工作区内的相对路径")
        return artifacts

    @staticmethod
    def _build_packet(
        *,
        source_name: str,
        reason: str,
        user_intent: str,
        handoff_summary: str,
        artifacts: list[str],
        constraints: list[str],
    ) -> str:
        def render(items: list[str]) -> str:
            return "\n".join(f"- {item}" for item in items) if items else "- 无"

        packet = (
            f"## 会话交接（来自 {source_name}）\n"
            f"- 转交原因：{reason}\n"
            f"- 用户原始诉求：{user_intent}\n"
            f"- 已完成工作摘要：{handoff_summary}\n"
            f"- 相关产物（位于用户 workspace）：\n{render(artifacts)}\n"
            f"- 约束与背景：\n{render(constraints)}\n"
            "请在此基础上继续，不要重复已完成的工作；如需更多细节，可读取上述产物文件或向用户确认。"
        )
        encoded = packet.encode("utf-8")
        if len(encoded) <= MAX_HANDOFF_PACKET_BYTES:
            return packet
        suffix = "\n[交接包已按预算截断]"
        return (
            encoded[: MAX_HANDOFF_PACKET_BYTES - len(suffix.encode("utf-8"))].decode(
                "utf-8", errors="ignore"
            )
            + suffix
        )

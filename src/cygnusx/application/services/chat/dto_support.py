"""聊天持久化模型到 API DTO 的转换。"""

from __future__ import annotations

from typing import Any

from cygnusx.application.schemas.chat import ChatAssistantDTO, ChatMessageDTO
from cygnusx.infrastructure.database.models.chat import ChatAssistantModel, ChatMessageModel


class ChatDtoSupport:
    """提供与运行时无关的消息和助手 DTO 转换。"""

    @staticmethod
    def _order_messages(messages: Any) -> list[ChatMessageModel]:
        """为历史消息提供稳定的会话顺序。"""
        role_order = {"user": 0, "assistant": 1, "tool": 2, "system": 3}
        return sorted(
            messages,
            key=lambda message: (
                message.created_at,
                role_order.get(message.role, 4),
                message.message_id,
            ),
        )

    @staticmethod
    def _to_msg_dto(
        message: ChatMessageModel,
        tool_output_replay: dict[str, Any] | None = None,
    ) -> ChatMessageDTO:
        usage = (message.metadata_json or {}).get("usage") or {} if message.role == "assistant" else {}
        input_tokens = (
            usage.get("prompt_tokens", 0) or usage.get("input_tokens", 0) or usage.get("input", 0)
        )
        output_tokens = (
            usage.get("completion_tokens", 0)
            or usage.get("output_tokens", 0)
            or usage.get("output", 0)
        )
        total_tokens = (
            usage.get("total_tokens", 0) or usage.get("total", 0) or input_tokens + output_tokens
        )
        cached_tokens = usage.get("cached_tokens", 0) or 0
        # WP2 双读：有事件的消息在终态快照 metadata 之外附带过程态回放块；
        # 无事件的旧会话不传 replay，metadata 原样透传，行为与升级前完全一致
        metadata_json = dict(message.metadata_json or {})
        if tool_output_replay:
            metadata_json["tool_output_replay"] = tool_output_replay
        return ChatMessageDTO(
            message_id=message.message_id,
            role=message.role,
            content=message.content,
            content_type=message.content_type,
            status=message.status,
            metadata_json=metadata_json,
            created_at=message.created_at,
            tokens={
                "input": input_tokens,
                "output": output_tokens,
                "total": total_tokens,
                "cached": cached_tokens,
            },
        )

    @staticmethod
    def _to_ast_dto(assistant: ChatAssistantModel) -> ChatAssistantDTO:
        return ChatAssistantDTO(
            assistant_id=assistant.assistant_id,
            name=assistant.name,
            description=assistant.description,
            system_prompt=assistant.system_prompt,
            default_model_id=assistant.default_model_id,
            default_temperature=assistant.default_temperature,
            default_max_tokens=assistant.default_max_tokens,
            icon=assistant.icon,
            color=assistant.color,
            category=assistant.category,
            is_builtin=assistant.is_builtin,
            is_active=assistant.is_active,
            is_default=assistant.is_default,
        )

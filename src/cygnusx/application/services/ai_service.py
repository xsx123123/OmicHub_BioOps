"""AI Copilot 应用服务 — 对话编排 + 流式响应 + Tool Use"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.schemas.ai import (
    ConversationDetailDTO,
    ConversationDTO,
    CreateConversationDTO,
    MessageDTO,
)
from cygnusx.application.services.ai_tools import AIToolExecutor
from cygnusx.core.config import get_settings
from cygnusx.core.exceptions import NotFoundError
from cygnusx.domain.ai.entities import Conversation, Message
from cygnusx.domain.ai.services import AIDomainService
from cygnusx.infrastructure.ai_provider import get_llm_provider
from cygnusx.infrastructure.config.prompt_loader import get_prompt
from cygnusx.infrastructure.database.repositories.ai_repository import (
    SqlAlchemyConversationRepository,
)


def _message_to_dto(msg: Message) -> MessageDTO:
    return MessageDTO(
        id=msg.id,
        role=msg.role.value if hasattr(msg.role, "value") else str(msg.role),
        content=msg.content,
        tool_calls=msg.tool_calls,
        tool_call_id=msg.tool_call_id,
        timestamp=msg.timestamp,
    )


def _conversation_to_dto(conv: Conversation, message_count: int | None = None) -> ConversationDTO:
    cnt = message_count if message_count is not None else len(conv.context_window.messages)
    return ConversationDTO(
        id=conv.id,
        user_id=conv.user_id,
        title=conv.title,
        model=conv.model,
        assistant_id=conv.assistant_id,
        message_count=cnt,
        created_at=conv.created_at,
        updated_at=conv.updated_at,
    )


class AIService:
    """AI Copilot 应用服务"""

    # 内置工具定义（OpenAI function calling 格式）
    TOOLS: list[dict[str, Any]] = [
        {
            "type": "function",
            "function": {
                "name": "submit_task",
                "description": "提交一个多组学分析任务，如 RNA-seq / ATAC-seq",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "flow_id": {
                            "type": "string",
                            "description": "分析流程 ID，对应 YAML 中 meta.id",
                        },
                        "parameters": {
                            "type": "object",
                            "description": "流程参数键值对",
                        },
                        "sample_sheet": {
                            "type": "array",
                            "description": "样本列表",
                            "items": {"type": "object"},
                        },
                        "name": {
                            "type": "string",
                            "description": "任务名称",
                        },
                    },
                    "required": ["flow_id", "name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "query_status",
                "description": "查询已提交分析任务的状态和进度",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task_id": {
                            "type": "string",
                            "description": "任务 UUID",
                        },
                    },
                    "required": ["task_id"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_samples",
                "description": "列出当前用户可用的样本文件",
                "parameters": {"type": "object", "properties": {}},
            },
        },
    ]

    def __init__(self, db: AsyncSession):
        self._db = db
        self._repo = SqlAlchemyConversationRepository(db)
        self._domain = AIDomainService(self._repo)
        self._settings = get_settings()

    async def create_conversation(
        self, user_id: UUID, req: CreateConversationDTO
    ) -> ConversationDTO:
        model = req.model or self._settings.kimi_model
        conv = await self._domain.create_conversation(user_id, req.title, model)
        conv.assistant_id = req.assistant_id
        await self._repo.save(conv)
        return _conversation_to_dto(conv, 0)

    async def list_conversations(self, user_id: UUID) -> list[ConversationDTO]:
        convs = await self._repo.list_by_user(user_id)
        return [_conversation_to_dto(c, 0) for c in convs]

    async def get_conversation(self, user_id: UUID, conversation_id: UUID) -> ConversationDetailDTO:
        conv = await self._repo.get_by_id(conversation_id)
        if conv is None or conv.user_id != user_id:
            raise NotFoundError("对话不存在")
        messages = [_message_to_dto(m) for m in conv.context_window.messages]
        dto = _conversation_to_dto(conv, len(messages))
        return ConversationDetailDTO(**dto.model_dump(), messages=messages)

    async def delete_conversation(self, user_id: UUID, conversation_id: UUID) -> bool:
        conv = await self._repo.get_by_id(conversation_id)
        if conv is None or conv.user_id != user_id:
            raise NotFoundError("对话不存在")
        return await self._repo.delete(conversation_id)

    async def stream_chat(
        self,
        user_id: UUID,
        conversation_id: UUID,
        content: str,
        assistant_id: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        """流式对话 - 逐 token 推送事件流

        事件类型：
          user_message / token / tool_call / tool_result / assistant_message / done / error
        """
        conv = await self._repo.get_by_id(conversation_id)
        if conv is None or conv.user_id != user_id:
            yield {"type": "error", "detail": "对话不存在"}
            return

        # 追加用户消息
        conv = await self._domain.append_user_message(conv, content)
        last_user = conv.context_window.messages[-1]
        yield {"type": "user_message", "message": _message_to_dto(last_user).model_dump()}

        # 上下文超长则压缩
        if len(conv.context_window.messages) > self._settings.ai_max_context_messages:
            conv = await self._domain.compress_context(conv, self._settings.ai_max_context_messages)

        provider = get_llm_provider()
        if not await provider.is_configured():
            yield {
                "type": "error",
                "detail": "AI 服务未配置：请在 .env 设置 KIMI_API_KEY / OPENAI_API_KEY，或在管理后台配置 AI Provider",
            }
            yield {"type": "done"}
            return

        # 构建 system prompt：基础 + 助手 + 技能
        system_prompt = (
            self._settings.ai_system_prompt or get_prompt("copilot.system")
        ) + get_prompt("copilot.tool_use")

        # 助手 system prompt 注入
        effective_assistant_id = conv.assistant_id or assistant_id
        if effective_assistant_id:
            from cygnusx.infrastructure.database.models.chat import ChatAssistantModel

            result = await self._db.execute(
                select(ChatAssistantModel).where(
                    ChatAssistantModel.assistant_id == effective_assistant_id,
                    ChatAssistantModel.is_active == True,  # noqa: E712
                )
            )
            ast = result.scalar_one_or_none()
            if ast and ast.system_prompt:
                system_prompt = ast.system_prompt + get_prompt("copilot.tool_use")

        # 技能 prompt 注入
        try:
            from cygnusx.application.services.skill_service import SkillService

            skills = await SkillService(self._db).get_active_skills()
            if skills:
                system_prompt += SkillService.build_skills_prompt(skills)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"技能注入失败: {e}")

        try:
            messages = await self._domain.build_context_messages(conv, system_prompt)

            # 第一轮：流式调用 + 工具调用
            stream_fn = getattr(provider, "stream_chat_with_tools", None)
            content_parts: list[str] = []
            final_tool_calls: list[dict[str, Any]] = []

            if stream_fn:
                async for ev in stream_fn(
                    messages,
                    temperature=self._settings.ai_temperature,
                    tools=self.TOOLS,
                ):
                    if ev.type == "text" and ev.content:
                        content_parts.append(ev.content)
                        yield {"type": "token", "content": ev.content}
                    elif ev.type == "tool_calls":
                        final_tool_calls = ev.tool_calls or []
            else:
                # Fallback：provider 不支持流式+tools，回退非流式
                response = await provider.chat(
                    messages,
                    temperature=self._settings.ai_temperature,
                    tools=self.TOOLS,
                )
                message = response.get("choices", [{}])[0].get("message", {})
                assistant_content = message.get("content", "") or ""
                content_parts.append(assistant_content)
                final_tool_calls = message.get("tool_calls") or []

            assistant_content = "".join(content_parts)

            # 兼容层：非 FC 模型可能通过文本代码块表达工具调用
            cleaned, extracted_tool_calls = self._extract_tool_calls(assistant_content)
            if extracted_tool_calls:
                assistant_content = cleaned

            # 合并 tool_calls
            tool_calls = self._normalize_tool_calls(final_tool_calls) + extracted_tool_calls

            # 存储助手消息
            conv = await self._domain.append_assistant_message(
                conv, assistant_content, tool_calls=tool_calls or None
            )
            last_assistant = conv.context_window.messages[-1]
            yield {
                "type": "assistant_message",
                "message": _message_to_dto(last_assistant).model_dump(),
            }

            # Tool Use 执行 + 二次流式回答（不变）
            if tool_calls:
                executor = AIToolExecutor(self._db, user_id)
                for tc in tool_calls:
                    yield {"type": "tool_call", "tool": tc["tool"], "arguments": tc["arguments"]}
                    result = await executor.execute(tc["tool"], tc["arguments"])
                    yield {"type": "tool_result", "tool": tc["tool"], "result": result}
                    conv = await self._domain.append_tool_message(
                        conv, tc["tool_call_id"], json.dumps(result, default=str)
                    )

                # 二次流式回答（带工具结果上下文）
                messages2 = await self._domain.build_context_messages(conv, system_prompt)
                final_parts: list[str] = []
                async for token in provider.stream_chat(
                    messages2, temperature=self._settings.ai_temperature
                ):
                    final_parts.append(token)
                    yield {"type": "token", "content": token}
                conv = await self._domain.append_assistant_message(conv, "".join(final_parts))
                last_final = conv.context_window.messages[-1]
                yield {
                    "type": "assistant_message",
                    "message": _message_to_dto(last_final).model_dump(),
                }

        except Exception as e:  # noqa: BLE001
            yield {"type": "error", "detail": f"AI 服务调用失败：{e}"}

        yield {"type": "done"}

    @staticmethod
    def _normalize_tool_calls(raw: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
        """将 OpenAI tool_calls 格式转为内部统一格式"""
        if not raw:
            return []
        result: list[dict[str, Any]] = []
        for tc in raw:
            func = tc.get("function", {})
            arguments = func.get("arguments", "{}")
            try:
                arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
            except json.JSONDecodeError:
                arguments = {}
            result.append(
                {
                    "tool": func.get("name", ""),
                    "arguments": arguments,
                    "tool_call_id": tc.get("id", uuid4().hex),
                }
            )
        return result

    @staticmethod
    def _extract_tool_calls(raw: str) -> tuple[str, list[dict[str, Any]]]:
        """从原始回复中抽取 ```tool``` 块，返回 (清理后正文, 工具调用列表)

        保留兼容层：非 function calling 模型仍可通过代码块触发工具。
        """
        import re

        tool_calls: list[dict[str, Any]] = []
        pattern = re.compile(r"```tool\s*\n(.*?)```", re.DOTALL)
        for match in pattern.finditer(raw):
            try:
                payload = json.loads(match.group(1).strip())
                tool = payload.get("tool", "")
                arguments = payload.get("arguments", {})
                tool_calls.append(
                    {
                        "tool": tool,
                        "arguments": arguments,
                        "tool_call_id": uuid4().hex,
                    }
                )
            except json.JSONDecodeError:
                continue
        cleaned = pattern.sub("", raw).strip()
        return cleaned, tool_calls

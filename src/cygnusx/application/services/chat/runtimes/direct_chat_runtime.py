"""直连模型聊天 Runtime。"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Any

from loguru import logger
from sqlalchemy import select

from cygnusx.application.services.chat.next_step_suggestions import suggestions_metadata
from cygnusx.application.services.chat.runtimes.base import ChatRuntime, ChatRuntimeRequest
from cygnusx.core.config import get_settings
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk, provider_manager
from cygnusx.infrastructure.database.models.ai_provider import AIProviderConfigModel
from cygnusx.middleware.trace_context import session_id_var

if TYPE_CHECKING:
    from cygnusx.application.services.chat_service import ChatService


class DirectChatRuntime(ChatRuntime):
    """承载非 Agent 直连模型的 SSE 流与研究工具回灌。"""

    def __init__(self, service: ChatService) -> None:
        self._service = service

    def __getattr__(self, name: str) -> Any:
        return getattr(self._service, name)

    async def _persist_message_snapshot(
        self,
        message_id: str,
        content: str,
        status: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """保存流式助手消息快照，并在断连前固定事务锚点。"""
        await self.update_message_content(message_id, content, status, metadata)
        await self._commit_stream_anchor()

    async def run(self, request: ChatRuntimeRequest) -> AsyncIterator[ChatChunk]:
        """以统一 Runtime 请求承载直连模型聊天。"""
        if request.model_id is None:
            yield ChatChunk(type="error", content="直连模型聊天缺少模型配置")
            return

        options = request.runtime_context
        async for chunk in self.stream(
            request.user_id,
            request.messages,
            request.model_id,
            session_id=request.session_id,
            assistant_id=options.get("assistant_id"),
            system_prompt=options.get("system_prompt"),
            temperature=options.get("temperature"),
            max_tokens=options.get("max_tokens"),
            enable_web_search=request.enable_web_search,
            project_id=request.project_id,
            page_context=options.get("page_context"),
        ):
            yield chunk

    async def stream(
        self,
        user_id: str,
        messages: list[dict[str, str]],
        model_id: uuid.UUID,
        session_id: str | None = None,
        assistant_id: str | None = None,
        system_prompt: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        enable_web_search: bool = False,
        project_id: str | None = None,
        page_context: str | None = None,
    ) -> AsyncIterator[ChatChunk]:
        from cygnusx.application.services.chat.configuration import (
            KNOWLEDGE_SEARCH_SYSTEM_PROMPT_SUFFIX,
            KNOWLEDGE_SEARCH_TOOL,
            RESEARCH_TOOL_CHANNEL,
            WEB_SEARCH_TOOL,
            build_page_context_prompt,
        )
        from cygnusx.application.services.chat_service import (
            DEFAULT_SYSTEM_PROMPT,
            USER_FACING_CHINESE_PROMPT_SUFFIX,
            _extract_user_message_metadata,
        )

        cookie_error = await self._ensure_cookie_balance(user_id)
        if cookie_error:
            yield ChatChunk(type="error", content=cookie_error)
            return

        # 1. 获取并验证模型配置
        result = await self._db.execute(
            select(AIProviderConfigModel).where(
                AIProviderConfigModel.id == model_id,
                AIProviderConfigModel.is_active == True,  # noqa: E712
            )
        )
        model_config = result.scalar_one_or_none()
        if not model_config:
            yield ChatChunk(type="error", content="指定的模型不存在或未启用")
            return
        if not model_config.api_key:
            yield ChatChunk(
                type="error",
                content=f"模型 '{model_config.name}' 的 API Key 未配置，请联系管理员设置",
            )
            return

        # 2. 获取或创建会话
        if session_id:
            session = await self.get_session(session_id, user_id)
            if not session:
                yield ChatChunk(type="error", content="会话不存在或已被删除")
                return
            current_session_id = session_id
        else:
            title = "新对话"
            if assistant_id:
                ast = await self.get_assistant(assistant_id)
                if ast:
                    title = f"与 {ast.name} 的对话"
            dto = await self.create_session(
                user_id, model_id, title, assistant_id, project_id=project_id,
                require_project=False,
            )
            current_session_id = dto.session_id

        # 发布会话 ID 到上下文：本次流式任务内所有 AI 调用日志都会带上 session_id，
        # 供管理端按会话聚合排查。每个请求运行在独立的 asyncio 上下文副本中，无需 reset。
        session_id_var.set(current_session_id)
        try:
            from opentelemetry import trace as _otel_trace

            _otel_trace.get_current_span().set_attribute("session.id", current_session_id)
        except Exception:  # noqa: BLE001
            pass

        # 3. 确定系统提示词：参数 > 助手配置 > 默认
        final_system_prompt = system_prompt
        if not final_system_prompt and assistant_id:
            ast = await self.get_assistant(assistant_id)
            if ast:
                final_system_prompt = ast.system_prompt
        if not final_system_prompt:
            final_system_prompt = DEFAULT_SYSTEM_PROMPT
        supports_function_tools = bool(
            (model_config.extra_params or {}).get("supports_tools", True)
        )
        research_tools = [KNOWLEDGE_SEARCH_TOOL, WEB_SEARCH_TOOL] if supports_function_tools else []
        if research_tools:
            final_system_prompt = (
                f"{final_system_prompt}\n\n{KNOWLEDGE_SEARCH_SYSTEM_PROMPT_SUFFIX}"
            )
        final_system_prompt = (
            f"{final_system_prompt}\n\n{USER_FACING_CHINESE_PROMPT_SUFFIX}"
        ).strip()
        # 前端按浏览位置附加的页面上下文（如全局侧边栏）：让模型知道用户当前所在页面
        if page_context:
            final_system_prompt = (
                f"{final_system_prompt}\n\n{build_page_context_prompt(page_context)}"
            ).strip()

        # 4. 保存用户消息
        # 敏感信息脱敏：落库前清洗用户消息，DB 不留存原始品种名等敏感词；
        # 同时构建送 LLM 的脱敏副本（不可逆，不还原）
        from cygnusx.core.sanitizer import sanitize_messages, sanitize_text

        sensitive_keywords = get_settings().sensitive_keywords
        user_content_raw = messages[-1].get("content", "") if messages else ""
        user_content = sanitize_text(user_content_raw, sensitive_keywords)
        await self._record_user_message_anchor(
            current_session_id,
            user_content,
            metadata=_extract_user_message_metadata(messages[-1] if messages else {}),
        )

        # 5. 创建 AI 消息记录
        ai_message = await self.add_message(
            current_session_id,
            "assistant",
            "",
            status="streaming",
            metadata={"model": model_config.name, "model_id": str(model_id)},
        )
        await self._commit_stream_anchor()

        # 6. 调用 LLM 流式输出
        # 送外部 LLM 的 messages 用脱敏副本，避免敏感词外泄到第三方模型
        llm_messages = sanitize_messages(
            [
                {"role": item.get("role", ""), "content": item.get("content", "")}
                for item in messages
            ],
            sensitive_keywords,
        )
        web_sources: list[dict[str, Any]] = []
        if enable_web_search and user_content.strip():
            query = user_content.strip()
            presearch_call_id = f"web-presearch-{uuid.uuid4()}"
            yield ChatChunk(
                type="tool_call",
                metadata={
                    "tool_call_id": presearch_call_id,
                    "tool_name": "web_search",
                    "arguments": {"query": query},
                    "mcp_server": RESEARCH_TOOL_CHANNEL,
                },
            )
            yield ChatChunk(type="web_search", content=query, metadata={"status": "searching"})
            try:
                presearch_result = await self._optimized_web_search(
                    query,
                    model_config=model_config,
                )
                web_sources = presearch_result["results"]
                yield ChatChunk(
                    type="tool_result",
                    metadata={
                        "tool_call_id": presearch_call_id,
                        "tool_name": "web_search",
                        "mcp_server": RESEARCH_TOOL_CHANNEL,
                        "success": True,
                        "result": presearch_result,
                        "ui_payload": presearch_result,
                    },
                )
                if web_sources:
                    context = "\n".join(
                        f"[{index}] {item['title']}\n{item['snippet']}\n来源: {item['url']}"
                        for index, item in enumerate(web_sources, 1)
                    )
                    final_system_prompt = (
                        f"{final_system_prompt}\n\n以下是联网搜索结果。仅在确有帮助时引用，"
                        "引用格式使用 [编号]，不要编造来源：\n" + context[:4000]
                    )
                    yield ChatChunk(type="web_search_results", metadata={"sources": web_sources})
                else:
                    yield ChatChunk(
                        type="web_search",
                        content="未找到相关结果，已基于模型知识回答",
                        metadata={"status": "empty"},
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("联网搜索失败，降级为普通对话: %s", exc)
                yield ChatChunk(
                    type="web_search",
                    content="联网搜索失败，已基于模型自身知识回答",
                    metadata={"status": "failed"},
                )
                yield ChatChunk(
                    type="tool_result",
                    metadata={
                        "tool_call_id": presearch_call_id,
                        "tool_name": "web_search",
                        "mcp_server": RESEARCH_TOOL_CHANNEL,
                        "success": False,
                        "result": {"error": str(exc)},
                        "ui_payload": {"error": str(exc)},
                    },
                )
        full_content = ""
        update_counter = 0
        last_usage: dict[str, Any] | None = None

        try:
            final_temp = temperature if temperature is not None else model_config.temperature
            final_max = max_tokens if max_tokens is not None else model_config.max_tokens
            for _round in range(8):
                tool_calls: list[dict[str, Any]] = []
                round_content = ""
                done_chunk: ChatChunk | None = None
                async for chunk in provider_manager.chat_stream(
                    config=model_config,
                    messages=llm_messages,
                    system_prompt=final_system_prompt,
                    temperature=final_temp,
                    max_tokens=final_max,
                    tools=research_tools or None,
                ):
                    if chunk.type == "text":
                        full_content += chunk.content
                        round_content += chunk.content
                        update_counter += 1
                        if update_counter % 5 == 0:
                            await self._persist_message_snapshot(
                                ai_message.message_id, full_content, "streaming"
                            )
                        if update_counter == 1:
                            chunk.metadata["session_id"] = current_session_id
                            chunk.metadata["message_id"] = ai_message.message_id
                        yield chunk
                    elif chunk.type == "tool_calls":
                        tool_calls.extend(
                            item
                            for item in chunk.metadata.get("tool_calls", [])
                            if isinstance(item, dict)
                        )
                    elif chunk.type == "error":
                        await self._persist_message_snapshot(
                            ai_message.message_id,
                            full_content,
                            "error",
                            {"error": chunk.content},
                        )
                        yield chunk
                        return
                    elif chunk.type == "done":
                        done_chunk = chunk
                    else:
                        yield chunk

                if not tool_calls:
                    last_usage = done_chunk.metadata.get("usage") if done_chunk else None
                    await self._persist_message_snapshot(
                        ai_message.message_id,
                        full_content,
                        "complete",
                        {
                            **({"usage": last_usage} if last_usage else {}),
                            **({"web_sources": web_sources} if web_sources else {}),
                            **suggestions_metadata(full_content),
                        }
                        or None,
                    )
                    await self._apply_usage_to_session(ai_message.message_id, last_usage)
                    await self._commit_stream_anchor()
                    done_chunk = done_chunk or ChatChunk(type="done")
                    done_chunk.metadata["session_id"] = current_session_id
                    done_chunk.metadata["message_id"] = ai_message.message_id
                    done_chunk.metadata.update(suggestions_metadata(full_content))
                    yield done_chunk
                    return

                llm_messages.append(
                    {
                        "role": "assistant",
                        "content": round_content or None,
                        "tool_calls": tool_calls,
                    }
                )
                for tool_call in tool_calls:
                    function = tool_call.get("function") or {}
                    tool_name = str(function.get("name") or "")
                    try:
                        args = json.loads(function.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    args = args if isinstance(args, dict) else {}
                    tool_call_id = str(tool_call.get("id") or uuid.uuid4())
                    yield ChatChunk(
                        type="tool_call",
                        metadata={
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "arguments": args,
                            "mcp_server": RESEARCH_TOOL_CHANNEL,
                        },
                    )
                    if tool_name == "knowledge_search":
                        result = await self._knowledge_search_chat(args, project_id=project_id)
                    elif tool_name == "web_search":
                        query = str(args.get("query") or "")
                        yield ChatChunk(
                            type="web_search", content=query, metadata={"status": "searching"}
                        )
                        result = await self._web_search(args)
                        payload = result.get("result") if isinstance(result, dict) else None
                        results = payload.get("results", []) if isinstance(payload, dict) else []
                        if result.get("success") and isinstance(results, list):
                            web_sources.extend(item for item in results if isinstance(item, dict))
                            if results:
                                yield ChatChunk(
                                    type="web_search_results", metadata={"sources": results}
                                )
                            else:
                                yield ChatChunk(
                                    type="web_search",
                                    content="未找到相关结果，已基于模型知识回答",
                                    metadata={"status": "empty"},
                                )
                        else:
                            yield ChatChunk(
                                type="web_search",
                                content="联网搜索失败，已基于模型自身知识回答",
                                metadata={"status": "failed"},
                            )
                    else:
                        result = {"success": False, "error": f"工具 {tool_name} 未挂载"}
                    tool_output = result.get("result") if isinstance(result, dict) else result
                    llm_result = (
                        tool_output if isinstance(tool_output, dict) else {"result": tool_output}
                    )
                    yield ChatChunk(
                        type="tool_result",
                        metadata={
                            "tool_call_id": tool_call_id,
                            "tool_name": tool_name,
                            "mcp_server": RESEARCH_TOOL_CHANNEL,
                            "success": bool(result.get("success"))
                            if isinstance(result, dict)
                            else True,
                            "result": llm_result,
                            "ui_payload": llm_result,
                        },
                    )
                    llm_messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call_id,
                            "content": json.dumps(llm_result, ensure_ascii=False, default=str),
                        }
                    )

            await self._persist_message_snapshot(
                ai_message.message_id,
                full_content,
                "error",
                {"error": "工具调用轮次达到上限"},
            )
            yield ChatChunk(type="error", content="工具调用轮次达到上限")

        except Exception as e:  # noqa: BLE001
            await self._persist_message_snapshot(
                ai_message.message_id,
                full_content,
                "error",
                {"error": str(e)},
            )
            yield ChatChunk(
                type="error",
                content=f"生成失败: {e}",
                metadata={"session_id": current_session_id, "message_id": ai_message.message_id},
            )

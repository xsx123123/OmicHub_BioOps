"""OmicStudio 内置工具 —— Agent Runner 的工作台工具集。

架构设计 §5.2（按仓库现状适配）：Studio 会话在既有 MCP/web_search 之外追加一组内置工具。
沙盒类工具（sandbox_execute / workspace_*）经 studio_sandbox_manager 落到会话专属
沙盒容器（每会话一个工作区，session_id 贯穿）；平台联动类工具（P1）：
- datahub_import / platform_result_import：数据不搬家，软链平台数据进 input/；
- artifact_register：产物登记回结果报告中心（版本树），需要 db + user_id；
- update_plan：待办计划，chat_service 拦截产出 plan 事件（此处为兜底回显）；
- pipeline_query：平台流程/工具只读目录。

双通道约定（与 MCP 工具一致）：dispatcher 返回
``{"success": bool, "result": {"llm_payload": ..., "ui_payload": ...}}``
- llm_payload：回灌 LLM 的紧凑结果（输出截尾、read 默认 200 行，防上下文爆炸）；
- ui_payload：前端渲染用的完整载荷（产物清单、diff、分页内容等）。

所有异常（沙盒不可用 / agent 4xx / 网络错误）都收敛为 success=False 的友好 payload，
绝不上抛，保证 Agent Runner 的工具闭环不被打断。
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from cygnusx.application.services.chat_message_event_service import message_event_service
from cygnusx.application.services.network_request_tool import (
    NETWORK_REQUEST_TOOL_NAME,
    NETWORK_REQUEST_TOOL_SCHEMA,
)
from cygnusx.application.services.ptc_orchestrator import (
    PTC_DEFAULT_TIMEOUT_SECONDS,
    run_orchestration,
)
from cygnusx.application.services.studio_context_service import (
    import_datahub_file,
    link_report_files,
    register_artifact_report,
)
from cygnusx.core.exceptions import CygnusXError
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk
from cygnusx.infrastructure.config.prompt_loader import get_prompt
from cygnusx.infrastructure.config.studio_loader import get_studio_config
from cygnusx.infrastructure.database.models.chat import ChatSessionModel
from cygnusx.infrastructure.database.models.report import ReportModel
from cygnusx.infrastructure.studio.manager import (
    StudioSandboxUnavailableError,
    studio_sandbox_manager,
)
from cygnusx.tools.schema_loader import schema_loader

# ===== 工具名与 OpenAI schema =====

# ask_user 澄清工具：Studio 与普通聊天会话均挂载（普通会话同样以交互卡片收集回答），
# 因此 schema 独立成常量；其余 Studio 工具仍只在 Studio 会话可用。
ASK_USER_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": (
            "向用户提问以澄清需求（缺物种、缺文件、缺参数等）。问题会以可交互卡片展示："
            "用户可点选选项、选择“其他”自由输入或跳过。调用后本轮回复随即结束，"
            "用户将在下一条消息中回答。不要编造参数，信息不足时先用本工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question": {"type": "string", "description": "要问用户的问题"},
                            "options": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": (
                                    "可一键点选的互斥选项；用户也可选“其他”自由输入。"
                                    "有推荐项时必须放在数组首位，并在选项文本中以（推荐）标注"
                                ),
                            },
                        },
                        "required": ["question"],
                    },
                    "description": "一次可向用户提 1~3 个问题，前端逐个分页收集回答（优先使用）",
                },
                "question": {
                    "type": "string",
                    "description": "要问用户的单个问题（兼容字段；提供了 questions 时忽略）",
                },
                "options": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "单个问题的快捷选项（兼容字段，与 question 搭配）",
                },
            },
            "required": [],
        },
    },
}

#: 显式 Finalize 动作（openai4s 外循环三选一之一，见 agent_execution_framework.md §3.3）：
# 模型主动提交最终答复并结束本轮，替代"无 tool_calls 的被动结束"。
# 仅 LangGraph 单 Runtime 挂载（legacy 逃生舱不识别本工具）。
SUBMIT_OUTPUT_TOOL_NAME = "submit_output"
SUBMIT_OUTPUT_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": SUBMIT_OUTPUT_TOOL_NAME,
        "description": (
            "提交最终答复并显式结束本轮（Finalize 动作）。当已有信息足以给出完整结论时调用，"
            "将最终答复全文写入 output 参数。调用后本轮立即结束，正文会以普通回复展示给用户；"
            "不要同时再输出正文或其他工具调用。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "output": {
                    "type": "string",
                    "description": "提交给用户的最终答复全文（Markdown）",
                },
            },
            "required": ["output"],
        },
    },
}

STUDIO_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "sandbox_execute",
        "workspace_write",
        "workspace_edit",
        "workspace_read",
        "workspace_list",
        "cygnusx_workspace_remember",
        "datahub_import",
        "platform_result_import",
        "artifact_register",
        "update_plan",
        "pipeline_query",
        "knowledge_search",
        "browser_navigate",
        "browser_screenshot",
        "browser_click",
        "browser_type",
        "browser_press",
        "browser_close",
        "document_inspect",
        "document_create",
        "document_edit",
        "document_convert",
        "onlyoffice_status",
        "onlyoffice_convert",
        "tool_orchestrate",
        "ask_user",
        NETWORK_REQUEST_TOOL_NAME,
    }
)

# 待办计划自动推进（§5.3 agent.plan）覆盖的工具：写操作/产物产出类。
# 模型经常只在任务开始时调用一次 update_plan（全 pending），不再更新，
# 导致已完成任务的待办卡片长期停留在"待执行"；成功执行下列工具后自动
# 推进 in_progress→done、pending→in_progress。查询/状态类只读工具不推进。
PLAN_ADVANCE_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "sandbox_execute",
        "workspace_write",
        "workspace_edit",
        "datahub_import",
        "platform_result_import",
        "artifact_register",
        "document_create",
        "document_edit",
        "document_convert",
        "onlyoffice_convert",
        "tool_orchestrate",
    }
)

STUDIO_TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "sandbox_execute",
            "description": (
                "在会话专属沙盒中执行代码（python/r/bash），流式返回 stdout/stderr，"
                "结束后给出 exit_code、耗时与 /workspace/output 下新增/修改的产物清单。"
                "请先用 workspace_write 把脚本落盘，再用本工具运行。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "language": {
                        "type": "string",
                        "enum": ["python", "r", "bash"],
                        "description": "执行语言",
                    },
                    "code": {"type": "string", "description": "要执行的完整代码"},
                    "timeout": {
                        "type": "integer",
                        "description": "超时秒数，缺省用沙盒默认（600s）",
                    },
                },
                "required": ["language", "code"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_write",
            "description": (
                "写文件到会话工作区 /workspace（新建或整体覆盖，自动创建父目录）。"
                "生成脚本请落盘到工作区（如 scripts/xxx.py），产物文件放 output/。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对 /workspace 的路径"},
                    "content": {"type": "string", "description": "完整文件内容"},
                },
                "required": ["path", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_edit",
            "description": (
                "对工作区文件做精确文本替换（old_string 必须在文件中唯一出现），"
                "返回 unified diff。修改已有文件优先用本工具，不要盲目整体重写。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对 /workspace 的路径"},
                    "old_string": {"type": "string", "description": "被替换的原始文本（需唯一）"},
                    "new_string": {"type": "string", "description": "替换后的新文本"},
                },
                "required": ["path", "old_string", "new_string"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_read",
            "description": (
                "分页读取工作区文本文件，默认只回前 200 行；"
                "大文件请用 offset/limit 翻页，不要一次读入整个文件。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "相对 /workspace 的路径"},
                    "offset": {"type": "integer", "default": 0, "description": "起始行（0 基）"},
                    "limit": {
                        "type": "integer",
                        "default": 200,
                        "description": "读取行数（默认 200，最大 2000）",
                    },
                },
                "required": ["path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "workspace_list",
            "description": "分页列出工作区目录内容，含名称/类型/大小/修改时间。",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "default": "",
                        "description": "相对 /workspace 的目录路径，缺省为根目录",
                    },
                    "offset": {"type": "integer", "default": 0, "description": "起始条目（0 基）"},
                    "limit": {
                        "type": "integer",
                        "default": 200,
                        "description": "返回条目数（默认 200，最大 1000）",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cygnusx_workspace_remember",
            "description": "将工作区记忆正文写入 .memory 并追加 MEMORY.md 索引；正文不会自动注入上下文。",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string", "description": "记忆标题"},
                    "summary": {"type": "string", "description": "索引中的一句话摘要"},
                    "content": {"type": "string", "description": "记忆正文"},
                },
                "required": ["title", "summary", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "datahub_import",
            "description": (
                "从平台「数据管理」引入文件到工作区：在 /workspace/input/ 下建立只读软链"
                "（数据不搬家），返回沙盒内可读路径，引入后即可用 pandas 等直接读取。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "file_id": {"type": "string", "description": "数据管理中的文件 ID"},
                    "name": {
                        "type": "string",
                        "description": "工作区内显示名，缺省用原文件名",
                    },
                },
                "required": ["file_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "platform_result_import",
            "description": (
                "把平台「结果报告中心」某个报告的全部产物文件引入当前工作区"
                "（/workspace/input/ 只读软链），用于对既有流程结果做二次分析。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "report_id": {"type": "string", "description": "报告 ID"},
                },
                "required": ["report_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "artifact_register",
            "description": (
                "把 /workspace/output/ 下的产物登记到平台「结果报告中心」生成新报告；"
                "若当前会话由报告优化场景创建，自动挂为原报告的下一版本（版本树）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "产物路径（相对 /workspace，必须在 output/ 下）",
                    },
                    "title": {"type": "string", "description": "报告标题"},
                    "type": {
                        "type": "string",
                        "description": "产物类型（html/pdf/png/csv 等），缺省按扩展名推断",
                    },
                    "description": {"type": "string", "description": "报告描述"},
                },
                "required": ["path", "title"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "update_plan",
            "description": (
                "更新任务执行计划（3-8 步），驱动右栏待办面板。开始任务前先建立计划，"
                "每完成一步及时把该步骤标为 done、下一步标为 in_progress。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "steps": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string", "description": "步骤标题"},
                                "status": {
                                    "type": "string",
                                    "enum": ["pending", "in_progress", "done"],
                                },
                            },
                            "required": ["title", "status"],
                        },
                        "description": "计划步骤列表（3-8 步）",
                    },
                },
                "required": ["steps"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "knowledge_search",
            "description": (
                "检索已发布的 CygnusX 实验室知识库文档，返回标题、分类和短摘录。"
                "只读，不返回待审核文档或整篇正文；需要完整内容时请打开返回的文档 ID。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "知识检索关键词"},
                    "limit": {
                        "type": "integer",
                        "minimum": 1,
                        "maximum": 8,
                        "description": "最多返回条数，缺省 5",
                    },
                },
                "required": ["query"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "pipeline_query",
            "description": (
                "查询平台内置分析流程与生信工具的只读目录（名称/简介/分类），"
                "用于了解平台已有能力、建议用户复用现成流程而非重复造轮子。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "可选关键词，按名称/简介过滤；缺省返回全部目录",
                    },
                },
                "required": [],
            },
        },
    },
    ASK_USER_TOOL_SCHEMA,
]

# tool_orchestrate（Programmatic Tool Calling）：模型提交一段 Python 编排代码，
# 在宿主受限子进程中运行并可多次回调白名单内工具（见 ptc_orchestrator.py）。
# 中间子调用结果不回灌模型上下文，只回传代码 print 的最终汇总——schema 不进
# STUDIO_TOOL_SCHEMAS，由 chat_service 按 agent features.ptc_enabled 条件挂载。
TOOL_ORCHESTRATE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "tool_orchestrate",
        "description": (
            "用一段 Python 代码编排调用多个平台工具（批量/循环/条件分支场景，如遍历多个文件"
            "逐个处理再汇总）。代码中可用两个注入函数：call_tool(name, **args) 调用单个工具"
            "（成功返回结果 dict，失败抛 RuntimeError）；parallel_calls([{'name':..., 'args': {...}}])"
            " 并发调用多个工具（按顺序返回结果列表，单项失败位置为 {'error': ...}）。"
            "可用工具：workspace_read / workspace_list / workspace_write / workspace_edit / "
            "sandbox_execute / knowledge_search / pipeline_query / document_inspect / "
            "document_create / document_edit / document_convert / datahub_import / "
            "platform_result_import / artifact_register / llm_query"
            "（call_tool('llm_query', prompt='...', system_hint=None) 向当前会话模型发起一次"
            "受限问答，返回 {'answer', 'model', 'usage'}，不进入宿主上下文、全程审计）。"
            "重要契约：子调用的中间结果不会回传给你，代码必须用 print 输出最终汇总，"
            "你只能看到 print 的内容。单次最多 50 次子调用，总超时默认 600 秒。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python 编排代码，必须用 print 输出最终汇总",
                },
                "timeout": {
                    "type": "integer",
                    "description": "总超时秒数（默认 600，上限 1800）",
                },
            },
            "required": ["code"],
        },
    },
}


def studio_runtime_tool_schemas(features: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Studio 工具 schema 全集 + 按 agent features 条件挂载的工具。

    目前仅 ptc_enabled → tool_orchestrate；chat_service._studio_runtime 统一经此
    组装，保证工具名单与下发给模型的 schema 一致。
    """
    schemas = list(STUDIO_TOOL_SCHEMAS)
    if (features or {}).get("ptc_enabled"):
        schemas.append(TOOL_ORCHESTRATE_SCHEMA)
    return schemas


def _studio_function_schema(
    name: str, description: str, properties: dict[str, Any], required: list[str] | None = None
) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required or [],
            },
        },
    }


STUDIO_TOOL_SCHEMAS.extend(
    [
        NETWORK_REQUEST_TOOL_SCHEMA,
        _studio_function_schema(
            "browser_navigate",
            "在会话专属 Chromium 中打开网页，返回标题、状态码、正文摘要和链接。仅允许 http/https；遵循沙箱网络白名单。",
            {
                "url": {"type": "string", "description": "目标 URL"},
                "wait_until": {
                    "type": "string",
                    "enum": ["commit", "domcontentloaded", "load", "networkidle"],
                    "default": "domcontentloaded",
                },
                "timeout": {"type": "integer", "default": 30, "maximum": 120},
            },
            ["url"],
        ),
        _studio_function_schema(
            "browser_screenshot",
            "截取当前 Chromium 页面或 CSS 选择器元素，图片写入工作区并返回路径。",
            {
                "path": {"type": "string", "default": "output/browser-screenshot.png"},
                "selector": {"type": "string", "default": ""},
                "full_page": {"type": "boolean", "default": False},
                "timeout": {"type": "integer", "default": 30, "maximum": 120},
            },
        ),
        _studio_function_schema(
            "browser_click",
            "点击当前页面中唯一明确的 CSS 选择器元素。",
            {
                "selector": {"type": "string"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "default": "left"},
                "click_count": {"type": "integer", "default": 1, "maximum": 3},
                "timeout": {"type": "integer", "default": 30, "maximum": 120},
            },
            ["selector"],
        ),
        _studio_function_schema(
            "browser_type",
            "向当前页面的输入控件填入文本；默认清空后填入，避免误拼接用户数据。",
            {
                "selector": {"type": "string"},
                "text": {"type": "string"},
                "clear": {"type": "boolean", "default": True},
                "timeout": {"type": "integer", "default": 30, "maximum": 120},
            },
            ["selector", "text"],
        ),
        _studio_function_schema(
            "browser_press",
            "向当前页面的指定元素发送键盘按键。",
            {
                "selector": {"type": "string"},
                "key": {"type": "string"},
                "timeout": {"type": "integer", "default": 30, "maximum": 120},
            },
            ["selector", "key"],
        ),
        _studio_function_schema(
            "browser_close",
            "关闭当前会话的 Chromium 上下文并清理页面状态。",
            {},
        ),
        _studio_function_schema(
            "document_inspect",
            "检查工作区文档的格式、大小、页/表信息和受限预览。支持文本、DOCX、XLSX 等。",
            {"path": {"type": "string", "description": "相对 /workspace 的文档路径"}},
            ["path"],
        ),
        _studio_function_schema(
            "document_create",
            "创建文本、DOCX 或 XLSX 文档。内容落在会话工作区，不能写入 input/ 或 ref/。",
            {
                "path": {"type": "string"},
                "title": {"type": "string", "default": ""},
                "content": {"type": "string", "default": ""},
            },
            ["path"],
        ),
        _studio_function_schema(
            "document_edit",
            "对文本、DOCX 或 XLSX 文档执行受限字符串替换，返回修改数量和新的文档摘要。",
            {
                "path": {"type": "string"},
                "operations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"old": {"type": "string"}, "new": {"type": "string"}},
                        "required": ["old", "new"],
                    },
                },
            },
            ["path", "operations"],
        ),
        _studio_function_schema(
            "document_convert",
            "用沙箱内 LibreOffice headless 将文档转换为 PDF、DOCX、XLSX 等格式，产物写入 output/。",
            {
                "path": {"type": "string"},
                "output_format": {"type": "string", "description": "例如 pdf、docx、xlsx"},
                "output_path": {"type": "string", "default": ""},
            },
            ["path", "output_format"],
        ),
        _studio_function_schema(
            "onlyoffice_status",
            "检查当前会话是否配置并能访问 OnlyOffice Document Server；不可用时不会伪造成功。",
            {},
        ),
        _studio_function_schema(
            "onlyoffice_convert",
            "请求 OnlyOffice Document Server 转换文档。只有配置远程 Document Server 且文档可被其访问时才执行。",
            {
                "path": {"type": "string"},
                "output_format": {"type": "string"},
                "output_path": {"type": "string", "default": ""},
                "async_mode": {"type": "boolean", "default": False},
            },
            ["path", "output_format"],
        ),
    ]
)

# ===== Studio 系统提示词后缀（架构设计 §5.2，中文紧凑版）=====

STUDIO_SYSTEM_PROMPT_SUFFIX = "\n\n".join(
    value for value in (get_prompt("studio.system"), get_prompt("shared.sandbox_protocol")) if value
)

# ===== 通道截断常量 =====

_LLM_STDOUT_TAIL = 2000  # llm_payload stdout 尾部保留上限（字符）
_LLM_STDERR_TAIL = 1000  # llm_payload stderr 尾部保留上限（字符）
_UI_OUTPUT_CAP = 20000  # ui_payload 单通道输出上限（字符；agent 流内已限 10KB）
_STREAM_QUEUE_MAX_CHUNKS = 32  # 慢客户端时限制待发送 tool_output 事件
_LIST_LLM_CAP = 200  # workspace_list 回灌 LLM 的条目上限
# 长时间无输出（如沙盒静默计算）时按此间隔下发 SSE 心跳，防反向代理读超时掐断流
_STREAM_HEARTBEAT_INTERVAL_SECONDS = 15

# 输出增量回调：(stream, data) -> None；stream ∈ {"stdout", "stderr"}
OutputCallback = Callable[[str, str], Awaitable[None]]


def _tail(text: str, limit: int) -> tuple[str, bool]:
    """保留尾部 limit 字符，返回 (文本, 是否截断)。"""
    if len(text) <= limit:
        return text, False
    return text[-limit:], True


def _append_bounded_text(current: str, data: str, limit: int) -> tuple[str, bool]:
    """追加输出并只保留尾部，避免慢客户端或异常工具撑大 Web 进程内存。"""
    combined = f"{current}\n{data}" if current else data
    return _tail(combined, limit)


def _error_result(message: str) -> dict[str, Any]:
    """失败信封：llm/ui 双通道同一份错误，闭环不中断。"""
    payload = {"error": message}
    return {
        "success": False,
        "result": {"llm_payload": payload, "ui_payload": dict(payload)},
    }


def _ok_result(llm_payload: dict[str, Any], ui_payload: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "result": {"llm_payload": llm_payload, "ui_payload": ui_payload}}


async def _workspace_remember(args: dict[str, Any], session_id: str) -> dict[str, Any]:
    """写入正文和索引；失败时恢复两者原状。"""
    from datetime import date

    title = str(args.get("title") or "").strip()
    summary = str(args.get("summary") or "").strip()
    content = str(args.get("content") or "")
    if not title or not summary or not content:
        return _error_result("title、summary、content 均不能为空")
    workspace = studio_sandbox_manager.workspace_dir(session_id)
    memory_dir = workspace / ".memory"
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", title).strip("-").lower() or "note"
    index_path = workspace / "MEMORY.md"
    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
        old_index = index_path.read_bytes() if index_path.exists() else None
        index = old_index.decode("utf-8") if old_index else ""
        entries = [line for line in index.splitlines() if line.lstrip().startswith("- [")]
        if len(entries) >= 200:
            return _error_result("MEMORY.md 已达到 200 条，请先合并精简记忆")

        date_prefix = date.today().isoformat()
        note_path = memory_dir / f"{date_prefix}-{slug}.md"
        suffix = 2
        while note_path.exists():
            note_path = memory_dir / f"{date_prefix}-{slug}-{suffix}.md"
            suffix += 1
        old_note = note_path.read_bytes() if note_path.exists() else None
        entry = f"- [{title}](.memory/{note_path.name}) — {summary}"
    except (OSError, UnicodeDecodeError) as exc:
        return _error_result(f"工作区记忆准备失败: {exc}")

    try:
        note_path.write_text(f"# {title}\n\n{content}\n", encoding="utf-8")
        index_path.write_text(
            (index.rstrip() + "\n" if index.strip() else "") + entry + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        if old_note is None:
            note_path.unlink(missing_ok=True)
        else:
            note_path.write_bytes(old_note)
        if old_index is None:
            index_path.unlink(missing_ok=True)
        else:
            index_path.write_bytes(old_index)
        return _error_result(f"工作区记忆写入失败: {exc}")
    payload = {"title": title, "summary": summary, "path": f".memory/{note_path.name}", "index": "MEMORY.md"}
    return _ok_result(payload, dict(payload))


# ===== 各工具执行器 =====


async def _sandbox_execute(
    args: dict[str, Any],
    session_id: str,
    image: str | None,
    on_output: OutputCallback | None,
    user_id: str | None = None,
) -> dict[str, Any]:
    language = str(args.get("language") or "python")
    if language not in ("python", "r", "bash"):
        return _error_result(f"不支持的语言: {language}（仅支持 python / r / bash）")
    code = str(args.get("code") or "")
    if not code.strip():
        return _error_result("code 不能为空")
    timeout_raw = args.get("timeout")
    timeout_sec = int(timeout_raw) if isinstance(timeout_raw, int | float) else None

    if timeout_sec is not None and user_id:
        from cygnusx.application.services.studio_task_service import (
            STUDIO_LONG_TASK_THRESHOLD_SECONDS,
            submit_studio_sandbox_task,
        )

        if timeout_sec > STUDIO_LONG_TASK_THRESHOLD_SECONDS:
            command_id = str(args.get("command_id") or "").strip() or None
            queued = await submit_studio_sandbox_task(
                user_id=user_id,
                session_id=session_id,
                language=language,
                code=code,
                timeout_sec=min(timeout_sec, 3600),
                image=image,
                command_id=command_id,
            )
            llm_payload = {
                "task_id": queued["task_id"],
                "status": queued["status"],
                "message": "预计执行超过 10 分钟，已转入任务中心后台执行。完成后请刷新工作区查看产物。",
            }
            if queued.get("deduplicated"):
                llm_payload["message"] = (
                    "相同任务已存在（幂等去重），直接沿用既有后台任务，完成后请刷新工作区查看产物。"
                )
            return _ok_result(llm_payload, {**queued, "message": llm_payload["message"]})

    stdout_full = ""
    stderr_full = ""
    stdout_buffer_cut = False
    stderr_buffer_cut = False
    plotly_figures: list[Any] = []
    result_event: dict[str, Any] = {}
    async for event in studio_sandbox_manager.exec(
        session_id, language, code, timeout_sec=timeout_sec, image=image, user_id=user_id
    ):
        etype = event.get("type")
        if etype in ("stdout", "stderr"):
            data = str(event.get("data", ""))
            if etype == "stdout":
                stdout_full, was_cut = _append_bounded_text(stdout_full, data, _UI_OUTPUT_CAP)
                stdout_buffer_cut = stdout_buffer_cut or was_cut
            else:
                stderr_full, was_cut = _append_bounded_text(stderr_full, data, _UI_OUTPUT_CAP)
                stderr_buffer_cut = stderr_buffer_cut or was_cut
            if on_output is not None:
                await on_output(etype, data)
        elif etype == "plotly":
            # 沙盒内 show_plotly(fig) 发射的 figure JSON，交给前端交互式渲染
            figure = event.get("data")
            if isinstance(figure, dict):
                plotly_figures.append(figure)
        elif etype == "result":
            result_event = event

    exit_code = result_event.get("exit_code", -1)
    duration_ms = result_event.get("duration_ms", 0)
    artifacts = result_event.get("artifacts") or []
    overflow_logs = result_event.get("truncated_output_files") or []

    stdout_tail, stdout_cut = _tail(stdout_full, _LLM_STDOUT_TAIL)
    stderr_tail, stderr_cut = _tail(stderr_full, _LLM_STDERR_TAIL)
    llm_payload: dict[str, Any] = {
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": stdout_tail,
        "stderr": stderr_tail,
        "artifacts": artifacts,
    }
    if result_event.get("timed_out"):
        llm_payload["timed_out"] = True
        llm_payload["error"] = result_event.get("error", "执行超时")
    if plotly_figures:
        llm_payload["plotly_count"] = len(plotly_figures)
        llm_payload["plotly_note"] = (
            "plotly 图表已在消息中内联交互预览，无需再引导用户下载 HTML 查看"
        )
    if stdout_cut or stderr_cut or stdout_buffer_cut or stderr_buffer_cut or overflow_logs:
        llm_payload["output_truncated"] = True
        llm_payload["note"] = (
            "输出过长已截尾；完整输出在工作区 .logs/ 下，可用 workspace_read 分页读取"
        )
        if overflow_logs:
            llm_payload["output_files"] = overflow_logs

    ui_payload: dict[str, Any] = {
        "language": language,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "stdout": _tail(stdout_full, _UI_OUTPUT_CAP)[0],
        "stderr": _tail(stderr_full, _UI_OUTPUT_CAP)[0],
        "artifacts": artifacts,
    }
    if plotly_figures:
        ui_payload["plotly_figures"] = plotly_figures
    if result_event.get("timed_out"):
        ui_payload["timed_out"] = True
        ui_payload["error"] = result_event.get("error", "执行超时")
    if overflow_logs:
        ui_payload["output_files"] = overflow_logs

    # 非零退出不算工具失败：结果照常回灌，由模型解读报错
    return _ok_result(llm_payload, ui_payload)


async def _tool_orchestrate(
    args: dict[str, Any],
    session_id: str,
    image: str | None,
    on_output: OutputCallback | None,
    user_id: str | None,
    db: AsyncSession | None,
) -> dict[str, Any]:
    """tool_orchestrate：模型提交的编排代码交给 ptc_orchestrator 在受限子进程运行，
    子调用进度经 on_output 以 stdout 流桥接给前端（同 sandbox_execute 的流式通道）。"""
    code = str(args.get("code") or "")
    if not code.strip():
        return _error_result("code 不能为空")
    timeout_raw = args.get("timeout")
    timeout_sec = (
        int(timeout_raw) if isinstance(timeout_raw, int | float) else PTC_DEFAULT_TIMEOUT_SECONDS
    )

    async def _progress(text: str) -> None:
        if on_output is not None:
            await on_output("stdout", f"{text}\n")

    return await run_orchestration(
        code,
        session_id,
        user_id=user_id,
        db=db,
        image=image,
        timeout_sec=timeout_sec,
        on_progress=_progress,
    )


async def _workspace_write(
    args: dict[str, Any], session_id: str, image: str | None, user_id: str | None = None
) -> dict[str, Any]:
    path = str(args.get("path") or "")
    content = str(args.get("content") or "")
    if not path:
        return _error_result("path 不能为空")
    data = await studio_sandbox_manager.write_file(
        session_id, path, content, image=image, user_id=user_id
    )
    llm_payload = {
        "path": data.get("path", path),
        "size": data.get("size", len(content)),
        "message": "文件已写入",
    }
    return _ok_result(llm_payload, dict(llm_payload))


async def _workspace_edit(
    args: dict[str, Any], session_id: str, image: str | None, user_id: str | None = None
) -> dict[str, Any]:
    path = str(args.get("path") or "")
    old_string = str(args.get("old_string") or "")
    new_string = str(args.get("new_string") or "")
    if not path or not old_string:
        return _error_result("path 与 old_string 不能为空")
    data = await studio_sandbox_manager.edit_file(
        session_id, path, old_string, new_string, image=image, user_id=user_id
    )
    llm_payload = {
        "path": data.get("path", path),
        "size": data.get("size"),
        "message": "替换成功，diff 已展示给用户",
    }
    ui_payload = {
        "path": data.get("path", path),
        "size": data.get("size"),
        "diff": data.get("diff", ""),
        "reverse_edit": data.get("reverse_edit"),
    }
    return _ok_result(llm_payload, ui_payload)


async def _workspace_read(
    args: dict[str, Any], session_id: str, image: str | None, user_id: str | None = None
) -> dict[str, Any]:
    path = str(args.get("path") or "")
    if not path:
        return _error_result("path 不能为空")
    offset_raw = args.get("offset")
    offset = int(offset_raw) if isinstance(offset_raw, int | float) else 0
    kwargs: dict[str, Any] = {"offset": offset}
    limit_raw = args.get("limit")
    if isinstance(limit_raw, int | float):
        kwargs["limit"] = int(limit_raw)
    # limit 缺省走 manager 默认（200 行），防上下文爆炸
    data = await studio_sandbox_manager.read_file(
        session_id, path, image=image, user_id=user_id, **kwargs
    )
    payload: dict[str, Any] = {
        "path": path,
        "content": data.get("content", ""),
        "total_lines": data.get("total_lines", 0),
        "truncated": data.get("truncated", False),
    }
    if payload["truncated"]:
        payload["note"] = (
            f"文件共 {payload['total_lines']} 行，仅显示部分内容，"
            "需继续阅读请用 offset 参数翻页"
        )
    return _ok_result(payload, dict(payload))


async def _workspace_list(
    args: dict[str, Any], session_id: str, image: str | None, user_id: str | None = None
) -> dict[str, Any]:
    path = str(args.get("path") or "")
    data = await studio_sandbox_manager.list_files(session_id, path, image=image, user_id=user_id)
    entries = data.get("entries") or []
    offset_raw = args.get("offset")
    offset = max(0, int(offset_raw)) if isinstance(offset_raw, int | float) else 0
    limit_raw = args.get("limit")
    limit = min(1000, max(1, int(limit_raw))) if isinstance(limit_raw, int | float) else 200
    page = entries[offset : offset + limit]
    llm_entries = page[:_LIST_LLM_CAP]
    llm_payload: dict[str, Any] = {
        "path": data.get("path", path),
        "entries": llm_entries,
        "total": len(entries),
        "offset": offset,
        "truncated": offset + len(page) < len(entries),
    }
    if llm_payload["truncated"]:
        llm_payload["next_offset"] = offset + len(page)
    if len(page) > len(llm_entries):
        llm_payload["note"] = f"本页共 {len(page)} 项，仅回灌前 {len(llm_entries)} 项"
    ui_payload = {
        "path": data.get("path", path),
        "entries": page,
        "total": len(entries),
        "offset": offset,
        "truncated": llm_payload["truncated"],
        **({"next_offset": llm_payload["next_offset"]} if llm_payload["truncated"] else {}),
    }
    return _ok_result(llm_payload, ui_payload)


# ===== 平台联动工具（P1：数据不搬家 / 产物回填 / 计划 / 目录查询） =====

_PLAN_STATUSES = ("pending", "in_progress", "done")
_PIPELINE_TOOLS_CAP = 60  # pipeline_query 回灌 LLM 的工具条目上限
_PIPELINE_LLM_CAP = 6000  # pipeline_query llm_payload 字符上限（防上下文爆炸）


def _need_context(db: AsyncSession | None, user_id: str | None) -> dict[str, Any] | None:
    """平台联动工具需要 db + user_id；缺失时返回错误信封（调用方直接 return）。"""
    if db is None or user_id is None:
        return _error_result("该工具需要登录态与数据库上下文，当前调用方式不支持")
    return None


def advance_plan_steps(steps: list[dict[str, str]]) -> list[dict[str, str]] | None:
    """执行一个成功工具后推进待办计划：当前 in_progress 步骤标 done、首个 pending 标 in_progress。

    模型经常只在任务开始时调用一次 update_plan（全 pending），之后不再更新，
    导致已完成任务的待办卡片长期停留在"待执行"。此推进逻辑让卡片状态跟随真实
    执行进度；Agent 显式调用 update_plan 时仍以其返回的最新计划为准（整体覆盖）。
    无 in_progress 步骤（计划尚未开始或已全部完成）时返回 None 表示无需推进。
    """
    if not steps:
        return None
    if not any(step.get("status") == "in_progress" for step in steps):
        return None
    advanced = [dict(step) for step in steps]
    for step in advanced:
        if step.get("status") == "in_progress":
            step["status"] = "done"
            break
    for step in advanced:
        if step.get("status") == "pending":
            step["status"] = "in_progress"
            break
    return advanced


def normalize_plan_steps(args: dict[str, Any]) -> tuple[list[dict[str, str]] | None, str | None]:
    """校验并规范化 update_plan 参数，返回 (steps, error)。

    供 chat_service 拦截分支与本模块兜底执行器共用；非法 status 宽容降级为 pending。
    """
    raw = args.get("steps")
    if not isinstance(raw, list) or not raw:
        return None, "steps 不能为空（至少 1 步，建议 3-8 步）"
    if len(raw) > 20:
        return None, f"steps 过多（{len(raw)} 步，最多 20 步）"
    steps: list[dict[str, str]] = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            return None, f"steps[{i}] 必须是 {{title, status}} 对象"
        title = str(item.get("title") or "").strip()
        if not title:
            return None, f"steps[{i}].title 不能为空"
        status = str(item.get("status") or "pending")
        if status not in _PLAN_STATUSES:
            status = "pending"
        steps.append({"title": title[:100], "status": status})
    return steps, None


async def _datahub_import(
    args: dict[str, Any], session_id: str, user_id: str | None, db: AsyncSession | None
) -> dict[str, Any]:
    if (err := _need_context(db, user_id)) is not None:
        return err
    assert db is not None and user_id is not None  # narrowing：_need_context 已拦截
    try:
        payload = await import_datahub_file(
            str(user_id),
            session_id,
            str(args.get("file_id") or "").strip(),
            str(args.get("name") or "") or None,
            db,
        )
    except CygnusXError as e:
        return _error_result(e.detail)

    llm_payload: dict[str, Any] = {
        "sandbox_path": payload["sandbox_path"],
        "name": payload["name"],
        "size": payload["size"],
        "file_type": payload["file_type"],
        "input_files": payload["input_files"],
        "note": "文件已以只读软链引入 input/，直接用 pandas 等读取即可；请勿修改 input/ 下文件",
    }
    ui_payload = {
        "sandbox_path": payload["sandbox_path"],
        "name": payload["name"],
        "size": payload["size"],
        "file_type": payload["file_type"],
        "original_name": payload["original_name"],
    }
    return _ok_result(llm_payload, ui_payload)


async def _platform_result_import(
    args: dict[str, Any], session_id: str, user_id: str | None, db: AsyncSession | None
) -> dict[str, Any]:
    if (err := _need_context(db, user_id)) is not None:
        return err
    assert db is not None and user_id is not None
    report_id_raw = str(args.get("report_id") or "").strip()
    if not report_id_raw:
        return _error_result("report_id 不能为空")
    try:
        report_uuid = uuid.UUID(report_id_raw)
    except ValueError:
        return _error_result("report_id 格式非法")

    result = await db.execute(
        select(ReportModel)
        .where(ReportModel.id == report_uuid)
        .options(selectinload(ReportModel.files))
    )
    report = result.scalar_one_or_none()
    if report is None or str(report.user_id) != str(user_id):
        return _error_result("报告不存在或无权访问")
    if not report.files:
        return _error_result("该报告没有产物文件")

    workspace = studio_sandbox_manager.workspace_dir(session_id)
    studio_sandbox_manager.ensure_workspace_dirs(workspace)
    linked = link_report_files(report, workspace, str(user_id))
    if not linked:
        return _error_result("报告产物文件均已丢失或不可访问")

    imported = [
        {"name": item["name"], "sandbox_path": item["sandbox_path"], "role": item["role"]}
        for item in linked
    ]
    llm_payload: dict[str, Any] = {
        "report_id": str(report.id),
        "title": report.title,
        "flow": report.flow_name or report.flow_id,
        "imported": imported,
        "note": "产物已以只读软链引入 input/，可直接读取做二次分析；请勿修改 input/ 下文件",
    }
    skipped = len(report.files) - len(linked)
    if skipped > 0:
        llm_payload["note"] += f"；另有 {skipped} 个文件已丢失未引入"
    ui_payload = {
        "report_id": str(report.id),
        "title": report.title,
        "imported": [
            {**item, "size": linked[i]["size"]} for i, item in enumerate(imported)
        ],
    }
    return _ok_result(llm_payload, ui_payload)


async def _artifact_register(
    args: dict[str, Any], session_id: str, user_id: str | None, db: AsyncSession | None
) -> dict[str, Any]:
    if (err := _need_context(db, user_id)) is not None:
        return err
    assert db is not None and user_id is not None
    path = str(args.get("path") or "").strip()
    title = str(args.get("title") or "").strip()
    if not path or not title:
        return _error_result("path 与 title 不能为空")

    # 版本树判定依赖会话 sandbox_meta.context_pack，需取会话行
    result = await db.execute(
        select(ChatSessionModel).where(
            ChatSessionModel.session_id == session_id,
            ChatSessionModel.user_id == str(user_id),
        )
    )
    session = result.scalar_one_or_none()
    if session is None:
        return _error_result("会话不存在或无权访问")

    try:
        report, file_model = await register_artifact_report(
            str(user_id),
            session,
            path,
            title,
            db,
            artifact_type=str(args.get("type") or "") or None,
            description=str(args.get("description") or "") or None,
        )
    except CygnusXError as e:
        return _error_result(e.detail)

    llm_payload: dict[str, Any] = {
        "report_id": str(report.id),
        "title": report.title,
        "version": report.version,
        "parent_id": str(report.parent_id) if report.parent_id else None,
        "message": f"已登记到结果报告中心（{report.title}，v{report.version}）",
    }
    ui_payload = {
        "report_id": str(report.id),
        "title": report.title,
        "version": report.version,
        "parent_id": str(report.parent_id) if report.parent_id else None,
        "file": {"name": file_model.name, "size": file_model.size, "type": file_model.type},
    }
    return _ok_result(llm_payload, ui_payload)


async def _update_plan(args: dict[str, Any]) -> dict[str, Any]:
    """update_plan 兜底执行器：正常路径由 chat_service 拦截（产出 plan 事件并落库），
    直接经 execute_studio_tool 调用时仅校验并回显。"""
    steps, error = normalize_plan_steps(args)
    if steps is None:
        return _error_result(error or "steps 非法")
    llm_payload = {"steps": steps, "message": "计划已更新，右栏待办面板已同步"}
    return _ok_result(llm_payload, {"steps": steps})


async def _knowledge_search(
    args: dict[str, Any], db: AsyncSession | None, *, project_id: str | None = None
) -> dict[str, Any]:
    """权限过滤后执行向量召回、关键词重排并返回可追溯引用。"""
    if db is None:
        return _error_result("知识库查询上下文不可用")
    query = str(args.get("query") or "").strip()
    if not query:
        return _error_result("query 不能为空")
    limit_raw = args.get("limit", 5)
    try:
        limit = max(1, min(int(limit_raw), 8))
    except (TypeError, ValueError):
        limit = 5

    from cygnusx.application.services.vector_retrieval_service import VectorRetrievalService

    matches = [
        {
            "citation_id": _knowledge_citation_id(
                doc_id=item.doc_id,
                section_path=item.section_path,
                excerpt=item.excerpt,
            ),
            "doc_id": item.doc_id,
            "title": item.title,
            "category": item.category,
            "excerpt": item.excerpt,
            "section_path": item.section_path,
            "url": item.url,
            "score": round(item.score, 4),
        }
        for item in await VectorRetrievalService(db).search_knowledge(
            query=query, limit=limit, project_id=project_id
        )
    ]
    payload = {"query": query, "results": matches, "total": len(matches)}
    return _ok_result(payload, payload)


def _knowledge_citation_id(*, doc_id: str, section_path: str, excerpt: str) -> str:
    """Build a stable opaque identifier for one retrieved knowledge passage."""
    fingerprint = "\x1f".join((doc_id, section_path, excerpt)).encode("utf-8")
    return f"kb-{hashlib.sha256(fingerprint).hexdigest()[:16]}"


async def _pipeline_query(args: dict[str, Any]) -> dict[str, Any]:
    query = str(args.get("query") or "").strip().lower()

    flows: list[dict[str, Any]] = []
    try:
        from cygnusx.application.services.flow_service import FlowService  # 局部导入防循环

        for item in FlowService().list_flows().items:
            flows.append(
                {
                    "id": item.id,
                    "name": item.name,
                    "category": item.category,
                    "description": (item.description or "")[:120],
                }
            )
    except Exception as e:  # noqa: BLE001 - 目录加载失败不阻断工具闭环
        logger.warning(f"[Studio] pipeline_query 加载流程列表失败: {e}")

    tools: list[dict[str, Any]] = []
    try:
        for t in schema_loader.list_tools():
            tools.append(
                {"name": t.name, "category": t.category, "description": t.description[:120]}
            )
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Studio] pipeline_query 加载工具目录失败: {e}")

    if query:
        flows = [f for f in flows if query in json.dumps(f, ensure_ascii=False).lower()]
        tools = [t for t in tools if query in json.dumps(t, ensure_ascii=False).lower()]

    # 条目与总体积双 cap，防上下文爆炸
    tools = tools[:_PIPELINE_TOOLS_CAP]
    while tools and len(json.dumps({"flows": flows, "tools": tools}, ensure_ascii=False)) > (
        _PIPELINE_LLM_CAP
    ):
        tools = tools[: len(tools) // 2]

    llm_payload: dict[str, Any] = {
        "flows": flows,
        "tools": tools,
        "note": "平台内置流程与生信工具目录（只读）；如需详情可带 query 关键词再查",
    }
    return _ok_result(llm_payload, dict(llm_payload))


async def _browser_tool(
    name: str,
    args: dict[str, Any],
    session_id: str,
    image: str | None,
    user_id: str | None,
) -> dict[str, Any]:
    if name == "browser_navigate":
        data = await studio_sandbox_manager.browser_navigate(
            session_id, str(args.get("url") or ""), str(args.get("wait_until") or "domcontentloaded"),
            int(args.get("timeout") or 30), image=image, user_id=user_id,
        )
    elif name == "browser_screenshot":
        data = await studio_sandbox_manager.browser_screenshot(
            session_id, str(args.get("path") or "output/browser-screenshot.png"),
            str(args.get("selector") or ""), bool(args.get("full_page", False)),
            int(args.get("timeout") or 30), image=image, user_id=user_id,
        )
    elif name == "browser_click":
        data = await studio_sandbox_manager.browser_click(
            session_id, str(args.get("selector") or ""), str(args.get("button") or "left"),
            int(args.get("click_count") or 1), int(args.get("timeout") or 30),
            image=image, user_id=user_id,
        )
    elif name == "browser_type":
        data = await studio_sandbox_manager.browser_type(
            session_id, str(args.get("selector") or ""), str(args.get("text") or ""),
            bool(args.get("clear", True)), int(args.get("timeout") or 30),
            image=image, user_id=user_id,
        )
    elif name == "browser_press":
        data = await studio_sandbox_manager.browser_press(
            session_id, str(args.get("selector") or ""), str(args.get("key") or ""),
            int(args.get("timeout") or 30), image=image, user_id=user_id,
        )
    elif name == "browser_close":
        data = await studio_sandbox_manager.browser_close(session_id, image=image, user_id=user_id)
    else:
        return _error_result(f"未知浏览器工具: {name}")
    return _ok_result(dict(data), dict(data))


async def _document_tool(
    name: str,
    args: dict[str, Any],
    session_id: str,
    image: str | None,
    user_id: str | None,
) -> dict[str, Any]:
    if name == "onlyoffice_status":
        data = await studio_sandbox_manager.onlyoffice_status(session_id, image=image, user_id=user_id)
    else:
        payload: dict[str, Any] = {
            key: args[key]
            for key in ("path", "title", "content", "operations", "output_format", "output_path", "async_mode")
            if key in args
        }
        endpoint = {
            "document_inspect": "/document/inspect",
            "document_create": "/document/create",
            "document_edit": "/document/edit",
            "document_convert": "/document/convert",
            "onlyoffice_convert": "/onlyoffice/convert",
        }.get(name)
        if endpoint is None:
            return _error_result(f"未知文档工具: {name}")
        data = await studio_sandbox_manager.document_call(
            session_id, endpoint, payload, image=image, user_id=user_id
        )
    return _ok_result(dict(data), dict(data))


# ===== 分发器 =====


async def execute_studio_tool(
    name: str,
    args: dict[str, Any],
    session_id: str,
    image: str | None = None,
    on_output: OutputCallback | None = None,
    *,
    user_id: str | None = None,
    db: AsyncSession | None = None,
) -> dict[str, Any]:
    """执行 Studio 内置工具，返回 {"success": bool, "result": {"llm_payload", "ui_payload"}}。

    - 同一会话的所有工具共享该会话工作区（session_id 直达 sandbox manager）；
    - on_output 对 sandbox_execute / tool_orchestrate 有意义：前者回调 stdout/stderr
      增量，后者回调每次子调用的进度行；
    - user_id / db 仅平台联动工具（datahub_import / platform_result_import /
      artifact_register）需要，由 chat_service 从会话上下文注入；缺省时这些工具
      返回友好错误而非抛异常；
    - 沙盒不可用（镜像未构建 / Docker 未就绪 / Studio 未启用）等异常统一收敛为
      success=False 的友好文案，绝不向上抛出。
    """
    try:
        browser_tools = {
            "browser_navigate", "browser_screenshot", "browser_click",
            "browser_type", "browser_press", "browser_close",
        }
        document_tools = {
            "document_inspect", "document_create", "document_edit", "document_convert",
            "onlyoffice_status", "onlyoffice_convert",
        }
        if name in browser_tools or name in document_tools:
            config = get_studio_config()
            effective_image = image or config.default_image
            granted = set(config.capabilities_for_image(effective_image))
            required = "browser" if name in browser_tools else "document"
            if required not in granted:
                upgraded_image = config.image_for_capabilities(["code", required])
                if not upgraded_image:
                    return _error_result(
                        f"当前 Studio 未配置 {required} 能力镜像，无法启动对应工具。"
                    )
                await studio_sandbox_manager.ensure_running(
                    session_id,
                    image=upgraded_image,
                    user_id=user_id,
                    capabilities_requested=["code", required],
                )
                image = upgraded_image
        if name == "sandbox_execute":
            return await _sandbox_execute(args, session_id, image, on_output, user_id)
        if name == "tool_orchestrate":
            return await _tool_orchestrate(args, session_id, image, on_output, user_id, db)
        if name == "workspace_write":
            return await _workspace_write(args, session_id, image, user_id)
        if name == "workspace_edit":
            return await _workspace_edit(args, session_id, image, user_id)
        if name == "workspace_read":
            return await _workspace_read(args, session_id, image, user_id)
        if name == "workspace_list":
            return await _workspace_list(args, session_id, image, user_id)
        if name == "cygnusx_workspace_remember":
            return await _workspace_remember(args, session_id)
        if name == "datahub_import":
            return await _datahub_import(args, session_id, user_id, db)
        if name == "platform_result_import":
            return await _platform_result_import(args, session_id, user_id, db)
        if name == "artifact_register":
            return await _artifact_register(args, session_id, user_id, db)
        if name == "update_plan":
            return await _update_plan(args)
        if name == "pipeline_query":
            return await _pipeline_query(args)
        if name in browser_tools:
            return await _browser_tool(name, args, session_id, image, user_id)
        if name in document_tools:
            return await _document_tool(name, args, session_id, image, user_id)
        if name == "knowledge_search":
            project_id = None
            if db is not None:
                session = await db.scalar(
                    select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
                )
                project_id = session.project_id if session else None
            return await _knowledge_search(args, db, project_id=project_id)
        return _error_result(f"未知 Studio 工具: {name}")
    except StudioSandboxUnavailableError as e:
        logger.info(f"[Studio] 沙盒不可用（会话 {session_id[:8]}）: {e}")
        return _error_result(
            f"沙盒暂不可用：{e}。请确认 Studio 已启用、Docker 正常且沙盒镜像已构建后重试。"
        )
    except httpx.HTTPStatusError as e:
        # sandbox-agent 的 4xx（路径逃逸 / 文件不存在 / old_string 不唯一等）
        detail = str(e)
        with contextlib.suppress(Exception):
            detail = str(e.response.json().get("detail") or detail)
        logger.info(f"[Studio] 工具 {name} 被沙盒拒绝（会话 {session_id[:8]}）: {detail}")
        return _error_result(f"沙盒拒绝了该操作：{detail}")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[Studio] 工具 {name} 执行异常（会话 {session_id[:8]}）: {e}")
        return _error_result(f"工具执行失败: {e}")


async def stream_studio_tool(
    name: str,
    args: dict[str, Any],
    session_id: str,
    image: str | None = None,
    tool_call_id: str = "",
    *,
    user_id: str | None = None,
    db: AsyncSession | None = None,
    message_id: str | None = None,
) -> AsyncIterator[ChatChunk | dict[str, Any]]:
    """执行 Studio 工具并流式产出事件。

    产出序列：ChatChunk(type="tool_output")*（sandbox_execute 输出 stdout/stderr 增量，
    tool_orchestrate 输出每次子调用的进度行；metadata={"tool", "tool_call_id",
    "stream": "stdout"|"stderr", "data"}），最后一项为结果信封 dict
    （同 execute_studio_tool 返回值）。tool_output chunk 同时按 message_id
    追加到 chat_message_events（攒批落库，失败降级不影响流式）。
    """
    queue: asyncio.Queue[tuple[str, str]] = asyncio.Queue(maxsize=_STREAM_QUEUE_MAX_CHUNKS)

    async def _on_output(stream: str, data: str) -> None:
        await queue.put((stream, data))

    task = asyncio.create_task(
        execute_studio_tool(
            name,
            args,
            session_id,
            image=image,
            on_output=_on_output if name in ("sandbox_execute", "tool_orchestrate") else None,
            user_id=user_id,
            db=db,
        )
    )
    # 沙盒长任务可能长时间无输出（静默计算），期间 SSE 无数据会被反向代理按读超时
    # 掐断，前端即表现为「流式连接意外中断」。这里按间隔下发心跳保活（SSE 注释帧）。
    last_emit = time.monotonic()
    while True:
        if task.done() and queue.empty():
            break
        try:
            stream, data = await asyncio.wait_for(queue.get(), timeout=0.05)
        except TimeoutError:
            if time.monotonic() - last_emit >= _STREAM_HEARTBEAT_INTERVAL_SECONDS:
                last_emit = time.monotonic()
                yield ChatChunk(type="heartbeat")
            continue
        last_emit = time.monotonic()
        yield ChatChunk(
            type="tool_output",
            metadata={"tool": name, "tool_call_id": tool_call_id, "stream": stream, "data": data},
        )
        # WP2：tool_output chunk 追加到事件表（攒批，失败降级不阻塞流式）
        await message_event_service.append_tool_output(
            message_id or "",
            tool_call_id=tool_call_id,
            stream=stream,
            data=data,
        )
    await message_event_service.flush_message_events(message_id or "")
    try:
        yield await task
    except Exception as e:  # noqa: BLE001 - execute_studio_tool 设计上不抛异常，此处兜底
        logger.warning(f"[Studio] 工具 {name} 流式执行异常: {e}")
        yield _error_result(f"工具执行失败: {e}")

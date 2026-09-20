"""LLM 代码生成器 — 根据自然语言需求生成 MCP Server 代码.

封装 ProviderManager.chat_stream：拼装 Builder 系统提示 → 流式收集 →
从 Markdown 代码围栏中提取 Python 代码。主要用于后端 API 直连路径；
交互式构建由 agent-mcp-builder 在 Studio 会话内驱动（见 data/ai/mcp_builder.yaml）。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.ai_provider.openai_compatible import provider_manager
from cygnusx.infrastructure.database.models.ai_provider import AIProviderConfigModel
from cygnusx.infrastructure.mcp.builder.safety import GENERATED_MARKER

_CODE_FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)

_SYSTEM_HINT = f"""\
你是 MCP Server 代码生成器。根据用户需求输出一份完整、可直接运行的 Python MCP Server 代码。

硬性要求：
1. 代码顶部必须包含 `{GENERATED_MARKER} = True`
2. 使用 mcp.server.Server + stdio_server 实现 tools/list 与 tools/call
3. 仅导入白名单包：mcp, pydantic, json, re, datetime, typing, collections, itertools,
   math, hashlib, base64, uuid, string, pathlib, asyncio, httpx, requests, numpy, pandas
   及标准库安全子集；禁止 subprocess/os.system/eval/exec/pickle/socket/ctypes
4. 所有工具返回 JSON 字符串包裹的 TextContent；异常捕获后以 {{"error": ...}} 返回
5. 网络请求必须设置超时，并在 ALLOWED_DOMAINS 常量中声明目标域名
6. 只输出一个 ```python 代码围栏，不要额外解释
"""


@dataclass
class GenerationResult:
    """生成结果"""

    code: str
    model_used: str
    duration_ms: int
    raw_output: str = ""
    tokens: int | None = None
    error: str | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.code)


def extract_python_code(text: str) -> str:
    """从 LLM 输出中提取 Python 代码（优先代码围栏，回退整体）。"""
    blocks = _CODE_FENCE_RE.findall(text)
    if blocks:
        # 取包含 MCP 标记或最长的那个围栏
        marked = [b for b in blocks if GENERATED_MARKER in b or "list_tools" in b]
        return (max(marked, key=len) if marked else max(blocks, key=len)).strip()
    return text.strip()


class MCPCodeGenerator:
    """基于平台 Provider 体系的 MCP 代码生成器."""

    def __init__(self, db: AsyncSession):
        self._db = db

    async def _resolve_model(self, model_name: str) -> AIProviderConfigModel | None:
        result = await self._db.execute(
            select(AIProviderConfigModel).where(
                AIProviderConfigModel.name == model_name,
                AIProviderConfigModel.is_active == True,  # noqa: E712
            )
        )
        return result.scalar_one_or_none()

    async def generate(
        self,
        requirement: str,
        *,
        model_name: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 8000,
    ) -> GenerationResult:
        """生成 MCP Server 代码.

        Args:
            requirement: 自然语言需求（可包含工具清单、测试数据等上下文）
            model_name: 模型名（对应 ai_provider_configs.name），缺省用配置默认
        """
        from cygnusx.core.config import get_settings

        settings = get_settings()
        model_name = model_name or settings.mcp_builder_default_model

        config = await self._resolve_model(model_name)
        if config is None:
            return GenerationResult(
                code="",
                model_used=model_name,
                duration_ms=0,
                error=f"模型 {model_name!r} 未配置或未启用",
            )

        messages = [{"role": "user", "content": f"需求：{requirement}"}]
        start = time.monotonic()
        chunks: list[str] = []
        tokens: int | None = None
        try:
            async for chunk in provider_manager.chat_stream(
                config,
                messages,
                system_prompt=_SYSTEM_HINT,
                temperature=temperature,
                max_tokens=max_tokens,
            ):
                if chunk.type == "text" and chunk.content:
                    chunks.append(chunk.content)
                elif chunk.type == "done":
                    tokens = chunk.metadata.get("total_tokens") or chunk.metadata.get("tokens")
                elif chunk.type == "error":
                    return GenerationResult(
                        code="",
                        model_used=model_name,
                        duration_ms=int((time.monotonic() - start) * 1000),
                        error=chunk.content or "LLM 返回错误",
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"[MCPBuilder] 代码生成失败: {exc}")
            return GenerationResult(
                code="",
                model_used=model_name,
                duration_ms=int((time.monotonic() - start) * 1000),
                error=f"生成异常: {type(exc).__name__}: {exc}",
            )

        raw = "".join(chunks)
        code = extract_python_code(raw)
        return GenerationResult(
            code=code,
            model_used=model_name,
            duration_ms=int((time.monotonic() - start) * 1000),
            raw_output=raw,
            tokens=tokens,
        )

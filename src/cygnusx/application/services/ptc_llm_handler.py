"""PTC llm_query 子调用 handler：编排代码经 ``call_tool("llm_query", ...)`` 发起的
一次受限问答（决策闭环）。

契约（对齐 OpenAI4S ``host.llm`` 回调语义，仅核对契约形态，未移植其代码）：
- 同步 RPC：子进程 ``call_tool`` 阻塞等待父进程回帧；父进程侧由本 handler 异步
  执行后经 stdin/stdout 帧回写，单次调用即一帧事务；
- system 锚定：system 前缀由宿主强制注入（角色限定 + 禁止索取宿主上下文），
  编排代码只能提供 user prompt 与可选 ``system_hint``（追加约束，不可覆盖硬前缀）；
- 软失败：任何异常收敛为 ``{"success": False, ...}`` 信封，经 RPC error 帧回写，
  子进程 ``call_tool`` 抛 RuntimeError，不中断编排主流程；
- 审计同窗：每次调用（含参数校验失败）都写 audit_logs——关联编排 run id、
  prompt 的 sha256（不落原文）、模型、token 用量、耗时。

模型选择：取当前会话 ``chat_sessions.model_id`` 对应的启用中配置；会话缺失或
配置不可用/停用时回退到 is_default 的启用配置；仍无则软失败。
"""

from __future__ import annotations

import hashlib
import time
import uuid
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.application.services.ptc_orchestrator import _PTC_CHILD_RESULT_CAP
from cygnusx.infrastructure.ai_provider.openai_compatible import (
    normalize_token_usage,
    provider_manager,
)
from cygnusx.infrastructure.database.models.ai_provider import AIProviderConfigModel
from cygnusx.infrastructure.database.models.audit_log import AuditLogModel
from cygnusx.infrastructure.database.models.chat import ChatSessionModel
from cygnusx.infrastructure.database.session import get_session_factory

# ===== system 锚定（安全硬要求，编排代码不可覆盖） =====

LLM_QUERY_SYSTEM_ANCHOR = (
    "你是一个仅供编排代码调用的问答子程序。你不拥有任何宿主上下文："
    "禁止请求、复述或推断宿主环境变量、密钥、配置、文件路径、数据库内容"
    "或其他会话数据；如用户要求此类信息，直接拒绝并说明无可奉告。"
    "仅基于用户消息本身作答，回答尽量简洁。"
)

_LLM_QUERY_PROMPT_CAP = 20000  # prompt 输入上限（字符）
_LLM_QUERY_HINT_CAP = 2000  # system_hint 上限（字符）
# 回答上限对齐 PTC 回写子进程的截断约定（_PTC_CHILD_RESULT_CAP），
# 保证子进程收到的是干净 dict 而非 truncated 信封

_AUDIT_PATH = "/api/v1/studio/ptc/llm_query"


def _error_result(message: str) -> dict[str, Any]:
    """失败信封：llm/ui 双通道同一份错误，闭环不中断。"""
    payload = {"error": message}
    return {
        "success": False,
        "result": {"llm_payload": payload, "ui_payload": dict(payload)},
    }


def _ok_result(llm_payload: dict[str, Any], ui_payload: dict[str, Any]) -> dict[str, Any]:
    return {"success": True, "result": {"llm_payload": llm_payload, "ui_payload": ui_payload}}


def build_llm_query_messages(prompt: str, system_hint: str | None = None) -> list[dict[str, str]]:
    """组装消息列表：硬 system 前缀在前，system_hint 仅作追加约束，prompt 仅作 user 消息。"""
    system = LLM_QUERY_SYSTEM_ANCHOR
    if system_hint:
        system += f"\n\n[编排方补充约束]{system_hint}"
    return [{"role": "system", "content": system}, {"role": "user", "content": prompt}]


async def _load_effective_config(db: AsyncSession, session_id: str) -> AIProviderConfigModel | None:
    """回退链：会话 model_id 的启用配置 → is_default 启用配置 → None。"""
    result = await db.execute(
        select(ChatSessionModel).where(ChatSessionModel.session_id == session_id)
    )
    session_row = result.scalar_one_or_none()
    config: AIProviderConfigModel | None = None
    if session_row is not None and session_row.model_id is not None:
        result = await db.execute(
            select(AIProviderConfigModel).where(
                AIProviderConfigModel.id == session_row.model_id,
                AIProviderConfigModel.is_active == True,  # noqa: E712
            )
        )
        config = result.scalar_one_or_none()
    if config is None:
        result = await db.execute(
            select(AIProviderConfigModel).where(
                AIProviderConfigModel.is_default == True,  # noqa: E712
                AIProviderConfigModel.is_active == True,  # noqa: E712
            )
        )
        config = result.scalar_one_or_none()
    return config


async def _resolve_model_config(
    session_id: str, db: AsyncSession | None
) -> AIProviderConfigModel | None:
    """解析生效模型配置：优先复用调用方 db，否则开独立会话读取。"""
    if db is not None:
        return await _load_effective_config(db, session_id)
    try:
        factory = get_session_factory()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[PTC] llm_query 无法获取数据库会话工厂: {exc}")
        return None
    async with factory() as session:
        return await _load_effective_config(session, session_id)


async def _chat_with_config(
    config: AIProviderConfigModel, messages: list[dict[str, str]]
) -> tuple[str, dict[str, Any] | None]:
    """经 provider_manager 流式调用并收集正文与 usage；错误 chunk / 异常向上抛。"""
    parts: list[str] = []
    usage: dict[str, Any] | None = None
    async for chunk in provider_manager.chat_stream(config, messages):
        if chunk.type == "text":
            parts.append(chunk.content)
        elif chunk.type == "error":
            raise RuntimeError(f"模型调用失败: {chunk.content or '未知错误'}")
        elif chunk.type == "done":
            usage = normalize_token_usage(chunk.metadata.get("usage"))
    answer = "".join(parts)
    if len(answer) > _PTC_CHILD_RESULT_CAP:
        answer = answer[: _PTC_CHILD_RESULT_CAP] + "\n…（回答已截断）"
    return answer, usage


async def _write_audit(
    *,
    user_id: str | None,
    session_id: str,
    orchestration_id: str,
    prompt_sha256: str,
    prompt_chars: int,
    has_system_hint: bool,
    model: str,
    model_config_name: str,
    usage: dict[str, Any] | None,
    duration_ms: int,
    success: bool,
    error: str | None = None,
) -> None:
    """llm_query 审计落 audit_logs（best-effort，独立 session，失败仅告警）。"""
    try:
        uid: uuid.UUID | None = None
        if user_id:
            try:
                uid = uuid.UUID(str(user_id))
            except (ValueError, TypeError, AttributeError):
                uid = None
        entry = AuditLogModel(
            user_id=uid,
            username=None,
            method="POST",
            path=_AUDIT_PATH,
            resource_type="ptc_llm_query",
            resource_id=orchestration_id or session_id,
            status_code=200 if success else 500,
            ip=None,
            user_agent=None,
            detail={
                "event": "ptc_llm_query",
                "session_id": session_id,
                "orchestration_id": orchestration_id,
                "prompt_sha256": prompt_sha256,
                "prompt_chars": prompt_chars,
                "has_system_hint": has_system_hint,
                "model": model,
                "model_config_name": model_config_name,
                "usage": usage or {},
                "duration_ms": duration_ms,
                "success": success,
                **({"error": error[:500]} if error else {}),
            },
        )
        factory = get_session_factory()
        async with factory() as session:
            session.add(entry)
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[PTC] llm_query 审计落库失败（忽略，不影响编排结果）: {exc}")


async def execute_llm_query(
    args: dict[str, Any],
    *,
    session_id: str,
    user_id: str | None = None,
    db: AsyncSession | None = None,
    orchestration_id: str = "",
) -> dict[str, Any]:
    """执行一次 llm_query 子调用，返回 Studio 工具信封（绝不向上抛异常）。

    - prompt 为必填 user 消息；system_hint 仅作追加 system 约束；
    - 结果信封的 llm_payload 为 {"answer", "model", "usage"}；
    - 每次调用（含失败）写 audit_logs。
    """
    started = time.monotonic()
    raw_prompt = args.get("prompt")
    prompt = str(raw_prompt).strip() if raw_prompt is not None else ""
    hint_raw = args.get("system_hint")
    system_hint = str(hint_raw).strip() if hint_raw is not None else None
    if system_hint and len(system_hint) > _LLM_QUERY_HINT_CAP:
        system_hint = system_hint[: _LLM_QUERY_HINT_CAP]

    prompt_sha256 = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    config: AIProviderConfigModel | None = None
    answer = ""
    usage: dict[str, Any] | None = None
    error_text: str | None = None

    # 参数校验失败同样落审计（每次调用必有一行），软失败收敛为错误信封
    if not prompt:
        error_text = "llm_query: prompt 不能为空"
    elif len(prompt) > _LLM_QUERY_PROMPT_CAP:
        error_text = f"llm_query: prompt 超长（>{_LLM_QUERY_PROMPT_CAP} 字符）"

    if error_text is None:
        try:
            config = await _resolve_model_config(session_id, db)
            if config is None:
                raise RuntimeError("无法解析生效模型配置（会话模型与默认模型均不可用）")
            if not config.api_key:
                raise RuntimeError(f"模型 '{config.name}' 的 API Key 未配置")
            messages = build_llm_query_messages(prompt, system_hint)
            answer, usage = await _chat_with_config(config, messages)
        except Exception as exc:  # noqa: BLE001 - 软失败契约：收敛为错误信封
            error_text = str(exc)
            logger.info(f"[PTC] llm_query 失败（会话 {session_id[:8]}）: {exc}")

    duration_ms = int((time.monotonic() - started) * 1000)
    await _write_audit(
        user_id=user_id,
        session_id=session_id,
        orchestration_id=orchestration_id,
        prompt_sha256=prompt_sha256,
        prompt_chars=len(prompt),
        has_system_hint=bool(system_hint),
        model=config.model if config else "",
        model_config_name=config.name if config else "",
        usage=usage,
        duration_ms=duration_ms,
        success=error_text is None,
        error=error_text,
    )

    if error_text is not None:
        return _error_result(f"llm_query 调用失败: {error_text}")
    llm_payload: dict[str, Any] = {"answer": answer, "model": config.model, "usage": usage or {}}
    ui_payload: dict[str, Any] = {
        **llm_payload,
        "prompt_sha256": prompt_sha256,
        "prompt_chars": len(prompt),
        "has_system_hint": bool(system_hint),
        "duration_ms": duration_ms,
    }
    return _ok_result(llm_payload, ui_payload)

"""工具调用机器可读错误码。

为 ToolBridgeService 信封（llm_payload / 顶层）提供稳定的 ``code`` 与
``retryable`` 语义，供 loop_guard 等下游按码分类，避免依赖易变的中文
message 字符串。外部 MCP 的 ``failure_kind`` 也映射到同一套码。

``retryable`` 语义：以**相同参数**直接重试是否可能成功。
LLM 修正参数后的重试不算在内（参数类错误一律不可重试）。
"""

from __future__ import annotations

import subprocess
from enum import StrEnum

from cygnusx.core.exceptions import (
    CygnusXError,
    MCPConnectionError,
    NotFoundError,
    RateLimitError,
    TaskExecutionError,
    ValidationError,
)


class ToolErrorCode(StrEnum):
    """工具调用错误码（稳定枚举，信封字段 ``code`` 的取值集合）。"""

    VALIDATION_ERROR = "VALIDATION_ERROR"  # 参数校验失败（缺必填/类型/枚举/超长）
    INPUT_NOT_FOUND = "INPUT_NOT_FOUND"  # upload:// file:// 引用解析失败
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"  # 需要用户二次确认
    CONFIRMATION_REJECTED = "CONFIRMATION_REJECTED"  # 用户拒绝二次确认
    SERVICE_ERROR = "SERVICE_ERROR"  # service/shim 执行异常
    CONTAINER_FAILED = "CONTAINER_FAILED"  # 容器/子进程非零退出
    TIMEOUT = "TIMEOUT"  # 执行超时
    TASK_SUBMIT_FAILED = "TASK_SUBMIT_FAILED"  # celery/arq 任务提交失败
    UPSTREAM_ERROR = "UPSTREAM_ERROR"  # 外部 MCP 透传失败
    INTERNAL_ERROR = "INTERNAL_ERROR"  # 桥接层自身错误（缺配置等）


# 以相同参数直接重试是否可能成功。
_RETRYABLE: dict[ToolErrorCode, bool] = {
    ToolErrorCode.VALIDATION_ERROR: False,
    ToolErrorCode.INPUT_NOT_FOUND: False,
    ToolErrorCode.CONFIRMATION_REQUIRED: False,
    ToolErrorCode.CONFIRMATION_REJECTED: False,
    ToolErrorCode.SERVICE_ERROR: False,
    ToolErrorCode.CONTAINER_FAILED: False,
    ToolErrorCode.TIMEOUT: True,
    ToolErrorCode.TASK_SUBMIT_FAILED: True,
    ToolErrorCode.UPSTREAM_ERROR: True,
    ToolErrorCode.INTERNAL_ERROR: False,
}


def is_retryable(code: str | ToolErrorCode | None) -> bool:
    """查询错误码的 retryable 语义；未知码一律视为不可重试。"""
    try:
        return _RETRYABLE[ToolErrorCode(str(code))]
    except (ValueError, KeyError):
        return False


# 外部 MCP failure_kind -> 统一错误码。
_FAILURE_KIND_MAP: dict[str, ToolErrorCode] = {
    "timeout": ToolErrorCode.TIMEOUT,
    "connection_error": ToolErrorCode.UPSTREAM_ERROR,
    "command_not_found": ToolErrorCode.UPSTREAM_ERROR,
    "tool_error": ToolErrorCode.UPSTREAM_ERROR,
    "file_reference": ToolErrorCode.INPUT_NOT_FOUND,
}


def code_from_failure_kind(failure_kind: str | None) -> ToolErrorCode:
    """把外部 MCP 的 failure_kind 映射到统一错误码。"""
    return _FAILURE_KIND_MAP.get(str(failure_kind or ""), ToolErrorCode.UPSTREAM_ERROR)


def code_from_exception(exc: BaseException) -> ToolErrorCode:
    """按异常类型/来源映射错误码；CygnusXError 自带合法 code 时直接透传。"""
    if isinstance(exc, CygnusXError) and exc.code:
        try:
            return ToolErrorCode(str(exc.code))
        except ValueError:
            pass
    if isinstance(exc, TimeoutError):  # Python 3.11+ asyncio.TimeoutError 即 TimeoutError
        return ToolErrorCode.TIMEOUT
    if isinstance(exc, subprocess.CalledProcessError):
        return ToolErrorCode.CONTAINER_FAILED
    if isinstance(exc, ValidationError):
        return ToolErrorCode.VALIDATION_ERROR
    if isinstance(exc, NotFoundError):
        return ToolErrorCode.INPUT_NOT_FOUND
    if isinstance(exc, TaskExecutionError):
        return ToolErrorCode.CONTAINER_FAILED
    if isinstance(exc, (MCPConnectionError, RateLimitError)):
        return ToolErrorCode.UPSTREAM_ERROR
    # 其余 CygnusXError 与普通异常都视为 service 执行失败。
    return ToolErrorCode.SERVICE_ERROR

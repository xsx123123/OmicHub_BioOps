"""Celery 任务的 trace context 跨进程传播（web → worker）。

- ``before_task_publish``：把当前 span context（traceparent）与 session_id 注入任务
  headers，派发方无需逐个改动 ``apply_async``/``delay`` 调用点；
- ``task_prerun``：worker 侧提取并 attach，恢复 session_id ContextVar，使
  ``LoggedTask`` 的 ``celery.task`` span 成为派发方 span 的子 span 且带 session.id；
- ``task_postrun``：detach / 复位，避免串扰同一 worker 的下一个任务。

遥测异常一律降级 no-op，不影响任务收发与执行。
"""

from __future__ import annotations

import contextlib
from typing import Any

from loguru import logger

from cygnusx.core.telemetry import (
    detach_extracted,
    extract_and_attach,
    inject_trace_context,
)

_wired = False
_TOKENS_ATTR = "_cygnusx_trace_tokens"


def _on_before_task_publish(sender: Any = None, headers: Any = None, **kwargs: Any) -> None:  # noqa: ARG001
    if headers is None:
        return
    try:
        inject_trace_context(headers)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"celery trace 注入失败（忽略）: {exc}")


def _on_task_prerun(sender: Any = None, task: Any = None, **kwargs: Any) -> None:  # noqa: ARG001
    task = task or sender
    request = getattr(task, "request", None)
    headers = getattr(request, "headers", None)
    if not headers:
        return
    try:
        tokens = extract_and_attach(headers)
        setattr(request, _TOKENS_ATTR, tokens)
    except Exception as exc:  # noqa: BLE001
        logger.debug(f"celery trace 提取失败（忽略）: {exc}")


def _on_task_postrun(sender: Any = None, task: Any = None, **kwargs: Any) -> None:  # noqa: ARG001
    task = task or sender
    request = getattr(task, "request", None)
    tokens = getattr(request, _TOKENS_ATTR, None)
    if tokens is None:
        return
    with contextlib.suppress(Exception):
        detach_extracted(tokens)
    with contextlib.suppress(Exception):
        delattr(request, _TOKENS_ATTR)


def wire_celery_tracing() -> None:
    """连接 Celery 信号（幂等）。发布方与 worker 都会 import celery_app，两端均生效。"""
    global _wired
    if _wired:
        return
    try:
        from celery.signals import before_task_publish, task_postrun, task_prerun

        before_task_publish.connect(_on_before_task_publish, weak=False)
        task_prerun.connect(_on_task_prerun, weak=False)
        task_postrun.connect(_on_task_postrun, weak=False)
        _wired = True
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"celery trace 信号接线失败（降级不传播）: {exc}")

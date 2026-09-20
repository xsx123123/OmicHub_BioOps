"""Studio 沙箱生命周期审计事件。

审计使用结构化 loguru 字段，不写数据库、不阻断主流程；后续接入统一事件总线时只需替换
这里的 emit 实现。事件名保持稳定，供日志采集器按 ``event`` 字段检索。
"""

from __future__ import annotations

from typing import Any

from loguru import logger


_SANDBOX_EVENTS = {
    "sandbox.create",
    "sandbox.rebuild",
    "sandbox.capability_denied",
    "sandbox.reuse",
    "sandbox.reclaim",
    "sandbox.quota_exceeded",
}


def emit(event: str, **fields: Any) -> None:
    """尽力写一条结构化事件；日志设施故障不得阻断沙箱主流程。"""
    if event not in _SANDBOX_EVENTS:
        raise ValueError(f"未知 Studio 沙箱审计事件: {event}")
    try:
        logger.bind(event=event, component="studio_sandbox", **fields).info(
            "Studio sandbox event: {}", event
        )
    except Exception as exc:  # noqa: BLE001 - 审计降级不得影响主流程
        logger.warning("Studio 沙箱审计事件写入失败: {}", exc)

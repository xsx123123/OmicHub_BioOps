"""AI 调用指标应用内持久化 — 缓冲 + 后台批量写库

设计目标：
- 在 AI 调用 choke point（record_ai_call_metrics）以 O(1) 追加进内存缓冲，绝不阻塞
  调用链、绝不因写库失败影响业务；真正的 INSERT 由单个后台守护线程批量完成。
- 缓冲满时丢弃最旧记录（deque maxlen），而非背压到 AI 请求。
- 进程退出最多丢失一个刷写间隔的数据——对指标可接受。

与 OTel 指标（Prometheus/OTLP）互补：OTel 是导出即弃的瞬时指标，这里落库是为了
管理端按日趋势聚合与告警（错误率/p95/成本），二者共用同一 choke point。
"""

from __future__ import annotations

import asyncio
import threading
import time
from collections import deque
from typing import Any

from loguru import logger

from cygnusx.core.config import get_settings

_buffer: deque[dict[str, Any]] = deque(maxlen=get_settings().ai_metrics_buffer_size)
_lock = threading.Lock()
_flusher_started = False


def record_ai_call(
    provider: str,
    model: str,
    status: str,
    duration_ms: float,
    usage: dict[str, Any] | None,
    session_id: str | None = None,
) -> None:
    """把一次 AI 调用追加进内存缓冲（非阻塞，容错）。"""
    settings = get_settings()
    if not settings.ai_metrics_enabled:
        return
    usage = usage or {}
    row = {
        "provider": (provider or "unknown")[:64],
        "model": (model or "unknown")[:128],
        "status": (status or "unknown")[:16],
        "duration_ms": float(duration_ms or 0.0),
        "prompt_tokens": int(usage.get("prompt_tokens", 0) or 0),
        "completion_tokens": int(usage.get("completion_tokens", 0) or 0),
        "total_tokens": int(usage.get("total_tokens", 0) or 0),
        "session_id": (session_id or None) and str(session_id)[:64],
    }
    with _lock:
        _buffer.append(row)
    _ensure_flusher()


def _ensure_flusher() -> None:
    """幂等启动后台刷写守护线程。"""
    global _flusher_started
    if _flusher_started:
        return
    with _lock:
        if _flusher_started:
            return
        _flusher_started = True
    thread = threading.Thread(target=_flusher_loop, name="ai-metrics-flusher", daemon=True)
    thread.start()


def _flusher_loop() -> None:
    """周期性刷写；任何异常都吞掉并继续，保证线程长存。"""
    interval = max(1, get_settings().ai_metrics_flush_interval)
    while True:
        time.sleep(interval)
        try:
            flush()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"AI 指标刷写失败（已忽略）: {exc}")


def flush() -> int:
    """把当前缓冲批量写入 ai_call_metrics；返回写入条数。供后台线程与测试调用。"""
    with _lock:
        if not _buffer:
            return 0
        batch = list(_buffer)
        _buffer.clear()
    try:
        asyncio.run(_insert(batch))
        return len(batch)
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"AI 指标批量写库失败，丢弃 {len(batch)} 条: {exc}")
        return 0


async def _insert(batch: list[dict[str, Any]]) -> None:
    from cygnusx.infrastructure.database.models.ai_metric import AiCallMetricModel
    from cygnusx.infrastructure.database.session import create_unpooled_engine
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    engine = create_unpooled_engine()
    try:
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            session.add_all([AiCallMetricModel(**row) for row in batch])
            await session.commit()
    finally:
        await engine.dispose()

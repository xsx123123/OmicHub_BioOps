"""WP2 消息过程态事件落库与回放服务（chat_message_events）。

设计要点（对应 OpenAI4S 事件帧契约的理解层借鉴，见交付报告）：

- append-only：只插不改不删，(message_id, seq) 联合主键保证消息内单调有序；
  代码层不提供任何更新/删除路径。
- 写隔离：事件写入使用独立短生命周期 session（每批一次事务），与流式主链路
  共享的请求级 session 完全解耦——落库失败只会回滚事件批，绝不污染主事务。
- 降级：任何异常（含 seq 冲突回退失败）只记日志并丢弃该批，流式主链路
  保持现状行为，不阻塞、不重试风暴。
- seq 生成：进程内单调计数器 + 冲突时以 DB max(seq)+1 重分配回退，保证唯一。
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from cygnusx.infrastructure.database.models.chat import (
    ChatMessageEventModel,
    ChatMessageModel,
)

# 攒批阈值：条数或序列化字节数先到先刷。执行期可见性由 tool 完成时的
# flush_message_events 保证（长输出按条数阈值中途可见）。
_FLUSH_EVENT_COUNT = 8
_FLUSH_PAYLOAD_BYTES = 32 * 1024

_EVENT_TYPE_TOOL_OUTPUT = "tool_output"


class _MessageEventBuffer:
    """单条消息的事件攒批缓冲（内存态，进程内）。"""

    __slots__ = ("events", "bytes")

    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []
        self.bytes = 0

    def append(self, event: dict[str, Any]) -> None:
        self.events.append(event)
        try:
            self.bytes += len(json.dumps(event["payload"], ensure_ascii=False, default=str))
        except (TypeError, ValueError):
            self.bytes += 1024  # 无法序列化时按保守值计，避免超大 payload 不触发刷库


class ChatMessageEventService:
    """chat_message_events 的唯一写入口（append-only）。"""

    def __init__(self) -> None:
        self._buffers: dict[str, _MessageEventBuffer] = {}
        self._seq_counters: dict[str, int] = {}
        self._lock = asyncio.Lock()

    # ----- 写入 -----

    async def append_tool_output(
        self,
        message_id: str,
        *,
        tool_call_id: str,
        stream: str,
        data: str,
    ) -> bool:
        """缓存一条 tool_output 事件；达攒批阈值时异步刷库。

        返回 False 表示该事件被降级丢弃（已记日志），调用方不得因此中断流式链路。
        """
        if not message_id:
            return False
        try:
            async with self._lock:
                buffer = self._buffers.setdefault(message_id, _MessageEventBuffer())
                buffer.append(
                    {
                        "event_type": _EVENT_TYPE_TOOL_OUTPUT,
                        "payload": {
                            "tool_call_id": tool_call_id,
                            "stream": stream,
                            "data": data,
                        },
                    }
                )
                should_flush = (
                    len(buffer.events) >= _FLUSH_EVENT_COUNT
                    or buffer.bytes >= _FLUSH_PAYLOAD_BYTES
                )
                events = list(buffer.events) if should_flush else None
                if should_flush:
                    self._buffers.pop(message_id, None)
            if events:
                await self._flush_events(message_id, events)
            return True
        except Exception as e:  # noqa: BLE001 - 降级契约：任何失败不得上抛
            logger.warning(f"[Events] tool_output 事件缓存失败（降级丢弃）: {e}")
            return False

    async def flush_message_events(self, message_id: str) -> None:
        """刷出指定消息剩余缓冲（工具完成 / 流式结束时的显式 flush）。"""
        if not message_id:
            return
        try:
            async with self._lock:
                buffer = self._buffers.pop(message_id, None)
                events = list(buffer.events) if buffer else []
            if events:
                await self._flush_events(message_id, events)
        except Exception as e:  # noqa: BLE001 - 降级契约
            logger.warning(f"[Events] 消息 {message_id[:8]} 事件刷库失败（降级丢弃）: {e}")

    async def _flush_events(
        self, message_id: str, events: list[dict[str, Any]]
    ) -> None:
        """独立 session 单事务批量插入；seq 冲突时以 DB max(seq)+1 整体重分配。"""
        from cygnusx.infrastructure.database.session import get_session_factory

        factory = get_session_factory()
        async with factory() as session:
            try:
                async with self._lock:
                    await self._insert_batch(session, message_id, events)
                await session.commit()
            except IntegrityError:
                await session.rollback()
                try:
                    async with self._lock:
                        await self._resync_seq(session, message_id)
                        await self._insert_batch(session, message_id, events)
                    await session.commit()
                except Exception as e:  # noqa: BLE001 - 降级契约
                    await session.rollback()
                    logger.warning(
                        f"[Events] 消息 {message_id[:8]} 事件批量插入失败（降级丢弃 "
                        f"{len(events)} 条）: {e}"
                    )
            except Exception as e:  # noqa: BLE001 - 降级契约
                await session.rollback()
                logger.warning(
                    f"[Events] 消息 {message_id[:8]} 事件批量插入失败（降级丢弃 "
                    f"{len(events)} 条）: {e}"
                )

    async def _insert_batch(
        self,
        session: AsyncSession,
        message_id: str,
        events: list[dict[str, Any]],
    ) -> None:
        next_seq = self._seq_counters.get(message_id, 0)
        for event in events:
            next_seq += 1
            session.add(
                ChatMessageEventModel(
                    message_id=message_id,
                    seq=next_seq,
                    event_type=event["event_type"],
                    payload=event["payload"],
                )
            )
        self._seq_counters[message_id] = next_seq
        await session.flush()

    async def _resync_seq(self, session: AsyncSession, message_id: str) -> None:
        """seq 冲突回退：以 DB 现有 max(seq) 重设内存计数器。"""
        result = await session.execute(
            select(func.coalesce(func.max(ChatMessageEventModel.seq), 0)).where(
                ChatMessageEventModel.message_id == message_id
            )
        )
        self._seq_counters[message_id] = int(result.scalar_one())

    # ----- 读取（重建链路） -----

    async def has_events(self, session: AsyncSession, message_id: str) -> bool:
        """便宜的存在性判定（主键前缀索引，limit 1）。"""
        result = await session.execute(
            select(ChatMessageEventModel.seq)
            .where(ChatMessageEventModel.message_id == message_id)
            .limit(1)
        )
        return result.first() is not None

    async def load_replay(
        self, session: AsyncSession, message_ids: list[str]
    ) -> dict[str, dict[str, Any]]:
        """按消息加载事件并回放为工具卡过程输出结构。

        返回 {message_id: {"tool_outputs": {tool_call_id: {"stdout": ..., "stderr": ...}},
        "consistent_with_snapshot": bool|None}}；与终态快照（ui_payload.stdout/stderr）
        可比较时给出一致性标记。无事件的消息不在返回中。
        """
        if not message_ids:
            return {}
        result = await session.execute(
            select(ChatMessageEventModel)
            .where(ChatMessageEventModel.message_id.in_(message_ids))
            .order_by(ChatMessageEventModel.message_id, ChatMessageEventModel.seq)
        )
        rows = list(result.scalars().all())

        # 取这些消息的终态快照用于一致性核对
        msg_result = await session.execute(
            select(ChatMessageModel.message_id, ChatMessageModel.metadata_json).where(
                ChatMessageModel.message_id.in_(message_ids)
            )
        )
        snapshots = {row[0]: (row[1] or {}) for row in msg_result.all()}

        replay: dict[str, dict[str, Any]] = {}
        per_message: dict[str, list[ChatMessageEventModel]] = {}
        for row in rows:
            per_message.setdefault(row.message_id, []).append(row)

        for message_id, events in per_message.items():
            tool_outputs: dict[str, dict[str, str]] = {}
            for event in events:
                if event.event_type != _EVENT_TYPE_TOOL_OUTPUT:
                    continue
                payload = event.payload or {}
                tool_call_id = str(payload.get("tool_call_id") or "")
                stream_name = str(payload.get("stream") or "stdout")
                data = str(payload.get("data") or "")
                bucket = tool_outputs.setdefault(tool_call_id, {})
                bucket[stream_name] = bucket.get(stream_name, "") + data
            if not tool_outputs:
                continue
            consistent: bool | None = None
            snapshot_invocations = snapshots.get(message_id, {}).get("tool_invocations")
            if isinstance(snapshot_invocations, list) and snapshot_invocations:
                consistent = self._check_snapshot_consistency(
                    tool_outputs, snapshot_invocations
                )
            replay[message_id] = {
                "tool_outputs": tool_outputs,
                "consistent_with_snapshot": consistent,
                "event_count": len(events),
            }
        return replay

    @staticmethod
    def _check_snapshot_consistency(
        tool_outputs: dict[str, dict[str, str]],
        snapshot_invocations: list[Any],
    ) -> bool:
        """回放拼接结果与终态快照逐工具比较（无可比较项时视为一致）。"""
        checked = 0
        for invocation in snapshot_invocations:
            if not isinstance(invocation, dict):
                continue
            tool_call_id = str(invocation.get("tool_call_id") or "")
            replayed = tool_outputs.get(tool_call_id)
            if replayed is None:
                continue
            ui_payload = invocation.get("ui_payload")
            if not isinstance(ui_payload, dict):
                continue
            for stream_key, ui_key in (("stdout", "stdout"), ("stderr", "stderr")):
                snapshot_text = ui_payload.get(ui_key)
                if not isinstance(snapshot_text, str):
                    continue
                checked += 1
                if replayed.get(stream_key, "") != snapshot_text:
                    return False
        return True


# 模块级单例：攒批缓冲与 seq 计数器必须进程内共享
message_event_service = ChatMessageEventService()

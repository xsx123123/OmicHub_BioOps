"""聊天 SSE 出口的事件序列校验。"""

from __future__ import annotations

from dataclasses import dataclass, field

from loguru import logger

from cygnusx.application.services.execution_events import (
    EventSequenceError,
    validate_event_sequence,
)
from cygnusx.core.config import Settings, get_settings
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


@dataclass
class ChatEventService:
    """在 SSE 发送前验证单个聊天流的统一状态转移。"""

    enforcement: str
    _events: list[ChatChunk] = field(default_factory=list)

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> ChatEventService:
        settings = settings or get_settings()
        return cls(enforcement=settings.chat_event_sequence_enforcement)

    def before_send(self, chunk: ChatChunk) -> ChatChunk:
        """在 SSE 输出前校验事件；生产告警模式不会中断用户流。"""
        self._events.append(chunk)
        try:
            validate_event_sequence(self._events, require_completion=False)
        except EventSequenceError as exc:
            self._events.pop()
            self._handle_violation(chunk.type, exc)
        return chunk

    def after_stream(self) -> None:
        """在生成器正常结束时确认执行生命周期已完成。"""
        try:
            validate_event_sequence(self._events, require_completion=True)
        except EventSequenceError as exc:
            self._handle_violation("stream_completed", exc)

    def _handle_violation(self, event_type: str, exc: EventSequenceError) -> None:
        if self.enforcement == "raise":
            raise exc
        if self.enforcement == "warn":
            logger.warning("event_sequence_violation event_type={} reason={}", event_type, exc)

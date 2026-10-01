"""Provider-aware context token estimates used by chat compaction.

This module is deliberately independent from the database and LLM gateway.  It
prices the message view sent to a provider, keeping standing system context and
tool/provider wire state visible as separate buckets for diagnostics.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

IMAGE_TOKEN_ESTIMATE = 1_024
MESSAGE_FRAME_TOKENS = 8

_CJK_RUN_RE = re.compile(
    "[\u1100-\u11ff\u3000-\u303f\u3040-\u30ff\u3100-\u312f\u3130-\u318f"
    "\u31a0-\u31bf\u3400-\u4dbf\u4e00-\u9fff\ua960-\ua97f\uac00-\ud7af"
    "\ud7b0-\ud7ff\uf900-\ufaff\uff00-\uffef\U00020000-\U0003ffff]+"
)


def _json_text(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _chars_to_tokens(value: str) -> int:
    """Count CJK characters as one token and other text at four chars/token."""
    if not value:
        return 0
    if value.isascii():
        return max(1, (len(value) + 3) // 4)
    cjk = sum(len(run) for run in _CJK_RUN_RE.findall(value))
    return max(1, cjk + (len(value) - cjk + 3) // 4)


def _content_estimate(content: Any) -> tuple[int, int]:
    if content is None:
        return 0, 0
    if isinstance(content, str):
        return _chars_to_tokens(content), 0
    if isinstance(content, Sequence) and not isinstance(content, (bytes, bytearray, str)):
        text_tokens = 0
        image_tokens = 0
        for block in content:
            if isinstance(block, Mapping):
                kind = str(block.get("type") or "").lower()
                is_image = kind in {"image", "image_url", "input_image", "output_image"} or any(
                    key in block for key in ("image_url", "image", "source")
                )
                if is_image:
                    image_tokens += IMAGE_TOKEN_ESTIMATE
                    serialized = _json_text(block)
                    if "base64" in serialized or "data:image" in serialized:
                        image_tokens += _chars_to_tokens(serialized)
                    continue
                block_text = block.get("text")
                text_tokens += _chars_to_tokens(block_text if isinstance(block_text, str) else _json_text(block))
            else:
                text_tokens += _chars_to_tokens(str(block))
        return text_tokens, image_tokens
    return _chars_to_tokens(_json_text(content)), 0


def _artifact_reference_tokens(message: Mapping[str, Any]) -> int:
    refs: list[Any] = []
    for key in ("artifact_ref", "artifact_refs", "artifacts"):
        value = message.get(key)
        if value not in (None, "", [], {}):
            refs.append(value)
    content = message.get("content")
    if isinstance(content, Sequence) and not isinstance(content, (bytes, bytearray, str)):
        refs.extend(
            block
            for block in content
            if isinstance(block, Mapping)
            and str(block.get("type") or "").lower() in {"artifact", "artifact_ref", "file", "input_file"}
        )
    return _chars_to_tokens(_json_text(refs)) if refs else 0


@dataclass(frozen=True)
class ContextEstimate:
    text: int = 0
    images: int = 0
    tool_schemas: int = 0
    tool_calls: int = 0
    tool_results: int = 0
    artifact_refs: int = 0
    wire_state: int = 0
    system_prompt: int = 0

    @property
    def total(self) -> int:
        return sum(asdict(self).values())

    def as_dict(self) -> dict[str, int]:
        return {**asdict(self), "total": self.total}


def estimate_context(
    messages: Iterable[Mapping[str, Any]],
    tool_schemas: Iterable[Mapping[str, Any]] = (),
    *,
    system_prompt: str | None = None,
) -> ContextEstimate:
    text = images = tool_calls = tool_results = artifact_refs = wire_state = 0
    message_system_prompt_tokens = 0
    for message in messages:
        content_text, content_images = _content_estimate(message.get("content"))
        role = message.get("role")
        if role == "tool":
            tool_results += content_text + MESSAGE_FRAME_TOKENS
        elif role == "system":
            message_system_prompt_tokens += content_text + MESSAGE_FRAME_TOKENS
        else:
            text += content_text + MESSAGE_FRAME_TOKENS
        images += content_images
        artifact_refs += _artifact_reference_tokens(message)
        if message.get("tool_calls"):
            tool_calls += _chars_to_tokens(_json_text(message["tool_calls"])) + 4
        if message.get("wire_state"):
            wire_state += _chars_to_tokens(_json_text(message["wire_state"])) + 4
    tool_schema_tokens = sum(_chars_to_tokens(_json_text(schema)) + 4 for schema in tool_schemas)
    if system_prompt:
        system_prompt_text = str(system_prompt)
        system_prompt_tokens = _chars_to_tokens(system_prompt_text) + MESSAGE_FRAME_TOKENS
    else:
        system_prompt_tokens = 0
    return ContextEstimate(
        text=text,
        images=images,
        tool_schemas=tool_schema_tokens,
        tool_calls=tool_calls,
        tool_results=tool_results,
        artifact_refs=artifact_refs,
        wire_state=wire_state,
        system_prompt=message_system_prompt_tokens + system_prompt_tokens,
    )


def calibration_ratio(previous: float | None, actual_prompt_tokens: int | None, estimated_tokens: int | None) -> float:
    """Return a stable provider correction ratio clamped to [0.5, 8]."""
    prior = float(previous) if previous and previous > 0 else 1.0
    if not actual_prompt_tokens or not estimated_tokens or estimated_tokens <= 0:
        return min(8.0, max(0.5, prior))
    return min(8.0, max(0.5, actual_prompt_tokens / estimated_tokens))


__all__ = ["ContextEstimate", "estimate_context", "calibration_ratio", "_chars_to_tokens"]

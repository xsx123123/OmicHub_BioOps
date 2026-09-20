"""tool_invocations 落库 200KB 护栏的截断元信息行为。"""

from __future__ import annotations

import json

from cygnusx.application.services.chat.utils import (
    _cap_tool_invocation_payload,
    _cap_tool_invocation_payload_detail,
)


def test_small_payload_kept_unchanged_without_meta() -> None:
    value = {"stdout": "hello", "n": 123}
    payload, meta = _cap_tool_invocation_payload_detail(value)
    assert payload == value
    assert meta == {}


def test_none_payload_passthrough() -> None:
    assert _cap_tool_invocation_payload_detail(None) == (None, {})


def test_boundary_payload_at_limit_not_truncated() -> None:
    filler = "a" * (200_000 - len('{"stdout": ""}'))
    value = {"stdout": filler}
    assert len(json.dumps(value, ensure_ascii=False)) == 200_000
    payload, meta = _cap_tool_invocation_payload_detail(value)
    assert payload == value
    assert meta == {}


def test_oversized_payload_replaced_with_envelope_meta() -> None:
    value = {"stdout": "x" * 500_000}
    payload, meta = _cap_tool_invocation_payload_detail(value)
    assert payload == {"_cygnusx_payload_truncated": True}
    assert meta["payload_truncated"] is True
    assert meta["original_bytes"] == len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
    assert meta["original_bytes"] > 200_000
    assert "truncation_note" in meta


def test_legacy_wrapper_signature_unchanged() -> None:
    """旧调用点（langgraph runtime 等）仅取载荷，行为与改动前一致。"""
    assert _cap_tool_invocation_payload({"a": 1}) == {"a": 1}
    assert _cap_tool_invocation_payload(None) is None
    assert _cap_tool_invocation_payload({"stdout": "x" * 500_000}) == {
        "_cygnusx_payload_truncated": True
    }

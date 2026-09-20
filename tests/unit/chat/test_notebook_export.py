"""WP3-Task1/2 单元测试：cell 信封字段 + 只读确定性 notebook 导出。"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

from cygnusx.application.services.chat.notebook_export_service import (
    _encode,
    build_notebook,
)
from cygnusx.application.services.chat.utils import (
    _code_cell_envelope_fields,
    _invocation_payload_hash,
    _max_persisted_cell_index,
)


def _msg(
    message_id: str,
    role: str,
    content: str = "",
    tool_invocations: list | None = None,
    created_at: str = "2026-09-18T00:00:00+00:00",
):
    return SimpleNamespace(
        message_id=message_id,
        role=role,
        content=content,
        created_at=created_at,
        metadata_json={"tool_invocations": tool_invocations} if tool_invocations else {},
    )


def _envelope(tool_call_id: str, code: str, language: str, cell_index: int, **overrides):
    envelope: dict = {
        "tool_call_id": tool_call_id,
        "tool_name": "sandbox_execute",
        "arguments": {"language": language, "code": code},
        "success": True,
        "result": {"stdout": "hello\n"},
        "ui_payload": {"language": language, "stdout": "hello\n", "stderr": ""},
        "mcp_server": "studio",
        "cell_index": cell_index,
        "language": language,
    }
    envelope.update(overrides)
    envelope["payload_hash"] = _invocation_payload_hash(envelope)
    return envelope


# ===== WP3-Task1：cell 信封字段 =====


def test_code_cell_fields_increment_and_hash_coverage() -> None:
    fields = _code_cell_envelope_fields(
        "sandbox_execute", {"language": "python", "code": "print(1)"}, 3
    )
    assert fields == {"cell_index": 3, "language": "python"}
    envelope = {
        "tool_call_id": "c1",
        "tool_name": "sandbox_execute",
        "arguments": {"language": "python", "code": "print(1)"},
        "success": True,
        "result": None,
        "ui_payload": None,
        **fields,
    }
    envelope["payload_hash"] = _invocation_payload_hash(envelope)
    # hash 覆盖 cell_index/language：复算一致，篡改即不匹配
    assert _invocation_payload_hash(envelope) == envelope["payload_hash"]
    tampered = {**envelope, "cell_index": 99}
    assert _invocation_payload_hash(tampered) != envelope["payload_hash"]
    tampered_lang = {**envelope, "language": "r"}
    assert _invocation_payload_hash(tampered_lang) != envelope["payload_hash"]


def test_non_code_tool_gets_null_cell_index() -> None:
    fields = _code_cell_envelope_fields("knowledge_search", {"query": "x"}, 7)
    assert fields == {"cell_index": None, "language": None}
    fields2 = _code_cell_envelope_fields("chat_sandbox_execute", {}, 0)
    assert fields2 == {"cell_index": 0, "language": None}


def test_max_persisted_cell_index_base() -> None:
    messages = [
        _msg("m1", "assistant", tool_invocations=[_envelope("c1", "a", "python", 0)]),
        _msg("m2", "assistant", tool_invocations=[_envelope("c2", "b", "r", 1)]),
        _msg("m3", "assistant", tool_invocations=[{"tool_name": "web_search"}]),  # 无字段旧信封
    ]
    assert _max_persisted_cell_index(messages) == 2
    assert _max_persisted_cell_index([]) == 0
    assert _max_persisted_cell_index([_msg("m", "user", content="hi")]) == 0


# ===== WP3-Task2：notebook 导出 =====


def _history():
    return [
        _msg("u1", "user", content="帮我跑两段代码"),
        _msg(
            "a1",
            "assistant",
            tool_invocations=[
                _envelope("c1", "print('one')", "python", 0),
                _envelope(
                    "c2",
                    "print('two')",
                    "r",
                    1,
                    result={"_cygnusx_payload_truncated": True},
                    result_truncation={
                        "payload_truncated": True,
                        "truncation_note": "工具结果序列化超过 200KB 落库护栏",
                        "original_bytes": 999999,
                    },
                ),
            ],
        ),
        _msg("a2", "assistant", content="已完成分析"),
    ]


def test_notebook_structure_and_order() -> None:
    nb = build_notebook(_history())
    assert nb["nbformat"] == 4 and nb["nbformat_minor"] == 5
    assert nb["metadata"]["kernelspec"]["name"] == "python3"  # 首个代码 cell 语言
    kinds = [(c["cell_type"], "".join(c["source"])) for c in nb["cells"]]
    # 顺序：user 文本 → code(0) → 截断说明 markdown → code(1) → assistant 文本
    assert kinds[0] == ("markdown", "帮我跑两段代码")
    assert kinds[1][0] == "code" and "print('one')" in kinds[1][1]
    assert kinds[2][0] == "markdown" and "截断" in kinds[2][1]
    assert kinds[3][0] == "code" and "print('two')" in kinds[3][1]
    assert kinds[4] == ("markdown", "已完成分析")
    code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert code_cells[0]["execution_count"] == 1  # cell_index 0 → 1
    assert code_cells[1]["execution_count"] == 2
    assert code_cells[0]["metadata"]["cygnusx"]["language"] == "python"
    assert code_cells[1]["metadata"]["cygnusx"]["payload_truncated"] is True
    # 截断说明落在 stderr stream，不静默丢弃
    streams = [o for o in code_cells[1]["outputs"] if o["output_type"] == "stream"]
    assert any("截断说明" in "".join(o["text"]) for o in streams)


def test_notebook_determinism_byte_identical() -> None:
    first = _encode(build_notebook(_history()))
    second = _encode(build_notebook(_history()))
    assert first == second
    # 内容自身确定性 hash：对不含 content_sha256 字段的正文计算
    nb = json.loads(first)
    probe = json.loads(first)
    del probe["metadata"]["cygnusx"]["content_sha256"]
    assert nb["metadata"]["cygnusx"]["content_sha256"] == hashlib.sha256(_encode(probe)).hexdigest()


def test_notebook_legacy_envelope_without_cell_fields() -> None:
    legacy = _envelope("c9", "print('old')", "python", 0)
    legacy.pop("cell_index")
    legacy.pop("language")
    legacy["payload_hash"] = _invocation_payload_hash(legacy)
    nb = build_notebook([_msg("a", "assistant", tool_invocations=[legacy])])
    code_cells = [c for c in nb["cells"] if c["cell_type"] == "code"]
    assert len(code_cells) == 1
    assert code_cells[0]["execution_count"] == 1  # 按顺序补编号
    assert code_cells[0]["metadata"]["cygnusx"]["cell_index"] is None

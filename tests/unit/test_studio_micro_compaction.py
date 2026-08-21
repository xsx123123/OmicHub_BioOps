"""历史工具输出微压缩测试。"""

import pytest

from omichub.application.services.studio_micro_compaction import compact_tool_history


@pytest.mark.unit
def test_compacts_long_historical_tool_output_but_keeps_recent_message():
    long_output = "\n".join(f"line-{index}" for index in range(200))
    messages = [
        {
            "role": "assistant",
            "content": "早期结论",
            "metadata": {
                "tool_invocations": [
                    {
                        "tool_name": "sandbox_execute",
                        "arguments": {"path": "output/log.txt"},
                        "result": long_output,
                    }
                ]
            },
        },
        {"role": "user", "content": "继续分析"},
    ]

    compacted = compact_tool_history(messages, threshold=100)

    assert "输出已压缩" in compacted[0]["content"]
    assert "output/log.txt" in compacted[0]["content"]
    assert compacted[1] == messages[1]


@pytest.mark.unit
def test_does_not_compact_ask_user_invocation():
    output = "x" * 500
    messages = [
        {
            "role": "assistant",
            "content": "需要确认",
            "metadata": {
                "tool_invocations": [
                    {"tool_name": "ask_user", "result": output}
                ]
            },
        },
        {"role": "user", "content": "回答"},
    ]

    compacted = compact_tool_history(messages, threshold=100)

    assert compacted[0]["content"] == "需要确认"

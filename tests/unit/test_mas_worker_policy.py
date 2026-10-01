"""worker_policy 纯函数单测（手册阶段 2 验收项）。"""

from cygnusx.domain.mas.worker_policy import (
    build_worker_messages,
    filter_trace_messages,
    strip_worker_tools,
    truncate_for_supervisor,
)


def test_strip_worker_tools_removes_recursive_features() -> None:
    features = {
        "parallel_subagents": {"max": 3},
        "transfer_to_agent": True,
        "studio": {"image": "x"},
    }
    stripped = strip_worker_tools(features)
    assert "parallel_subagents" not in stripped
    assert "transfer_to_agent" not in stripped
    assert stripped["studio"] == {"image": "x"}
    # 入参不被修改
    assert "parallel_subagents" in features


def test_strip_worker_tools_none_safe() -> None:
    assert strip_worker_tools(None) == {}


def test_build_worker_messages_trims_to_limit() -> None:
    history = [{"role": "user", "content": f"q{i}"} for i in range(20)]
    messages = build_worker_messages(history, fold_summary="早期讨论摘要", limit=10)
    # 摘要 + 最近 10 条
    assert len(messages) == 11
    assert messages[0]["role"] == "system"
    assert messages[0]["name"] == "mas_summary"
    assert messages[0]["content"] == "早期讨论摘要"
    assert messages[1]["content"] == "q10"
    assert messages[-1]["content"] == "q19"


def test_build_worker_messages_filters_system_roles() -> None:
    history = [
        {"role": "user", "content": "问题"},
        {"role": "mas_trace", "content": "派工轨迹"},
        {"role": "plan_card", "content": "计划"},
        {"role": "assistant", "name": "agent-rnaseq", "content": "回答"},
    ]
    messages = build_worker_messages(history, limit=10)
    assert len(messages) == 2
    assert all(m["role"] in ("user", "assistant") for m in messages)


def test_build_worker_messages_no_summary_when_within_limit() -> None:
    history = [{"role": "user", "content": "q1"}]
    messages = build_worker_messages(history, fold_summary="摘要", limit=10)
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


def test_build_worker_messages_no_older_no_summary_injected() -> None:
    history = [{"role": "user", "content": f"q{i}"} for i in range(10)]
    messages = build_worker_messages(history, fold_summary="摘要", limit=10)
    assert len(messages) == 10
    assert not any(m.get("name") == "mas_summary" for m in messages)


def test_truncate_for_supervisor_caps_long_text() -> None:
    text = "x" * 5000
    truncated = truncate_for_supervisor(text)
    assert len(truncated) <= 4000 + len("\n…[已截断]")
    assert truncated.endswith("…[已截断]")


def test_truncate_for_supervisor_keeps_short_text() -> None:
    assert truncate_for_supervisor("短文本") == "短文本"


def test_filter_trace_messages_for_supervisor_context() -> None:
    messages = [
        {"role": "user", "content": "问题"},
        {"role": "mas_trace", "name": "mas_trace", "content": "轨迹"},
        {"role": "plan_card", "content": "计划"},
        {"role": "assistant", "name": "agent-rnaseq", "content": "回答"},
    ]
    filtered = filter_trace_messages(messages)
    assert len(filtered) == 2
    assert all(m["role"] in ("user", "assistant") for m in filtered)

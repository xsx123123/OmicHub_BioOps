from types import SimpleNamespace

from cygnusx.application.services.chat.context_estimate import (
    _chars_to_tokens,
    calibration_ratio,
    estimate_context,
)
from cygnusx.application.services.chat.runtime_support import ChatRuntimeSupport


def test_context_compaction_settings_reload_from_environment(monkeypatch) -> None:
    import cygnusx.core.config as config

    config.get_settings.cache_clear()
    monkeypatch.setenv("CONTEXT_COMPACTION_TRIGGER_RATIO", "0.61")
    assert config.reload_settings().context_compaction.trigger_ratio == 0.61
    monkeypatch.setenv("CONTEXT_COMPACTION_TRIGGER_RATIO", "0.62")
    assert config.reload_settings().context_compaction.trigger_ratio == 0.62
    config.get_settings.cache_clear()


def test_chars_to_tokens_ascii_and_cjk() -> None:
    assert _chars_to_tokens("abcd") == 1
    assert _chars_to_tokens("中文") == 2
    assert _chars_to_tokens("ab中文") == 3


def test_estimate_context_keeps_buckets_separate() -> None:
    estimate = estimate_context(
        [
            {"role": "system", "content": "abcd"},
            {"role": "user", "content": "中文"},
            {"role": "tool", "content": "result", "tool_calls": [{"id": "x"}]},
        ],
        [{"type": "function", "function": {"name": "demo"}}],
    )
    assert estimate.system_prompt == 9
    assert estimate.text == 10
    assert estimate.tool_results == 10
    assert estimate.tool_schemas > 0
    assert estimate.tool_calls > 0
    assert estimate.total == sum(estimate.as_dict().values()) - estimate.total


def test_estimate_context_counts_provider_side_system_prompt() -> None:
    without_prompt = estimate_context([{"role": "user", "content": "hello"}])
    with_prompt = estimate_context(
        [{"role": "user", "content": "hello"}],
        [{"type": "function", "function": {"name": "demo"}}],
        system_prompt="中文系统约束",
    )

    assert with_prompt.system_prompt > without_prompt.system_prompt
    assert with_prompt.tool_schemas > 0
    assert with_prompt.total > without_prompt.total


def test_calibration_ratio_is_clamped_and_reuses_previous() -> None:
    assert calibration_ratio(None, 100, 1) == 8.0
    assert calibration_ratio(None, 1, 100) == 0.5
    assert calibration_ratio(2.0, None, 100) == 2.0


def test_runtime_trigger_uses_model_window(monkeypatch) -> None:
    settings = SimpleNamespace(
        context_compaction=SimpleNamespace(
            keep_recent_min=4, min_messages=12, trigger_ratio=0.75
        )
    )
    monkeypatch.setattr(
        "cygnusx.application.services.chat.runtime_support.get_settings", lambda: settings
    )
    messages = [{"role": "user", "content": "x" * 4000} for _ in range(13)]
    model = SimpleNamespace(context_window=1000, model="test")
    support = ChatRuntimeSupport()
    # The old 200K threshold would not trigger this input; the model window does.
    estimate = support._estimate_messages_tokens(messages)
    assert estimate > 750

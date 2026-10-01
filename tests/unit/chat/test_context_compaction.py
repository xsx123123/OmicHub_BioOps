from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

from cygnusx.application.services.chat.context_compaction import (
    CompactionCancelled,
    HANDOFF_FIELDS,
    CompactionPolicy,
    CompactionResult,
    CompactionSummaryError,
    compact,
    externalize_large_outputs,
    load_externalized_output,
    _keep_by_tokens,
    write_compaction_archive,
    segment_messages,
)
from cygnusx.application.services.chat.context_estimate import ContextEstimate
from cygnusx.application.services.chat.runtime_support import ChatRuntimeSupport


def test_externalize_large_tool_output_is_content_addressed(tmp_path) -> None:
    large = "x" * 20_000
    projected, archived = externalize_large_outputs(
        [
            {"role": "user", "content": "real user input"},
            {"role": "tool", "content": large},
            {"role": "assistant", "content": "```python\nprint(1)\n```"},
        ],
        tmp_path,
        threshold_chars=16_384,
        preview_chars=768,
    )
    assert archived == 1
    assert projected[0]["content"] == "real user input"
    assert projected[1]["context_externalized"] is True
    assert len(projected[1]["content"]) <= 768
    assert load_externalized_output(tmp_path, projected[1]["context_blob_sha256"]) == large
    assert "context_externalized" not in projected[2]


def test_externalize_threshold_and_dedupe(tmp_path) -> None:
    exact = "x" * 16_385
    messages = [
        {"role": "tool", "content": exact},
        {"role": "tool", "content": exact},
    ]
    projected, archived = externalize_large_outputs(messages, tmp_path)
    assert archived == 2
    assert projected[0]["context_blob_sha256"] == projected[1]["context_blob_sha256"]
    assert len(list((tmp_path / "context-blobs").glob("*/*.json"))) == 1

    below, archived = externalize_large_outputs(
        [{"role": "tool", "content": "x" * 16_383}], tmp_path
    )
    assert archived == 0
    assert "context_externalized" not in below[0]


def test_externalization_never_replaces_a_real_user_prompt(tmp_path) -> None:
    user_prompt = "[Observation] " + "用户明确提供的原始输入。" * 2_000
    projected, archived = externalize_large_outputs(
        [
            {"role": "assistant", "content": "前序回答"},
            {"role": "assistant", "content": "继续说明"},
            {"role": "user", "content": user_prompt},
        ],
        tmp_path,
    )

    assert archived == 0
    assert projected[2]["content"] == user_prompt

    projected, archived = externalize_large_outputs(
        [
            {"role": "assistant", "content": "前序回答"},
            {"role": "assistant", "content": "继续说明"},
            {
                "role": "user",
                "content": user_prompt,
                "context_observation": True,
            },
        ],
        tmp_path,
    )

    assert archived == 1
    assert projected[2]["context_externalized"] is True


def test_externalize_writes_workspace_copy(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    projected, archived = externalize_large_outputs(
        [{"role": "tool", "content": "z" * 16_385}],
        tmp_path / "host",
        workspace_dir=workspace,
    )
    digest = projected[0]["context_blob_sha256"]
    assert archived == 1
    workspace_blob = workspace / ".context-archive" / "context-blobs" / digest[:2] / f"{digest}.json"
    assert workspace_blob.exists()
    assert load_externalized_output(workspace / ".context-archive", digest) == "z" * 16_385


def test_externalize_rejects_workspace_archive_symlink(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / ".context-archive").symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        externalize_large_outputs(
            [{"role": "tool", "content": "z" * 16_385}],
            tmp_path / "host",
            workspace_dir=workspace,
        )


def test_externalize_rejects_host_archive_symlink(tmp_path) -> None:
    archive = tmp_path / "host"
    archive.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (archive / "context-blobs").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        externalize_large_outputs(
            [{"role": "tool", "content": "z" * 16_385}], archive
        )


def test_externalize_rejects_symlinked_archive_parent(tmp_path) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        externalize_large_outputs(
            [{"role": "tool", "content": "z" * 16_385}],
            linked_parent / "session",
        )


def test_externalize_same_blob_is_safe_under_concurrent_first_writes(tmp_path) -> None:
    messages = [{"role": "tool", "content": "z" * 16_385}]

    def write_once() -> tuple[list[dict], int]:
        return externalize_large_outputs(messages, tmp_path / "host", workspace_dir=tmp_path / "workspace")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _index: write_once(), range(8)))

    assert all(archived == 1 for _projected, archived in results)
    digest = results[0][0][0]["context_blob_sha256"]
    assert load_externalized_output(tmp_path / "host", digest) == messages[0]["content"]
    assert load_externalized_output(tmp_path / "workspace" / ".context-archive", digest) == messages[0]["content"]


def test_externalize_repairs_torn_existing_blob(tmp_path) -> None:
    messages = [{"role": "tool", "content": "z" * 16_385}]
    projected, _ = externalize_large_outputs(messages, tmp_path)
    digest = projected[0]["context_blob_sha256"]
    blob = tmp_path / "context-blobs" / digest[:2] / f"{digest}.json"
    blob.write_text('{"sha256":"wrong","content":"tampered"}', encoding="utf-8")

    externalize_large_outputs(messages, tmp_path)

    assert load_externalized_output(tmp_path, digest) == messages[0]["content"]


def test_compaction_archive_is_atomic_json(tmp_path) -> None:
    path = write_compaction_archive(tmp_path, {"handoff": "x", "compacted_messages": []}, archive_id="s-1")
    assert path.endswith("compaction-s-1.json")
    assert '"handoff": "x"' in (tmp_path / "compaction-s-1.json").read_text()


def test_compaction_archive_rejects_symlinked_target(tmp_path) -> None:
    archive = tmp_path / "archive"
    archive.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("outside", encoding="utf-8")
    (archive / "compaction-s-1.json").symlink_to(outside)

    with pytest.raises(ValueError, match="symlink"):
        write_compaction_archive(archive, {"handoff": "x"}, archive_id="s-1")


def test_compaction_archive_rejects_symlinked_parent(tmp_path) -> None:
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink"):
        write_compaction_archive(
            linked_parent / "session", {"handoff": "x"}, archive_id="s-1"
        )


@pytest.mark.asyncio
async def test_policy_opens_after_failures_and_reopens_after_growth() -> None:
    policy = CompactionPolicy(breaker_attempts=2)
    calls = 0

    async def failing():
        nonlocal calls
        calls += 1
        raise RuntimeError("provider down")

    assert await policy.prepare([], compact_fn=failing, context_total=100) is None
    assert await policy.prepare([], compact_fn=failing, context_total=100) is None
    assert policy.circuit_open is True
    assert calls == 2

    async def success():
        return CompactionResult([{"role": "system", "content": "handoff"}], 200, 50, "handoff")

    assert await policy.prepare([], compact_fn=success, context_total=100) is None
    assert calls == 2
    adopted = await policy.prepare([], compact_fn=success, context_total=150)
    assert adopted is not None
    assert policy.circuit_open is False


@pytest.mark.asyncio
async def test_policy_rejects_low_yield_and_opens_circuit() -> None:
    policy = CompactionPolicy(min_yield_ratio=0.10, breaker_attempts=2)

    async def low_yield():
        return CompactionResult([], 100, 95, "handoff")

    assert await policy.prepare([], compact_fn=low_yield, context_total=100) is None
    assert policy.low_yield_streak == 1
    assert await policy.prepare([], compact_fn=low_yield, context_total=100) is None
    assert policy.circuit_open is True


@pytest.mark.asyncio
async def test_policy_does_not_count_noop_as_low_yield() -> None:
    policy = CompactionPolicy(breaker_attempts=1)

    async def noop():
        return None

    assert await policy.prepare([], compact_fn=noop, context_total=100) is None
    assert policy.low_yield_streak == 0
    assert policy.failure_streak == 0
    assert policy.circuit_open is False


@pytest.mark.asyncio
async def test_low_yield_success_resets_failure_streak() -> None:
    policy = CompactionPolicy(breaker_attempts=2)

    async def failing():
        raise RuntimeError("provider unavailable")

    async def low_yield():
        return CompactionResult([], 100, 95, "handoff")

    assert await policy.prepare([], compact_fn=failing, context_total=100) is None
    assert policy.failure_streak == 1
    assert await policy.prepare([], compact_fn=low_yield, context_total=100) is None
    assert policy.failure_streak == 0
    assert policy.circuit_open is False


@pytest.mark.asyncio
async def test_policy_does_not_count_cancellation_as_failure() -> None:
    policy = CompactionPolicy(breaker_attempts=1)

    async def cancelled():
        raise CompactionCancelled("client disconnected")

    with pytest.raises(CompactionCancelled):
        await policy.prepare([], compact_fn=cancelled, context_total=100)
    assert policy.failure_streak == 0
    assert policy.circuit_open is False


def test_segments_keep_tool_batches_atomic() -> None:
    segments = segment_messages(
        [
            {"role": "user", "content": "goal"},
            {"role": "assistant", "tool_calls": [{"id": "1"}], "content": ""},
            {"role": "tool", "tool_call_id": "1", "content": "result"},
            {"role": "user", "content": "next"},
        ]
    )
    assert [(item.start, item.end, item.kind) for item in segments] == [
        (0, 1, "message"),
        (1, 3, "assistant_tool_group"),
        (3, 4, "message"),
    ]


def test_keep_by_tokens_uses_the_actual_tail_budget_once() -> None:
    """每个消息只计一次，避免 token tail 无故少保留一半上下文。"""
    messages = [
        {"role": "assistant", "content": "1234"},
        {"role": "assistant", "content": "5678"},
        {"role": "assistant", "content": "abcd"},
    ]

    # 每条消息 = 1 个文本 token + 8 个消息框架 token；18 token 正好保留两条。
    assert _keep_by_tokens(messages, budget=18) == 2


@pytest.mark.asyncio
async def test_compact_normalizes_handoff_and_keeps_head_tail() -> None:
    summary = "\n\n".join(f"## {field}\n- recorded" for field in HANDOFF_FIELDS)

    async def chat_fn(_request, *, max_tokens, temperature):
        return {"content": summary, "finish_reason": "stop"}

    messages = [{"role": "user", "content": "goal"}]
    messages.extend({"role": "assistant", "content": f"step-{index}"} for index in range(12))
    result = await compact(
        messages,
        chat_fn=chat_fn,
        context_window=100,
        host_state_fact="workspace-continuous",
        keep_recent=4,
    )
    assert result is not None
    assert result.projected[0]["content"] == "goal"
    handoff = next(message for message in result.projected if message.get("compaction_handoff"))
    assert "workspace-continuous" in handoff["content"]
    assert result.projected[-1]["content"] == "step-11"


@pytest.mark.asyncio
async def test_second_compaction_replaces_prior_handoff() -> None:
    summary = "\n\n".join(f"## {field}\n- recorded" for field in HANDOFF_FIELDS)

    async def chat_fn(_request, *, max_tokens, temperature):
        return {"content": summary, "finish_reason": "stop"}

    messages = [{"role": "user", "content": "goal"}] + [
        {"role": "assistant", "content": f"step-{index}"} for index in range(12)
    ]
    first = await compact(messages, chat_fn=chat_fn, context_window=100, keep_recent=2)
    assert first is not None
    expanded = first.projected[:-2] + [
        {"role": "assistant", "content": f"later-{index}"} for index in range(8)
    ] + first.projected[-2:]
    second = await compact(expanded, chat_fn=chat_fn, context_window=100, keep_recent=2)
    assert second is not None
    assert sum(bool(message.get("compaction_handoff")) for message in second.projected) == 1


@pytest.mark.asyncio
async def test_compact_retries_truncated_summary() -> None:
    calls = []
    summary = "\n\n".join(f"## {field}\n- recorded" for field in HANDOFF_FIELDS)

    async def chat_fn(_request, *, max_tokens, temperature):
        calls.append(max_tokens)
        if len(calls) == 1:
            return {"content": "partial", "finish_reason": "length"}
        return {"content": summary, "finish_reason": "stop"}

    messages = [{"role": "user", "content": "goal"}] + [
        {"role": "assistant", "content": str(index)} for index in range(8)
    ]
    result = await compact(messages, chat_fn=chat_fn, context_window=100, keep_recent=2)
    assert result is not None
    assert calls[:2] == [1, 2]


@pytest.mark.asyncio
async def test_compact_summary_omits_images_and_caps_tool_arguments() -> None:
    captured: list[list[dict]] = []
    summary = "\n\n".join(f"## {field}\n- recorded" for field in HANDOFF_FIELDS)

    async def chat_fn(request, *, max_tokens, temperature):
        captured.append(request)
        return {"content": summary, "finish_reason": "stop"}

    messages = [
        {"role": "user", "content": "goal"},
        {"role": "assistant", "content": "setup"},
        {
            "role": "assistant",
            "content": [{"type": "image_url", "image_url": "data:image/png;base64," + "A" * 4000}],
            "tool_calls": [{"function": {"name": "run", "arguments": "B" * 4000}}],
        },
    ] + [{"role": "assistant", "content": str(index)} for index in range(7)]
    result = await compact(messages, chat_fn=chat_fn, context_window=100, keep_recent=2)
    assert result is not None
    transcript = captured[0][1]["content"]
    assert '"omitted": true' in transcript
    assert "B" * 2001 not in transcript


@pytest.mark.asyncio
async def test_compact_empty_summary_fails_without_projection() -> None:
    async def chat_fn(_request, *, max_tokens, temperature):
        return {"content": "", "finish_reason": "stop"}

    messages = [{"role": "user", "content": "goal"}] + [
        {"role": "assistant", "content": str(index)} for index in range(8)
    ]
    with pytest.raises(CompactionSummaryError):
        await compact(messages, chat_fn=chat_fn, context_window=100, keep_recent=2)


def _runtime_settings(tmp_path, *, trigger_ratio: float = 0.1):
    return SimpleNamespace(
        storage_path=str(tmp_path),
        context_compaction=SimpleNamespace(
            trigger_ratio=trigger_ratio,
            large_output_chars=16_384,
            preview_chars=768,
            keep_recent_min=2,
            tail_ratio=0.25,
            min_yield_ratio=0.1,
            breaker_attempts=2,
            circuit_retry_growth=1.5,
            min_messages=2,
            summary_max_chars=6000,
        ),
    )


@pytest.mark.asyncio
async def test_runtime_compaction_failure_returns_original_messages(monkeypatch, tmp_path) -> None:
    import cygnusx.application.services.chat.runtime_support as runtime_support

    original = [{"role": "user", "content": f"message-{index}"} for index in range(8)]
    monkeypatch.setattr(runtime_support, "get_settings", lambda: _runtime_settings(tmp_path))
    monkeypatch.setattr(runtime_support, "externalize_large_outputs", lambda messages, *_args, **_kwargs: (list(messages), 0))

    async def fail_compaction(*_args, **_kwargs):
        raise RuntimeError("summary provider unavailable")

    monkeypatch.setattr(runtime_support, "compact", fail_compaction)
    support = ChatRuntimeSupport()
    support._active_context_session_id = "session-1"
    model = SimpleNamespace(context_window=20, model="test", max_tokens=128)

    projected, compressed, _ = await support._compress_context_if_needed(original, model)

    assert compressed is False
    assert projected is original
    assert support._last_context_compaction is None


@pytest.mark.asyncio
async def test_runtime_compaction_prices_tools_and_system_prompt(monkeypatch, tmp_path) -> None:
    import cygnusx.application.services.chat.runtime_support as runtime_support

    original = [{"role": "user", "content": f"message-{index}"} for index in range(8)]
    monkeypatch.setattr(runtime_support, "get_settings", lambda: _runtime_settings(tmp_path))
    monkeypatch.setattr(
        runtime_support,
        "externalize_large_outputs",
        lambda messages, *_args, **_kwargs: (list(messages), 0),
    )
    captured: dict[str, object] = {}

    async def skip_compaction(*_args, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(runtime_support, "compact", skip_compaction)
    support = ChatRuntimeSupport()
    support._active_context_session_id = "session-1"
    model = SimpleNamespace(context_window=20, model="test", max_tokens=128)
    tools = [{"type": "function", "function": {"name": "demo"}}]

    await support._compress_context_if_needed(
        original,
        model,
        tool_schemas=tools,
        system_prompt="必须保留证据链",
    )

    assert captured["tool_schemas"] == tools
    assert captured["system_prompt"] == "必须保留证据链"


@pytest.mark.asyncio
async def test_runtime_externalization_only_reports_original_tokens(monkeypatch, tmp_path) -> None:
    import cygnusx.application.services.chat.runtime_support as runtime_support

    original = [
        {"role": "user", "content": "goal"},
        {"role": "tool", "content": "x" * 20_000},
    ]
    projected = [
        original[0],
        {"role": "tool", "content": "preview", "context_externalized": True},
    ]
    monkeypatch.setattr(runtime_support, "get_settings", lambda: _runtime_settings(tmp_path, trigger_ratio=1.0))
    monkeypatch.setattr(
        runtime_support,
        "externalize_large_outputs",
        lambda messages, *_args, **_kwargs: (projected, 1),
    )
    support = ChatRuntimeSupport()
    support._active_context_session_id = "externalized-only"
    model = SimpleNamespace(context_window=1_000_000, model="test", max_tokens=128)

    compacted, did_compress, tokens_before = await support._compress_context_if_needed(original, model)

    assert did_compress is True
    assert compacted is projected
    assert tokens_before == support._estimate_messages_tokens(original)
    assert tokens_before > support._estimate_messages_tokens(projected)
    assert support._last_context_compaction["tokens_before"] == tokens_before


@pytest.mark.asyncio
async def test_runtime_archive_failure_does_not_adopt_projection(monkeypatch, tmp_path) -> None:
    import cygnusx.application.services.chat.runtime_support as runtime_support

    original = [{"role": "user", "content": f"message-{index}"} for index in range(8)]
    projected = [{"role": "system", "content": "handoff", "compaction_handoff": True}]
    result = CompactionResult(
        projected=projected,
        tokens_before=100,
        tokens_after=20,
        handoff="## Objective\n- retained",
        archive_payload={"handoff": "retained"},
    )
    monkeypatch.setattr(runtime_support, "get_settings", lambda: _runtime_settings(tmp_path))
    monkeypatch.setattr(runtime_support, "externalize_large_outputs", lambda messages, *_args, **_kwargs: (list(messages), 0))
    monkeypatch.setattr(runtime_support, "compact", lambda *_args, **_kwargs: _return_result(result))
    monkeypatch.setattr(runtime_support, "write_compaction_archive", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")))
    support = ChatRuntimeSupport()
    support._active_context_session_id = "session-1"
    model = SimpleNamespace(context_window=20, model="test", max_tokens=128)

    retained, compressed, _ = await support._compress_context_if_needed(original, model)

    assert compressed is False
    assert retained is original
    assert support._last_context_compaction is None


@pytest.mark.asyncio
async def test_runtime_adopts_only_after_archive_and_keeps_db_source_unchanged(monkeypatch, tmp_path) -> None:
    import cygnusx.application.services.chat.runtime_support as runtime_support
    from cygnusx.application.services.chat_message_event_service import message_event_service

    original = [{"role": "user", "content": f"message-{index}"} for index in range(8)]
    snapshot = [dict(message) for message in original]
    result = CompactionResult(
        projected=[{"role": "system", "content": "handoff", "compaction_handoff": True}],
        tokens_before=100,
        tokens_after=20,
        handoff="## Objective\n- retained",
        archive_payload={"handoff": "retained"},
    )
    events: list[dict] = []
    monkeypatch.setattr(runtime_support, "get_settings", lambda: _runtime_settings(tmp_path))
    monkeypatch.setattr(runtime_support, "externalize_large_outputs", lambda messages, *_args, **_kwargs: (list(messages), 0))
    monkeypatch.setattr(runtime_support, "compact", lambda *_args, **_kwargs: _return_result(result))

    async def capture(_message_id, **payload):
        events.append(payload)
        return True

    monkeypatch.setattr(message_event_service, "append_compaction_event", capture)
    support = ChatRuntimeSupport()
    support._active_context_session_id = "session/unsafe"
    support._active_context_message_id = "message-1"
    model = SimpleNamespace(context_window=20, model="test", max_tokens=128)

    projected, compressed, _ = await support._compress_context_if_needed(original, model)

    assert compressed is True
    assert projected[0].get("compaction_handoff") is True
    assert original == snapshot
    assert events[0]["archive_ref"].endswith(".json")
    assert "/session/" not in events[0]["archive_ref"]
    key = support._context_calibration_key("session/unsafe", model)
    assert support._context_last_estimates[key] == result.tokens_after
    support._record_context_usage("session/unsafe", model, 30)
    assert support._context_calibration_ratios[key] == 1.5


@pytest.mark.asyncio
async def test_runtime_legacy_fallback_switch_uses_legacy_summary(monkeypatch, tmp_path) -> None:
    import cygnusx.application.services.chat.runtime_support as runtime_support

    settings = _runtime_settings(tmp_path)
    settings.context_compaction.legacy_fallback = True
    monkeypatch.setattr(runtime_support, "get_settings", lambda: settings)

    class Chunk:
        type = "text"
        content = "legacy summary"

    async def fake_stream(**_kwargs):
        yield Chunk()

    monkeypatch.setattr(runtime_support.provider_manager, "chat_stream", fake_stream)
    original = [{"role": "user", "content": "message-0 " + "x" * 410_000}]
    original.extend(
        {"role": "assistant", "content": f"message-{index}"} for index in range(1, 14)
    )
    projected, compressed, _ = await ChatRuntimeSupport()._compress_context_if_needed(
        original, SimpleNamespace(context_window=100, model="test")
    )
    assert compressed is True
    assert projected[0]["content"].startswith("[早期对话已压缩为摘要")


@pytest.mark.asyncio
@pytest.mark.parametrize("runtime_name", ["legacy", "langgraph"])
async def test_runtime_compaction_contract_over_thirty_tool_turns(
    monkeypatch, tmp_path, runtime_name: str
) -> None:
    """Exercise the shared pre-runtime pipeline with a realistic long transcript."""
    import cygnusx.application.services.chat.runtime_support as runtime_support

    settings = _runtime_settings(tmp_path, trigger_ratio=0.75)
    settings.context_compaction.min_messages = 4
    settings.context_compaction.keep_recent_min = 4
    monkeypatch.setattr(runtime_support, "get_settings", lambda: settings)
    handoff = "\n\n".join(f"## {field}\n- retained" for field in HANDOFF_FIELDS)

    async def fake_stream(**_kwargs):
        yield SimpleNamespace(type="text", content=handoff, metadata={})
        yield SimpleNamespace(type="done", content="", metadata={})

    monkeypatch.setattr(runtime_support.provider_manager, "chat_stream", fake_stream)
    support = ChatRuntimeSupport()
    support._active_context_session_id = f"contract-{runtime_name}"
    support._active_context_host_state_fact = "workspace-continuous"
    model = SimpleNamespace(context_window=1000, model=f"test-{runtime_name}", max_tokens=128)

    db_messages = [{"role": "user", "content": "目标：分析中文工具执行结果并保留证据。"}]
    compressed = False
    last_projection = db_messages
    for turn in range(30):
        db_messages.extend(
            [
                {"role": "assistant", "content": f"第 {turn} 轮准备执行工具，保留参数与结论。"},
                {"role": "tool", "content": f"工具结果 {turn}: " + "测序结果与路径证据。" * 12},
            ]
        )
        before = [dict(message) for message in db_messages]
        last_projection, did_compress, _ = await support._compress_context_if_needed(
            db_messages, model
        )
        assert db_messages == before
        compressed = compressed or did_compress

    assert compressed is True
    assert last_projection[0]["content"].startswith("目标：分析中文工具")
    assert support._last_context_compaction is not None
    assert support._last_context_compaction["tokens_after"] < model.context_window * 0.75


@pytest.mark.asyncio
async def test_runtime_provider_failure_is_failure_safe_and_opens_circuit(
    monkeypatch, tmp_path
) -> None:
    import cygnusx.application.services.chat.runtime_support as runtime_support

    settings = _runtime_settings(tmp_path, trigger_ratio=0.1)
    settings.context_compaction.min_messages = 2
    settings.context_compaction.breaker_attempts = 2
    monkeypatch.setattr(runtime_support, "get_settings", lambda: settings)
    calls = 0

    async def failing_stream(**_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("injected provider failure")
        if False:  # pragma: no cover - keeps this callable an async generator
            yield SimpleNamespace(type="done", content="", metadata={})

    monkeypatch.setattr(runtime_support.provider_manager, "chat_stream", failing_stream)
    support = ChatRuntimeSupport()
    support._active_context_session_id = "provider-failure-contract"
    original = [{"role": "user", "content": f"message-{index}"} for index in range(10)]
    model = SimpleNamespace(context_window=20, model="failure-test", max_tokens=128)

    for _ in range(2):
        projected, compressed, _ = await support._compress_context_if_needed(original, model)
        assert projected is original
        assert compressed is False

    policy = support._context_compaction_policies[
        support._context_calibration_key("provider-failure-contract", model)
    ]
    assert policy.circuit_open is True
    projected, compressed, _ = await support._compress_context_if_needed(original, model)
    assert projected is original
    assert compressed is False
    assert calls == 2


@pytest.mark.asyncio
async def test_runtime_persists_compaction_audit_buckets_and_policy_state() -> None:
    """P3 audit metadata is durable on the session, not on the projection."""
    from cygnusx.application.services.chat.context_compaction import CompactionPolicy

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalar_one_or_none(self):
            return self.value

    class _Db:
        def __init__(self, session):
            self.session = session
            self.flushed = False

        async def execute(self, _statement):
            return _Result(self.session)

        async def flush(self):
            self.flushed = True

    session = SimpleNamespace(session_id="audit-session", sandbox_meta={})
    support = ChatRuntimeSupport()
    support._db = _Db(session)
    support._active_context_session_id = session.session_id
    model = SimpleNamespace(model="audit-model")
    support._active_model_config = model
    key = support._context_calibration_key(session.session_id, model)
    policy = CompactionPolicy()
    policy.failure_streak = 1
    policy.low_yield_streak = 1
    policy.circuit_open = True
    policy.circuit_reason = "low yield"
    support._context_compaction_policies[key] = policy

    estimate = ContextEstimate(
        text=100,
        images=2,
        tool_schemas=3,
        tool_calls=4,
        tool_results=5,
        artifact_refs=6,
        wire_state=7,
        system_prompt=8,
    )
    await support._persist_context_compaction_audit(
        tokens=135,
        calibrated_tokens=202.5,
        estimate=estimate,
    )

    audit = session.sandbox_meta["context_compaction"]
    assert audit["context_estimate"] == estimate.as_dict()
    assert audit["context_estimate_total"] == 135
    assert audit["context_estimate_calibrated_total"] == 202.5
    assert audit["compaction_failure_streak"] == 1
    assert audit["compaction_low_yield_streak"] == 1
    assert audit["compaction_circuit_open"] is True
    assert audit["compaction_circuit_reason"] == "low yield"
    assert support._db.flushed is True


@pytest.mark.asyncio
async def test_runtime_reload_updates_existing_compaction_policy(monkeypatch, tmp_path) -> None:
    import cygnusx.application.services.chat.runtime_support as runtime_support

    settings = _runtime_settings(tmp_path, trigger_ratio=0.1)
    settings.context_compaction.min_messages = 2
    settings.context_compaction.breaker_attempts = 2
    monkeypatch.setattr(runtime_support, "get_settings", lambda: settings)

    async def failing_compaction(*_args, **_kwargs):
        raise RuntimeError("injected provider failure")

    monkeypatch.setattr(runtime_support, "compact", failing_compaction)
    support = ChatRuntimeSupport()
    support._active_context_session_id = "hot-reload-policy"
    original = [{"role": "user", "content": f"message-{index}"} for index in range(10)]
    model = SimpleNamespace(context_window=20, model="hot-reload", max_tokens=128)

    await support._compress_context_if_needed(original, model)
    key = support._context_calibration_key("hot-reload-policy", model)
    policy = support._context_compaction_policies[key]
    assert policy.failure_streak == 1
    assert policy.breaker_attempts == 2

    settings.context_compaction.breaker_attempts = 1
    await support._compress_context_if_needed(original, model)

    assert policy.breaker_attempts == 1
    assert policy.circuit_open is True


async def _return_result(result):
    return result

"""Chat Runtime 双跑比较工具测试。"""

import pytest

from cygnusx.application.services.chat.dual_run import (
    DualRunResult,
    assert_equivalent,
    capture_golden_record,
    compare_golden_record,
    compare_streams,
    write_report,
)
from cygnusx.application.services.execution_events import EventSequenceError
from cygnusx.application.services.chat.golden_records import save_events
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk


async def _stream(*chunks: ChatChunk):
    for chunk in chunks:
        yield chunk


async def _failing_stream():
    yield ChatChunk(type="text", content="partial")
    raise RuntimeError("stream failed")


@pytest.mark.asyncio
async def test_compare_streams_ignores_volatile_event_metadata() -> None:
    result = await compare_streams(
        "direct-text",
        lambda: _stream(ChatChunk(type="text", content="answer", metadata={"run_id": "old"})),
        lambda: _stream(ChatChunk(type="text", content="answer", metadata={"run_id": "new"})),
    )

    assert result.equivalent
    assert result.differences == []
    assert result.baseline_duration_ms >= 0
    assert result.candidate_duration_ms >= 0


@pytest.mark.asyncio
async def test_compare_streams_rejects_incomplete_execution_candidate() -> None:
    with pytest.raises(EventSequenceError, match="以 done 事件收尾"):
        await compare_streams(
            "invalid-execution-candidate",
            lambda: _stream(ChatChunk(type="text", content="baseline")),
            lambda: _stream(
                ChatChunk(type="agent_turn_started"),
                ChatChunk(type="agent_final_result"),
            ),
        )


@pytest.mark.asyncio
async def test_compare_golden_record_and_write_report(tmp_path) -> None:
    golden_path = tmp_path / "golden.json"
    report_path = tmp_path / "report.json"
    save_events(golden_path, [ChatChunk(type="text", content="baseline")])

    result = await compare_golden_record(
        "golden-text",
        golden_path,
        lambda: _stream(ChatChunk(type="text", content="candidate")),
    )

    report = write_report(report_path, [result])

    assert not result.equivalent
    assert report[0]["scenario"] == "golden-text"
    assert report[0]["differences"] == result.differences
    assert report[0]["candidate_duration_ms"] >= 0
    assert '"equivalent": false' in report_path.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_capture_golden_record_writes_only_completed_stream(tmp_path) -> None:
    golden_path = tmp_path / "captured.json"

    events = await capture_golden_record(
        golden_path,
        _stream(
            ChatChunk(type="text", content="answer", metadata={"run_id": "volatile"}),
            ChatChunk(type="done"),
        ),
    )

    assert events == [{"type": "text", "content": "answer"}, {"type": "done"}]
    assert golden_path.exists()


@pytest.mark.asyncio
async def test_capture_golden_record_does_not_write_failed_stream(tmp_path) -> None:
    golden_path = tmp_path / "failed.json"

    with pytest.raises(RuntimeError, match="stream failed"):
        await capture_golden_record(golden_path, _failing_stream())

    assert not golden_path.exists()


def test_assert_equivalent_reports_all_failed_scenarios() -> None:
    result = DualRunResult(
        scenario="mismatch",
        baseline_events=[{"type": "text", "content": "one"}],
        candidate_events=[{"type": "text", "content": "two"}],
        differences=["event[0] differs"],
    )

    with pytest.raises(AssertionError, match="mismatch"):
        assert_equivalent([result])

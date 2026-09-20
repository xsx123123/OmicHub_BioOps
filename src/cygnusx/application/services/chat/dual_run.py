"""Chat Runtime 新旧路径双跑比较与报告工具。"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator, Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cygnusx.application.services.chat.golden_records import (
    diff_normalized_events,
    load_events,
    normalize_events,
    save_events,
)
from cygnusx.application.services.execution_events import validate_event_sequence
from cygnusx.infrastructure.ai_provider.openai_compatible import ChatChunk

ChatStreamFactory = Callable[[], AsyncIterator[ChatChunk]]


@dataclass(frozen=True)
class DualRunResult:
    """一组相同请求在两条 Runtime 路径上的语义比较结果。"""

    scenario: str
    baseline_events: list[dict[str, Any]]
    candidate_events: list[dict[str, Any]]
    differences: list[str]
    baseline_duration_ms: float = 0.0
    candidate_duration_ms: float = 0.0

    @property
    def equivalent(self) -> bool:
        """两条路径事件序列是否语义等价。"""
        return not self.differences

    def as_dict(self) -> dict[str, Any]:
        """返回适合写入 JSON 报告的稳定结构。"""
        return {
            "scenario": self.scenario,
            "equivalent": self.equivalent,
            "differences": self.differences,
            "baseline_events": self.baseline_events,
            "candidate_events": self.candidate_events,
            "baseline_duration_ms": round(self.baseline_duration_ms, 2),
            "candidate_duration_ms": round(self.candidate_duration_ms, 2),
            "duration_delta_ms": round(self.candidate_duration_ms - self.baseline_duration_ms, 2),
        }


async def collect_events(stream: AsyncIterator[ChatChunk]) -> list[dict[str, Any]]:
    """完整消费并校验 SSE 流，再归一化为可比较事件。"""
    chunks = [chunk async for chunk in stream]
    validate_event_sequence(chunks)
    return normalize_events(chunks)


async def capture_golden_record(
    path: Path, stream: AsyncIterator[ChatChunk]
) -> list[dict[str, Any]]:
    """完整消费 SSE 流后保存稳定基线，避免异常流留下半份记录。"""
    chunks = [chunk async for chunk in stream]
    return save_events(path, chunks)


async def _collect_timed_events(stream: AsyncIterator[ChatChunk]) -> tuple[list[dict[str, Any]], float]:
    started = time.perf_counter()
    events = await collect_events(stream)
    return events, (time.perf_counter() - started) * 1000


async def compare_streams(
    scenario: str,
    baseline_factory: ChatStreamFactory,
    candidate_factory: ChatStreamFactory,
) -> DualRunResult:
    """执行同一场景的两条流，并返回逐事件 diff。"""
    baseline_events, baseline_duration_ms = await _collect_timed_events(baseline_factory())
    candidate_events, candidate_duration_ms = await _collect_timed_events(candidate_factory())
    return DualRunResult(
        scenario=scenario,
        baseline_events=baseline_events,
        candidate_events=candidate_events,
        differences=diff_normalized_events(baseline_events, candidate_events),
        baseline_duration_ms=baseline_duration_ms,
        candidate_duration_ms=candidate_duration_ms,
    )


async def compare_golden_record(
    scenario: str,
    golden_path: Path,
    candidate_factory: ChatStreamFactory,
) -> DualRunResult:
    """将候选 Runtime 流与已落盘的 golden record 比较。"""
    baseline_events = load_events(golden_path)
    candidate_events, candidate_duration_ms = await _collect_timed_events(candidate_factory())
    return DualRunResult(
        scenario=scenario,
        baseline_events=baseline_events,
        candidate_events=candidate_events,
        differences=diff_normalized_events(baseline_events, candidate_events),
        candidate_duration_ms=candidate_duration_ms,
    )


def write_report(path: Path, results: Iterable[DualRunResult]) -> list[dict[str, Any]]:
    """写入稳定 JSON 报告；有差异时保留双方事件以便评审。"""
    report = [result.as_dict() for result in results]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def assert_equivalent(results: Iterable[DualRunResult]) -> None:
    """供 CI 门禁使用：任一场景有差异即抛出聚合错误。"""
    failures = [
        f"{result.scenario}: {'; '.join(result.differences)}"
        for result in results
        if not result.equivalent
    ]
    if failures:
        raise AssertionError("Chat Runtime dual-run differences:\n" + "\n".join(failures))

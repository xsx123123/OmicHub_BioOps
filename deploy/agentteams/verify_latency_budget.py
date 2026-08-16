#!/usr/bin/env python3
"""Verify AgentTeams latency samples against the convergence SLO budget."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

SUPPORTED_METRICS = {
    "event_to_frontend_ms": 3000,
    "approval_accept_ms": 1000,
}


def percentile_95(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def load_measurements(path: Path) -> dict[str, list[float]]:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {metric: [] for metric in SUPPORTED_METRICS}
    if text.startswith("["):
        records = json.loads(text)
    elif text.startswith("{"):
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            records = [json.loads(line) for line in text.splitlines() if line.strip()]
        else:
            records = payload.get("measurements", [])
    else:
        records = [json.loads(line) for line in text.splitlines() if line.strip()]
    measurements = {metric: [] for metric in SUPPORTED_METRICS}
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Each latency measurement must be an object")
        metric = str(record.get("metric") or "")
        if metric not in measurements:
            raise ValueError(f"Unsupported latency metric: {metric or '<missing>'}")
        duration_ms = float(record.get("duration_ms"))
        if duration_ms < 0:
            raise ValueError("Latency duration_ms must be non-negative")
        measurements[metric].append(duration_ms)
    return measurements


def verify_latency_budget(
    measurements: dict[str, list[float]],
    *,
    min_samples: int,
    thresholds: dict[str, int] | None = None,
) -> dict[str, Any]:
    budgets = thresholds or SUPPORTED_METRICS
    metrics: dict[str, dict[str, Any]] = {}
    for metric, threshold_ms in budgets.items():
        values = measurements.get(metric, [])
        p95_ms = percentile_95(values)
        enough_samples = len(values) >= min_samples
        metrics[metric] = {
            "sample_count": len(values),
            "p95_ms": p95_ms,
            "threshold_ms": threshold_ms,
            "passed": enough_samples and p95_ms <= threshold_ms,
            "failure": None
            if enough_samples
            else f"requires at least {min_samples} samples",
        }
    return {
        "passed": all(result["passed"] for result in metrics.values()),
        "metrics": metrics,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check real AgentTeams event and approval latency samples against P95 SLOs."
    )
    parser.add_argument("input", type=Path, help="JSON or JSONL latency measurement file")
    parser.add_argument("--min-samples", type=int, default=20)
    parser.add_argument("--event-threshold-ms", type=int, default=3000)
    parser.add_argument("--approval-threshold-ms", type=int, default=1000)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.min_samples < 1:
        raise SystemExit("--min-samples must be at least 1")
    measurements = load_measurements(args.input)
    report = verify_latency_budget(
        measurements,
        min_samples=args.min_samples,
        thresholds={
            "event_to_frontend_ms": args.event_threshold_ms,
            "approval_accept_ms": args.approval_threshold_ms,
        },
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

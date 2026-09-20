#!/usr/bin/env python3
"""Offline, reproducible toolbox selection evaluation."""

from __future__ import annotations

import argparse
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import yaml
from cygnusx.tools.schema_loader import ToolsSchemaLoader


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cases", default="tool_configs/evals/tool_selection_cases.yaml")
    parser.add_argument("--schema", default="tool_configs/tools_schema.yaml")
    parser.add_argument("--report", default="tool_configs/evals/tool_selection_report.md")
    parser.add_argument("--mode", choices=["full", "retrieval"], default="full")
    args = parser.parse_args()
    cases = yaml.safe_load(Path(args.cases).read_text(encoding="utf-8"))["cases"]
    loader = ToolsSchemaLoader(args.schema)
    loader.get_config().tool_selection["mode"] = args.mode
    correct = 0
    details: list[str] = []
    for item in cases:
        expected = item["expected_tool"]
        if args.mode == "retrieval":
            candidates, _ = loader.select_tools(item["query"])
        else:
            candidates = loader.search_tools(item["query"], limit=1)
        actual = candidates[0].name if candidates else None
        matched = (
            expected is None
            and actual is None
            or actual in {expected, *item["acceptable_alternatives"]}
        )
        correct += int(matched)
        print(f"{'PASS' if matched else 'FAIL'}\t{actual or '-'}\t{item['query']}")
        details.append(
            f"| {'PASS' if matched else 'FAIL'} | {item['query']} | {expected or '-'} | {actual or '-'} |"
        )
    accuracy = correct / len(cases)
    print(f"top1_accuracy={accuracy:.2%} ({correct}/{len(cases)})")
    revision = subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()
    report = "\n".join(
        [
            "# 工具选择离线评测报告",
            "",
            f"- 执行时间：{datetime.now(UTC).isoformat()}",
            f"- 代码版本：`{revision}`",
            f"- 评测模式：确定性词法召回（{args.mode} schema injection）",
            f"- Top-1 命中率：**{accuracy:.2%}**（{correct}/{len(cases)}）",
            "",
            "| 结果 | Query | 期望工具 | Top-1 |",
            "|---|---|---|---|",
            *details,
            "",
        ]
    )
    Path(args.report).write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

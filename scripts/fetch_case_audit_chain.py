#!/usr/bin/env python3
"""按 case_id 一条命令拉取 AgentTeams 全量业务事件链（统一审计总线取证工具）。

聚合 Case 事件流 + 房间命名空间事件流（立项确认卡/立项前澄清），按
recorded_at 排序输出统一结构（含 correlation 关联字段与断链清单），
与 GET /api/v1/agentteams/cases/{case_id}/audit-chain 同一份服务逻辑
（运维态入口，manager 身份直连 Bridge，无 requester 校验）。

用法：
    uv run python scripts/fetch_case_audit_chain.py --case-id <case_id>
    uv run python scripts/fetch_case_audit_chain.py --case-id <case_id> --format table
    uv run python scripts/fetch_case_audit_chain.py --case-id <case_id> --output chain.jsonl

环境：
    需要能访问 OmicHub 数据库以读取 Bridge 运行时配置（URL 与 manager token）
    及房间-Case 绑定关系。
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from omichub.application.services.agentteams_audit_chain_service import (
    AgentTeamsAuditChainService,
)
from omichub.application.services.agentteams_bridge_settings_service import (
    AgentTeamsBridgeSettingsService,
)
from omichub.application.services.agentteams_service import AgentTeamsService
from omichub.core.config import get_settings
from omichub.infrastructure.database.session import close_db, get_session_factory


def _render_table(chain: dict[str, Any]) -> str:
    lines = [
        f"case_id={chain['case_id']} room_id={chain.get('room_id') or '-'} "
        f"events={chain['event_count']} broken_links={chain['broken_link_count']}"
    ]
    header = f"{'recorded_at':<25} {'source':<5} {'event_type':<36} {'actor':<18} links"
    lines.append(header)
    lines.append("-" * len(header))
    for event in chain["events"]:
        correlation = event.get("correlation") or {}
        link_bits = [
            f"{key.split('_')[0]}->{value[:8]}" for key, value in sorted(correlation.items())
        ]
        lines.append(
            f"{event['recorded_at'][:25]:<25} {event['source']:<5} "
            f"{event['event_type'][:36]:<36} {event['actor'][:18]:<18} {' '.join(link_bits)}"
        )
    if chain["broken_links"]:
        lines.append("")
        lines.append("断链（关联目标不在本链内）:")
        for link in chain["broken_links"]:
            lines.append(
                f"  {link['event_id'][:8]} {link['field']} -> {link['target_event_id'][:8]}"
            )
    return "\n".join(lines)


async def main() -> int:
    parser = argparse.ArgumentParser(description="拉取 AgentTeams Case 全量业务事件链")
    parser.add_argument("--case-id", required=True, help="Case ID")
    parser.add_argument(
        "--format",
        choices=["jsonl", "table"],
        default="jsonl",
        help="输出格式（默认 jsonl；table 为终端可读表格）",
    )
    parser.add_argument("--output", type=Path, default=None, help="写入文件（默认 stdout）")
    parser.add_argument(
        "--max-events", type=int, default=5000, help="单链最多拉取事件数（默认 5000）"
    )
    args = parser.parse_args()

    async with get_session_factory()() as db:
        try:
            settings = get_settings()
            bridge_config = await AgentTeamsBridgeSettingsService(db, settings).get_runtime_config()
            service = AgentTeamsService(settings, bridge_config)
            if not service.available:
                print("AgentTeams Bridge 未配置或已禁用", file=sys.stderr)
                return 1
            chain = await AgentTeamsAuditChainService(
                db, agentteams=service
            ).get_case_audit_chain_ops(args.case_id, max_events=args.max_events)
        finally:
            await close_db()

    if args.format == "table":
        text = _render_table(chain) + "\n"
    else:
        text = "".join(
            json.dumps(event, ensure_ascii=False, default=str) + "\n" for event in chain["events"]
        )
        summary: dict[str, Any] = {
            key: chain[key]
            for key in ("case_id", "room_id", "event_count", "broken_link_count", "broken_links", "generated_at")
        }
        text += json.dumps({"_summary": summary}, ensure_ascii=False, default=str) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
        print(f"事件链已写入: {args.output}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

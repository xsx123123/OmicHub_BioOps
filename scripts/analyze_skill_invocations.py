#!/usr/bin/env python3
"""Skill 调用遥测分析器。

读取 `skill_invocations` 表，输出高频 Skill 调用榜单和潜在的"Skill 化机会"：

1. 高频已挂载 Skill：调用次数高说明该能力值得更广泛应用或拆分为更专精的子 Skill；
2. 未命中 Skill 的会话：在同一会话中没有 `use_skill` 调用的用户消息，按关键词分组，
   识别可能被重复处理但未沉淀为 Skill 的意图。

用法：
    DATABASE_URL='postgresql+asyncpg://...' \
      uv run python scripts/analyze_skill_invocations.py --days 30 --top 10

输出示例：
    {
      "window_days": 30,
      "top_skills": [
        {"skill_id": "scrna-recluster", "total": 45, "last_invoked_at": "...", "proposal": "考虑拆分为亚群重聚类 vs 全局重聚类两个子 Skill"}
      ],
      "unhit_intent_groups": [
        {"markers": ["h5ad", "rds", "转换"], "session_count": 12, "sample_message": "...", "proposal_skill_id": "h5ad-rds-convert"}
      ]
    }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from omichub.application.services.domain_registry import normalize_marker
from omichub.infrastructure.database.models.chat import ChatMessageModel
from omichub.infrastructure.database.models.skill import SkillInvocationModel
from omichub.infrastructure.database.session import get_session_factory

# 常见停用词，避免分组被虚词主导
_STOPWORDS = {
    "的", "了", "和", "与", "或", "在", "是", "我", "请", "帮我", "给我", "需要",
    "想要", "可以", "一下", "一个", "看看", "一下", "运行", "执行", "生成", "得到",
    "怎么", "如何", "什么", "吗", "呢", "吧", "了", "有", "没有", "能", "不能",
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are",
}

# 至少出现这么多次才被视为"高频"
_HOT_THRESHOLD = 5


def _extract_markers(text: str) -> list[str]:
    """从用户消息中提取可用于分组的语义标记。

    策略：
    - 英文/数字视为一个词（如 h5ad, rds, csv）；
    - 连续中文字符按 2-gram 切分，保留常见短词；
    - 过滤停用词和单字。
    """
    normalized = normalize_marker(text)
    markers: list[str] = []
    # 英文/数字词
    markers.extend(re.findall(r"[a-z0-9]{2,}", normalized))
    # 中文 2-gram
    for seq in re.findall(r"[\u4e00-\u9fff]{2,}", normalized):
        for i in range(len(seq) - 1):
            bigram = seq[i : i + 2]
            if bigram not in _STOPWORDS:
                markers.append(bigram)
    return [m for m in markers if m not in _STOPWORDS and len(m) > 1]


def _group_unhit_messages(messages: list[str], min_sessions: int = 3) -> list[dict[str, Any]]:
    """对未命中 Skill 的用户消息做简单关键词共现分组。"""
    # 每条消息 → markers
    message_markers = [
        (msg, set(_extract_markers(msg)))
        for msg in messages
        if msg.strip()
    ]

    # 以出现频率最高的 30 个 marker 为种子，把包含该种子的消息归为一组
    all_markers: Counter[str] = Counter()
    for _, markers in message_markers:
        all_markers.update(markers)

    seed_markers = [m for m, _ in all_markers.most_common(30)]
    groups: dict[str, list[tuple[str, set[str]]]] = defaultdict(list)
    assigned: set[int] = set()

    for seed in seed_markers:
        for idx, (msg, markers) in enumerate(message_markers):
            if idx in assigned:
                continue
            if seed in markers:
                groups[seed].append((msg, markers))
                assigned.add(idx)

    results = []
    for seed, items in groups.items():
        if len(items) < min_sessions:
            continue
        # 取组内共同出现的其他高频 marker 作为组标签
        common = Counter()
        for _, markers in items:
            common.update(markers)
        group_markers = [m for m, c in common.most_common(5) if c >= len(items) * 0.5 and m != seed]
        label = [seed, *group_markers]
        sample = min(items, key=lambda x: len(x[0]))[0][:120]
        results.append({
            "markers": label,
            "session_count": len(items),
            "sample_message": sample,
            "proposal_skill_id": f"{seed}-workflow",
        })

    # 按会话数排序
    results.sort(key=lambda x: x["session_count"], reverse=True)
    return results[:10]


def _build_proposal(skill_id: str, total: int) -> str:
    """基于 Skill ID 和调用次数给出一个可读的后续建议。"""
    if total >= 50:
        return f"调用量高（{total} 次），建议评估是否拆分为更专精的子 Skill 或挂载到更多 Agent"
    if total >= _HOT_THRESHOLD:
        return f"调用较频繁（{total} 次），建议确认该 Skill 的挂载 Agent 是否最优、触发词是否足够清晰"
    return "调用量较低，暂不建议单独投入"


async def analyze(window_days: int, top_n: int) -> dict[str, Any]:
    since = datetime.now(timezone.utc) - timedelta(days=window_days)

    async with get_session_factory()() as db:
        # 1. 时间窗口内的 Skill 调用聚合
        agg_result = await db.execute(
            select(
                SkillInvocationModel.skill_id,
                SkillInvocationModel.skill_name,
                func.count(SkillInvocationModel.id),
                func.max(SkillInvocationModel.created_at),
            )
            .where(SkillInvocationModel.created_at >= since)
            .group_by(SkillInvocationModel.skill_id, SkillInvocationModel.skill_name)
            .order_by(func.count(SkillInvocationModel.id).desc())
        )
        agg_rows = agg_result.all()

        # 2. 未命中 Skill 的会话：取窗口内有消息但没有 skill_invocations 的 session
        # 简化策略：先取所有有 skill invocation 的 session_id；再取这些 session 外的用户消息
        invoked_sessions_result = await db.execute(
            select(SkillInvocationModel.session_id)
            .where(
                SkillInvocationModel.created_at >= since,
                SkillInvocationModel.session_id.isnot(None),
            )
            .distinct()
        )
        invoked_session_ids = {row[0] for row in invoked_sessions_result.all() if row[0]}

        unhit_messages: list[str] = []
        if invoked_session_ids:
            # 为避免全表扫描，只查最近 N 天的用户消息；PG 复合索引通常存在
            msg_result = await db.execute(
                select(ChatMessageModel.content)
                .where(
                    ChatMessageModel.created_at >= since,
                    ChatMessageModel.role == "user",
                    ChatMessageModel.session_id.notin_(invoked_session_ids),
                )
                .limit(5000)
            )
            unhit_messages = [row[0] for row in msg_result.all() if row[0]]
        else:
            msg_result = await db.execute(
                select(ChatMessageModel.content)
                .where(
                    ChatMessageModel.created_at >= since,
                    ChatMessageModel.role == "user",
                )
                .limit(5000)
            )
            unhit_messages = [row[0] for row in msg_result.all() if row[0]]

    top_skills = [
        {
            "skill_id": sid,
            "skill_name": sname,
            "total": int(cnt),
            "last_invoked_at": last.isoformat() if last else None,
            "proposal": _build_proposal(sid, int(cnt)),
        }
        for sid, sname, cnt, last in agg_rows[:top_n]
        if int(cnt) >= _HOT_THRESHOLD
    ]

    unhit_groups = _group_unhit_messages(unhit_messages)

    return {
        "window_days": window_days,
        "hot_threshold": _HOT_THRESHOLD,
        "top_skills": top_skills,
        "unhit_intent_groups": unhit_groups,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="分析 Skill 调用遥测，发现高频复用机会")
    parser.add_argument("--days", type=int, default=30, help="分析最近 N 天")
    parser.add_argument("--top", type=int, default=10, help="Top N 高频 Skill")
    parser.add_argument("--output", type=str, default="", help="输出 JSON 文件路径，默认 stdout")
    args = parser.parse_args()

    result = asyncio.run(analyze(args.days, args.top))
    payload = json.dumps(result, ensure_ascii=False, indent=2)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(payload)
        print(f"报告已写入 {args.output}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

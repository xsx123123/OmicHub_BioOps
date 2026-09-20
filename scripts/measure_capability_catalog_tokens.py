"""F5 渐进暴露能力目录：派单/转交上下文 token 量测量脚本。

口径：tiktoken cl100k_base；统计对象为实际注入 LLM prompt 的目录 JSON 文本：
1. chat 路由目录（chat_service 路由 prompt 的 {catalog} 占位，逐候选注入）；
2. handoff 转交目录（agent_service._build_handoff_catalog 注入专家系统 prompt）。

用法：
    .venv/bin/python scripts/measure_capability_catalog_tokens.py           # 全量(detail)注入口径
    .venv/bin/python scripts/measure_capability_catalog_tokens.py --summary # summary 分层口径
"""

from __future__ import annotations

import argparse
import json
import sys

import tiktoken
from cygnusx.application.services.agentteams_capability_registry import (
    AgentTeamsCapabilityRegistry,
)
from cygnusx.application.services.chat_service import (
    ROUTER_CATALOG_SUMMARY_KEYS,
    ROUTER_SYSTEM_PROMPT,
)

# 与 chat_service 路由 prompt 注入的键集合一一对应。
_ROUTER_FULL_KEYS = (
    "agent_id",
    "name",
    "description",
    "category",
    "chat_entry",
    "capabilities",
    "not_suitable_for",
    "handoff_when",
    "preferred_inputs",
    "routing_hints",
    "capability_tags",
    "routing_notes",
)
# F5 summary 层键集合直接引用 chat_service.ROUTER_CATALOG_SUMMARY_KEYS，防漂移。
_ROUTER_SUMMARY_KEYS = ROUTER_CATALOG_SUMMARY_KEYS

# 与 agent_service._build_handoff_catalog 注入的键集合一一对应。
_HANDOFF_FULL_KEYS = (
    "agent_id",
    "name",
    "description",
    "category",
    "chat_entry",
    "capabilities",
    "not_suitable_for",
    "handoff_when",
    "preferred_inputs",
)
_HANDOFF_SUMMARY_KEYS = ("agent_id", "name", "description", "category", "chat_entry")


def _tokens(text: str) -> int:
    return len(tiktoken.get_encoding("cl100k_base").encode(text))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--summary",
        action="store_true",
        help="按 F5 summary 分层口径渲染（默认按改造前全量 detail 口径）",
    )
    args = parser.parse_args()

    registry = AgentTeamsCapabilityRegistry()
    snapshot = registry.snapshot()
    candidates = list(snapshot.get("chat_router_catalog") or [])
    router_keys = _ROUTER_SUMMARY_KEYS if args.summary else _ROUTER_FULL_KEYS
    router_catalog = json.dumps(
        [{key: entry.get(key) for key in router_keys} for entry in candidates],
        ensure_ascii=False,
    )

    handoff_keys = _HANDOFF_SUMMARY_KEYS if args.summary else _HANDOFF_FULL_KEYS
    handoff_catalog = json.dumps(
        [{key: entry.get(key) for key in handoff_keys} for entry in candidates],
        ensure_ascii=False,
    )

    # P2-11：完整预算审计 —— ROUTER_SYSTEM_PROMPT 模板与 flow 目录也计入。
    # 与 chat_service 实际注入方式一致：模板 .replace("{catalog}", ...).replace("{flow_catalog}", ...)。
    flow_catalog = json.dumps(
        snapshot.get("flow_router_catalog") or [],
        ensure_ascii=False,
    )
    router_prompt = ROUTER_SYSTEM_PROMPT.replace("{catalog}", router_catalog).replace(
        "{flow_catalog}", flow_catalog
    )
    router_template = ROUTER_SYSTEM_PROMPT.replace("{catalog}", "").replace(
        "{flow_catalog}", ""
    )

    mode = "summary 分层" if args.summary else "全量 detail"
    print(f"口径: {mode} | tokenizer: tiktoken cl100k_base | 候选数: {len(candidates)}")
    print(f"router 模板:   {_tokens(router_template):>6} tokens ({len(router_template)} chars)")
    print(f"router 目录:   {_tokens(router_catalog):>6} tokens ({len(router_catalog)} chars)")
    print(f"flow 目录:     {_tokens(flow_catalog):>6} tokens ({len(flow_catalog)} chars)")
    print(f"router 完整 system prompt: {_tokens(router_prompt):>6} tokens")
    print(f"handoff 目录:  {_tokens(handoff_catalog):>6} tokens ({len(handoff_catalog)} chars)")
    print(f"合计:          {_tokens(router_catalog) + _tokens(handoff_catalog):>6} tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Run 20 real Router classifications without requiring the application web server.

The script calls the same Router model and prompt used by ``ChatService``. It prints
the raw JSON decision and the final validated Agent ID; it never prints API keys.
Run from the repository root in an environment with ``DP_API_KEY`` (or pass another
OpenAI-compatible provider through the environment before importing this module).
"""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import uuid
from typing import Any

if sys.version_info < (3, 11):
    raise SystemExit(
        "该脚本需要 Python >= 3.11；当前版本为 "
        f"{sys.version_info.major}.{sys.version_info.minor}。"
        "请使用 .venv/bin/python scripts/evaluate_router_20.py。"
    )

if importlib.util.find_spec("pydantic_settings") is None:
    raise SystemExit(
        "当前 Python 环境缺少项目依赖 pydantic-settings；"
        "请先执行 source .venv/bin/activate，再运行本脚本。"
    )

sys.path.insert(0, "src")

from cygnusx.application.services.agentteams_capability_registry import (  # noqa: E402
    get_agentteams_capability_registry,
)
from cygnusx.application.services.chat.utils import _extract_route_json  # noqa: E402
from cygnusx.application.services.chat_service import (  # noqa: E402
    ROUTER_MAX_TOKENS,
    ROUTER_SYSTEM_PROMPT,
)
from cygnusx.application.services.unified_intent_router import normalize_decision  # noqa: E402
from cygnusx.infrastructure.ai_provider.openai_compatible import (  # noqa: E402
    OpenAICompatibleProvider,
)
from cygnusx.infrastructure.database.models.ai_provider import (  # noqa: E402
    AIProviderConfigModel,
)


CASES: list[tuple[str, str]] = [
    ("@inbox/raw-data/integration_harmony.qs 帮我可视化细胞注释结果，并展示特定亚群的 top 基因", "agent-scrna"),
    ("这个 h5ad 对象需要做 QC、双细胞检测和聚类", "agent-scrna"),
    ("基于已聚类的 Seurat 对象验证 T 细胞 marker 并做细胞类型注释", "agent-scrna-advanced"),
    ("Harmony 整合后 UMAP 仍有明显批次效应，请复核聚类稳定性", "agent-scrna-integration"),
    ("请检查 Cell Ranger web_summary.html 和 barcode rank 的上游质量", "agent-scrna-upstream"),
    ("6 个样本的 bulk RNA-seq 做差异表达分析", "agent-rnaseq"),
    ("比较 bulk RNA 两组并做 GO/KEGG 富集", "agent-rnaseq"),
    ("ATAC-seq 数据做 peak calling、差异可及性和 motif 分析", "agent-atacseq"),
    ("根据差异表达 CSV 画火山图和热图，要求出版级配色", "agent-viz"),
    ("把这张已有图片的字体、配色和版式美化到投稿标准", "agent-viz"),
    ("把 integration_harmony.qs 转成 h5ad，并保留细胞注释", "agent-scrna"),
    ("请调试这段 Scanpy Python 脚本的 KeyError", "agent-code"),
    ("构建一个 MCP Server，把这个内部 API 注册成工具", "agent-mcp-builder"),
    ("解释 TAM 与 T 细胞通讯结果，并设计拟时序验证", "agent-scrna-advanced"),
    ("检索 TP53 肺癌免疫耐受的近期文献并整理证据", "agent-general"),
    ("检查当前 Slurm 集群容量和任务排队异常", "agent-cloud-ops"),
    ("你好，介绍一下你能做什么", "agent-general"),
    ("帮我设计一个 RNA-seq 样本分组和统计分析方案", "agent-rnaseq"),
    ("单细胞对象中的某个 cluster 想看 marker、DotPlot 和通路", "agent-scrna-advanced"),
    ("我有一棵 Newick 系统发育树，帮我做可视化排版", "agent-viz"),
]


def _provider_config() -> AIProviderConfigModel:
    key = os.environ.get("DP_API_KEY", "")
    if not key:
        raise RuntimeError("DP_API_KEY 未设置，无法进行真实 Router LLM 测试")
    return AIProviderConfigModel(
        id=uuid.uuid4(),
        name="deepseek-v4-flash",
        provider_type="openai_compatible",
        model="deepseek-v4-flash",
        base_url="https://api.deepseek.com",
        api_key=key,
        temperature=0,
        max_tokens=ROUTER_MAX_TOKENS,
        top_p=1.0,
        timeout=30,
        is_active=True,
        is_default=False,
        extra_params={},
    )


async def classify(provider: OpenAICompatibleProvider, prompt: str, text: str) -> dict[str, Any]:
    raw = ""
    async for chunk in provider.chat_stream(
        messages=[{"role": "user", "content": text}],
        system_prompt=prompt,
        temperature=0,
        max_tokens=ROUTER_MAX_TOKENS,
        tools=None,
        deep_thinking=False,
    ):
        if chunk.type == "text" and not chunk.metadata.get("is_reasoning"):
            raw += chunk.content
    decision = _extract_route_json(raw) or {}
    return {"raw": raw.strip(), "decision": decision}


async def main() -> None:
    registry = get_agentteams_capability_registry()
    snapshot = registry.snapshot()
    prompt = ROUTER_SYSTEM_PROMPT.replace(
        "{catalog}", json.dumps(snapshot["chat_router_catalog"], ensure_ascii=False)
    ).replace("{flow_catalog}", json.dumps(snapshot["flow_router_catalog"], ensure_ascii=False))
    valid_ids = {str(item["agent_id"]) for item in snapshot["chat_router_catalog"]}
    fallback = "agent-general" if "agent-general" in valid_ids else sorted(valid_ids)[0]
    provider = OpenAICompatibleProvider(_provider_config())

    for index, (question, expected) in enumerate(CASES, 1):
        try:
            result = await classify(provider, prompt, question)
            normalized = normalize_decision(
                result["decision"], fallback_agent_id=fallback, valid_agent_ids=valid_ids
            )
            print(json.dumps({
                "case": index,
                "question": question,
                "expected_agent": expected,
                "model_agent": result["decision"].get("agent_id"),
                "final_agent": normalized.target_agent_id,
                "intent": normalized.intent,
                "confidence": normalized.confidence,
                "reason": normalized.reason,
                "raw": result["raw"],
            }, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({
                "case": index,
                "question": question,
                "expected_agent": expected,
                "error": f"{type(exc).__name__}: {str(exc)[:300]}",
            }, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

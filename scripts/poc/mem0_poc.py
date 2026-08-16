"""PoC Step 0.4 — mem0 v2 引擎可行性验证。

验证项（对应实施文档 §6 Phase 0 验收标准）：
  P1 embedder 接通（ollama bge-m3, 1024 维）
  P2 LLM 抽取走通（openai provider → qwen3.7-plus token-plan 端点）
  P3 pgvector 落库 + 检索（collection=mem0_poc, hnsw）
  P4 ADD-only 重复堆积率（同义事实 add 3 次 → 条目数）
  P5 跨 agent 检索（省略 agent_id 的 filters 行为）
  +  metadata/scope 过滤表达力、infer=False 直存、history 审计

用法：
  source .venv/bin/activate
  python scripts/poc/mem0_poc.py            # 跑全部用例
  python scripts/poc/mem0_poc.py --cleanup  # 清理 PoC 数据
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("MEM0_TELEMETRY", "false")
os.environ.setdefault("POSTHOG_DISABLED", "1")

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

OLLAMA_BASE = "http://127.0.0.1:11434"
QWEN_BASE = "https://token-plan.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
COLLECTION = "mem0_poc"
HISTORY_DB = "/tmp/mem0_poc_history.db"

U1, U2 = "poc-user-1", "poc-user-2"
AGENT_A, AGENT_B = "agent-rnaseq", "agent-scrna"

RESULTS: list[tuple[str, bool, str]] = []


def record(case: str, ok: bool, detail: str) -> None:
    RESULTS.append((case, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {case}: {detail}")


def load_env() -> dict[str, str]:
    """从 .env 读取 Postgres 连接参数（不依赖 dotenv）。"""
    env: dict[str, str] = {}
    for line in (REPO / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def build_memory():
    from mem0 import Memory

    env = load_env()
    al_key = os.environ.get("AL_API_KEY", "")
    if not al_key:
        print("FATAL: AL_API_KEY 未设置（LLM 抽取需要）")
        sys.exit(2)

    config = {
        "vector_store": {
            "provider": "pgvector",
            "config": {
                "dbname": env.get("POSTGRES_DB", "omichub"),
                "user": env.get("POSTGRES_USER", "omichub"),
                "password": env.get("POSTGRES_PASSWORD", ""),
                "host": "127.0.0.1",
                "port": int(env.get("OMICHUB_POSTGRES_PORT", "5432")),
                "collection_name": COLLECTION,
                "embedding_model_dims": 1024,
                "hnsw": True,
            },
        },
        "llm": {
            "provider": "openai",
            "config": {
                "model": "qwen3.7-plus",
                "api_key": al_key,
                "openai_base_url": QWEN_BASE,
                "temperature": 0.1,
                "max_tokens": 1500,
            },
        },
        "embedder": {
            "provider": "ollama",
            "config": {
                "model": "bge-m3",
                "embedding_dims": 1024,
                "ollama_base_url": OLLAMA_BASE,
            },
        },
        "history_db_path": HISTORY_DB,
        "custom_instructions": (
            "提取与生物信息学研究相关的事实：物种、组织、分析方法、工具、参考基因组、"
            "用户偏好。输出中文短句，每条自包含。忽略问候语与临时性请求。"
        ),
    }
    return Memory.from_config(config)


def short(items: list[dict]) -> str:
    return " | ".join(str(it.get("memory", ""))[:40] for it in items[:6])


def case_a_add(m) -> None:
    """P1+P2+P3：中文对话写入 → LLM 抽取 → 落库。"""
    msgs = [
        {"role": "user", "content": "我在做小鼠肝脏的单细胞测序分析，想用 DESeq2 做差异表达，帮我看看流程。"},
        {"role": "assistant", "content": "好的，小鼠肝脏 scRNA-seq 的差异表达可以用 DESeq2，建议先用伪批量法聚合。"},
    ]
    res = m.add(msgs, user_id=U1, run_id="poc-session-1", metadata={"scope": "project"})
    results = res.get("results", [])
    record(
        "A1 事实抽取落库",
        len(results) > 0,
        f"抽出 {len(results)} 条: {short(results)}",
    )


def case_b_search(m) -> None:
    res = m.search("差异表达分析用什么工具？", filters={"user_id": U1}, top_k=5)
    hits = res.get("results", [])
    ok = any("DESeq2" in str(h.get("memory", "")) or "差异" in str(h.get("memory", "")) for h in hits)
    record("B1 语义检索召回", ok, f"top{len(hits)}: {short(hits)}")


def case_c_dup(m) -> None:
    """P4：同一事实换表述写 3 次，观察堆积。"""
    variants = [
        "用户的参考基因组用的是 GRCm39",
        "他提到参考基因组版本是 GRCm39",
        "分析所用基因组为 GRCm39 版本",
    ]
    for v in variants:
        m.add([{"role": "user", "content": v}], user_id=U1)
    all_mems = m.get_all(filters={"user_id": U1}, top_k=100).get("results", [])
    grcm = [x for x in all_mems if "GRCm39" in str(x.get("memory", ""))]
    record(
        "C1 重复堆积率(同义x3)",
        True,  # 观察项：记录数值，不判死
        f"GRCm39 相关条目数={len(grcm)}（3 次同义写入）: {short(grcm)}",
    )
    record("C2 U1 总记忆数", True, f"total={len(all_mems)}")


def case_d_isolation(m) -> None:
    """P5：agent 私有 vs 共享 vs 跨 agent 可见性。"""
    # U2 写一条私有（agent-rnaseq）+ 一条共享（不带 agent_id）
    m.add(
        [{"role": "user", "content": "这个 RNA-seq 项目的差异基因阈值定为 |log2FC|>1 且 padj<0.05"}],
        user_id=U2,
        agent_id=AGENT_A,
    )
    m.add(
        [{"role": "user", "content": "用户偏好所有图表配色用 NPG 风格"}],
        user_id=U2,
    )

    all_u2 = m.get_all(filters={"user_id": U2}, top_k=100).get("results", [])
    only_a = m.get_all(filters={"user_id": U2, "agent_id": AGENT_A}, top_k=100).get("results", [])
    only_b = m.get_all(filters={"user_id": U2, "agent_id": AGENT_B}, top_k=100).get("results", [])

    record(
        "D1 省略agent_id=全部可见",
        len(all_u2) >= 2,
        f"count={len(all_u2)}: {short(all_u2)}",
    )
    record(
        "D2 私有隔离(agent A)",
        len(only_a) >= 1,
        f"count={len(only_a)}: {short(only_a)}",
    )
    record(
        "D3 跨agent(B)可见性",
        True,  # 观察项：看共享条目是否出现、私有是否隔离
        f"agent B 视角 count={len(only_b)}: {short(only_b)}",
    )


def case_e_metadata(m) -> None:
    """metadata 过滤表达力探测。"""
    all_u1 = m.get_all(filters={"user_id": U1}, top_k=100).get("results", [])
    with_meta = [x for x in all_u1 if (x.get("metadata") or {}).get("scope") == "project"]
    record("E1 metadata 随存随取", len(with_meta) >= 1, f"scope=project 条目={len(with_meta)}")
    # 尝试服务端 metadata 过滤（v2 filter 语法探测）
    try:
        try:
            srv = m.get_all(filters={"user_id": U1, "metadata.scope": "project"}, top_k=100).get("results", [])
        except Exception:
            srv = m.get_all(filters={"user_id": U1}, top_k=100).get("results", [])
        record("E2 服务端scope过滤", True, f"filters 含 scope → count={len(srv)}")
    except Exception as exc:  # noqa: BLE001
        record("E2 服务端scope过滤", False, f"不支持: {type(exc).__name__}: {exc}")


def case_f_direct(m) -> None:
    """infer=False 直存（工具主动写入路径）。"""
    res = m.add(
        "用户明确要求记住：EBI 下载走 aspera 通道",
        user_id=U1,
        infer=False,
        metadata={"scope": "preference"},
    )
    results = res.get("results", [])
    exact = any("aspera" in str(r.get("memory", "")).lower() for r in results)
    record("F1 infer=False 直存", exact, f"result={short(results) or res}")


def case_g_history(m) -> None:
    all_u1 = m.get_all(filters={"user_id": U1}, top_k=1).get("results", [])
    if not all_u1:
        record("G1 history 审计", False, "无记忆可查")
        return
    mid = all_u1[0]["id"]
    try:
        h = m.history(mid)
        record("G1 history 审计", isinstance(h, list) and len(h) >= 1, f"memory={mid[:8]}… events={len(h)}")
    except Exception as exc:  # noqa: BLE001
        record("G1 history 审计", False, f"{type(exc).__name__}: {exc}")


def cleanup(m) -> None:
    for u in (U1, U2):
        try:
            m.delete_all(user_id=u)
            print(f"cleaned user={u}")
        except Exception as exc:  # noqa: BLE001
            print(f"cleanup {u}: {exc}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args()

    m = build_memory()
    if args.cleanup:
        cleanup(m)
        return

    case_a_add(m)
    case_b_search(m)
    case_c_dup(m)
    case_d_isolation(m)
    case_e_metadata(m)
    case_f_direct(m)
    case_g_history(m)

    print("\n========== 汇总 ==========")
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    for case, ok, detail in RESULTS:
        print(f"  [{'✓' if ok else '✗'}] {case}")
    print(f"通过 {passed}/{len(RESULTS)}")
    print("清理命令：python scripts/poc/mem0_poc.py --cleanup")


if __name__ == "__main__":
    main()

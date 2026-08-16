"""适配层运行时冒烟：mem0_engine_enabled=true 下 AgentMemoryService 全链路。

覆盖：save(直存+查重) / search / list / build_prompt_context(L1+L2) /
update / forget / 跨agent可见性 / clear_memories。

用法：
  source .venv/bin/activate
  python scripts/poc/mem0_adapter_smoke.py
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (REPO / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


_dotenv = load_env()
_pg_user = _dotenv.get("POSTGRES_USER", "omichub")
_pg_pass = _dotenv.get("POSTGRES_PASSWORD", "")
_pg_db = _dotenv.get("POSTGRES_DB", "omichub")

os.environ["DATABASE_URL"] = f"postgresql+asyncpg://{_pg_user}:{_pg_pass}@127.0.0.1:5432/{_pg_db}"
os.environ["MEM0_ENGINE_ENABLED"] = "true"
os.environ["MEM0_COLLECTION"] = "mem0_smoke"
os.environ["MEM0_HISTORY_DIR"] = "/tmp/omichub-mem0-smoke"
os.environ.setdefault("MEM0_TELEMETRY", "false")

USER = "smoke-user-1"
AGENT_A = "agent-rnaseq"
AGENT_B = "agent-scrna"

PASS: list[str] = []
FAIL: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"[{'PASS' if ok else 'FAIL'}] {name} {detail}")


async def main() -> None:
    from omichub.application.services.agent_memory_service import AgentMemoryService
    from omichub.infrastructure.memory.mem0_engine import get_mem0_engine

    svc = AgentMemoryService(None)  # mem0 路径不使用 db session

    # 前置清理
    engine = await get_mem0_engine()
    await engine.delete_all(USER)

    # 1. 工具写入（project 私有，agent A）
    r1 = await svc.save_memory(
        user_id=USER, content="差异表达分析使用 DESeq2，阈值 padj<0.05",
        scope="project", keywords=["deseq2", "差异表达"], agent_id=AGENT_A,
    )
    mid_project = r1["memory"]["id"]
    check("save project 私有", r1["action"] == "created" and mid_project, f"action={r1['action']}")

    # 2. 同义重写 → 查重命中转 update
    r2 = await svc.save_memory(
        user_id=USER, content="差异表达分析用 DESeq2，显著性阈值设为 padj<0.05",
        scope="project", keywords=["deseq2"], agent_id=AGENT_A,
    )
    check("save 同义查重→update", r2["action"] == "updated", f"action={r2['action']}")

    # 3. preference 共享（agent_id=None）
    r3 = await svc.save_memory(
        user_id=USER, content="图表配色偏好 NPG 风格", scope="preference",
        keywords=["配色"], agent_id=None,
    )
    check("save preference 共享", r3["action"] == "created")

    # 4. search：agent A 视角能看到私有+共享
    s1 = await svc.search_memory(user_id=USER, query="差异表达用什么工具", agent_id=AGENT_A)
    check("search agentA 召回私有", s1["count"] >= 1, f"count={s1['count']}")
    s2 = await svc.search_memory(user_id=USER, query="差异表达用什么工具", agent_id=AGENT_B)
    sees_private_b = any(m["agent_id"] == AGENT_A for m in s2["memories"])
    check("search agentB 不见 A 私有", not sees_private_b, f"count={s2['count']}")

    # 5. list：scope 过滤
    lst = await svc.list_memories(USER, scope="preference")
    check("list scope=preference", len(lst) == 1 and lst[0].scope == "preference", f"n={len(lst)}")

    # 6. build_prompt_context：L1(preference 常驻) + L2(project 召回)
    ctx_a = await svc.build_prompt_context(USER, AGENT_A, "帮我复核差异表达流程")
    check("注入包含 preference(L1)", "NPG" in ctx_a, f"len={len(ctx_a)}")
    check("注入包含 project(L2)", "DESeq2" in ctx_a)
    ctx_b = await svc.build_prompt_context(USER, AGENT_B, "帮我复核差异表达流程")
    check("agentB 注入不含 A 私有", "DESeq2" not in ctx_b or "padj" not in ctx_b)
    check("agentB 注入仍含共享", "NPG" in ctx_b)

    # 7. update
    u = await svc.update_memory(user_id=USER, memory_id=mid_project, content="差异表达改用 edgeR")
    check("update 内容生效", u["memory"]["content"] == "差异表达改用 edgeR")

    # 8. forget
    f = await svc.forget_memory(user_id=USER, memory_id=mid_project)
    check("forget 返回 forgotten", f.get("forgotten") is True)
    s3 = await svc.search_memory(user_id=USER, query="edgeR", agent_id=AGENT_A)
    check("forget 后不可召回", s3["count"] == 0, f"count={s3['count']}")

    # 9. clear
    n = await svc.clear_memories(USER)
    check("clear 清空", n >= 1, f"cleared={n}")
    left = await svc.list_memories(USER)
    check("clear 后列表为空", len(left) == 0, f"left={len(left)}")

    print(f"\n===== 冒烟结果：{len(PASS)} 通过 / {len(FAIL)} 失败 =====")
    if FAIL:
        print("失败项:", FAIL)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

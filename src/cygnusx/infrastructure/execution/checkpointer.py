"""Orchestrator 编排图 checkpointer 工厂

P0 决策（data/ai/update/update_agent.md:615-624"明确权威状态存储"）：
LangGraph checkpoint 只作图执行恢复载体，overdrive_runs/overdrive_events
表仍是权威状态账本——禁止另建第二套业务状态存储。checkpoint 表结构由
langgraph-checkpoint-postgres 自带 ``setup()`` 建立，复用现有 Postgres
连接配置（psycopg 驱动，与 asyncpg 并存只是驱动差异，同库不同连接）。

用法：
    async with postgres_checkpointer() as saver:
        engine = build_orchestrator_engine(deps, checkpointer=saver)
测试环境直接用 ``memory_checkpointer()``（InMemorySaver），不触库。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from langgraph.checkpoint.memory import InMemorySaver


def memory_checkpointer() -> InMemorySaver:
    """测试/进程内临时场景的内存 checkpointer。"""
    return InMemorySaver()


def _postgres_dsn() -> str:
    """从现有 Postgres 配置派生 psycopg DSN（复用 config 的 postgres_* 项）。"""
    from cygnusx.core.config import get_settings

    settings = get_settings()
    return (
        f"postgresql://{settings.postgres_user}:{settings.postgres_password}"
        f"@{settings.postgres_host}:{settings.postgres_port}/{settings.postgres_db}"
    )


@asynccontextmanager
async def postgres_checkpointer() -> AsyncIterator[Any]:
    """生产用 PostgresSaver（AsyncPostgresSaver，psycopg 异步连接）。

    首次调用执行 ``setup()`` 建表（checkpoints/checkpoint_blobs/
    checkpoint_writes/checkpoint_migrations，幂等）。依赖
    langgraph-checkpoint-postgres，未安装时给出显式报错而非静默降级。
    """
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    except ImportError as exc:  # pragma: no cover - 依赖缺失时明确失败
        raise RuntimeError(
            "orchestrator_engine=langgraph 需要 langgraph-checkpoint-postgres，"
            "请先安装依赖（pyproject.toml 已声明）"
        ) from exc
    async with AsyncPostgresSaver.from_conn_string(_postgres_dsn()) as saver:
        await saver.setup()
        yield saver

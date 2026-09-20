"""数据库健康观测 — 管理员只读端点。

提供两类只读信息：
- ``GET /health``：迁移版本同步状态（alembic_version ↔ 代码 head）、表数量、
  连接池占用、只读副本配置、服务名。
- ``GET /drift``：ORM metadata ↔ 实际 schema 对账，逻辑与
  ``scripts/check_schema_drift.py`` 一致（方向：代码需要的，库里必须有；
  多出的表仅列出）。忽略表集合与脚本保持一致。

仅管理员可访问（AdminRequired）。全部查询只读，不做任何写操作。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter

from cygnusx.api.deps import AdminRequired, DbSession
from cygnusx.core.config import get_settings
from cygnusx.infrastructure.database.base import Base
from cygnusx.infrastructure.database.session import get_engine

router = APIRouter()

# 与 scripts/check_schema_drift.py 的 _IGNORED_EXTRA_TABLES 保持一致：
# alembic 版本表与 mem0 自建表不参与漂移对账。
_IGNORED_EXTRA_TABLES = {"alembic_version", "mem0_memories"}

_ALEMBIC_INI = Path(__file__).resolve().parents[5] / "alembic.ini"


def _get_alembic_heads() -> list[str]:
    """读取代码侧 alembic head 版本（只解析迁移脚本，不连库）。"""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(_ALEMBIC_INI))
    return sorted(ScriptDirectory.from_config(cfg).get_heads())


def _get_pool_stats() -> dict[str, Any]:
    """返回主库连接池占用；NullPool 等无容量语义的池只返回类名。"""
    pool = get_engine().sync_engine.pool
    stats: dict[str, Any] = {"class": type(pool).__name__}
    for attr, key in (
        ("size", "size"),
        ("checkedout", "checked_out"),
        ("checkedin", "checked_in"),
        ("overflow", "overflow"),
    ):
        method = getattr(pool, attr, None)
        if callable(method):
            try:
                stats[key] = method()
            except Exception:  # noqa: BLE001 - 池实现差异，容错跳过
                continue
    return stats


def _inspect_drift(sync_conn: sa.engine.Connection) -> dict[str, Any]:
    """ORM metadata ↔ 实际 schema 对账（与 check_schema_drift.py 同逻辑）。"""
    insp = sa.inspect(sync_conn)
    existing_tables = set(insp.get_table_names())
    missing_tables: list[str] = []
    missing_columns: list[str] = []
    for table_name, table in Base.metadata.tables.items():
        if table_name not in existing_tables:
            missing_tables.append(table_name)
            continue
        existing_columns = {c["name"] for c in insp.get_columns(table_name)}
        for col in table.columns:
            if col.name not in existing_columns:
                missing_columns.append(f"{table_name}.{col.name}")
    extra_tables = sorted(
        existing_tables - set(Base.metadata.tables) - _IGNORED_EXTRA_TABLES
    )
    return {
        "ok": not missing_tables and not missing_columns,
        "missing_tables": sorted(missing_tables),
        "missing_columns": sorted(missing_columns),
        "extra_tables": extra_tables,
    }


@router.get("/health", summary="数据库健康汇总（迁移版本 / 表数量 / 连接池 / 只读副本）")
async def database_health(_admin: AdminRequired, db: DbSession) -> dict[str, Any]:
    """只读汇总：alembic 版本同步状态、public schema 表数量、连接池占用、只读副本配置。"""
    settings = get_settings()

    def _collect(sync_conn: sa.engine.Connection) -> tuple[list[str], int]:
        versions: list[str] = []
        insp = sa.inspect(sync_conn)
        if "alembic_version" in insp.get_table_names():
            rows = sync_conn.execute(sa.text("SELECT version_num FROM alembic_version"))
            versions = sorted(row[0] for row in rows)
        table_count = sync_conn.execute(
            sa.text(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'"
            )
        ).scalar_one()
        return versions, int(table_count)

    conn = await db.connection()
    db_versions, table_count = await conn.run_sync(_collect)
    heads = _get_alembic_heads()

    return {
        "service_name": settings.service_name,
        "alembic_db_version": db_versions,
        "alembic_head": heads,
        "version_in_sync": bool(heads) and set(db_versions) == set(heads),
        "table_count": table_count,
        "readonly_replica_configured": bool(settings.readonly_database_url),
        "pool": _get_pool_stats(),
    }


@router.get("/drift", summary="Schema 漂移检查（ORM metadata ↔ 数据库对账）")
async def schema_drift(_admin: AdminRequired, db: DbSession) -> dict[str, Any]:
    """与 scripts/check_schema_drift.py 相同的对账：代码需要的表/列必须存在于库中。"""
    conn = await db.connection()
    return await conn.run_sync(_inspect_drift)

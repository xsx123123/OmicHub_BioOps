#!/usr/bin/env python3
"""Schema 漂移检查：ORM metadata ↔ 实际数据库。

背景：历史上出现过"alembic_version 版本戳已记录、但实际 DDL 未生效"
（手工建列 / create_all / 备份恢复等）导致运行期 UndefinedColumnError 的事故。
`alembic upgrade head` 只保证版本戳推进，发现不了这种漂移，需要在迁移后
直接用 ORM metadata 对账真实 schema。

检查方向只做"代码需要的，库里必须有"：
  - metadata 中的表必须存在；
  - metadata 中的列必须存在（类型不强制比对，避免方言噪音）。
库中多出的表/列（如下线遗留）只告警、不失败。

运行方式：
    python scripts/check_schema_drift.py          # 有漂移时退出码 1
容器入口在 `alembic upgrade head` 之后调用本脚本做 fail-fast。
"""

from __future__ import annotations

import asyncio
import sys

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import create_async_engine

# 导入模型包以注册全部表到 Base.metadata
import omichub.infrastructure.database.models  # noqa: F401
from omichub.core.config import get_settings
from omichub.infrastructure.database.base import Base

_IGNORED_EXTRA_TABLES = {"alembic_version"}


async def _collect() -> tuple[list[str], list[str], list[str]]:
    engine = create_async_engine(get_settings().database_url)
    try:
        async with engine.connect() as conn:

            def inspect(sync_conn) -> tuple[list[str], list[str], list[str]]:
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
                    existing_tables
                    - set(Base.metadata.tables)
                    - _IGNORED_EXTRA_TABLES
                )
                return missing_tables, missing_columns, extra_tables

            return await conn.run_sync(inspect)
    finally:
        await engine.dispose()


def main() -> int:
    missing_tables, missing_columns, extra_tables = asyncio.run(_collect())

    for table in extra_tables:
        print(f"⚠️  数据库存在 metadata 之外的表（仅告警）: {table}")

    if not missing_tables and not missing_columns:
        print("✅ Schema 无漂移：ORM metadata 与数据库一致。")
        return 0

    print("❌ 检测到 schema 漂移（代码需要但数据库缺失）：")
    for table in missing_tables:
        print(f"   - 缺失表: {table}")
    for col in missing_columns:
        print(f"   - 缺失列: {col}")
    print(
        "\n说明 alembic_version 版本戳与实际 DDL 不一致。"
        "请核对对应迁移为何未生效（手工 DDL / create_all / 备份恢复），"
        "补齐后重新 stamp，切勿直接再 stamp 跳过。"
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())

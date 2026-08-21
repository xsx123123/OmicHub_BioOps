"""Alembic 迁移环境 - 异步配置"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# 导入模型包以注册全部表到 metadata（autogenerate 依赖）；
# 不要改成挑选子模块导入——清单会过期，遗漏的表会被 autogenerate 误判为待删除。
import omichub.infrastructure.database.models  # noqa: F401
from omichub.core.config import get_settings
from omichub.infrastructure.database.base import Base

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# 从应用配置覆盖 SQLAlchemy URL
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# 有迁移建表但无对应 ORM 模型的表（外部组件/日志表），
# autogenerate 必须跳过，否则会生成 drop_table 误删。
_NON_ORM_TABLES = {"mcp_logs"}


def include_object(object_, name, type_, reflected, compare_to):  # noqa: ANN001, ANN201
    if type_ == "table" and name in _NON_ORM_TABLES:
        return False
    return True


def run_migrations_offline() -> None:
    """离线模式 - 生成 SQL 脚本"""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """在线模式 - 异步连接执行"""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())

"""数据库会话管理 - 异步 SQLAlchemy"""

from collections.abc import AsyncIterator

from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import NullPool

from cygnusx.core.config import get_settings
from cygnusx.core.telemetry import get_meter

_engine: AsyncEngine | None = None
_readonly_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_readonly_session_factory: async_sessionmaker[AsyncSession] | None = None
_meter = get_meter("cygnusx.database")
_pool_checked_out = _meter.create_up_down_counter(
    "cygnusx.database.pool.checked_out",
    unit="{connection}",
    description="Database connections currently checked out from the SQLAlchemy pool.",
)
_pool_checkout_total = _meter.create_counter(
    "cygnusx.database.pool.checkouts",
    unit="{connection}",
    description="Successful SQLAlchemy database pool checkouts.",
)
_pool_connect_total = _meter.create_counter(
    "cygnusx.database.pool.connects",
    unit="{connection}",
    description="Database connections opened by SQLAlchemy.",
)
_pool_invalidated_total = _meter.create_counter(
    "cygnusx.database.pool.invalidations",
    unit="{connection}",
    description="Database connections invalidated by SQLAlchemy.",
)


def get_engine() -> AsyncEngine:
    """获取异步引擎（单例）"""
    global _engine
    if _engine is None:
        settings = get_settings()
        engine_options: dict[str, object] = {
            "echo": settings.app_debug,
            "pool_pre_ping": True,
        }
        pool_name = "NullPool"
        if settings.service_name == "web":
            # AsyncEngine 默认创建 AsyncAdaptedQueuePool；显式传入同步 QueuePool
            # 会被 SQLAlchemy 拒绝，因此这里只提供容量参数。
            pool_name = "AsyncAdaptedQueuePool"
            engine_options.update(
                pool_size=settings.database_pool_size,
                max_overflow=settings.database_max_overflow,
                pool_timeout=settings.database_pool_timeout_seconds,
                pool_recycle=settings.database_pool_recycle_seconds,
            )
        else:
            # Celery/Beat 每个任务可由 asyncio.run() 建立新事件循环；保留连接会导致
            # "Future attached to a different loop"，因此 Worker 仍使用 NullPool。
            engine_options["poolclass"] = NullPool
        _engine = create_async_engine(settings.database_url, **engine_options)
        _instrument_pool(_engine, service_name=settings.service_name, pool_name=pool_name)
    return _engine


def create_unpooled_engine() -> AsyncEngine:
    """创建供独立事件循环使用的短生命周期数据库引擎。

    后台线程会通过 ``asyncio.run()`` 创建自己的事件循环，不能复用 Web
    请求循环中连接池保存的 asyncpg 连接，否则连接回收后会触发跨事件循环错误。
    调用方负责在使用后 dispose 引擎。
    """
    settings = get_settings()
    engine = create_async_engine(
        settings.database_url,
        echo=settings.app_debug,
        pool_pre_ping=True,
        poolclass=NullPool,
    )
    _instrument_pool(engine, service_name=settings.service_name, pool_name="NullPool")
    return engine


def _instrument_pool(engine: AsyncEngine, *, service_name: str, pool_name: str) -> None:
    """Expose SQLAlchemy connection-pool lifecycle metrics through OTel/Prometheus."""
    attributes = {"service": service_name, "pool": pool_name}
    pool = engine.sync_engine.pool

    @event.listens_for(pool, "connect")
    def _on_connect(*_args: object) -> None:
        _pool_connect_total.add(1, attributes)

    @event.listens_for(pool, "checkout")
    def _on_checkout(*_args: object) -> None:
        _pool_checked_out.add(1, attributes)
        _pool_checkout_total.add(1, attributes)

    @event.listens_for(pool, "checkin")
    def _on_checkin(*_args: object) -> None:
        _pool_checked_out.add(-1, attributes)

    @event.listens_for(pool, "invalidate")
    def _on_invalidate(*_args: object) -> None:
        _pool_invalidated_total.add(1, attributes)


def get_readonly_engine() -> AsyncEngine:
    """获取只读副本引擎（单例）；未配置 `readonly_database_url` 时回退主库。"""
    global _readonly_engine
    settings = get_settings()
    if not settings.readonly_database_url:
        return get_engine()
    if _readonly_engine is None:
        _readonly_engine = create_async_engine(
            settings.readonly_database_url,
            echo=settings.app_debug,
            pool_pre_ping=True,
            pool_size=settings.database_pool_size,
            max_overflow=settings.database_max_overflow,
            pool_timeout=settings.database_pool_timeout_seconds,
            pool_recycle=settings.database_pool_recycle_seconds,
        )
        _instrument_pool(
            _readonly_engine,
            service_name=settings.service_name,
            pool_name="ReadonlyAsyncAdaptedQueuePool",
        )
    return _readonly_engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取会话工厂（单例）"""
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(
            get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_factory


def get_readonly_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取只读会话工厂（单例）；用于报表/列表等读多场景分流到只读副本。"""
    global _readonly_session_factory
    if _readonly_session_factory is None:
        _readonly_session_factory = async_sessionmaker(
            get_readonly_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _readonly_session_factory


# 别名，供 deps.py 导入
async_session_factory = get_session_factory


async def init_db() -> None:
    """初始化数据库连接（预热引擎）。

    schema 建表/变更统一由 Alembic 迁移管理：容器启动时 entrypoint 执行
    `alembic upgrade head`（见 deploy/docker/entrypoint.sh）。

    历史上 dev 模式用 `Base.metadata.create_all` 自动建表，已弃用——它只建新表、
    不会给已存在的表补字段，曾导致 `users.storage_quota` 缺列引发登录 500
    （代码查新列、DB 无该列）。统一走 Alembic 后，加字段必出迁移脚本，schema 与代码强绑定。
    """
    # 仅触发引擎懒初始化（建立连接池），不在此建表
    _ = get_engine()


async def close_db() -> None:
    """关闭数据库连接"""
    global _engine, _session_factory, _readonly_engine, _readonly_session_factory
    if _readonly_engine is not None:
        await _readonly_engine.dispose()
        _readonly_engine = None
        _readonly_session_factory = None
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        _session_factory = None


async def get_db() -> AsyncIterator[AsyncSession]:
    """获取数据库会话（FastAPI 依赖）"""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

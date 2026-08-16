"""Database pool selection and instrumentation contracts."""

from types import SimpleNamespace

from sqlalchemy.pool import NullPool

from omichub.infrastructure.database import session as database_session


def _settings(service_name: str) -> SimpleNamespace:
    return SimpleNamespace(
        database_url="postgresql+asyncpg://omichub:password@db:5432/omichub",
        app_debug=False,
        service_name=service_name,
        database_pool_size=7,
        database_max_overflow=11,
        database_pool_timeout_seconds=13,
        database_pool_recycle_seconds=17,
    )


def test_web_uses_configured_queue_pool(monkeypatch) -> None:
    monkeypatch.setattr(database_session, "get_settings", lambda: _settings("web"))
    database_session._engine = None

    engine = database_session.get_engine()

    assert engine.sync_engine.pool.__class__.__name__ == "AsyncAdaptedQueuePool"
    assert engine.sync_engine.pool.size() == 7
    assert engine.sync_engine.pool._max_overflow == 11


def test_worker_uses_null_pool_for_asyncio_run_lifecycle(monkeypatch) -> None:
    monkeypatch.setattr(database_session, "get_settings", lambda: _settings("worker"))
    database_session._engine = None

    engine = database_session.get_engine()

    assert isinstance(engine.sync_engine.pool, NullPool)


def test_background_loop_engine_is_always_unpooled(monkeypatch) -> None:
    monkeypatch.setattr(database_session, "get_settings", lambda: _settings("web"))

    engine = database_session.create_unpooled_engine()

    try:
        assert isinstance(engine.sync_engine.pool, NullPool)
    finally:
        engine.sync_engine.dispose()

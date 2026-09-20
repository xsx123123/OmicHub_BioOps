"""Database 模块公共契约测试。

覆盖历史上真实出过问题的契约：
- models 包 `__all__` 与 import 清单不一致（曾导致 `import *` AttributeError）；
- 迁移建表的 ORM 模型未注册进 metadata（曾被 env.py 当作外部表排除）；
- repositories 包导出不完整，包级 facade 名存实亡。
"""

import importlib
from types import SimpleNamespace

import cygnusx.infrastructure.database.models as models_pkg
from cygnusx.infrastructure.database import session as database_session
from cygnusx.infrastructure.database.base import Base


def test_models_all_entries_are_importable() -> None:
    """__all__ 中的每个名字都必须真实存在于包命名空间。"""
    missing = [name for name in models_pkg.__all__ if not hasattr(models_pkg, name)]
    assert not missing, f"models.__all__ 声明但未导入: {missing}"


def test_all_model_modules_register_tables() -> None:
    """models 目录下每个定义了 Base 子类的模块都必须被包级导入注册。"""
    import pkgutil

    import cygnusx.infrastructure.database.models as pkg

    unregistered: list[str] = []
    for mod_info in pkgutil.iter_modules(pkg.__path__):
        if mod_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{pkg.__name__}.{mod_info.name}")
        for value in vars(module).values():
            if (
                isinstance(value, type)
                and issubclass(value, Base)
                and value is not Base
                and value.__module__ == module.__name__
            ):
                table = getattr(value, "__tablename__", None)
                if table and table not in Base.metadata.tables:
                    unregistered.append(f"{mod_info.name}.{value.__name__}({table})")
    assert not unregistered, f"模型未注册进 metadata: {unregistered}"


def test_alembic_excluded_tables_are_not_orm_managed() -> None:
    """env.py 的 _NON_ORM_TABLES 只能包含不在 metadata 中的外部组件表。"""
    from pathlib import Path

    env_path = Path(__file__).resolve().parents[2] / "alembic" / "env.py"
    source = env_path.read_text(encoding="utf-8")
    # 解析 _NON_ORM_TABLES = {...} 字面量
    import ast

    tree = ast.parse(source)
    excluded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "_NON_ORM_TABLES" for t in node.targets
        ):
            excluded = set(ast.literal_eval(node.value))
    assert excluded, "env.py 中未找到 _NON_ORM_TABLES"
    overlap = excluded & set(Base.metadata.tables)
    assert not overlap, f"被 alembic 排除的表却注册了 ORM 模型: {overlap}"


def test_repositories_package_exports_resolve() -> None:
    from cygnusx.infrastructure.database import repositories as repos_pkg

    missing = [name for name in repos_pkg.__all__ if not hasattr(repos_pkg, name)]
    assert not missing, f"repositories.__all__ 声明但未导入: {missing}"


def _settings(readonly_url: str) -> SimpleNamespace:
    return SimpleNamespace(
        database_url="postgresql+asyncpg://cygnusx:password@db:5432/cygnusx",
        readonly_database_url=readonly_url,
        app_debug=False,
        service_name="web",
        database_pool_size=7,
        database_max_overflow=11,
        database_pool_timeout_seconds=13,
        database_pool_recycle_seconds=17,
    )


def test_readonly_engine_falls_back_to_primary(monkeypatch) -> None:
    """未配置 readonly_database_url 时，只读引擎回退主库（同一实例）。"""
    monkeypatch.setattr(database_session, "get_settings", lambda: _settings(""))
    database_session._engine = None
    database_session._readonly_engine = None

    assert database_session.get_readonly_engine() is database_session.get_engine()


def test_readonly_engine_uses_readonly_url_when_configured(monkeypatch) -> None:
    readonly_url = "postgresql+asyncpg://cygnusx:password@db-replica:5432/cygnusx"
    monkeypatch.setattr(database_session, "get_settings", lambda: _settings(readonly_url))
    database_session._engine = None
    database_session._readonly_engine = None

    engine = database_session.get_readonly_engine()

    try:
        assert engine is not database_session.get_engine()
        assert "db-replica" in str(engine.url)
    finally:
        engine.sync_engine.dispose()

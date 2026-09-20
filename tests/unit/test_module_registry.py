"""模块注册表加载器单元测试 — 正常加载 / 重复 key / 坏语法 / 字段校验。"""

from pathlib import Path

import pytest
import yaml

from cygnusx.infrastructure.config.module_registry import (
    DEFAULT_REGISTRY_PATH,
    ModuleRegistryError,
    load_registry,
    parse_registry,
)


def _write_yaml(path: Path, data: dict) -> Path:
    path.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return path


def _entry(key: str, **overrides) -> dict:
    base = {
        "key": key,
        "name": f"模块 {key}",
        "route_prefix": f"/{key}",
        "api_prefix": f"/api/v1/{key}",
        "lockable": True,
        "default_locked": False,
        "ai": False,
    }
    base.update(overrides)
    return base


def test_load_real_registry_file():
    """仓库内置的 data/MODULE_LOCKED.yaml 必须能通过硬校验。"""
    registry = load_registry(DEFAULT_REGISTRY_PATH)
    keys = {m.key for m in registry.modules}
    # 覆盖契约要求的核心模块
    assert {"home", "ai-assistant", "ai-workbench", "tools", "admin"} <= keys
    # 管理员专属与首页不可按用户锁定
    by_key = {m.key: m for m in registry.modules}
    assert by_key["home"].lockable is False
    assert by_key["admin"].lockable is False
    # AI 标记
    assert by_key["ai-assistant"].ai is True
    assert by_key["ai-workbench"].ai is True
    # 当前全部 default_locked: false
    assert registry.default_locked_keys() == []


def test_parse_normalizes_string_prefix_to_list():
    """route_prefix / api_prefix 写字符串时归一化为 list[str]。"""
    registry = parse_registry({"modules": [_entry("ai-assistant")]})
    module = registry.modules[0]
    assert module.route_prefix == ["/ai-assistant"]
    assert module.api_prefix == ["/api/v1/ai-assistant"]
    assert module.to_dict()["route_prefix"] == ["/ai-assistant"]


def test_parse_accepts_empty_api_prefix():
    """无 API 的模块允许 api_prefix: []。"""
    registry = parse_registry({"modules": [_entry("about", api_prefix=[])]})
    assert registry.modules[0].api_prefix == []


def test_parse_rejects_duplicate_key():
    """key 重复时抛 ModuleRegistryError 并指出重复的 key。"""
    with pytest.raises(ModuleRegistryError, match="重复"):
        parse_registry({"modules": [_entry("ai-assistant"), _entry("ai-assistant")]})


def test_parse_rejects_missing_field():
    """缺必填字段时抛错并列出缺失字段名。"""
    entry = _entry("tools")
    del entry["api_prefix"]
    with pytest.raises(ModuleRegistryError, match="api_prefix"):
        parse_registry({"modules": [entry]})


def test_parse_rejects_bad_route_prefix():
    """route_prefix 不以 '/' 开头时抛错。"""
    with pytest.raises(ModuleRegistryError, match="route_prefix"):
        parse_registry({"modules": [_entry("bad", route_prefix="no-slash")]})


def test_load_registry_bad_yaml_syntax(tmp_path: Path):
    """YAML 语法错误时抛 ModuleRegistryError，错误信息带行号。"""
    bad = tmp_path / "MODULE_LOCKED.yaml"
    bad.write_text("modules:\n  - key: ai-assistant\n   name: 缩进错误\n", encoding="utf-8")
    with pytest.raises(ModuleRegistryError) as exc_info:
        load_registry(bad)
    assert "语法错误" in str(exc_info.value)


def test_load_registry_missing_file(tmp_path: Path):
    """注册表文件不存在时抛错，不允许带病启动。"""
    with pytest.raises(ModuleRegistryError, match="不存在"):
        load_registry(tmp_path / "not-exist.yaml")


def test_default_locked_keys(tmp_path: Path):
    """default_locked: true 的模块进入新用户默认锁定列表（仅 lockable 模块）。"""
    yaml_path = _write_yaml(
        tmp_path / "MODULE_LOCKED.yaml",
        {
            "modules": [
                _entry("ai-assistant", default_locked=True),
                _entry("flows", default_locked=False),
                _entry("admin", lockable=False, default_locked=True),
            ]
        },
    )
    registry = load_registry(yaml_path)
    assert registry.default_locked_keys() == ["ai-assistant"]
    assert registry.lockable_keys() == {"ai-assistant", "flows"}

"""模块注册表加载器 —— 从 data/MODULE_LOCKED.yaml 加载平台模块清单

模块权限管控的唯一数据源。启动时加载并硬校验：
语法错误（含 yaml 行号）、必填字段缺失、key 重复、route_prefix 非法
均抛出 ModuleRegistryError，拒绝带病启动。

职责边界：YAML 只声明「平台有哪些可锁模块」；
每个用户实际被禁的模块 key 列表在数据库 users.disabled_modules。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# 默认注册表路径（仓库根 data/MODULE_LOCKED.yaml）
DEFAULT_REGISTRY_PATH = Path("data/MODULE_LOCKED.yaml")

_REQUIRED_FIELDS = ("key", "name", "route_prefix", "api_prefix", "lockable", "default_locked", "ai")


class ModuleRegistryError(Exception):
    """模块注册表配置错误 —— 启动时硬校验失败，不允许带病启动"""



@dataclass(frozen=True)
class ModuleEntry:
    """单个模块注册条目（route_prefix / api_prefix 已归一化为 list[str]）"""

    key: str
    name: str
    route_prefix: list[str]
    api_prefix: list[str]
    lockable: bool
    default_locked: bool
    ai: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "route_prefix": list(self.route_prefix),
            "api_prefix": list(self.api_prefix),
            "lockable": self.lockable,
            "default_locked": self.default_locked,
            "ai": self.ai,
        }


@dataclass(frozen=True)
class ModuleRegistry:
    """解析完成并校验通过的模块注册表"""

    modules: tuple[ModuleEntry, ...] = field(default_factory=tuple)

    def lockable_modules(self) -> list[ModuleEntry]:
        """可被管理员按用户禁用的模块（权限对话框与拦截中间件只关心这些）"""
        return [m for m in self.modules if m.lockable]

    def lockable_keys(self) -> set[str]:
        return {m.key for m in self.modules if m.lockable}

    def default_locked_keys(self) -> list[str]:
        """新用户注册时默认锁定的模块 key 列表"""
        return [m.key for m in self.modules if m.lockable and m.default_locked]

    def to_dict(self) -> dict[str, Any]:
        return {"modules": [m.to_dict() for m in self.modules]}


def _normalize_prefixes(value: Any, *, field_name: str, key: str) -> list[str]:
    """把字符串或字符串列表归一化为 list[str]，并校验每个前缀以 '/' 开头"""
    if isinstance(value, str):
        items: list[Any] = [value]
    elif isinstance(value, list):
        items = value
    else:
        raise ModuleRegistryError(
            f"模块 '{key}' 的 {field_name} 必须是字符串或字符串列表，实际为 {type(value).__name__}"
        )
    prefixes: list[str] = []
    for item in items:
        if not isinstance(item, str) or not item.startswith("/"):
            raise ModuleRegistryError(
                f"模块 '{key}' 的 {field_name} 含非法前缀 {item!r}：必须以 '/' 开头"
            )
        prefixes.append(item)
    return prefixes


def parse_registry(data: Any, *, source: str = "<memory>") -> ModuleRegistry:
    """解析并校验注册表数据（dict），非法时抛 ModuleRegistryError"""
    if not isinstance(data, dict) or not isinstance(data.get("modules"), list):
        raise ModuleRegistryError(f"{source}: 注册表必须是含 modules 列表的 YAML 对象")

    entries: list[ModuleEntry] = []
    seen_keys: set[str] = set()
    for index, raw in enumerate(data["modules"]):
        if not isinstance(raw, dict):
            raise ModuleRegistryError(f"{source}: 第 {index + 1} 个模块条目必须是 YAML 对象")
        missing = [f for f in _REQUIRED_FIELDS if f not in raw]
        label = raw.get("key", f"#{index + 1}")
        if missing:
            raise ModuleRegistryError(f"{source}: 模块 '{label}' 缺少必填字段: {', '.join(missing)}")

        key = str(raw["key"]).strip()
        if not key:
            raise ModuleRegistryError(f"{source}: 第 {index + 1} 个模块条目的 key 不能为空")
        if key in seen_keys:
            raise ModuleRegistryError(f"{source}: 模块 key 重复: '{key}'")
        seen_keys.add(key)

        entries.append(
            ModuleEntry(
                key=key,
                name=str(raw["name"]).strip(),
                route_prefix=_normalize_prefixes(raw["route_prefix"], field_name="route_prefix", key=key),
                api_prefix=_normalize_prefixes(raw["api_prefix"], field_name="api_prefix", key=key),
                lockable=bool(raw["lockable"]),
                default_locked=bool(raw["default_locked"]),
                ai=bool(raw["ai"]),
            )
        )
    return ModuleRegistry(modules=tuple(entries))


def load_registry(path: Path = DEFAULT_REGISTRY_PATH) -> ModuleRegistry:
    """从 YAML 文件加载模块注册表，任何错误都抛 ModuleRegistryError（fail fast）"""
    if not path.exists():
        raise ModuleRegistryError(f"模块注册表文件不存在: {path}")
    try:
        with path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        location = f" 第 {mark.line + 1} 行第 {mark.column + 1} 列" if mark else ""
        raise ModuleRegistryError(f"模块注册表 YAML 语法错误 {path}{location}: {exc}") from exc
    except OSError as exc:
        raise ModuleRegistryError(f"模块注册表读取失败 {path}: {exc}") from exc
    return parse_registry(data, source=str(path))


# ------------------------------------------------------------------
# 进程内缓存：启动时 init 一次，运行期经 get 读取
# ------------------------------------------------------------------
_cached_registry: ModuleRegistry | None = None


def init_module_registry(path: Path = DEFAULT_REGISTRY_PATH) -> ModuleRegistry:
    """启动时加载并缓存注册表；失败抛 ModuleRegistryError，拒绝带病启动"""
    global _cached_registry
    _cached_registry = load_registry(path)
    return _cached_registry


def get_module_registry() -> ModuleRegistry:
    """读取进程内缓存的注册表；未初始化时按需加载（同样 fail fast）"""
    global _cached_registry
    if _cached_registry is None:
        _cached_registry = load_registry()
    return _cached_registry

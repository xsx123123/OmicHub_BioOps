"""外置 Prompt Registry 加载器。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from cygnusx.core.config import get_settings

_VARIABLE_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")


@dataclass(frozen=True)
class PromptDefinition:
    key: str
    file: str
    kind: str
    owners: tuple[str, ...]
    variables: tuple[str, ...]


class PromptRegistry:
    """提示词注册表，支持 mtime 热重载与安全变量渲染。"""

    def __init__(self, registry_path: str | Path | None = None) -> None:
        settings = get_settings()
        self.registry_path = Path(registry_path or settings.prompts_registry_yaml)
        self.root = self.registry_path.parent
        self._definitions: dict[str, PromptDefinition] = {}
        self._content_cache: dict[str, tuple[float, str]] = {}
        self._registry_mtime = -1.0

    def _reload_registry_if_needed(self) -> None:
        try:
            mtime = self.registry_path.stat().st_mtime
        except OSError:
            self._definitions = {}
            self._registry_mtime = -1.0
            return
        if self._definitions and mtime <= self._registry_mtime:
            return
        try:
            raw = yaml.safe_load(self.registry_path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            self._definitions = {}
            return
        prompts = raw.get("prompts", {}) if isinstance(raw, dict) else {}
        definitions: dict[str, PromptDefinition] = {}
        if isinstance(prompts, dict):
            for key, item in prompts.items():
                if not isinstance(item, dict) or not item.get("file"):
                    continue
                definitions[str(key)] = PromptDefinition(
                    key=str(key),
                    file=str(item["file"]),
                    kind=str(item.get("kind") or "text"),
                    owners=tuple(str(value) for value in item.get("owners", [])),
                    variables=tuple(str(value) for value in item.get("variables", [])),
                )
        self._definitions = definitions
        self._registry_mtime = mtime

    def definition(self, key: str) -> PromptDefinition | None:
        self._reload_registry_if_needed()
        return self._definitions.get(key)

    def _resolve_path(self, definition: PromptDefinition) -> Path:
        path = (self.root / definition.file).resolve()
        root = self.root.resolve()
        if path != root and root not in path.parents:
            raise ValueError(f"Prompt 路径越界: {definition.file}")
        return path

    def get(self, key: str, default: str = "") -> str:
        definition = self.definition(key)
        if definition is None or definition.kind == "mapping":
            return default
        try:
            path = self._resolve_path(definition)
            mtime = path.stat().st_mtime
        except (OSError, ValueError):
            return default
        cached = self._content_cache.get(key)
        if cached and cached[0] >= mtime:
            return cached[1]
        try:
            content = path.read_text(encoding="utf-8").strip()
        except OSError:
            return default
        self._content_cache[key] = (mtime, content)
        return content or default

    def get_mapping(self, key: str) -> dict[str, Any]:
        definition = self.definition(key)
        if definition is None or definition.kind != "mapping":
            return {}
        try:
            path = self._resolve_path(definition)
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, ValueError, yaml.YAMLError):
            return {}
        return raw if isinstance(raw, dict) else {}

    def render(self, key: str, default: str = "", **variables: Any) -> str:
        definition = self.definition(key)
        template = self.get(key, default)
        if not template:
            return ""
        declared = set(definition.variables if definition else ())
        unknown = set(variables) - declared if declared else set()
        if unknown:
            raise ValueError(f"Prompt {key} 收到未声明变量: {sorted(unknown)}")

        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in variables:
                raise ValueError(f"Prompt {key} 缺少变量: {name}")
            return str(variables[name])

        return _VARIABLE_RE.sub(replace, template)


prompt_registry = PromptRegistry()


def get_prompt(key: str, default: str = "") -> str:
    return prompt_registry.get(key, default)


def render_prompt(key: str, default: str = "", **variables: Any) -> str:
    return prompt_registry.render(key, default, **variables)

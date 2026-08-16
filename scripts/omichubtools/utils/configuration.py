#!/usr/bin/env python3
"""Configuration loading utilities for omichubtools.

This module follows the same package-resource pattern as the gpse utilities: the
default YAML files live inside ``omichubtools.config`` and can be overridden by
project-level YAML files without depending on an external checkout.
"""

from __future__ import annotations

import logging
from copy import deepcopy
from importlib import resources
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger("omichubtools.config")

PROJECT_CONFIG_FILES = ("omichubtools.yaml", "omichubtools.local.yaml")


def _load_yaml(config_name: str) -> dict[str, Any]:
    config_path = resources.files("omichubtools.config") / f"{config_name}.yaml"
    logger.debug("Loading config '%s' from %s", config_name, config_path)
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise TypeError(f"Package config must be a YAML mapping: {config_path}")
    return data


def _load_yaml_path(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path).expanduser()
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise TypeError(f"User config must be a YAML mapping: {path}")
    return data


def _merge_named_list(base: list[Any], override: list[Any]) -> list[Any]:
    if not all(isinstance(item, dict) and "name" in item for item in base + override):
        return deepcopy(override)

    merged: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for item in base:
        name = str(item["name"])
        merged[name] = deepcopy(item)
        order.append(name)
    for item in override:
        name = str(item["name"])
        if name in merged:
            merged[name] = _deep_merge(merged[name], item)
        else:
            merged[name] = deepcopy(item)
            order.append(name)
    return [merged[name] for name in order]


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        elif key in result and isinstance(result[key], list) and isinstance(value, list):
            result[key] = _merge_named_list(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def _project_config_paths(search_dir: str | Path | None = None) -> list[Path]:
    root = Path(search_dir or Path.cwd())
    return [root / name for name in PROJECT_CONFIG_FILES if (root / name).is_file()]


def get_loaded_project_configs(search_dir: str | Path | None = None) -> list[Path]:
    return _project_config_paths(search_dir)


def _load_config_with_overrides(
    config_name: str,
    user_config_path: str | Path | None = None,
    *,
    auto_project_config: bool = False,
    search_dir: str | Path | None = None,
) -> dict[str, Any]:
    config = _load_yaml(config_name)

    override_paths: list[Path] = []
    if auto_project_config:
        override_paths.extend(_project_config_paths(search_dir))
    if user_config_path:
        override_paths.append(Path(user_config_path).expanduser())

    for path in override_paths:
        if not path.is_file():
            raise FileNotFoundError(f"User config not found: {path}")
        config = _deep_merge(config, _load_yaml_path(path))
    return config


def load_software_config(
    user_config_path: str | Path | None = None,
    *,
    auto_project_config: bool = False,
    search_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _load_config_with_overrides(
        "software",
        user_config_path,
        auto_project_config=auto_project_config,
        search_dir=search_dir,
    )


def load_default_config(
    user_config_path: str | Path | None = None,
    *,
    auto_project_config: bool = False,
    search_dir: str | Path | None = None,
) -> dict[str, Any]:
    return _load_config_with_overrides(
        "default",
        user_config_path,
        auto_project_config=auto_project_config,
        search_dir=search_dir,
    )

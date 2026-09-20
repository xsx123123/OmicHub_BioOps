"""AI Provider YAML 同步共享工具。

AIProviderYamlLoader（ старт同步 yaml→DB）与 AIProviderYamlWriter（写操作回写 DB→yaml）
共用本模块的工具，避免二者互相 import 造成循环依赖。
"""

from __future__ import annotations

import re

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")


def provider_env_key(name: str) -> str:
    """由 provider 名称推导约定环境变量名：转大写、非字母数字转下划线、加 _API_KEY 后缀。

    例如 "qdoubao-seed-evolving" -> "DEEPSEEK_V4_FLASH_API_KEY"。
    网页端回写 YAML 时用该名生成 ``${...}`` 占位，真实 Key 只存 DB，不落盘。
    """
    sanitized = re.sub(r"[^A-Za-z0-9]+", "_", (name or "").strip()).strip("_").upper()
    return f"{sanitized or 'PROVIDER'}_API_KEY"


def interpolate_env(value) -> object:
    """递归替换字符串中的 ${ENV} / ${ENV:-default}。"""
    if isinstance(value, str):

        def replacer(match: re.Match[str]) -> str:
            import os

            var_name = match.group(1)
            default = match.group(2)
            return os.environ.get(var_name, default if default is not None else "")

        return _ENV_PATTERN.sub(replacer, value)
    if isinstance(value, dict):
        return {k: interpolate_env(v) for k, v in value.items()}
    if isinstance(value, list):
        return [interpolate_env(v) for v in value]
    return value

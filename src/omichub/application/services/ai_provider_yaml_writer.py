"""AI Provider YAML 回写器 — 把 DB 中的 Provider 配置回写到 providers.yaml。

设计目标（YAML 单一事实源 + 双向同步）：
- 网页端增删改/设默认后，把当前 DB 状态回写 data/ai/providers.yaml；
- api_key 为敏感信息，回写时一律写 ``${ENV_KEY}`` 占位（由 provider name 派生），
  真实 Key 只存 DB（加密），不落盘；
- 保留 YAML 文件头部注释（说明性文字），body 用 safe_dump 重新生成。

与 AIProviderYamlLoader 配套：loader 启动时以 yaml 为权威 prune DB，
writer 在写操作后以 DB 为快照回写 yaml，二者共同形成「yaml 优先 + 网页可改且回写」闭环。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from loguru import logger

from omichub.application.services.ai_provider_yaml_shared import provider_env_key
from omichub.core.config import get_settings
from omichub.domain.ai_provider.entities import AIProviderConfig


def _provider_to_yaml_dict(config: AIProviderConfig) -> dict[str, Any]:
    """把单个 Provider 实体转为 YAML 行；api_key 写 ${ENV_KEY} 占位，绝不落真实 Key。"""
    return {
        "name": config.name,
        "provider_type": config.provider_type.value,
        "model": config.model,
        "base_url": config.base_url,
        # 占位：真实 Key 只存 DB，YAML 只声明 env 变量名，运行时由 loader 从 .env 解析
        "api_key": f"${{{provider_env_key(config.name)}}}",
        "temperature": config.temperature,
        "max_tokens": config.max_tokens,
        "top_p": config.top_p,
        "timeout": config.timeout,
        "is_default": config.is_default,
        "is_active": config.is_active,
        "extra_params": config.extra_params or {},
    }


def _dump_with_header(path: Path, providers: list[dict[str, Any]]) -> None:
    """保留原文件头部注释，追加 safe_dump 的 providers 段。"""
    header_lines: list[str] = []
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.lstrip().startswith("#") or line.strip() == "":
                header_lines.append(line)
            else:
                break
    # 去掉 header 尾部多余空行，保留一组说明性注释
    while header_lines and header_lines[-1].strip() == "":
        header_lines.pop()

    body = yaml.safe_dump(
        {"providers": providers},
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    content = "\n".join(header_lines) + ("\n\n" if header_lines else "") + body
    path.write_text(content, encoding="utf-8")


class AIProviderYamlWriter:
    """把 DB 当前 Provider 配置全量回写到 providers.yaml。"""

    def __init__(self, yaml_path: str | None = None) -> None:
        self._path = Path(yaml_path or get_settings().ai_provider_config_yaml)

    def write_configs(self, configs: list[AIProviderConfig]) -> None:
        """按 DB 当前全量 provider 列表回写 YAML（含停用项，保证文件与 DB 一致）。"""
        try:
            providers = [_provider_to_yaml_dict(c) for c in configs]
            self._path.parent.mkdir(parents=True, exist_ok=True)
            _dump_with_header(self._path, providers)
            logger.info("已回写 AI Provider YAML: {path}（{n} 项）", path=self._path, n=len(providers))
        except Exception as exc:  # noqa: BLE001
            # 回写失败不影响 DB 写入已生效；下次写操作会再尝试
            logger.warning("回写 AI Provider YAML 失败: {exc}", exc=exc)

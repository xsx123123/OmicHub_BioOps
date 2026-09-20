"""工具箱前端注册表外置 YAML 配置加载器。

配置文件路径由 settings.tools_setting_yaml 决定（默认 tool_configs/tools_setting.yaml，
集中配置于 tool_configs/ 根目录，仓库内源码管控；容器内经 tool_configs/ 挂载 :ro 可读）。

职责边界：
- 本文件只管「哪些工具加载到前端 + 展示元数据」（title/description/icon/gradient/route）。
- 各工具的「功能配置」放 tool_configs/<工具名>/（如 jbrowse/jbrowse_config.yaml、
  enrichments/species_config.yaml），由各自加载器解析，互不耦合。

热重载策略（与 jbrowse_config / enrichment_config 一致）：
- ToolsRegistryConfigManager 单例缓存解析后的 ToolsRegistry，按文件 mtime 判定是否重解析；
- 文件不存在 / 解析失败 / 字段缺失时回退到内置默认空配置，绝不抛异常
  （前端工具箱降级为空列表，不影响平台其它功能）；
- 改文件后由加载器 mtime 自动热重载，无需重启；管理员可调 POST /api/v1/tools/reload 强制。

icon 字段是字符串 key，前端 ToolsHubView 的 ICON_MAP 映射回 @vicons/ionicons5 组件
（Vue 组件不能由字符串动态 import 而不经打包，故新增图标须在前端登记）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field

from cygnusx.core.config import get_settings


class ToolItem(BaseModel):
    """单个工具的注册表项（前端工具箱卡片）。"""

    model_config = ConfigDict(extra="ignore")

    key: str = Field(..., description="工具唯一标识，同时是前端路由 token")
    title: str = Field(..., description="卡片标题")
    description: str = Field(default="", description="卡片描述")
    icon: str = Field(default="AppsOutline", description="图标字符串 key，前端 ICON_MAP 映射回组件")
    gradient: str = Field(
        default="linear-gradient(135deg, #165DFF 0%, #6B8DD6 100%)",
        description="卡片图标背景渐变（CSS linear-gradient）",
    )
    route: str = Field(..., description="点击卡片跳转的前端路由")
    group: str = Field(default="", description="工具分组 key（供前端工具箱归类展示）")
    enabled: bool = Field(default=True, description="false 则不出现在工具箱")
    order: int = Field(default=0, description="卡片排序，升序")
    config_dir: str = Field(default="", description="该工具功能配置目录（相对仓库根），仅展示用")


class ToolsRegistry(BaseModel):
    """根配置模型。"""

    model_config = ConfigDict(extra="ignore")

    tools: list[ToolItem] = Field(default_factory=list)


class ToolsRegistryConfigManager:
    """配置管理器，支持 mtime 热重载。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = str(config_path) if config_path else get_settings().tools_setting_yaml
        self._config: ToolsRegistry | None = None
        self._mtime: float = 0.0

    def _load_yaml(self) -> dict[str, Any]:
        """读盘；文件不存在 / 解析失败时返回空 dict（由降级逻辑兜底）。"""
        path = Path(self.config_path)
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def get_config(self) -> ToolsRegistry:
        """获取配置，自动检测文件变更并热重载；文件缺失返回默认空配置。"""
        path = Path(self.config_path)
        if not path.exists():
            self._config = ToolsRegistry()
            return self._config

        try:
            current_mtime = path.stat().st_mtime
        except OSError:
            return self._config or ToolsRegistry()

        if self._config is None or current_mtime > self._mtime:
            raw = self._load_yaml()
            try:
                self._config = ToolsRegistry(**raw)
            except Exception:
                # 字段不合法时回退默认，避免拖垮整个 API
                self._config = ToolsRegistry()
            self._mtime = current_mtime

        return self._config

    def reload(self) -> ToolsRegistry:
        """强制重载配置（管理员接口调用）。"""
        self._config = None
        return self.get_config()

    def list_enabled_tools(self) -> list[ToolItem]:
        """返回 enabled=True 的工具列表（按 order 升序，order 相同保持 YAML 顺序）。"""
        return sorted(
            [t for t in self.get_config().tools if t.enabled],
            key=lambda t: t.order,
        )


# 全局单例
config_manager = ToolsRegistryConfigManager()


def get_tools_registry() -> ToolsRegistry:
    """FastAPI 依赖用快捷函数。"""
    return config_manager.get_config()

"""AI 助手可调用的工具 Schema 加载器。

与 tools_setting.yaml 解耦：本文件负责把 tools_schema.yaml 加载为 LLM 可消费的
OpenAI function schema，并支持 mtime 热重载。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from omichub.core.config import get_settings
from omichub.infrastructure.config.prompt_loader import render_prompt


class ToolAnnotation(BaseModel):
    """MCP Tool Annotations 语义标注。"""

    model_config = ConfigDict(extra="ignore")

    read_only_hint: bool = Field(default=False, alias="readOnlyHint")
    destructive_hint: bool = Field(default=False, alias="destructiveHint")
    open_world: bool = Field(default=False, alias="openWorld")
    idempotent: bool = Field(default=False)


class ToolSchema(BaseModel):
    """单个工具完整 schema（含执行元数据）。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    key: str
    name: str
    description: str
    keywords: list[str] = Field(default_factory=list)
    category: str = ""
    invocation_mode: str = Field(..., alias="invocation_mode")
    service: str = ""
    method: str = ""
    shim_module: str = Field(default="", alias="shim_module")
    route: str = ""
    requires_confirm: bool = Field(default=False, alias="requires_confirm")
    annotations: ToolAnnotation = Field(default_factory=ToolAnnotation)
    input_schema: dict[str, Any] = Field(default_factory=dict, alias="input_schema")
    llm_result_fields: list[str] = Field(default_factory=list, alias="llm_result_fields")
    ui_result_fields: list[str] = Field(default_factory=list, alias="ui_result_fields")
    runtime_profile: str | None = None
    required_capabilities: set[str] = Field(default_factory=set)
    mas_execution_policy: str | None = None
    extra: dict[str, Any] | None = Field(
        default=None, description="额外元数据，如 flow_id / tool_role"
    )

    def resolve_runtime_image(self) -> str | None:
        """解析工具声明的独立任务运行时；未声明时保持现有进程内/服务执行行为。"""
        if not self.runtime_profile:
            return None
        from omichub.infrastructure.config.runtime_image_loader import get_runtime_images

        _, profile = get_runtime_images().select(
            self.required_capabilities,
            "toolbox",
            self.runtime_profile,
        )
        return profile.image

    def resolve_mas_execution_policy(self) -> object | None:
        """Return the server-owned MAS execution policy referenced by this tool, if any."""
        if not self.mas_execution_policy:
            return None
        from omichub.domain.mas.tool_policy import load_execution_policies

        return load_execution_policies(get_settings().mas_tool_policies_yaml).get(
            self.mas_execution_policy
        )


class ToolsSchemaRegistry(BaseModel):
    """根配置模型。"""

    model_config = ConfigDict(extra="ignore")

    tools: list[ToolSchema] = Field(default_factory=list)
    tool_selection: dict[str, Any] = Field(default_factory=dict)


class ToolsSchemaLoader:
    """工具 Schema 加载器，支持 mtime 热重载。"""

    def __init__(self, config_path: str | Path | None = None) -> None:
        self.config_path = str(config_path) if config_path else get_settings().tools_schema_yaml
        self._config: ToolsSchemaRegistry | None = None
        self._mtime: float = 0.0
        self._tools_by_name: dict[str, ToolSchema] = {}
        # 动态 Flow tools 缓存
        self._flow_tools: list[ToolSchema] | None = None
        self._flow_mtime: float = 0.0

    def _load_yaml(self) -> dict[str, Any]:
        """读盘；文件不存在 / 解析失败时返回空 dict。"""
        path = Path(self.config_path)
        if not path.exists():
            return {}
        try:
            with path.open("r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
        except (yaml.YAMLError, OSError):
            return {}
        return data if isinstance(data, dict) else {}

    def _rebuild_index(self) -> None:
        """按 name 重建索引，并校验唯一性（后定义的覆盖先定义的，同时打警告）。"""
        self._tools_by_name = {}
        all_tools = list(self._config.tools if self._config else [])
        if self._flow_tools:
            all_tools = all_tools + self._flow_tools
        for tool in all_tools:
            if tool.name in self._tools_by_name:
                import logging

                logging.getLogger(__name__).warning(f"工具名重复: {tool.name}")
            self._tools_by_name[tool.name] = tool

    def reload(self) -> ToolsSchemaRegistry:
        """强制重载配置。"""
        self._config = None
        self._flow_tools = None
        return self.get_config()

    def get_config(self) -> ToolsSchemaRegistry:
        """获取配置，自动检测文件变更并热重载；文件缺失返回默认空配置。"""
        path = Path(self.config_path)
        need_rebuild = False

        if not path.exists():
            if self._config is None:
                self._config = ToolsSchemaRegistry()
                need_rebuild = True
        else:
            try:
                current_mtime = path.stat().st_mtime
            except OSError:
                return self._config or ToolsSchemaRegistry()

            if self._config is None or current_mtime > self._mtime:
                raw = self._load_yaml()
                try:
                    self._config = ToolsSchemaRegistry(**raw)
                except ValidationError:
                    import logging

                    logging.getLogger(__name__).exception(
                        "tools_schema.yaml 校验失败，降级为空配置"
                    )
                    self._config = ToolsSchemaRegistry()
                self._mtime = current_mtime
                need_rebuild = True

        # 检测 Flow YAML 变更并热重载动态 tools
        flow_tools = self._load_flow_tools()
        if need_rebuild or flow_tools is not self._flow_tools:
            self._flow_tools = flow_tools
            self._rebuild_index()

        return self._config or ToolsSchemaRegistry()

    def list_tools(self) -> list[ToolSchema]:
        """返回全部工具 schema（含动态 Flow tools）。"""
        return list(self.get_config().tools) + (self._flow_tools or [])

    def _load_flow_tools(self) -> list[ToolSchema]:
        """动态编译 ai.enabled 的 Flow 为 ToolSchema。"""
        from omichub.application.services.flow_service import FlowService
        from omichub.tools.flow_schema_compiler import FlowToolSchemaCompiler

        try:
            flow_service = FlowService()
            compiler = FlowToolSchemaCompiler()
            flows = flow_service.list_ai_enabled_flows()
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).warning("加载 Flow 列表失败", exc_info=True)
            return []

        tools: list[ToolSchema] = []
        for flow in flows:
            if not (flow.ai and flow.ai.enabled):
                continue
            try:
                tool_def = compiler.compile_prepare_tool(flow)
                tools.append(
                    ToolSchema(
                        key=f"flow-{flow.meta.id}",
                        name=tool_def["name"],
                        description=tool_def["description"],
                        category="workflow",
                        invocation_mode="analysis_flow",
                        requires_confirm=flow.ai.requires_confirmation if flow.ai else True,
                        input_schema=tool_def["input_schema"],
                        llm_result_fields=[
                            "valid",
                            "confirmation_id",
                            "flow_id",
                            "flow_name",
                            "sample_count",
                            "comparison_count",
                            "resource_hint",
                            "parameter_preview",
                            "task_id",
                            "status",
                            "task_url",
                            "summary",
                            "errors",
                            "warnings",
                        ],
                        ui_result_fields=["confirmation_card", "task_card", "error_card"],
                        extra={"flow_id": flow.meta.id, "tool_role": "prepare"},
                    )
                )
            except Exception:  # noqa: BLE001
                import logging

                logging.getLogger(__name__).warning(
                    f"编译 Flow tool 失败: {flow.meta.id}", exc_info=True
                )

        # 通用查询工具
        for tool_def in [compiler.compile_status_tool(), compiler.compile_summary_tool()]:
            tools.append(
                ToolSchema(
                    key=f"flow-{tool_def['name']}",
                    name=tool_def["name"],
                    description=tool_def["description"],
                    category="workflow",
                    invocation_mode="analysis_flow",
                    requires_confirm=False,
                    input_schema=tool_def["input_schema"],
                    llm_result_fields=["task_id", "status", "progress", "summary"],
                    ui_result_fields=["task_card"],
                    extra={"tool_role": "status" if "status" in tool_def["name"] else "summary"},
                )
            )

        return tools

    def get_tool(self, name: str) -> ToolSchema | None:
        """按 name 查找工具 schema（含动态 Flow tools）。"""
        self.get_config()
        return self._tools_by_name.get(name)

    def to_openai_tools(self, category: str | None = None) -> list[dict[str, Any]]:
        """转换为 OpenAI functions 格式；可传入 category 做两阶段过滤。"""
        tools = self.list_tools()
        if category:
            tools = [t for t in tools if t.category == category]
        result: list[dict[str, Any]] = []
        for tool in tools:
            schema = {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema or {"type": "object", "properties": {}},
                },
            }
            result.append(schema)
        return result

    def search_tools(self, query: str, limit: int = 8) -> list[ToolSchema]:
        """Return a deterministic lexical ranking for toolbox progressive disclosure.

        The ranking deliberately has no external state: schema mtime reload rebuilds the
        searchable corpus, while a malformed query simply returns the catalog order.
        """
        tokens = self._tokenize(query)
        tools = self.list_tools()
        if not tokens:
            return []

        ranked: list[tuple[int, ToolSchema]] = []
        for tool in tools:
            haystack = " ".join([tool.name, tool.description, *tool.keywords]).lower()
            score = sum(haystack.count(token) for token in tokens)
            if score:
                ranked.append((score, tool))
        ranked.sort(key=lambda item: (-item[0], item[1].name))
        return [tool for _, tool in ranked[:limit]]

    def select_tools(
        self, query: str, *, pinned_names: set[str] | None = None
    ) -> tuple[list[ToolSchema], str]:
        """Select pinned plus recalled tools, with conservative full-mode fallback."""
        tools = self.list_tools()
        config = self.get_config().tool_selection
        mode = str(config.get("mode", "full")).lower()
        if mode != "retrieval" or len(tools) <= 15:
            return tools, "full"
        try:
            top_n = max(1, int(config.get("top_n", 8)))
            pinned_names = pinned_names or set()
            pinned = [tool for tool in tools if tool.name in pinned_names]
            recalled = self.search_tools(query, limit=top_n)
            selected = {tool.name: tool for tool in [*pinned, *recalled]}
            return list(selected.values()), "retrieval"
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning("工具检索失败，回落全量注入", exc_info=True)
            return tools, "full"

    @staticmethod
    def _tokenize(value: str) -> list[str]:
        normalized = value.lower().strip()
        if not normalized:
            return []
        english = re.findall(r"[a-z0-9_+-]+", normalized)
        chinese_runs = re.findall(r"[\u4e00-\u9fff]+", normalized)
        chinese = [
            gram
            for run in chinese_runs
            for gram in (run[i : i + 2] for i in range(len(run) - 1))
        ]
        return list(dict.fromkeys([*english, *chinese]))

    def build_system_hint(self, allowed_names: set[str] | None = None) -> str:
        """生成注入系统提示词的工具清单。"""
        tools = self.list_tools()
        if allowed_names is not None:
            tools = [tool for tool in tools if tool.name in allowed_names]
        catalog = "\n".join(
            f"{idx}. {tool.name} — {tool.description}"
            for idx, tool in enumerate(tools, 1)
        )
        return render_prompt("tools.omichub_system_hint", tool_catalog=catalog)

    def toolbox_catalog(self, query: str, limit: int = 20) -> list[dict[str, str]]:
        """Return concise discovery metadata without exposing implementation details."""
        return [
            {
                "name": tool.name,
                "summary": tool.description.split("。", 1)[0] + "。",
            }
            for tool in self.search_tools(query, limit=limit)
        ]


# 全局单例
schema_loader = ToolsSchemaLoader()


def get_tools_schema_loader() -> ToolsSchemaLoader:
    """FastAPI 依赖用快捷函数。"""
    return schema_loader

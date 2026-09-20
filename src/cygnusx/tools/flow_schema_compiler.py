"""Flow 转 MCP Tool Schema 编译器。

根据 FlowConfig.ai 配置，把启用 AI 的流程动态编译为 LLM 可调用的 tool schema。
支持基础类型、枚举、条件提示、样本表两种模式（内联 / 引用）。
"""

from __future__ import annotations

from typing import Any

from cygnusx.domain.flow.entities import FlowConfig, Parameter
from cygnusx.domain.flow.value_objects import (
    FlowAIConfig,
    ParameterTypeEnum,
    SampleSheetConfig,
)


class FlowToolSchemaCompiler:
    """把 FlowConfig 编译为 OpenAI function schema。"""

    # 参数类型 -> JSON Schema 类型映射
    _TYPE_MAP: dict[ParameterTypeEnum, str] = {
        ParameterTypeEnum.STRING: "string",
        ParameterTypeEnum.INT: "integer",
        ParameterTypeEnum.FLOAT: "number",
        ParameterTypeEnum.SELECT: "string",
        ParameterTypeEnum.FILE: "string",
        ParameterTypeEnum.BOOLEAN: "boolean",
        ParameterTypeEnum.GROUP: "array",
        ParameterTypeEnum.SECTION: "object",
    }

    def compile_prepare_tool(self, flow: FlowConfig) -> dict[str, Any]:
        """编译流程的 prepare 工具 schema。

        生成名为 cygnusx_prepare_{tool_slug}_submission 的 tool schema。
        """
        ai = flow.ai or FlowAIConfig(enabled=False)
        if not ai.enabled:
            raise ValueError(f"流程 {flow.meta.id} 未启用 AI 接入")

        tool_slug = ai.tool_slug or flow.meta.id
        tool_name = f"cygnusx_prepare_{tool_slug}_submission"

        properties: dict[str, Any] = {
            "name": {
                "type": "string",
                "description": "用户必须提供的、便于在任务中心识别的任务名称",
                "minLength": 1,
                "maxLength": 128,
            },
            "parameters": self._compile_parameters(flow, ai),
        }
        required = ["name", "parameters"]

        if flow.sample_sheet is not None:
            properties["sample_sheet"] = self._compile_sample_sheet(flow.sample_sheet)
            required.append("sample_sheet")

        if self._has_comparisons(flow):
            properties["comparisons"] = self._compile_comparisons(flow)

        return {
            "name": tool_name,
            "description": self._build_description(flow, ai),
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    def compile_status_tool(self) -> dict[str, Any]:
        """编译任务状态查询工具 schema。"""
        return {
            "name": "cygnusx_get_analysis_task_status",
            "description": "查询当前用户在 AI 助手中提交的分析任务状态。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "任务 ID（UUID）",
                    }
                },
                "required": ["task_id"],
            },
        }

    def compile_summary_tool(self) -> dict[str, Any]:
        """编译任务摘要查询工具 schema。"""
        return {
            "name": "cygnusx_get_analysis_task_summary",
            "description": "查询当前用户在 AI 助手中提交的分析任务结果摘要（仅完成后可用）。",
            "input_schema": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "任务 ID（UUID）",
                    }
                },
                "required": ["task_id"],
            },
        }

    def _build_description(self, flow: FlowConfig, ai: FlowAIConfig) -> str:
        """构建 tool 描述。"""
        lines = [
            ai.assistant_summary or flow.meta.description,
            "",
            f"流程名称: {flow.meta.name}",
            f"流程 ID: {flow.meta.id}",
        ]
        if ai.allowed_execution_modes:
            lines.append(f"允许执行模式: {', '.join(ai.allowed_execution_modes)}")
        if ai.max_samples:
            lines.append(f"最大样本数: {ai.max_samples}")
        if ai.max_comparisons:
            lines.append(f"最大比较组数: {ai.max_comparisons}")
        if ai.requires_confirmation:
            lines.append("注意：该流程需要用户在页面上二次确认后才会真正提交任务。")
        return "\n".join(lines)

    def _compile_parameters(
        self, flow: FlowConfig, ai: FlowAIConfig
    ) -> dict[str, Any]:
        """递归编译参数列表为 JSON Schema。"""
        allowed = set(ai.allowed_parameters or [])

        def compile_param(param: Parameter, parent_conditions: list[str] | None = None) -> dict[str, Any]:
            if ai.allowed_parameters and param.name not in allowed:
                return None  # type: ignore[return-value]

            schema: dict[str, Any] = {
                "type": self._TYPE_MAP.get(param.type, "string"),
                "description": self._build_param_description(param),
            }

            if param.default is not None:
                schema["default"] = param.default

            self._apply_type_constraints(param, schema)

            condition_desc = self._describe_condition(param, parent_conditions)
            if condition_desc:
                schema["description"] += f"\n[条件] {condition_desc}"

            if param.type == ParameterTypeEnum.SECTION and param.section_config:
                child_props: dict[str, Any] = {}
                child_required: list[str] = []
                for child in param.section_config.parameters:
                    compiled = compile_param(child, parent_conditions)
                    if compiled is None:
                        continue
                    child_props[child.name] = compiled
                    if child.required:
                        child_required.append(child.name)
                schema["properties"] = child_props
                if child_required:
                    schema["required"] = child_required

            if param.type == ParameterTypeEnum.GROUP and param.group_config:
                item_props: dict[str, Any] = {}
                item_required: list[str] = []
                for child in param.group_config.parameters:
                    compiled = compile_param(child, parent_conditions)
                    if compiled is None:
                        continue
                    item_props[child.name] = compiled
                    if child.required:
                        item_required.append(child.name)
                schema["items"] = {
                    "type": "object",
                    "properties": item_props,
                    "required": item_required,
                }
                if param.group_config.min_items is not None:
                    schema["minItems"] = param.group_config.min_items
                if param.group_config.max_items is not None:
                    schema["maxItems"] = param.group_config.max_items

            return schema

        properties: dict[str, Any] = {}
        required_names: list[str] = []
        for p in flow.parameters:
            compiled = compile_param(p)
            if compiled is None:
                continue
            properties[p.name] = compiled
            if p.required:
                required_names.append(p.name)

        return {
            "type": "object",
            "description": f"{flow.meta.name} 分析参数",
            "properties": properties,
            "required": required_names,
        }

    def _build_param_description(self, param: Parameter) -> str:
        parts = [param.help_text or param.label]
        if param.placeholder:
            parts.append(f"示例: {param.placeholder}")
        return "; ".join(parts)

    def _apply_type_constraints(self, param: Parameter, schema: dict[str, Any]) -> None:
        if param.type == ParameterTypeEnum.STRING and param.string_config:
            cfg = param.string_config
            if cfg.min_length is not None:
                schema["minLength"] = cfg.min_length
            if cfg.max_length is not None:
                schema["maxLength"] = cfg.max_length
            if cfg.regex_pattern:
                schema["pattern"] = cfg.regex_pattern
        elif param.type in (ParameterTypeEnum.INT, ParameterTypeEnum.FLOAT) and param.number_config:
            cfg = param.number_config
            if cfg.min is not None:
                schema["minimum"] = cfg.min
            if cfg.max is not None:
                schema["maximum"] = cfg.max
        elif param.type == ParameterTypeEnum.SELECT and param.select_config:
            options = param.select_config.options
            enum_values = [opt.value for opt in options]
            if enum_values:
                schema["enum"] = enum_values
            if param.select_config.multi:
                schema["type"] = "array"
                schema["items"] = {"type": "string", "enum": enum_values}
                schema.pop("enum", None)
        elif param.type == ParameterTypeEnum.FILE and param.file_config:
            schema["pattern"] = "^(upload|file|directory)://"

    def _describe_condition(
        self, param: Parameter, parent_conditions: list[str] | None = None
    ) -> str:
        cond = param.condition
        if cond is None:
            return ""
        # 简单条件
        if cond.field and cond.operator:
            op_map = {
                "eq": "等于",
                "ne": "不等于",
                "gt": "大于",
                "lt": "小于",
                "gte": "大于等于",
                "lte": "小于等于",
                "in": "属于",
                "not_in": "不属于",
                "contains": "包含",
                "exists": "存在且非空",
                "regex": "匹配正则",
            }
            op_label = op_map.get(cond.operator.value, cond.operator.value)
            value = cond.value if cond.value is not None else ""
            return f"仅当 {cond.field} {op_label} {value} 时有效"
        return ""

    def _compile_sample_sheet(self, sample_sheet: SampleSheetConfig) -> dict[str, Any]:
        """编译样本表 schema：支持引用预保存样本表或内联样本数组。"""
        col_props: dict[str, Any] = {}
        required_cols: list[str] = []
        for col in sample_sheet.columns:
            col_schema: dict[str, Any] = {
                "type": col.type,
                "description": col.description or col.name,
            }
            if col.example:
                col_schema["description"] += f"; 示例: {col.example}"
            if col.allowed_values:
                col_schema["enum"] = col.allowed_values
            col_props[col.name] = col_schema
            if col.required:
                required_cols.append(col.name)

        inline_schema: dict[str, Any] = {
            "type": "array",
            "description": "样本列表（适合少量样本）；每行一个样本对象",
            "items": {
                "type": "object",
                "properties": col_props,
                "required": required_cols,
            },
        }

        ref_schema: dict[str, Any] = {
            "type": "string",
            "pattern": "^sample_sheet_ref://",
            "description": "引用已保存的样本表（推荐用于大量样本）",
        }

        return {"oneOf": [ref_schema, inline_schema]}

    def _compile_comparisons(self, flow: FlowConfig) -> dict[str, Any]:
        """编译差异比较组 schema。"""
        mapping = flow.pipeline_mapping
        control_col = "Control"
        treat_col = "Treat"
        if mapping and mapping.comparisons:
            cols = list(mapping.comparisons.columns.keys())
            if len(cols) >= 2:
                control_col, treat_col = cols[0], cols[1]

        return {
            "type": "array",
            "description": "差异比较组列表；control 和 treat 必须存在于样本表 group 列",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "比较组名称"},
                    control_col: {"type": "string", "description": "对照组名"},
                    treat_col: {"type": "string", "description": "实验组名"},
                },
                "required": ["name", control_col, treat_col],
            },
        }

    def _has_comparisons(self, flow: FlowConfig) -> bool:
        return any(p.name == "comparisons" for p in flow.parameters)


def get_flow_schema_compiler() -> FlowToolSchemaCompiler:
    """全局编译器单例。"""
    return FlowToolSchemaCompiler()

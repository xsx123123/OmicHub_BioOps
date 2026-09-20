"""流程域实体 — 基于 docs/modules/04_yaml_schema.md 规范

包含 ConditionRule（条件渲染规则）、Parameter（参数定义）、
FlowConfig（顶层流程配置）以及 FlowDefinition 聚合根。
所有模型使用 Pydantic v2 严格校验。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from cygnusx.domain.flow.value_objects import (
    ConditionOperatorEnum,
    ExecutionConfig,
    FileConfig,
    FlowAIConfig,
    FlowGroupDefinition,
    FlowMeta,
    GroupConfig,
    NumberConfig,
    ParameterTypeEnum,
    ParameterUIHint,
    PipelineMappingConfig,
    SampleSheetConfig,
    SectionConfig,
    SelectConfig,
    StringConfig,
)

# ============================================================
# 1. 条件渲染规则（核心）
# ============================================================


class ConditionRule(BaseModel):
    """条件渲染规则 — 支持简单条件和复合条件（and / or 嵌套）。

    简单条件: field + operator + value
    AND 复合: and_rules=[rule1, rule2]
    OR 复合:  or_rules=[rule1, rule2]
    混合嵌套: and_rules=[rule1, ConditionRule(or_rules=[r2, r3])]
    """

    model_config = ConfigDict(extra="forbid")

    field: str | None = Field(default=None, description="依赖的字段名")
    operator: ConditionOperatorEnum | None = Field(default=None, description="比较运算符")
    value: Any = Field(default=None, description="比较值")

    and_rules: list[ConditionRule] | None = Field(default=None, description="AND 复合条件")
    or_rules: list[ConditionRule] | None = Field(default=None, description="OR 复合条件")

    @model_validator(mode="after")
    def validate_condition_structure(self) -> ConditionRule:
        """校验条件结构合法性"""
        has_simple = self.field is not None and self.operator is not None
        has_and = self.and_rules is not None
        has_or = self.or_rules is not None

        if has_simple and (has_and or has_or):
            raise ValueError(
                "简单条件（field+operator）不能与复合条件（and_rules/or_rules）同时使用"
            )
        if not has_simple and not has_and and not has_or:
            raise ValueError(
                "条件规则必须包含简单条件（field+operator）或复合条件（and_rules/or_rules）"
            )
        if has_and and has_or:
            raise ValueError("不能同时设置 and_rules 和 or_rules")
        return self


# ============================================================
# 2. 参数模型（核心）
# ============================================================


class Parameter(BaseModel):
    """单个参数定义 — 前端据此渲染表单控件。

    type 决定使用哪个 _config 子模型；
    condition 决定参数是否显示；
    name 作为表单值的键名，必须全局唯一。
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$", description="参数ID")
    label: str = Field(..., min_length=1, description="显示标签")
    type: ParameterTypeEnum = Field(..., description="参数类型")
    required: bool = Field(default=False, description="是否必填")
    default: Any = Field(default=None, description="默认值")
    help_text: str = Field(default="", description="帮助文本（悬浮提示）")
    placeholder: str | None = Field(default=None, description="占位文本")
    order: int = Field(default=0, description="显示顺序权重（越小越靠前）")

    # 条件渲染规则
    condition: ConditionRule | None = Field(default=None, description="条件渲染规则")

    # 类型专属配置（根据 type 选择对应的 config）
    string_config: StringConfig | None = None
    number_config: NumberConfig | None = None
    select_config: SelectConfig | None = None
    file_config: FileConfig | None = None
    group_config: GroupConfig | None = None
    section_config: SectionConfig | None = None

    # 前端渲染提示（可选，向后兼容）
    ui: ParameterUIHint | None = Field(default=None, description="前端 UI 渲染提示")

    @model_validator(mode="after")
    def validate_type_specific_config(self) -> Parameter:
        """校验类型专属配置的一致性"""
        config_map: dict[ParameterTypeEnum, str | None] = {
            ParameterTypeEnum.STRING: "string_config",
            ParameterTypeEnum.INT: "number_config",
            ParameterTypeEnum.FLOAT: "number_config",
            ParameterTypeEnum.SELECT: "select_config",
            ParameterTypeEnum.FILE: "file_config",
            ParameterTypeEnum.BOOLEAN: None,
            ParameterTypeEnum.GROUP: "group_config",
            ParameterTypeEnum.SECTION: "section_config",
        }

        expected_attr = config_map.get(self.type)

        all_configs = {
            "string_config": self.string_config,
            "number_config": self.number_config,
            "select_config": self.select_config,
            "file_config": self.file_config,
            "group_config": self.group_config,
            "section_config": self.section_config,
        }

        for attr_name, config_value in all_configs.items():
            if config_value is not None and attr_name != expected_attr:
                raise ValueError(
                    f"type='{self.type.value}' 不应设置 {attr_name}，期望: {expected_attr}"
                )

        # GROUP/SECTION 必须有对应的 config 且包含子参数
        if self.type == ParameterTypeEnum.GROUP:
            if self.group_config is None:
                raise ValueError("type='group' 必须设置 group_config")
            if not self.group_config.parameters:
                raise ValueError("group_config.parameters 不能为空")

        if self.type == ParameterTypeEnum.SECTION:
            if self.section_config is None:
                raise ValueError("type='section' 必须设置 section_config")
            if not self.section_config.parameters:
                raise ValueError("section_config.parameters 不能为空")

        return self

    @field_validator("default")
    @classmethod
    def validate_default_type(cls, v: Any, info) -> Any:
        """校验 default 值与 type 一致"""
        param_type = info.data.get("type")
        if v is None or param_type is None:
            return v

        type_checks: dict[ParameterTypeEnum, type | None] = {
            ParameterTypeEnum.STRING: str,
            ParameterTypeEnum.INT: int,
            ParameterTypeEnum.FLOAT: (int, float),
            ParameterTypeEnum.BOOLEAN: bool,
            ParameterTypeEnum.SELECT: None,
        }

        if param_type in type_checks:
            expected_type = type_checks[param_type]
            if expected_type is not None and not isinstance(v, expected_type):
                raise ValueError(f"type='{param_type.value}' 的 default 必须是 {expected_type}")

        return v


# ============================================================
# 3. 顶层流程配置模型
# ============================================================


class FlowConfig(BaseModel):
    """完整流程配置 — 顶层模型。

    YAML 文件解析后的完整结构：meta + parameters + execution + sample_sheet + pipeline_mapping。
    """

    model_config = ConfigDict(extra="forbid")

    meta: FlowMeta = Field(..., description="流程元信息")
    parameters: list[Parameter] = Field(..., min_length=1, description="参数定义列表")
    execution: ExecutionConfig = Field(..., description="执行配置")
    groups: list[FlowGroupDefinition] | None = Field(
        default=None, description="前端分组定义（缺省使用默认三组）"
    )
    ai: FlowAIConfig | None = Field(default=None, description="AI 助手接入配置")
    sample_sheet: SampleSheetConfig | None = Field(
        default=None, description="样本表配置（如流程需要样本表）"
    )
    pipeline_mapping: PipelineMappingConfig | None = Field(
        default=None, description="前端参数到底层流程输入文件的映射规则"
    )

    @field_validator("parameters")
    @classmethod
    def validate_unique_param_names(cls, v: list[Parameter]) -> list[Parameter]:
        """校验参数 name 全局唯一（含 group/section 内递归）"""
        names: list[str] = []

        def collect_names(params: list[Parameter], prefix: str = "") -> None:
            for p in params:
                full_name = f"{prefix}{p.name}"
                if full_name in names:
                    raise ValueError(f"参数名 '{full_name}' 重复定义")
                names.append(full_name)

                if p.type == ParameterTypeEnum.GROUP and p.group_config:
                    collect_names(p.group_config.parameters, f"{full_name}[].")
                elif p.type == ParameterTypeEnum.SECTION and p.section_config:
                    collect_names(p.section_config.parameters, f"{full_name}.")

        collect_names(v)
        return v

    @model_validator(mode="after")
    def validate_condition_references(self) -> FlowConfig:
        """校验 condition 中引用的 field 存在于已定义的参数中"""
        all_fields: set[str] = set()

        def collect_fields(params: list[Parameter]) -> None:
            for p in params:
                all_fields.add(p.name)
                if p.type == ParameterTypeEnum.GROUP and p.group_config:
                    collect_fields(p.group_config.parameters)
                elif p.type == ParameterTypeEnum.SECTION and p.section_config:
                    collect_fields(p.section_config.parameters)

        collect_fields(self.parameters)

        def check_rule(rule: ConditionRule | None, path: str) -> None:
            if rule is None:
                return
            if rule.field and rule.field not in all_fields:
                raise ValueError(f"参数 '{path}' 的 condition 引用了未定义的字段: '{rule.field}'")
            if rule.and_rules:
                for r in rule.and_rules:
                    check_rule(r, path)
            if rule.or_rules:
                for r in rule.or_rules:
                    check_rule(r, path)

        def check_params(params: list[Parameter], path: str = "") -> None:
            for p in params:
                current_path = f"{path}{p.name}"
                check_rule(p.condition, current_path)
                if p.type == ParameterTypeEnum.GROUP and p.group_config:
                    check_params(p.group_config.parameters, f"{current_path}[].")
                elif p.type == ParameterTypeEnum.SECTION and p.section_config:
                    check_params(p.section_config.parameters, f"{current_path}.")

        check_params(self.parameters)
        return self


# ============================================================
# 4. FlowDefinition 聚合根
# ============================================================


class FlowDefinition(BaseModel):
    """流程定义聚合根 — 包装 FlowConfig + 系统 ID。

    聚合 FlowConfig（YAML 配置内容）+ UUID（系统标识）+ 元信息（激活/时间戳）。
    """

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    flow_config: FlowConfig
    is_active: bool = True
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    @property
    def flow_id(self) -> str:
        """流程业务 ID（来自 YAML meta.id）"""
        return self.flow_config.meta.id

    @property
    def name(self) -> str:
        return self.flow_config.meta.name

    @property
    def category(self) -> str:
        return self.flow_config.meta.category

    @property
    def version(self) -> str:
        return self.flow_config.meta.version

    @property
    def description(self) -> str:
        return self.flow_config.meta.description


# 解决递归类型引用（GroupConfig / SectionConfig 中包含 Parameter）
ConditionRule.model_rebuild()
Parameter.model_rebuild()
GroupConfig.model_rebuild()
SectionConfig.model_rebuild()

# 6.4 CygnusX YAML 配置规范与动态表单架构

> 本文档定义 CygnusX 分析流程的 YAML 配置规范、Pydantic v2 数据模型、动态表单渲染架构及前后端协同校验策略。

---

## 目录

1. [Pydantic Model 定义](#1-pydantic-model-定义)
2. [完整 YAML 配置示例](#2-完整-yaml-配置示例)
3. [参数联动与条件渲染设计](#3-参数联动与条件渲染设计)
4. [前后端协同校验策略](#4-前后端协同校验策略)
5. [动态表单渲染架构](#5-动态表单渲染架构)
6. [JSON Schema 导出](#6-json-schema-导出)

---

## 1. Pydantic Model 定义

### 1.1 完整 Python 模型代码

以下所有模型使用 **Pydantic v2** 编写，可直接用于 FastAPI 请求体校验。

```python
"""
CygnusX Flow Configuration Schema - Pydantic v2 Models
完整定义分析流程配置的声明式数据结构
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


# ============================================================
# 1. 枚举定义
# ============================================================

class ParameterTypeEnum(str, Enum):
    """参数类型枚举 — 前端据此选择渲染组件"""
    STRING = "string"      # 文本输入框
    INT = "int"            # 整数输入框 / 步进器
    FLOAT = "float"        # 浮点数输入框 / 滑块
    SELECT = "select"      # 下拉选择（单/多选）
    FILE = "file"          # 文件上传
    BOOLEAN = "boolean"    # 开关 / 复选框
    GROUP = "group"        # 可重复参数组（动态增减）
    SECTION = "section"    # 折叠区域（高级参数）


class ConditionOperatorEnum(str, Enum):
    """条件运算符枚举"""
    EQ = "eq"              # 等于
    NE = "ne"              # 不等于
    GT = "gt"              # 大于
    LT = "lt"              # 小于
    GTE = "gte"            # 大于等于
    LTE = "lte"            # 小于等于
    IN = "in"              # 包含于（value 为列表）
    NOT_IN = "not_in"      # 不包含于
    CONTAINS = "contains"  # 包含（字符串或列表）
    EXISTS = "exists"      # 字段存在且非空
    REGEX = "regex"        # 正则匹配


class FileAcceptType(str, Enum):
    """文件上传接受的 MIME 类型分组"""
    FASTQ = ".fastq,.fastq.gz,.fq,.fq.gz"
    BAM = ".bam"
    VCF = ".vcf,.vcf.gz"
    GTF = ".gtf,.gff,.gff3"
    CSV = ".csv,.tsv,.txt"
    ANY = "*"


# ============================================================
# 2. 配置子模型（类型特定属性）
# ============================================================

class SelectOption(BaseModel):
    """下拉选项定义"""
    model_config = ConfigDict(extra="forbid")

    label: str = Field(..., description="显示标签")
    value: Any = Field(..., description="选项值")
    help_text: str = Field(default="", description="选项说明提示")


class StringConfig(BaseModel):
    """STRING 类型专属配置"""
    model_config = ConfigDict(extra="forbid")

    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    regex_pattern: str | None = Field(default=None, description="正则校验模式")
    multiline: bool = Field(default=False, description="是否多行文本")
    rows: int = Field(default=3, ge=1, description="多行文本行数")


class NumberConfig(BaseModel):
    """INT / FLOAT 类型专属配置"""
    model_config = ConfigDict(extra="forbid")

    min: float | None = None
    max: float | None = None
    step: float = 1.0
    use_slider: bool = Field(default=False, description="是否使用滑块组件")
    slider_marks: dict[str, str] | None = None
    precision: int = Field(default=2, ge=0, le=10, description="小数精度(FLOAT)")


class SelectConfig(BaseModel):
    """SELECT 类型专属配置"""
    model_config = ConfigDict(extra="forbid")

    options: list[SelectOption] = Field(default=[], description="选项列表")
    multi: bool = Field(default=False, description="是否多选")
    allow_clear: bool = Field(default=True, description="允许清除")
    searchable: bool = Field(default=True, description="允许搜索")


class FileConfig(BaseModel):
    """FILE 类型专属配置"""
    model_config = ConfigDict(extra="forbid")

    accept: str = Field(default="*", description="接受的文件扩展名，如 .fastq.gz")
    max_size: int | None = Field(default=None, description="最大文件大小（字节）")
    multiple: bool = Field(default=False, description="是否允许多文件")
    directory: bool = Field(default=False, description="是否为目录选择")
    show_file_list: bool = Field(default=True, description="是否显示文件列表")


class GroupConfig(BaseModel):
    """GROUP 类型专属配置 — 可重复参数组"""
    model_config = ConfigDict(extra="forbid")

    min_items: int = Field(default=1, ge=0, description="最少组数")
    max_items: int | None = Field(default=None, ge=1, description="最多组数")
    item_label: str = Field(default="条目", description="单组显示标签")
    add_button_text: str = Field(default="+ 添加", description="添加按钮文案")
    parameters: list[Parameter] = Field(
        default=[], description="组内参数定义（递归）"
    )


class SectionConfig(BaseModel):
    """SECTION 类型专属配置 — 折叠区域"""
    model_config = ConfigDict(extra="forbid")

    title: str = Field(default="高级设置", description="折叠区域标题")
    default_expanded: bool = Field(default=False, description="默认展开")
    description: str = Field(default="", description="区域说明")
    parameters: list[Parameter] = Field(
        default=[], description="区域内参数定义（递归）"
    )


# ============================================================
# 3. 条件渲染规则（核心）
# ============================================================

class ConditionRule(BaseModel):
    """
    条件渲染规则 — 支持简单条件和复合条件（and / or 嵌套）

    使用方式：
      - 简单条件: ConditionRule(field="aligner", operator="eq", value="STAR")
      - AND 复合: ConditionRule(and_rules=[rule1, rule2])
      - OR 复合:  ConditionRule(or_rules=[rule1, rule2])
      - 混合嵌套: ConditionRule(and_rules=[rule1, ConditionRule(or_rules=[r2, r3])])
    """
    model_config = ConfigDict(extra="forbid")

    field: str | None = Field(default=None, description="依赖的字段名")
    operator: ConditionOperatorEnum | None = Field(
        default=None, description="比较运算符"
    )
    value: Any = Field(default=None, description="比较值")

    # 复合条件支持
    and_rules: list["ConditionRule"] | None = Field(
        default=None, description="AND 复合条件"
    )
    or_rules: list["ConditionRule"] | None = Field(
        default=None, description="OR 复合条件"
    )

    @model_validator(mode="after")
    def validate_condition_structure(self):
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
# 4. 参数模型（核心）
# ============================================================

class Parameter(BaseModel):
    """
    单个参数定义 — 前端据此渲染表单控件

    设计原则：
      - type 决定使用哪个 _config 子模型
      - condition 决定参数是否显示（前端 v-if / 后端条件校验）
      - name 作为表单值的键名，必须全局唯一
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
    condition: ConditionRule | None = Field(
        default=None, description="条件渲染规则"
    )

    # 类型专属配置（根据 type 选择对应的 config）
    string_config: StringConfig | None = None
    number_config: NumberConfig | None = None
    select_config: SelectConfig | None = None
    file_config: FileConfig | None = None
    group_config: GroupConfig | None = None
    section_config: SectionConfig | None = None

    @model_validator(mode="after")
    def validate_type_specific_config(self):
        """校验类型专属配置的一致性"""
        config_map = {
            ParameterTypeEnum.STRING: ("string_config", StringConfig),
            ParameterTypeEnum.INT: ("number_config", NumberConfig),
            ParameterTypeEnum.FLOAT: ("number_config", NumberConfig),
            ParameterTypeEnum.SELECT: ("select_config", SelectConfig),
            ParameterTypeEnum.FILE: ("file_config", FileConfig),
            ParameterTypeEnum.BOOLEAN: (None, None),  # boolean 无专属配置
            ParameterTypeEnum.GROUP: ("group_config", GroupConfig),
            ParameterTypeEnum.SECTION: ("section_config", SectionConfig),
        }

        expected_attr, _ = config_map.get(self.type, (None, None))

        # 检查是否使用了正确的 config
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
                    f"type='{self.type.value}' 不应设置 {attr_name}，"
                    f"期望: {expected_attr}"
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
    def validate_default_type(cls, v, info):
        """校验 default 值与 type 一致"""
        param_type = info.data.get("type")
        if v is None or param_type is None:
            return v

        type_checks = {
            ParameterTypeEnum.STRING: (str, "string"),
            ParameterTypeEnum.INT: (int, "integer"),
            ParameterTypeEnum.FLOAT: ((int, float), "number"),
            ParameterTypeEnum.BOOLEAN: (bool, "boolean"),
            ParameterTypeEnum.SELECT: (None, "any"),  # select 允许任意类型值
        }

        if param_type in type_checks:
            expected_type, _ = type_checks[param_type]
            if expected_type is not None and not isinstance(v, expected_type):
                raise ValueError(
                    f"type='{param_type.value}' 的 default 必须是 {expected_type}"
                )

        return v


# 解决递归类型引用（GroupConfig / SectionConfig 中包含 Parameter）
ConditionRule.model_rebuild()
GroupConfig.model_rebuild()
SectionConfig.model_rebuild()


# ============================================================
# 5. 执行配置模型
# ============================================================

class ResourcesConfig(BaseModel):
    """计算资源配置"""
    model_config = ConfigDict(extra="forbid")

    cores: int = Field(default=4, ge=1, le=128, description="CPU核心数")
    memory: str = Field(default="8G", pattern=r"^\d+[GMT]B?$", description="内存")
    time: str = Field(
        default="2h", pattern=r"^\d+[smhd]$", description="运行时间限制"
    )


class ExecutionConfig(BaseModel):
    """流程执行配置"""
    model_config = ConfigDict(extra="forbid")

    engine: Literal["snakemake", "nextflow"] = Field(
        default="snakemake", description="执行引擎"
    )
    snakefile: str = Field(
        ..., description="Snakefile 路径（相对于项目根目录）"
    )
    conda_env: str | None = Field(
        default=None, description="Conda 环境名"
    )
    default_resources: ResourcesConfig = Field(
        default_factory=ResourcesConfig, description="默认计算资源"
    )
    sample_sheet_format: Literal["csv", "excel", "json"] = Field(
        default="csv", description="样本表格式"
    )
    extra_args: list[str] = Field(
        default=[], description="额外传给 Snakemake 的参数"
    )


# ============================================================
# 6. 样本表配置模型
# ============================================================

class SampleSheetColumn(BaseModel):
    """样本表列定义"""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$", description="列名")
    required: bool = Field(default=True, description="是否必填")
    type: Literal["string", "int", "float", "boolean"] = Field(
        default="string", description="列数据类型"
    )
    description: str = Field(default="", description="列说明")
    example: str | None = Field(default=None, description="示例值")
    unique: bool = Field(default=False, description="是否唯一")
    allowed_values: list[str] | None = Field(
        default=None, description="允许的枚举值"
    )


class ValidationRule(BaseModel):
    """样本表自定义校验规则"""
    model_config = ConfigDict(extra="forbid")

    type: Literal["unique_combination", "mutual_exclusive", "regex"] = Field(
        ..., description="规则类型"
    )
    columns: list[str] = Field(..., description="涉及的列名")
    message: str = Field(default="校验失败", description="失败提示信息")
    regex_pattern: str | None = Field(default=None, description="正则模式（regex类型）")


class SampleSheetConfig(BaseModel):
    """样本表整体配置"""
    model_config = ConfigDict(extra="forbid")

    columns: list[SampleSheetColumn] = Field(
        ..., min_length=1, description="列定义列表"
    )
    validation_rules: list[ValidationRule] = Field(
        default=[], description="自定义校验规则"
    )


# ============================================================
# 7. 元信息模型
# ============================================================

class FlowMeta(BaseModel):
    """流程元信息"""
    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ..., pattern=r"^[a-z][a-z0-9_]*$", description="唯一标识符"
    )
    name: str = Field(..., min_length=1, description="显示名称")
    category: str = Field(..., description="分类")
    version: str = Field(
        ..., pattern=r"^\d+\.\d+\.\d+(-\w+)?$", description="语义化版本"
    )
    description: str = Field(..., min_length=1, description="流程描述")
    author: str | None = Field(default=None, description="作者")
    tags: list[str] = Field(default=[], description="标签列表")
    icon: str | None = Field(default=None, description="图标类名")
    docs_url: str | None = Field(default=None, description="文档链接")


# ============================================================
# 8. 顶层模型
# ============================================================

class FlowConfig(BaseModel):
    """完整流程配置 — 顶层模型"""
    model_config = ConfigDict(extra="forbid")

    meta: FlowMeta = Field(..., description="流程元信息")
    parameters: list[Parameter] = Field(
        ..., min_length=1, description="参数定义列表"
    )
    execution: ExecutionConfig = Field(..., description="执行配置")
    sample_sheet: SampleSheetConfig | None = Field(
        default=None, description="样本表配置（如流程需要样本表）"
    )

    @field_validator("parameters")
    @classmethod
    def validate_unique_param_names(cls, v: list[Parameter]):
        """校验参数 name 全局唯一"""
        names = []

        def collect_names(params: list[Parameter], prefix: str = ""):
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
    def validate_condition_references(self):
        """校验 condition 中引用的 field 存在于已定义的参数中"""
        all_fields = set()

        def collect_fields(params: list[Parameter]):
            for p in params:
                all_fields.add(p.name)
                if p.type == ParameterTypeEnum.GROUP and p.group_config:
                    collect_fields(p.group_config.parameters)
                elif p.type == ParameterTypeEnum.SECTION and p.section_config:
                    collect_fields(p.section_config.parameters)

        collect_fields(self.parameters)

        def check_rule(rule: ConditionRule | None, path: str):
            if rule is None:
                return
            if rule.field and rule.field not in all_fields:
                raise ValueError(
                    f"参数 '{path}' 的 condition 引用了未定义的字段: '{rule.field}'"
                )
            if rule.and_rules:
                for r in rule.and_rules:
                    check_rule(r, path)
            if rule.or_rules:
                for r in rule.or_rules:
                    check_rule(r, path)

        def check_params(params: list[Parameter], path: str = ""):
            for p in params:
                current_path = f"{path}{p.name}"
                check_rule(p.condition, current_path)
                if p.type == ParameterTypeEnum.GROUP and p.group_config:
                    check_params(p.group_config.parameters, f"{current_path}[].")
                elif p.type == ParameterTypeEnum.SECTION and p.section_config:
                    check_params(p.section_config.parameters, f"{current_path}.")

        check_params(self.parameters)
        return self
```

---

### 1.2 条件规则评估器（后端条件计算逻辑）

```python
"""
条件规则评估器 — 后端根据表单值计算参数是否应显示
"""

import re
from typing import Any

from .models import ConditionOperatorEnum, ConditionRule, ParameterTypeEnum


class ConditionEvaluator:
    """条件规则评估器"""

    @staticmethod
    def evaluate(rule: ConditionRule, form_values: dict[str, Any]) -> bool:
        """
        评估条件规则是否满足

        Args:
            rule: 条件规则
            form_values: 当前表单所有字段的值字典 {field_name: value}

        Returns:
            bool: 条件是否满足
        """
        # 复合条件：AND
        if rule.and_rules is not None:
            return all(
                ConditionEvaluator.evaluate(r, form_values) for r in rule.and_rules
            )

        # 复合条件：OR
        if rule.or_rules is not None:
            return any(
                ConditionEvaluator.evaluate(r, form_values) for r in rule.or_rules
            )

        # 简单条件
        if rule.field is None or rule.operator is None:
            return True

        actual_value = form_values.get(rule.field)

        return ConditionEvaluator._compare(
            actual_value, rule.operator, rule.value
        )

    @staticmethod
    def _compare(actual: Any, operator: ConditionOperatorEnum, expected: Any) -> bool:
        """单次比较运算"""
        op = operator

        if op == ConditionOperatorEnum.EXISTS:
            return actual is not None and actual != ""

        if op == ConditionOperatorEnum.EQ:
            return actual == expected

        if op == ConditionOperatorEnum.NE:
            return actual != expected

        # 数值比较 — 要求 actual 不为 None
        if actual is None:
            return False

        if op == ConditionOperatorEnum.GT:
            return actual > expected
        if op == ConditionOperatorEnum.LT:
            return actual < expected
        if op == ConditionOperatorEnum.GTE:
            return actual >= expected
        if op == ConditionOperatorEnum.LTE:
            return actual <= expected

        if op == ConditionOperatorEnum.IN:
            return actual in expected if expected is not None else False

        if op == ConditionOperatorEnum.NOT_IN:
            return actual not in expected if expected is not None else False

        if op == ConditionOperatorEnum.CONTAINS:
            if isinstance(actual, str):
                return expected in actual
            if isinstance(actual, (list, tuple)):
                return expected in actual
            return False

        if op == ConditionOperatorEnum.REGEX:
            if isinstance(actual, str) and isinstance(expected, str):
                return bool(re.search(expected, actual))
            return False

        return False


class ConditionalValidator:
    """
    条件参数校验器 — 仅校验当前可见（condition满足）的必填参数
    """

    @staticmethod
    def get_visible_params(
        parameters: list[Any],  # list[Parameter]
        form_values: dict[str, Any],
    ) -> list[str]:
        """
        获取当前条件下所有可见参数的名称列表

        返回值中的 GROUP 参数展开为内部参数名（带 [N]. 前缀）
        """
        visible = []

        def check(param: Any, prefix: str = ""):
            full_name = f"{prefix}{param.name}"

            # 检查条件
            if param.condition is not None:
                if not ConditionEvaluator.evaluate(param.condition, form_values):
                    return  # 条件不满足，参数不可见

            visible.append(full_name)

            # 递归处理 GROUP / SECTION
            if param.type == ParameterTypeEnum.GROUP and param.group_config:
                # 获取当前组数量
                group_value = form_values.get(param.name, [])
                num_items = len(group_value) if isinstance(group_value, list) else 1
                num_items = max(num_items, param.group_config.min_items)
                for i in range(num_items):
                    for sub_param in param.group_config.parameters:
                        check(sub_param, f"{full_name}[{i}].")

            elif param.type == ParameterTypeEnum.SECTION and param.section_config:
                for sub_param in param.section_config.parameters:
                    check(sub_param, f"{full_name}.")

        for p in parameters:
            check(p)

        return visible

    @staticmethod
    def validate_required(
        parameters: list[Any],
        form_values: dict[str, Any],
    ) -> list[dict]:
        """
        校验可见的必填参数是否已填写

        Returns:
            list[dict]: 错误列表，每项包含 field 和 message
        """
        errors = []
        visible = set(
            ConditionalValidator.get_visible_params(parameters, form_values)
        )

        def check(param: Any, prefix: str = ""):
            full_name = f"{prefix}{param.name}"

            # 跳过不可见参数
            if full_name not in visible:
                return

            # 检查必填
            if param.required:
                value = form_values.get(param.name)
                if value is None or value == "":
                    errors.append({
                        "field": full_name,
                        "message": f"'{param.label}' 是必填项",
                    })

            # 递归
            if param.type == ParameterTypeEnum.GROUP and param.group_config:
                group_value = form_values.get(param.name, [])
                if isinstance(group_value, list):
                    for i, item in enumerate(group_value):
                        item_prefix = f"{full_name}[{i}]."
                        # 将 item 的值合并到 form_values 中进行子参数检查
                        merged = {**form_values, **{
                            sp.name: item.get(sp.name) for sp in param.group_config.parameters
                        }}
                        for sub_param in param.group_config.parameters:
                            sub_full = f"{item_prefix}{sub_param.name}"
                            if sub_full not in visible:
                                continue
                            if sub_param.required:
                                v = item.get(sub_param.name)
                                if v is None or v == "":
                                    errors.append({
                                        "field": sub_full,
                                        "message": f"'{sub_param.label}' 是必填项",
                                    })

            elif param.type == ParameterTypeEnum.SECTION and param.section_config:
                for sub_param in param.section_config.parameters:
                    check(sub_param, f"{full_name}.")

        for p in parameters:
            check(p)

        return errors
```

---

### 1.3 模型文件结构

```
backend/
  app/
    schemas/
      __init__.py
      enums.py          # 所有枚举定义
      config_models.py  # 基础配置子模型
      condition.py      # 条件规则 + 评估器
      parameter.py      # Parameter 模型
      sample_sheet.py   # SampleSheet 相关模型
      execution.py      # ExecutionConfig + ResourcesConfig
      flow_config.py    # FlowConfig 顶层模型（含 validators）
      json_schema.py    # JSON Schema 导出工具
```

---

## 2. 完整 YAML 配置示例

### 2.1 RNA-seq 差异表达分析流程

```yaml
# ============================================================
# RNA-seq 差异表达分析流程配置
# 展示所有参数类型、条件渲染、可重复 Group、折叠 Section
# ============================================================

meta:
  id: rna_seq
  name: "RNA-seq 差异表达分析"
  category: transcriptomics
  version: "2.1.0"
  description: "基于 STAR + featureCounts + DESeq2 的标准 RNA-seq 差异表达分析流程，支持多组差异比较和高级质控参数。"
  author: "CygnusX Team"
  tags: ["rnaseq", "differential-expression", "STAR", "DESeq2", "featureCounts"]
  icon: "rna"
  docs_url: "https://docs.cygnusx.org/workflows/rna_seq"

parameters:
  # ----------------------------------------------------------
  # 一、基本参数
  # ----------------------------------------------------------
  - name: genome
    label: "参考基因组"
    type: select
    required: true
    default: "hg38"
    help_text: "选择比对使用的参考基因组版本"
    select_config:
      options:
        - label: "人类 GRCh38 (hg38)"
          value: "hg38"
          help_text: "UCSC GRCh38 完整基因组"
        - label: "人类 GRCh37 (hg19)"
          value: "hg19"
          help_text: "UCSC GRCh37 参考基因组"
        - label: "小鼠 GRCm39 (mm39)"
          value: "mm39"
          help_text: "小鼠最新参考基因组"
        - label: "小鼠 mm10"
          value: "mm10"
          help_text: "小鼠 mm10 参考基因组"
      multi: false
      searchable: true

  - name: aligner
    label: "比对工具"
    type: select
    required: true
    default: "STAR"
    help_text: "选择序列比对工具"
    select_config:
      options:
        - label: "STAR (推荐，速度快)"
          value: "STAR"
        - label: "HISAT2 (拼接友好)"
          value: "HISAT2"
        - label: "Bowtie2"
          value: "bowtie2"

  # ---- 条件渲染：仅当 aligner == "STAR" 时显示 ----
  - name: star_index
    label: "STAR 索引路径"
    type: string
    required: true
    default: "/data/ref/hg38/STAR_index"
    help_text: "STAR 基因组索引目录路径（仅 STAR 模式需要）"
    placeholder: "/path/to/STAR_index"
    condition:
      field: "aligner"
      operator: "eq"
      value: "STAR"

  - name: star_threads
    label: "STAR 比对线程数"
    type: int
    required: false
    default: 8
    help_text: "STAR 比对使用的线程数"
    condition:
      field: "aligner"
      operator: "eq"
      value: "STAR"
    number_config:
      min: 1
      max: 64
      step: 1

  # ---- 条件渲染：仅当 aligner == "HISAT2" 时显示 ----
  - name: hisat2_index
    label: "HISAT2 索引前缀"
    type: string
    required: true
    default: "/data/ref/hg38/hisat2_index/genome"
    help_text: "HISAT2 索引文件前缀路径"
    placeholder: "/path/to/hisat2_index/genome"
    condition:
      field: "aligner"
      operator: "eq"
      value: "HISAT2"

  - name: strandness
    label: "链特异性"
    type: select
    required: true
    default: "unstranded"
    help_text: "文库链特异性类型"
    select_config:
      options:
        - label: "非链特异性 (unstranded)"
          value: "unstranded"
        - label: "正向链 (forward)"
          value: "forward"
          help_text: "second-strand synthesis, e.g. TruSeq Stranded"
        - label: "反向链 (reverse)"
          value: "reverse"
          help_text: "first-strand synthesis, e.g. dUTP method"

  # ----------------------------------------------------------
  # 二、差异比较设置（可重复 Group）
  # ----------------------------------------------------------
  - name: comparisons
    label: "差异比较组"
    type: group
    required: true
    help_text: "定义需要比较的分组，每组指定对照组和实验组"
    group_config:
      min_items: 1
      max_items: 10
      item_label: "比较组"
      add_button_text: "+ 添加差异比较组"
      parameters:
        - name: comparison_name
          label: "比较名称"
          type: string
          required: true
          help_text: "为该差异比较命名，如 'Tumor_vs_Normal'"
          placeholder: "Tumor_vs_Normal"
          string_config:
            regex_pattern: "^[A-Za-z][A-Za-z0-9_]*$"

        - name: control_group
          label: "对照组"
          type: string
          required: true
          help_text: "对照组名称（需与样本表中 group 列一致）"
          placeholder: "control"

        - name: treatment_group
          label: "实验组"
          type: string
          required: true
          help_text: "实验组名称（需与样本表中 group 列一致）"
          placeholder: "treatment"

        - name: fdr_threshold
          label: "FDR 阈值"
          type: float
          required: false
          default: 0.05
          help_text: "差异表达基因的 FDR 显著性阈值"
          number_config:
            min: 0.001
            max: 1.0
            step: 0.001
            use_slider: true
            precision: 3

        - name: log2fc_threshold
          label: "log2FC 阈值"
          type: float
          required: false
          default: 1.0
          help_text: "最小 log2 倍数变化阈值"
          number_config:
            min: 0.0
            max: 10.0
            step: 0.5
            use_slider: true

  # ----------------------------------------------------------
  # 三、定量参数
  # ----------------------------------------------------------
  - name: quantifier
    label: "定量工具"
    type: select
    required: true
    default: "featureCounts"
    select_config:
      options:
        - label: "featureCounts"
          value: "featureCounts"
        - label: "HTSeq-count"
          value: "htseq"
        - label: "Salmon (alignment-free)"
          value: "salmon"

  # ---- 复合条件：quantifier == "featureCounts" AND aligner != "bowtie2" ----
  - name: fc_count_multimapping
    label: "允许多重比对计数"
    type: boolean
    required: false
    default: false
    help_text: "featureCounts 是否对多重比对 reads 进行计数分配"
    condition:
      and_rules:
        - field: "quantifier"
          operator: "eq"
          value: "featureCounts"
        - field: "aligner"
          operator: "ne"
          value: "bowtie2"

  - name: gtf_annotation
    label: "GTF 注释文件"
    type: file
    required: true
    help_text: "基因注释 GTF 文件"
    file_config:
      accept: ".gtf,.gtf.gz,.gff3"
      max_size: 536870912   # 512 MB
      multiple: false

  # ----------------------------------------------------------
  # 四、高级参数（折叠 Section）
  # ----------------------------------------------------------
  - name: advanced_params
    label: "高级参数"
    type: section
    section_config:
      title: "高级分析参数"
      default_expanded: false
      description: "包含质控阈值、归一化方法等高级设置，一般无需修改"
      parameters:
        - name: min_read_quality
          label: "最小碱基质量值"
          type: int
          required: false
          default: 20
          help_text: "FastQC 质控最小碱基质量阈值（Phred score）"
          number_config:
            min: 0
            max: 40
            step: 1

        - name: min_read_length
          label: "最小 read 长度"
          type: int
          required: false
          default: 36
          help_text: "过滤后最小 read 长度"
          number_config:
            min: 10
            max: 150
            step: 1

        - name: normalization_method
          label: "归一化方法"
          type: select
          required: false
          default: "rlog"
          help_text: "DESeq2 数据归一化方法"
          select_config:
            options:
              - label: "rlog (推荐)"
                value: "rlog"
              - label: "vst (方差稳定变换)"
                value: "vst"
              - label: "TPM"
                value: "tpm"

        - name: cook_cutoff
          label: "Cook 距离截断值"
          type: float
          required: false
          default: 0.99
          help_text: "DESeq2 离群样本检测 Cook 距离分位数阈值"
          number_config:
            min: 0.5
            max: 1.0
            step: 0.01
            precision: 2

        - name: independent_filtering
          label: "启用独立过滤"
          type: boolean
          required: false
          default: true
          help_text: "DESeq2 独立过滤，提高检测功效"

        - name: batch_correction
          label: "批次效应校正"
          type: select
          required: false
          default: "none"
          help_text: "是否进行批次效应校正"
          select_config:
            options:
              - label: "不进行校正"
                value: "none"
              - label: "ComBat (sva)"
                value: "combat"
              - label: "RUVSeq"
                value: "ruvseq"

        # ---- 条件渲染：仅当 batch_correction != "none" ----
        - name: batch_column
          label: "批次列名"
          type: string
          required: true
          help_text: "样本表中标识批次的列名"
          placeholder: "batch"
          condition:
            field: "batch_correction"
            operator: "ne"
            value: "none"

  # ----------------------------------------------------------
  # 五、资源参数
  # ----------------------------------------------------------
  - name: use_gpu
    label: "使用 GPU 加速"
    type: boolean
    required: false
    default: false
    help_text: "启用 GPU 加速（如支持）"

  # ---- OR 复合条件示例：use_gpu == true OR aligner == "STAR" ----
  - name: max_memory_gb
    label: "最大内存 (GB)"
    type: int
    required: false
    default: 32
    help_text: "流程最大可用内存"
    number_config:
      min: 8
      max: 256
      step: 4

# ============================================================
# 执行配置
# ============================================================
execution:
  engine: snakemake
  snakefile: "workflows/rna_seq/Snakefile"
  conda_env: "rna_seq_env"
  default_resources:
    cores: 8
    memory: "32G"
    time: "4h"
  sample_sheet_format: csv
  extra_args:
    - "--use-conda"
    - "--latency-wait 60"
    - "--rerun-incomplete"

# ============================================================
# 样本表配置
# ============================================================
sample_sheet:
  columns:
    - name: sample_id
      required: true
      type: string
      description: "样本唯一标识符"
      example: "S001_Tumor"
      unique: true

    - name: group
      required: true
      type: string
      description: "分组信息（用于差异比较）"
      example: "Tumor"

    - name: fastq_1
      required: true
      type: string
      description: "R1 FASTQ 文件路径"
      example: "/data/fastq/S001_Tumor_R1.fastq.gz"

    - name: fastq_2
      required: false
      type: string
      description: "R2 FASTQ 文件路径（双端测序）"
      example: "/data/fastq/S001_Tumor_R2.fastq.gz"

    - name: batch
      required: false
      type: string
      description: "批次信息（用于批次效应校正）"
      example: "batch_1"

    - name: replicate
      required: false
      type: int
      description: "生物学重复编号"
      example: "1"

  validation_rules:
    - type: unique_combination
      columns: ["sample_id"]
      message: "sample_id 必须唯一"

    - type: mutual_exclusive
      columns: ["fastq_2"]
      message: "双端测序样本必须提供 R2 文件"
```

---

### 2.2 YAML 示例参数说明

| 参数区域 | 展示内容 | 对应参数类型 |
|---------|---------|------------|
| 基本参数 | genome, aligner, strandness | select |
| 条件渲染 | star_index/star_threads（aligner==STAR）| string, int + condition |
| 条件渲染 | hisat2_index（aligner==HISAT2）| string + condition |
| 可重复组 | comparisons（差异比较）| group |
| 复合条件 | fc_count_multimapping（AND 条件）| boolean + and_rules |
| 文件上传 | gtf_annotation | file |
| 折叠区域 | advanced_params 内含 6 个子参数 | section |
| 嵌套条件 | batch_column（section 内条件参数）| string + condition |
| 布尔开关 | use_gpu, independent_filtering | boolean |
| 数值参数 | max_memory_gb, fdr_threshold, log2fc_threshold | int/float + number_config |

---

## 3. 参数联动与条件渲染设计

### 3.1 条件渲染规则完整说明

#### 3.1.1 运算符语义表

| 运算符 | 语义 | 适用类型 | value 类型 | 示例 |
|-------|------|---------|-----------|------|
| `eq` | 等于 | 任意 | 与字段同类型 | `{"field":"aligner","operator":"eq","value":"STAR"}` |
| `ne` | 不等于 | 任意 | 与字段同类型 | `{"field":"aligner","operator":"ne","value":"bowtie2"}` |
| `gt` | 大于 | int, float | 数值 | `{"field":"fdr","operator":"gt","value":0.01}` |
| `lt` | 小于 | int, float | 数值 | `{"field":"threads","operator":"lt","value":32}` |
| `gte` | 大于等于 | int, float | 数值 | `{"field":"cores","operator":"gte","value":4}` |
| `lte` | 小于等于 | int, float | 数值 | `{"field":"memory","operator":"lte","value":64}` |
| `in` | 包含于 | select(multi) | list | `{"field":"tags","operator":"in","value":["QC","DE"]}` |
| `not_in` | 不包含于 | select(multi) | list | `{"field":"method","operator":"not_in","value":["old"]}` |
| `contains` | 包含 | string, select(multi) | 任意 | `{"field":"genome","operator":"contains","value":"hg"}` |
| `exists` | 存在且非空 | 任意 | 不需要 | `{"field":"batch_column","operator":"exists"}` |
| `regex` | 正则匹配 | string | pattern | `{"field":"sample_id","operator":"regex","value":"^S[0-9]+"}` |

#### 3.1.2 复合条件逻辑

```yaml
# AND 条件 — 所有子条件必须同时满足
condition:
  and_rules:
    - field: "quantifier"
      operator: "eq"
      value: "featureCounts"
    - field: "aligner"
      operator: "ne"
      value: "bowtie2"

# OR 条件 — 任一子条件满足即可
condition:
  or_rules:
    - field: "use_gpu"
      operator: "eq"
      value: true
    - field: "aligner"
      operator: "eq"
      value: "STAR"

# 嵌套条件 — AND 中包含 OR
condition:
  and_rules:
    - field: "batch_correction"
      operator: "ne"
      value: "none"
    - or_rules:
        - field: "tool_version"
          operator: "gte"
          value: "2.0"
        - field: "force_run"
          operator: "eq"
          value: true
```

---

### 3.2 前端条件渲染实现

#### 3.2.1 Vue 3 条件渲染组件

```typescript
// composables/useConditionEvaluator.ts
// 条件规则评估器（前端复刻版）

import { type ConditionRule, type ConditionOperator } from "@/types/schema";

export function useConditionEvaluator() {
  /**
   * 评估条件规则
   */
  function evaluate(
    rule: ConditionRule,
    formValues: Record<string, any>
  ): boolean {
    // 复合条件：AND
    if (rule.and_rules && rule.and_rules.length > 0) {
      return rule.and_rules.every((r) => evaluate(r, formValues));
    }

    // 复合条件：OR
    if (rule.or_rules && rule.or_rules.length > 0) {
      return rule.or_rules.some((r) => evaluate(r, formValues));
    }

    // 简单条件
    if (!rule.field || !rule.operator) return true;

    const actual = formValues[rule.field];
    return compare(actual, rule.operator, rule.value);
  }

  /**
   * 单次比较
   */
  function compare(
    actual: any,
    operator: ConditionOperator,
    expected: any
  ): boolean {
    switch (operator) {
      case "exists":
        return actual !== null && actual !== undefined && actual !== "";
      case "eq":
        return actual === expected;
      case "ne":
        return actual !== expected;
      case "gt":
        return actual !== null && actual > expected;
      case "lt":
        return actual !== null && actual < expected;
      case "gte":
        return actual !== null && actual >= expected;
      case "lte":
        return actual !== null && actual <= expected;
      case "in":
        return Array.isArray(expected) && expected.includes(actual);
      case "not_in":
        return Array.isArray(expected) && !expected.includes(actual);
      case "contains":
        if (typeof actual === "string") return actual.includes(expected);
        if (Array.isArray(actual)) return actual.includes(expected);
        return false;
      case "regex":
        if (typeof actual === "string" && typeof expected === "string") {
          return new RegExp(expected).test(actual);
        }
        return false;
      default:
        return false;
    }
  }

  return { evaluate, compare };
}
```

#### 3.2.2 动态表单渲染组件

```vue
<!-- components/FlowForm.vue -->
<template>
  <n-form
    ref="formRef"
    :model="formValues"
    :rules="activeRules"
    label-placement="left"
    label-width="auto"
  >
    <template v-for="param in sortedParameters" :key="param.name">
      <DynamicFormItem
        v-if="isVisible(param)"
        :parameter="param"
        v-model:value="formValues[param.name]"
        @update:value="onParamChange(param.name, $event)"
      />
    </template>
  </n-form>
</template>

<script setup lang="ts">
import { ref, computed, watch, reactive } from "vue";
import type { Parameter, FlowConfig } from "@/types/schema";
import { useConditionEvaluator } from "@/composables/useConditionEvaluator";
import DynamicFormItem from "./DynamicFormItem.vue";

const props = defineProps<{
  config: FlowConfig;
}>();

const formRef = ref();
const formValues = reactive<Record<string, any>>({});
const { evaluate } = useConditionEvaluator();

// 按 order 排序的参数
const sortedParameters = computed(() =>
  [...props.config.parameters].sort((a, b) => a.order - b.order)
);

// 判断参数是否可见
function isVisible(param: Parameter): boolean {
  if (!param.condition) return true;
  return evaluate(param.condition, formValues);
}

// 收集所有可见参数的规则
const activeRules = computed(() => {
  const rules: Record<string, any> = {};

  function collectRules(params: Parameter[], prefix = "") {
    for (const p of params) {
      const visible = isVisible(p);
      if (!visible) continue;

      if (p.required) {
        rules[`${prefix}${p.name}`] = {
          required: true,
          message: `'${p.label}' 是必填项`,
          trigger: ["blur", "change"],
        };
      }

      // 递归收集 GROUP / SECTION 内规则
      if (p.type === "group" && p.group_config) {
        const arr = (formValues[p.name] as any[]) || [];
        arr.forEach((_, i) => {
          collectRules(p.group_config!.parameters, `${p.name}[${i}].`);
        });
      }
      if (p.type === "section" && p.section_config) {
        collectRules(p.section_config.parameters, `${p.name}.`);
      }
    }
  }

  collectRules(props.config.parameters);
  return rules;
});

// 参数值变化时，触发条件重新评估
function onParamChange(name: string, value: any) {
  formValues[name] = value;
  // 条件依赖已自动通过响应式追踪（formValues 是 reactive 对象）
}

// 收集表单值（提交用）
function collectValues(): Record<string, any> {
  return JSON.parse(JSON.stringify(formValues));
}

defineExpose({
  collectValues,
  validate: () => formRef.value?.validate(),
});
</script>
```

#### 3.2.3 单个动态参数组件映射

```vue
<!-- components/DynamicFormItem.vue -->
<template>
  <n-form-item :label="parameter.label" :path="parameter.name">
    <!-- STRING -->
    <n-input
      v-if="parameter.type === 'string'"
      v-model:value="localValue"
      :placeholder="parameter.placeholder"
      :maxlength="parameter.string_config?.max_length"
      :type="parameter.string_config?.multiline ? 'textarea' : 'text'"
      :rows="parameter.string_config?.rows"
    />

    <!-- INT / FLOAT -->
    <template v-else-if="parameter.type === 'int' || parameter.type === 'float'">
      <n-slider
        v-if="parameter.number_config?.use_slider"
        v-model:value="localValue"
        :min="parameter.number_config.min"
        :max="parameter.number_config.max"
        :step="parameter.number_config.step"
        :marks="parameter.number_config.slider_marks"
      />
      <n-input-number
        v-else
        v-model:value="localValue"
        :min="parameter.number_config?.min"
        :max="parameter.number_config?.max"
        :step="parameter.number_config?.step"
        :precision="parameter.type === 'float' ? parameter.number_config?.precision : 0"
        :placeholder="parameter.placeholder"
      />
    </template>

    <!-- SELECT -->
    <n-select
      v-else-if="parameter.type === 'select'"
      v-model:value="localValue"
      :options="selectOptions"
      :multiple="parameter.select_config?.multi"
      :clearable="parameter.select_config?.allow_clear"
      :filterable="parameter.select_config?.searchable"
      :placeholder="parameter.placeholder || '请选择'"
    />

    <!-- FILE -->
    <n-upload
      v-else-if="parameter.type === 'file'"
      v-model:file-list="fileList"
      :accept="parameter.file_config?.accept"
      :max-size="parameter.file_config?.max_size"
      :multiple="parameter.file_config?.multiple"
      :directory-dnd="parameter.file_config?.directory"
      @update:file-list="onFileChange"
    >
      <n-button>选择文件</n-button>
    </n-upload>

    <!-- BOOLEAN -->
    <n-switch
      v-else-if="parameter.type === 'boolean'"
      v-model:value="localValue"
    />

    <!-- GROUP（可重复） -->
    <RepeatableGroup
      v-else-if="parameter.type === 'group'"
      :config="parameter.group_config!"
      v-model:items="localValue"
    />

    <!-- SECTION（折叠区域） -->
    <CollapsibleSection
      v-else-if="parameter.type === 'section'"
      :config="parameter.section_config!"
      v-model:values="localValue"
    />

    <!-- help_text 提示 -->
    <template #feedback v-if="parameter.help_text">
      <n-tooltip>
        <template #trigger>
          <n-icon><HelpCircleOutline /></n-icon>
        </template>
        {{ parameter.help_text }}
      </n-tooltip>
    </template>
  </n-form-item>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { Parameter } from "@/types/schema";

const props = defineProps<{
  parameter: Parameter;
  value: any;
}>();

const emit = defineEmits<{
  "update:value": [value: any];
}>();

const localValue = computed({
  get: () => props.value,
  set: (v) => emit("update:value", v),
});

// SELECT 选项转换
const selectOptions = computed(() => {
  if (!props.parameter.select_config) return [];
  return props.parameter.select_config.options.map((opt) => ({
    label: opt.label,
    value: opt.value,
    // help 可在 render-option 中展示
  }));
});

// 文件列表
const fileList = computed({
  get: () => (props.value ? [props.value] : []),
  set: (list) => emit("update:value", list?.[0] || null),
});

function onFileChange(list: any[]) {
  emit("update:value", list?.[0] || null);
}
</script>
```

---

### 3.3 可重复 Group 设计

#### 3.3.1 前端渲染（动态增删）

```vue
<!-- components/RepeatableGroup.vue -->
<template>
  <div class="repeatable-group">
    <div
      v-for="(item, index) in items"
      :key="index"
      class="group-item"
    >
      <n-card :title="`${config.item_label} #${index + 1}`" size="small">
        <template #header-extra>
          <n-button
            v-if="items.length > config.min_items"
            text
            type="error"
            @click="removeItem(index)"
          >
            删除
          </n-button>
        </template>

        <!-- 组内参数渲染 -->
        <template v-for="param in config.parameters" :key="param.name">
          <DynamicFormItem
            v-if="isGroupParamVisible(param, item)"
            :parameter="param"
            v-model:value="item[param.name]"
          />
        </template>
      </n-card>
    </div>

    <n-button
      v-if="!config.max_items || items.length < config.max_items"
      dashed
      block
      @click="addItem"
    >
      {{ config.add_button_text }}
    </n-button>
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { GroupConfig, Parameter } from "@/types/schema";
import { useConditionEvaluator } from "@/composables/useConditionEvaluator";
import DynamicFormItem from "./DynamicFormItem.vue";

const props = defineProps<{
  config: GroupConfig;
  items: Record<string, any>[];
}>();

const emit = defineEmits<{
  "update:items": [items: Record<string, any>[]];
}>();

const items = computed({
  get: () => props.items,
  set: (v) => emit("update:items", v),
});

const { evaluate } = useConditionEvaluator();

// 创建空条目模板
function createEmptyItem(): Record<string, any> {
  const item: Record<string, any> = {};
  for (const p of props.config.parameters) {
    item[p.name] = p.default ?? null;
  }
  return item;
}

function addItem() {
  if (props.config.max_items && items.value.length >= props.config.max_items) {
    return;
  }
  items.value = [...items.value, createEmptyItem()];
}

function removeItem(index: number) {
  if (items.value.length <= props.config.min_items) return;
  items.value = items.value.filter((_, i) => i !== index);
}

// 组内参数可见性（基于当前组的局部值 + 全局值）
function isGroupParamVisible(param: Parameter, itemValues: Record<string, any>): boolean {
  if (!param.condition) return true;
  // 组内条件评估使用组内值
  return evaluate(param.condition, itemValues);
}
</script>
```

#### 3.3.2 后端数据结构处理

```python
# 可重复 Group 的数据结构示例
{
    "comparisons": [
        {
            "comparison_name": "Tumor_vs_Normal",
            "control_group": "Normal",
            "treatment_group": "Tumor",
            "fdr_threshold": 0.05,
            "log2fc_threshold": 1.0,
        },
        {
            "comparison_name": "Metastatic_vs_Primary",
            "control_group": "Primary",
            "treatment_group": "Metastatic",
            "fdr_threshold": 0.01,
            "log2fc_threshold": 1.5,
        },
    ]
}

# Snakemake config 生成时展开为列表
comparisons = config["comparisons"]  # -> Python list[dict]
```

#### 3.3.3 命名唯一性保证

| 层级 | 命名策略 | 示例 |
|------|---------|------|
| 顶层参数 | 直接 name | `aligner`, `genome` |
| Section 内参数 | section.name + `.` + param.name | `advanced_params.min_read_quality` |
| Group 内参数 | group.name + `[N].` + param.name | `comparisons[0].comparison_name` |

> Pydantic 的 `validate_unique_param_names` validator 在配置加载时递归检查所有层级的命名唯一性。

---

### 3.4 参数联动：数值滑块与输入框双向绑定

```vue
<!-- components/SliderInputPair.vue -->
<!-- 滑块与输入框双向绑定，用于 FLOAT/INT 类型参数 -->
<template>
  <div class="slider-input-pair">
    <n-slider
      v-model:value="localValue"
      :min="config.min"
      :max="config.max"
      :step="config.step"
      :marks="config.slider_marks"
      style="flex: 1"
    />
    <n-input-number
      v-model:value="localValue"
      :min="config.min"
      :max="config.max"
      :step="config.step"
      :precision="precision"
      style="width: 120px; margin-left: 12px"
    />
  </div>
</template>

<script setup lang="ts">
import { computed } from "vue";
import type { NumberConfig } from "@/types/schema";

const props = defineProps<{
  value: number;
  config: NumberConfig;
  isFloat: boolean;
}>();

const emit = defineEmits<{ "update:value": [value: number] }>();

const localValue = computed({
  get: () => props.value,
  set: (v) => emit("update:value", v),
});

const precision = computed(() =>
  props.isFloat ? (props.config.precision ?? 2) : 0
);
</script>

<style scoped>
.slider-input-pair {
  display: flex;
  align-items: center;
}
</style>
```

---

## 4. 前后端协同校验策略

### 4.1 前端校验（JSON Schema）

#### 4.1.1 Pydantic 转 JSON Schema

```python
# schemas/json_schema.py

from pydantic import TypeAdapter

from .flow_config import FlowConfig


def export_json_schema() -> dict:
    """
    导出 FlowConfig 的 JSON Schema (Draft 2020-12)
    供前端组件在编译时导入使用
    """
    adapter = TypeAdapter(FlowConfig)
    return adapter.json_schema()


def export_parameter_schema() -> dict:
    """
    导出 Parameter 的独立 JSON Schema
    供前端动态表单在运行时校验使用
    """
    from .parameter import Parameter
    adapter = TypeAdapter(Parameter)
    return adapter.json_schema()
```

#### 4.1.2 前端 Naive UI Form Rules 生成

```typescript
// utils/schemaToRules.ts
import type { Parameter, StringConfig, NumberConfig } from "@/types/schema";
import type { FormItemRule } from "naive-ui";

/**
 * 将 Parameter 定义转换为 Naive UI 的 FormItemRule[]
 */
export function parameterToRules(param: Parameter): FormItemRule[] {
  const rules: FormItemRule[] = [];

  // 必填校验
  if (param.required) {
    rules.push({
      required: true,
      message: `'${param.label}' 是必填项`,
      trigger: ["blur", "change"],
    });
  }

  // 类型专属校验
  switch (param.type) {
    case "string":
      if (param.string_config) {
        rules.push(...stringRules(param.string_config));
      }
      break;
    case "int":
    case "float":
      if (param.number_config) {
        rules.push(...numberRules(param.number_config, param.type));
      }
      break;
    case "select":
      if (param.select_config?.multi === false && param.select_config?.options) {
        const validValues = param.select_config.options.map((o) => o.value);
        rules.push({
          validator: (_rule: any, value: any) => {
            if (value === null || value === undefined) return true;
            return validValues.includes(value);
          },
          message: `请选择有效的选项`,
          trigger: "change",
        });
      }
      break;
    case "file":
      if (param.file_config?.max_size) {
        rules.push({
          validator: (_rule: any, value: any) => {
            if (!value) return true;
            const file = value.file || value;
            return file.size <= param.file_config!.max_size!;
          },
          message: `文件大小不能超过 ${formatBytes(param.file_config.max_size)}`,
          trigger: "change",
        });
      }
      break;
  }

  return rules;
}

function stringRules(config: StringConfig): FormItemRule[] {
  const rules: FormItemRule[] = [];
  if (config.min_length !== undefined) {
    rules.push({
      min: config.min_length,
      message: `最少 ${config.min_length} 个字符`,
      trigger: "blur",
    });
  }
  if (config.max_length !== undefined) {
    rules.push({
      max: config.max_length,
      message: `最多 ${config.max_length} 个字符`,
      trigger: "blur",
    });
  }
  if (config.regex_pattern) {
    const regex = new RegExp(config.regex_pattern);
    rules.push({
      pattern: regex,
      message: "格式不符合要求",
      trigger: "blur",
    });
  }
  return rules;
}

function numberRules(
  config: NumberConfig,
  type: "int" | "float"
): FormItemRule[] {
  const rules: FormItemRule[] = [];

  rules.push({
    type: type === "int" ? "integer" : "number",
    message: `必须是${type === "int" ? "整数" : "数值"}`,
    trigger: ["blur", "change"],
  });

  if (config.min !== undefined) {
    rules.push({
      validator: (_rule: any, value: any) => {
        if (value === null || value === undefined) return true;
        return value >= config.min!;
      },
      message: `不能小于 ${config.min}`,
      trigger: ["blur", "change"],
    });
  }
  if (config.max !== undefined) {
    rules.push({
      validator: (_rule: any, value: any) => {
        if (value === null || value === undefined) return true;
        return value <= config.max!;
      },
      message: `不能大于 ${config.max}`,
      trigger: ["blur", "change"],
    });
  }
  return rules;
}
```

---

### 4.2 后端校验（Pydantic）

#### 4.2.1 完整后端校验流程

```python
# services/task_validation.py

from pathlib import Path
from typing import Any

import pandas as pd
from pydantic import ValidationError

from app.schemas.flow_config import FlowConfig
from app.schemas.condition import ConditionalValidator
from app.schemas.enums import ParameterTypeEnum


class TaskValidationService:
    """任务提交校验服务"""

    @staticmethod
    async def validate_task_submission(
        config: FlowConfig,
        form_values: dict[str, Any],
        sample_sheet_df: pd.DataFrame | None = None,
    ) -> dict:
        """
        完整校验任务提交数据

        Returns:
            {"valid": bool, "errors": list[dict], "warnings": list[str]}
        """
        result = {"valid": True, "errors": [], "warnings": []}

        # 1. 校验条件参数必填项（仅校验可见参数）
        cond_errors = ConditionalValidator.validate_required(
            config.parameters, form_values
        )
        result["errors"].extend(cond_errors)

        # 2. 校验参数类型
        type_errors = await TaskValidationService._validate_types(
            config.parameters, form_values
        )
        result["errors"].extend(type_errors)

        # 3. 校验 GROUP 条目数
        group_errors = TaskValidationService._validate_group_counts(
            config.parameters, form_values
        )
        result["errors"].extend(group_errors)

        # 4. 校验样本表（如果需要）
        if config.sample_sheet and sample_sheet_df is not None:
            sheet_errors = TaskValidationService._validate_sample_sheet(
                config.sample_sheet, sample_sheet_df
            )
            result["errors"].extend(sheet_errors)
        elif config.sample_sheet and sample_sheet_df is None:
            result["errors"].append({
                "field": "sample_sheet",
                "message": "此流程需要上传样本表",
            })

        # 5. 校验文件参数（文件存在性）
        file_errors = await TaskValidationService._validate_files(
            config.parameters, form_values
        )
        result["errors"].extend(file_errors)

        result["valid"] = len(result["errors"]) == 0
        return result

    @staticmethod
    def _validate_types(
        parameters: list[Any], form_values: dict[str, Any], prefix: str = ""
    ) -> list[dict]:
        """校验参数类型一致性"""
        errors = []
        from app.schemas.condition import ConditionEvaluator

        for p in parameters:
            # 跳过不可见参数
            if p.condition and not ConditionEvaluator.evaluate(
                p.condition, form_values
            ):
                continue

            value = form_values.get(p.name)
            if value is None:
                continue

            # 类型校验
            if p.type == ParameterTypeEnum.INT and not isinstance(value, int):
                errors.append({
                    "field": f"{prefix}{p.name}",
                    "message": f"'{p.label}' 必须是整数",
                })
            elif p.type == ParameterTypeEnum.FLOAT and not isinstance(value, (int, float)):
                errors.append({
                    "field": f"{prefix}{p.name}",
                    "message": f"'{p.label}' 必须是数值",
                })
            elif p.type == ParameterTypeEnum.STRING and not isinstance(value, str):
                errors.append({
                    "field": f"{prefix}{p.name}",
                    "message": f"'{p.label}' 必须是字符串",
                })
            elif p.type == ParameterTypeEnum.BOOLEAN and not isinstance(value, bool):
                errors.append({
                    "field": f"{prefix}{p.name}",
                    "message": f"'{p.label}' 必须是布尔值",
                })

            # GROUP 递归校验
            if p.type == ParameterTypeEnum.GROUP and isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        sub_errors = TaskValidationService._validate_types(
                            p.group_config.parameters, item, f"{p.name}[{i}]."
                        )
                        errors.extend(sub_errors)

            # SECTION 递归校验
            if p.type == ParameterTypeEnum.SECTION and isinstance(value, dict):
                sub_errors = TaskValidationService._validate_types(
                    p.section_config.parameters, value, f"{p.name}."
                )
                errors.extend(sub_errors)

        return errors

    @staticmethod
    def _validate_group_counts(
        parameters: list[Any], form_values: dict[str, Any]
    ) -> list[dict]:
        """校验 GROUP 条目数是否在允许范围内"""
        errors = []

        for p in parameters:
            if p.type != ParameterTypeEnum.GROUP or not p.group_config:
                continue

            items = form_values.get(p.name, [])
            count = len(items) if isinstance(items, list) else 0

            if count < p.group_config.min_items:
                errors.append({
                    "field": p.name,
                    "message": f"'{p.label}' 至少需要 {p.group_config.min_items} 组",
                })

            if p.group_config.max_items and count > p.group_config.max_items:
                errors.append({
                    "field": p.name,
                    "message": f"'{p.label}' 最多允许 {p.group_config.max_items} 组",
                })

        return errors

    @staticmethod
    def _validate_sample_sheet(
        config: Any,  # SampleSheetConfig
        df: pd.DataFrame,
    ) -> list[dict]:
        """根据 YAML 样本表定义校验上传的样本表"""
        errors = []

        # 1. 检查必填列
        for col in config.columns:
            if col.required and col.name not in df.columns:
                errors.append({
                    "field": f"sample_sheet.{col.name}",
                    "message": f"样本表缺少必填列: '{col.name}'",
                })

        # 2. 检查列类型
        type_map = {"string": object, "int": "Int64", "float": float, "boolean": bool}
        for col in config.columns:
            if col.name not in df.columns:
                continue
            expected_dtype = type_map.get(col.type, object)
            try:
                if col.type == "int":
                    df[col.name] = pd.to_numeric(df[col.name], errors="coerce")
                    if df[col.name].isna().any():
                        errors.append({
                            "field": f"sample_sheet.{col.name}",
                            "message": f"列 '{col.name}' 包含非整数数据",
                        })
            except Exception as e:
                errors.append({
                    "field": f"sample_sheet.{col.name}",
                    "message": f"列 '{col.name}' 类型转换失败: {str(e)}",
                })

        # 3. 唯一性校验
        for col in config.columns:
            if col.unique and col.name in df.columns:
                if df[col.name].duplicated().any():
                    dupes = df[df[col.name].duplicated(keep=False)][col.name].unique()
                    errors.append({
                        "field": f"sample_sheet.{col.name}",
                        "message": f"列 '{col.name}' 存在重复值: {list(dupes)}",
                    })

        # 4. 自定义校验规则
        for rule in config.validation_rules:
            if rule.type == "unique_combination":
                subset = [c for c in rule.columns if c in df.columns]
                if subset and df[subset].duplicated().any():
                    errors.append({
                        "field": f"sample_sheet.{'.'.join(subset)}",
                        "message": rule.message,
                    })

        return errors

    @staticmethod
    async def _validate_files(
        parameters: list[Any], form_values: dict[str, Any]
    ) -> list[dict]:
        """校验文件参数：存在性、大小、扩展名"""
        errors = []

        for p in parameters:
            if p.type != ParameterTypeEnum.FILE or not p.file_config:
                continue

            value = form_values.get(p.name)
            if not value:
                continue

            files = value if isinstance(value, list) else [value]
            for file_info in files:
                if isinstance(file_info, str):
                    # 校验路径存在性
                    path = Path(file_info)
                    if not path.exists():
                        errors.append({
                            "field": p.name,
                            "message": f"文件不存在: {file_info}",
                        })

                if isinstance(file_info, dict) and "size" in file_info:
                    # 校验文件大小
                    if (
                        p.file_config.max_size
                        and file_info["size"] > p.file_config.max_size
                    ):
                        max_mb = p.file_config.max_size / (1024 * 1024)
                        errors.append({
                            "field": p.name,
                            "message": (
                                f"文件 '{file_info.get('name', 'unknown')}' "
                                f"大小超过限制 ({max_mb:.1f} MB)"
                            ),
                        })

                if isinstance(file_info, dict) and "name" in file_info:
                    # 校验扩展名
                    if p.file_config.accept and p.file_config.accept != "*":
                        accepted = [
                            ext.strip() for ext in p.file_config.accept.split(",")
                        ]
                        file_name = file_info["name"]
                        if not any(
                            file_name.endswith(ext) for ext in accepted
                        ):
                            errors.append({
                                "field": p.name,
                                "message": (
                                    f"文件 '{file_name}' 格式不符合要求，"
                                    f"允许: {p.file_config.accept}"
                                ),
                            })

        return errors
```

---

### 4.3 样本表校验流程（完整时序）

```
┌─────────────┐     ┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│   用户上传   │ ──▶ │  后端接收     │ ──▶ │  根据 YAML 定义  │ ──▶ │ 校验通过？   │
│  CSV/Excel   │     │  保存临时文件  │     │  校验样本表      │     │              │
└─────────────┘     └──────────────┘     └─────────────────┘     └──────┬───────┘
                                                                         │
                                                          ┌── 否 ──▶ 返回错误列表
                                                          │
                                                          ▼ 是
                                              ┌─────────────────────┐
                                              │  校验通过后写入任务   │
                                              │  目录的 samples.csv   │
                                              └─────────────────────┘
                                                         │
                                                         ▼
                                              ┌─────────────────────┐
                                              │  返回校验成功 +       │
                                              │  预览数据（前5行）    │
                                              └─────────────────────┘
```

**后端样本表处理接口：**

```python
# routers/sample_sheet.py

from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
import pandas as pd
import io

from app.schemas.flow_config import FlowConfig
from app.services.task_validation import TaskValidationService

router = APIRouter(prefix="/api/v1/sample-sheets", tags=["sample-sheet"])


@router.post("/validate/{flow_id}")
async def validate_sample_sheet(
    flow_id: str,
    file: UploadFile = File(...),
):
    """
    校验上传的样本表文件
    """
    # 1. 加载流程配置
    config = await load_flow_config(flow_id)
    if not config.sample_sheet:
        raise HTTPException(400, "此流程不需要样本表")

    # 2. 读取文件
    content = await file.read()
    try:
        if file.filename.endswith(".csv"):
            df = pd.read_csv(io.StringIO(content.decode("utf-8")))
        elif file.filename.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content))
        else:
            raise HTTPException(400, "仅支持 CSV 和 Excel 格式")
    except Exception as e:
        raise HTTPException(400, f"文件解析失败: {str(e)}")

    # 3. 校验
    result = TaskValidationService._validate_sample_sheet(
        config.sample_sheet, df
    )

    if result:
        return {
            "valid": False,
            "errors": result,
            "columns": list(df.columns),
            "row_count": len(df),
        }

    # 4. 返回预览
    return {
        "valid": True,
        "columns": list(df.columns),
        "row_count": len(df),
        "preview": df.head(5).to_dict("records"),
    }
```

---

## 5. 动态表单渲染架构

### 5.1 组件映射表

| 参数类型 (type) | Vue 组件 | Naive UI 组件 | 说明 |
|----------------|---------|--------------|------|
| `string` | `StringInput` | `n-input` | 文本/多行文本 |
| `int` | `NumberInput` | `n-input-number` / `n-slider` | 整数输入/滑块 |
| `float` | `NumberInput` | `n-input-number` / `n-slider` | 浮点数输入/滑块 |
| `select` | `SelectInput` | `n-select` | 单/多选下拉 |
| `file` | `FileUpload` | `n-upload` | 文件上传 |
| `boolean` | `BooleanInput` | `n-switch` | 开关 |
| `group` | `RepeatableGroup` | `n-card` + `n-button` | 可重复卡片组 |
| `section` | `CollapsibleSection` | `n-collapse` | 折叠区域 |

### 5.2 条件渲染响应式架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        响应式依赖图                              │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   formValues (reactive Proxy)                                   │
│       │                                                         │
│       ├── aligner = "STAR" ──────▶ star_index (visible=true)    │
│       │                    ──────▶ star_threads (visible=true)  │
│       │                                                         │
│       ├── aligner = "HISAT2" ────▶ hisat2_index (visible=true)  │
│       │                    ──────▶ star_index (visible=false)   │
│       │                                                         │
│       ├── quantifier = "featureCounts" ──┐                      │
│       │   AND aligner != "bowtie2"       ├──▶ fc_count_...      │
│       │                                  │    (visible=eval)     │
│       │                                  │                      │
│       └── batch_correction = "none" ────▶ batch_column           │
│                                          (visible=false)         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

> 关键设计：所有参数的 `v-if` 绑定到 `isVisible()` 函数，该函数读取 `formValues` 响应式对象。
> Vue 3 的自动依赖追踪会确保当 `formValues.xxx` 变化时，所有依赖该字段的条件参数自动重新评估。

### 5.3 表单值收集与提交

#### 5.3.1 表单值结构

```typescript
// 提交的表单值结构示例
interface TaskSubmission {
  flow_id: string;
  parameters: {
    genome: "hg38";
    aligner: "STAR";
    star_index: "/data/ref/hg38/STAR_index";
    star_threads: 8;
    strandness: "unstranded";
    comparisons: [
      {
        comparison_name: "Tumor_vs_Normal";
        control_group: "Normal";
        treatment_group: "Tumor";
        fdr_threshold: 0.05;
        log2fc_threshold: 1.0;
      },
      {
        comparison_name: "Metastatic_vs_Primary";
        control_group: "Primary";
        treatment_group: "Metastatic";
        fdr_threshold: 0.01;
        log2fc_threshold: 1.5;
      }
    ];
    quantifier: "featureCounts";
    fc_count_multimapping: false;
    gtf_annotation: { name: "genes.gtf"; size: 156000000; path: "/tmp/..." };
    advanced_params: {
      min_read_quality: 20;
      min_read_length: 36;
      normalization_method: "rlog";
      cook_cutoff: 0.99;
      independent_filtering: true;
      batch_correction: "none";
    };
    use_gpu: false;
    max_memory_gb: 32;
  };
  sample_sheet: "/uploads/task_001/samples.csv";
  resources: {
    cores: 8;
    memory: "32G";
    time: "4h";
  };
}
```

#### 5.3.2 提交 API

```python
# routers/task.py

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.schemas.flow_config import FlowConfig

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


class TaskCreateRequest(BaseModel):
    flow_id: str
    parameters: dict[str, Any]  # 动态表单值
    sample_sheet_path: str | None = None  # 已校验的样本表路径


@router.post("/")
async def create_task(
    request: TaskCreateRequest,
):
    """
    创建新分析任务
    """
    # 1. 加载流程配置
    config = await load_flow_config(request.flow_id)

    # 2. 完整校验（条件参数 + 类型 + 样本表）
    from app.services.task_validation import TaskValidationService

    sample_df = None
    if request.sample_sheet_path:
        sample_df = pd.read_csv(request.sample_sheet_path)

    validation = await TaskValidationService.validate_task_submission(
        config, request.parameters, sample_df
    )

    if not validation["valid"]:
        raise HTTPException(422, {
            "detail": "参数校验失败",
            "errors": validation["errors"],
        })

    # 3. 构建 Snakemake config
    snake_config = build_snakemake_config(config, request.parameters)

    # 4. 创建任务目录并写入配置
    task_dir = await create_task_directory(request.flow_id)
    await write_config_yaml(task_dir, snake_config)
    if request.sample_sheet_path:
        await copy_sample_sheet(request.sample_sheet_path, task_dir / "samples.csv")

    # 5. 提交到执行引擎
    task_id = await submit_to_engine(config.execution, task_dir)

    return {"task_id": task_id, "status": "queued"}


def build_snakemake_config(
    flow_config: FlowConfig,
    form_values: dict[str, Any],
) -> dict[str, Any]:
    """
    将表单值转换为 Snakemake 配置字典
    """
    config = dict(form_values)

    # 展开 Section 参数（将 section.name.value 扁平化）
    for param in flow_config.parameters:
        if param.type == ParameterTypeEnum.SECTION and param.section_config:
            section_values = config.get(param.name, {})
            if isinstance(section_values, dict):
                # 将 section 内的值提升到顶层（或保持嵌套，视 Snakefile 约定）
                for key, value in section_values.items():
                    config[f"{param.name}_{key}"] = value

    # 处理 GROUP 参数（Snakemake 直接接收列表）
    for param in flow_config.parameters:
        if param.type == ParameterTypeEnum.GROUP and param.group_config:
            group_values = config.get(param.name, [])
            if isinstance(group_values, list):
                config[param.name] = group_values

    return config
```

---

## 6. JSON Schema 导出

### 6.1 导出脚本

```python
# scripts/export_schema.py

"""
导出 JSON Schema 供前端 TypeScript 类型生成使用
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.schemas.json_schema import export_json_schema, export_parameter_schema


def main():
    # 导出完整配置 Schema
    schema = export_json_schema()
    output_path = Path("frontend/src/types/flow-config.schema.json")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(schema, f, indent=2, ensure_ascii=False)
    print(f"Schema exported to {output_path}")

    # 导出独立参数 Schema
    param_schema = export_parameter_schema()
    param_output = Path("frontend/src/types/parameter.schema.json")
    with open(param_output, "w", encoding="utf-8") as f:
        json.dump(param_schema, f, indent=2, ensure_ascii=False)
    print(f"Parameter schema exported to {param_output}")


if __name__ == "__main__":
    main()
```

### 6.2 前端类型生成

```bash
# package.json scripts
{
  "scripts": {
    "generate:types": "json2ts src/types/flow-config.schema.json > src/types/schema.d.ts"
  }
}

# 生成的 TypeScript 类型可直接用于表单组件
```

---

## 附录 A：条件渲染规则完整示例集

```yaml
# A1. 简单等于
condition:
  field: "aligner"
  operator: "eq"
  value: "STAR"

# A2. 简单不等于
condition:
  field: "batch_correction"
  operator: "ne"
  value: "none"

# A3. 数值范围
condition:
  field: "threads"
  operator: "gte"
  value: 4

# A4. 包含于列表
condition:
  field: "genome"
  operator: "in"
  value: ["hg38", "mm39", "rn6"]

# A5. 正则匹配
condition:
  field: "sample_id_pattern"
  operator: "regex"
  value: "^[A-Z]{2}[0-9]{3}$"

# A6. AND 复合
condition:
  and_rules:
    - field: "aligner"
      operator: "eq"
      value: "STAR"
    - field: "two_pass"
      operator: "eq"
      value: true

# A7. OR 复合
condition:
  or_rules:
    - field: "quantifier"
      operator: "eq"
      value: "salmon"
    - field: "aligner"
      operator: "eq"
      value: "bowtie2"

# A8. 嵌套复合（AND 中包含 OR）
condition:
  and_rules:
    - field: "run_qc"
      operator: "eq"
      value: true
    - or_rules:
        - field: "qc_tool"
          operator: "eq"
          value: "fastqc"
        - field: "qc_tool"
          operator: "eq"
          value: "multiqc"
```

---

## 附录 B：快速参考

### B.1 新增流程 YAML 的 checklist

- [ ] `meta.id` 全局唯一（小写下划线命名）
- [ ] `meta.version` 符合语义化版本规范
- [ ] 所有 `parameters[].name` 全局唯一（含 group/section 内参数）
- [ ] `condition` 引用的 field 存在于已定义的参数中
- [ ] `group_config.parameters` 非空
- [ ] `section_config.parameters` 非空
- [ ] 必填参数设置 `required: true`
- [ ] 样本表 `columns` 包含至少一列
- [ ] `snakefile` 路径相对于项目根目录

### B.2 文件上传大小参考

| 文件类型 | 典型大小 | 建议 max_size |
|---------|---------|-------------|
| GTF 注释 | 50-500 MB | 536870912 (512 MB) |
| 参考基因组 FASTA | 1-5 GB | 6442450944 (6 GB) |
| FASTQ 样本 | 1-10 GB | 直接使用路径而非上传 |
| 配置文件 | < 1 MB | 1048576 (1 MB) |

### B.3 命名规范

| 对象 | 规范 | 示例 |
|------|------|------|
| flow id | `^[a-z][a-z0-9_]*$` | `rna_seq`, `chip_seq_peak_calling` |
| 参数 name | `^[a-zA-Z_][a-zA-Z0-9_]*$` | `aligner`, `star_index`, `minQuality` |
| 版本号 | SemVer | `1.0.0`, `2.1.0-beta` |
| 列名 | `^[a-zA-Z_][a-zA-Z0-9_]*$` | `sample_id`, `fastq_1` |

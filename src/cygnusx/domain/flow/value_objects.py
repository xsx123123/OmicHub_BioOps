"""流程域值对象 — 基于 docs/modules/04_yaml_schema.md 规范

包含枚举、配置子模型、执行配置、样本表配置、流程元信息。
所有模型使用 Pydantic v2，extra="forbid" 严格校验。
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ============================================================
# 1. 枚举定义
# ============================================================


class ParameterTypeEnum(str, Enum):
    """参数类型枚举 — 前端据此选择渲染组件"""

    STRING = "string"  # 文本输入框
    INT = "int"  # 整数输入框 / 步进器
    FLOAT = "float"  # 浮点数输入框 / 滑块
    SELECT = "select"  # 下拉选择（单/多选）
    FILE = "file"  # 文件上传
    BOOLEAN = "boolean"  # 开关 / 复选框
    GROUP = "group"  # 可重复参数组（动态增减）
    SECTION = "section"  # 折叠区域（高级参数）


class ConditionOperatorEnum(str, Enum):
    """条件运算符枚举"""

    EQ = "eq"  # 等于
    NE = "ne"  # 不等于
    GT = "gt"  # 大于
    LT = "lt"  # 小于
    GTE = "gte"  # 大于等于
    LTE = "lte"  # 小于等于
    IN = "in"  # 包含于（value 为列表）
    NOT_IN = "not_in"  # 不包含于
    CONTAINS = "contains"  # 包含（字符串或列表）
    EXISTS = "exists"  # 字段存在且非空
    REGEX = "regex"  # 正则匹配


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


class _StrictModel(BaseModel):
    """严格模式基类 — 禁止额外字段"""

    model_config = ConfigDict(extra="forbid")


class SelectOption(_StrictModel):
    """下拉选项定义"""

    label: str = Field(..., description="显示标签")
    value: Any = Field(..., description="选项值")
    help_text: str = Field(default="", description="选项说明提示")


class StringConfig(_StrictModel):
    """STRING 类型专属配置"""

    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    regex_pattern: str | None = Field(default=None, description="正则校验模式")
    multiline: bool = Field(default=False, description="是否多行文本")
    rows: int = Field(default=3, ge=1, description="多行文本行数")


class NumberConfig(_StrictModel):
    """INT / FLOAT 类型专属配置"""

    min: float | None = None
    max: float | None = None
    step: float = 1.0
    use_slider: bool = Field(default=False, description="是否使用滑块组件")
    slider_marks: dict[str, str] | None = None
    precision: int = Field(default=2, ge=0, le=10, description="小数精度(FLOAT)")


class SelectConfig(_StrictModel):
    """SELECT 类型专属配置"""

    options: list[SelectOption] = Field(default=[], description="选项列表")
    multi: bool = Field(default=False, description="是否多选")
    allow_clear: bool = Field(default=True, description="允许清除")
    searchable: bool = Field(default=True, description="允许搜索")


class FileConfig(_StrictModel):
    """FILE 类型专属配置"""

    accept: str = Field(default="*", description="接受的文件扩展名，如 .fastq.gz")
    max_size: int | None = Field(default=None, description="最大文件大小（字节）")
    multiple: bool = Field(default=False, description="是否允许多文件")
    directory: bool = Field(default=False, description="是否为目录选择")
    show_file_list: bool = Field(default=True, description="是否显示文件列表")


class GroupConfig(_StrictModel):
    """GROUP 类型专属配置 — 可重复参数组。

    注：parameters 字段类型为 list[Parameter]，使用前向引用字符串。
    Parameter 在 entities.py 中定义，需在 entities.py 末尾调用 model_rebuild()。
    """

    min_items: int = Field(default=1, ge=0, description="最少组数")
    max_items: int | None = Field(default=None, ge=1, description="最多组数")
    item_label: str = Field(default="条目", description="单组显示标签")
    add_button_text: str = Field(default="+ 添加", description="添加按钮文案")
    parameters: list[Parameter] = Field(  # type: ignore[name-defined]
        default=[], description="组内参数定义（递归）"
    )


class SectionConfig(_StrictModel):
    """SECTION 类型专属配置 — 折叠区域。

    注：同 GroupConfig，parameters 使用前向引用。
    """

    title: str = Field(default="高级设置", description="折叠区域标题")
    default_expanded: bool = Field(default=False, description="默认展开")
    description: str = Field(default="", description="区域说明")
    parameters: list[Parameter] = Field(  # type: ignore[name-defined]
        default=[], description="区域内参数定义（递归）"
    )


# ============================================================
# 3. 执行配置模型
# ============================================================


class ResourcesConfig(_StrictModel):
    """计算资源配置"""

    cores: int = Field(default=4, ge=1, le=128, description="CPU核心数")
    memory: str = Field(default="8G", pattern=r"^\d+[GMT]B?$", description="内存")
    time: str = Field(default="2h", pattern=r"^\d+[smhd]$", description="运行时间限制")


class ExecutionConfig(_StrictModel):
    """流程执行配置"""

    engine: Literal["snakemake", "nextflow"] = Field(default="snakemake", description="执行引擎")
    snakefile: str = Field(..., description="Snakefile 路径（相对于项目根目录）")
    conda_env: str | None = Field(default=None, description="Conda 环境名")
    config_file_name: str = Field(
        default="config.yaml", description="流程主配置文件名（生成在工作目录下）"
    )
    default_resources: ResourcesConfig = Field(
        default_factory=ResourcesConfig, description="默认计算资源"
    )
    sample_sheet_format: Literal["csv", "excel", "json"] = Field(
        default="csv", description="样本表格式"
    )
    extra_args: list[str] = Field(default=[], description="额外传给 Snakemake 的参数")
    config_file_param: str | None = Field(
        default=None, description="流程通过 --config <param>=<config_file> 接收配置时的参数名"
    )


# ============================================================
# 4. 样本表配置模型
# ============================================================


class SampleSheetColumn(_StrictModel):
    """样本表列定义"""

    name: str = Field(..., pattern=r"^[a-zA-Z_][a-zA-Z0-9_]*$", description="列名")
    required: bool = Field(default=True, description="是否必填")
    type: Literal["string", "int", "float", "boolean"] = Field(
        default="string", description="列数据类型"
    )
    description: str = Field(default="", description="列说明")
    example: str | None = Field(default=None, description="示例值")
    unique: bool = Field(default=False, description="是否唯一")
    allowed_values: list[str] | None = Field(default=None, description="允许的枚举值")


class ValidationRule(_StrictModel):
    """样本表自定义校验规则"""

    type: Literal["unique_combination", "mutual_exclusive", "regex"] = Field(
        ..., description="规则类型"
    )
    columns: list[str] = Field(..., description="涉及的列名")
    message: str = Field(default="校验失败", description="失败提示信息")
    regex_pattern: str | None = Field(default=None, description="正则模式（regex类型）")


# ============================================================
# 4A. 前端 UI 提示模型（YAML 驱动表单渲染）
# ============================================================


class ParameterUIHint(_StrictModel):
    """参数级前端渲染提示 — 全部字段可选，向后兼容。

    渲染器对缺失提示有合理默认：
    - 未声明 group → 按 required 归 basic / boolean 归 modules / 其余归 advanced
    - string 且 key 含 dir|path → widget=path；boolean → switch；enum → select
    """

    group: str | None = Field(default=None, description="分组 id（对应 FlowGroupDefinition.id）")
    order: int | None = Field(default=None, description="组内排序权重")
    span: Literal[1, 2] | None = Field(default=None, description="占列数：1=半行 2=整行")
    widget: str | None = Field(
        default=None, description="控件类型：input|select|switch|path|textarea"
    )
    placeholder: str | None = Field(default=None, description="输入占位文本")
    subgroup: str | None = Field(default=None, description="模块组内二级小标题")
    exclusive: bool = Field(
        default=False, description="互斥开关：开启时其余模块置灰"
    )
    show_when: dict[str, Any] | None = Field(
        default=None, description="条件显示规则，如 {field: 'deg', value: true}"
    )
    linked_group_column: str | None = Field(
        default=None, description="联动样本表分组列（供比较组 select 取值）"
    )


class FlowGroupDefinition(_StrictModel):
    """流程级分组定义 — 用于前端表单分区渲染。

    缺省时渲染器使用默认三组（basic / modules / advanced）。
    """

    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$", description="分组唯一标识")
    title: str = Field(..., min_length=1, description="分组标题")
    desc: str = Field(default="", description="分组说明（标题右侧灰色文字）")
    collapsible: bool = Field(default=False, description="是否可折叠")
    collapsed: bool = Field(default=False, description="默认是否收起（需 collapsible=true）")


class SampleSheetUIConfig(_StrictModel):
    """样本表前端渲染提示"""

    import_: list[str] = Field(
        default=[],
        alias="import",
        serialization_alias="import",
        description="允许的批量导入方式：paste|csv|datacenter",
    )
    group_column: str | None = Field(
        default=None, description="标记分组列（供比较组联动去重取值）"
    )

    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SampleSheetConfig(_StrictModel):
    """样本表整体配置"""

    columns: list[SampleSheetColumn] = Field(..., min_length=1, description="列定义列表")
    validation_rules: list[ValidationRule] = Field(default=[], description="自定义校验规则")
    ui: SampleSheetUIConfig | None = Field(default=None, description="样本表前端渲染提示")


# ============================================================
# 5. 流程输入文件映射配置（通用构建器使用）
# ============================================================


class SampleSheetMappingConfig(_StrictModel):
    """样本表 CSV 输出映射配置。

    columns 为字典：key 是输出 CSV 列名，value 是 sample_sheet 行数据中的字段名。
    """

    output_name: str = Field(default="samples.csv", description="输出文件名")
    columns: dict[str, str] = Field(..., min_length=1, description="CSV 列名 → 输入字段名映射")


class ComparisonsMappingConfig(_StrictModel):
    """差异比较组 CSV 输出映射配置（如 contrasts.csv）。"""

    output_name: str = Field(default="contrasts.csv", description="输出文件名")
    columns: dict[str, str] = Field(..., min_length=1, description="CSV 列名 → 输入字段名映射")


class PipelineMappingConfig(_StrictModel):
    """YAML 解释器映射配置 — 声明前端参数如何转为底层流程输入文件。

    - config_fields: 需要写入主配置文件的字段列表。支持点号路径
      （如 "peak_calling.use_pooled_peaks"），此时会生成嵌套字典。
    - computed_fields: 由构建器动态计算的字段（如工作目录、样本表路径）。
      取值使用占位符：__work_dir__、__samples_csv__、__contrasts_csv__。
    - list_fields: 需要强制转换为字符串列表的字段（如 raw_data_path）。
    - defaults: 当前端未提供某字段时的默认值。
    - sample_sheet: 样本表 CSV 生成规则。
    - comparisons: 差异比较组 CSV 生成规则（可选）。
    """

    config_fields: list[str] = Field(
        default=[], description="写入主配置文件的字段列表（支持点号嵌套路径）"
    )
    computed_fields: dict[str, str] = Field(default={}, description="动态计算字段：输出键 → 占位符")
    list_fields: list[str] = Field(default=[], description="需要强制转为字符串列表的字段名")
    defaults: dict[str, Any] = Field(default={}, description="字段默认值（当前端未传或为空时使用）")
    sample_sheet: SampleSheetMappingConfig | None = Field(
        default=None, description="样本表 CSV 生成规则"
    )
    comparisons: ComparisonsMappingConfig | None = Field(
        default=None, description="差异比较组 CSV 生成规则"
    )


# ============================================================
# 6. 流程元信息
# ============================================================


class FlowMeta(_StrictModel):
    """流程元信息"""

    id: str = Field(..., pattern=r"^[a-z][a-z0-9_]*$", description="唯一标识符")
    name: str = Field(..., min_length=1, description="显示名称")
    category: str = Field(..., description="分类")
    version: str = Field(..., pattern=r"^\d+\.\d+\.\d+(-\w+)?$", description="语义化版本")
    description: str = Field(..., min_length=1, description="流程描述")
    author: str | None = Field(default=None, description="作者")
    tags: list[str] = Field(default=[], description="标签列表")
    icon: str | None = Field(default=None, description="图标，支持 Emoji 或图标名")
    color: str | None = Field(default=None, description="主题色 key，如 chart-1")
    docs_url: str | None = Field(default=None, description="文档链接")
    github_url: str | None = Field(default=None, description="GitHub 源码链接")


class FlowDialogueExample(_StrictModel):
    """给 LLM 的示例对话片段。"""

    user: str = Field(..., description="用户问句")
    assistant: str = Field(..., description="助手回复")


class FlowAIConfig(_StrictModel):
    """流程的 AI 助手接入配置。

    声明该流程是否对 AI 可见、工具 slug、参数白名单、确认策略等。
    """

    enabled: bool = Field(default=False, description="是否对 AI 助手可见")
    tool_slug: str | None = Field(default=None, description="MCP tool 名后缀；默认使用 flow_id")
    assistant_summary: str = Field(default="", description="给 LLM 的简短能力说明")
    requires_confirmation: bool = Field(default=True, description="是否需要用户二次确认")
    allowed_execution_modes: list[Literal["local", "remote"]] = Field(
        default=["local"], description="允许的执行模式"
    )
    allowed_parameters: list[str] = Field(default=[], description="AI 可提交的参数白名单")
    default_resource_hint: dict[str, Any] = Field(
        default_factory=dict, description="默认资源提示（cores/memory/time）"
    )
    max_samples: int | None = Field(default=None, ge=1, description="最大样本数限制")
    max_comparisons: int | None = Field(default=None, ge=1, description="最大比较组数限制")
    example_dialogue: list[FlowDialogueExample] = Field(default=[], description="示例对话")

    @field_validator("tool_slug")
    @classmethod
    def _validate_tool_slug(cls, v: str | None) -> str | None:
        if v is None:
            return v
        if not re.match(r"^[a-z][a-z0-9_]*$", v):
            raise ValueError("tool_slug 只能包含小写字母、数字和下划线，且以小写字母开头")
        return v

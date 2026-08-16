"""Flow 提交参数校验器。

职责：
- 参数白名单校验
- 条件可见性处理
- 样本表校验
- 比较组校验
- 文件引用校验
- 转换为标准 TaskSubmitRequest
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from omichub.application.schemas.task import TaskSubmitRequest
from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.managed_file_resolver import ManagedFileResolver
from omichub.domain.flow.entities import ConditionRule, FlowConfig, Parameter
from omichub.domain.flow.value_objects import (
    FlowAIConfig,
    ParameterTypeEnum,
    SampleSheetConfig,
)


class ValidationErrorItem(BaseModel):
    """单个校验错误。"""

    field: str
    code: str
    message: str
    suggestion: str | None = None


class ValidationWarningItem(BaseModel):
    """单个校验警告。"""

    field: str
    code: str
    message: str


class ValidationResult(BaseModel):
    """校验结果。"""

    valid: bool
    errors: list[ValidationErrorItem]
    warnings: list[ValidationWarningItem]
    normalized_request: TaskSubmitRequest | None = None


class FlowSubmissionValidator:
    """Flow 提交参数校验器。"""

    def __init__(self, file_resolver: ManagedFileResolver | None = None):
        self._file_resolver = file_resolver or ManagedFileResolver()

    async def validate(
        self,
        context: ToolInvocationContext,
        flow: FlowConfig,
        arguments: dict[str, Any],
    ) -> ValidationResult:
        """校验参数并生成标准化 TaskSubmitRequest。"""
        ai = flow.ai or FlowAIConfig(enabled=False)
        errors: list[ValidationErrorItem] = []
        warnings: list[ValidationWarningItem] = []

        task_name = arguments.get("name")
        if not isinstance(task_name, str) or not task_name.strip():
            errors.append(
                ValidationErrorItem(
                    field="name",
                    code="MISSING_REQUIRED",
                    message="必须提供非空的任务名称",
                )
            )

        # 1. 白名单校验
        raw_params = arguments.get("parameters", {})
        if not isinstance(raw_params, dict):
            errors.append(
                ValidationErrorItem(
                    field="parameters",
                    code="TYPE_ERROR",
                    message="parameters 必须是对象",
                )
            )
            raw_params = {}

        if ai.allowed_parameters:
            allowed = set(ai.allowed_parameters)
            for key in list(raw_params.keys()):
                if key not in allowed:
                    errors.append(
                        ValidationErrorItem(
                            field=f"parameters.{key}",
                            code="PARAMETER_NOT_ALLOWED",
                            message=f"参数 '{key}' 不在 AI 可提交白名单中",
                        )
                    )

        # 2. 收集所有顶层参数名
        param_map = {p.name: p for p in flow.parameters}

        # 3. 条件参数处理 + 默认值填充
        normalized_params: dict[str, Any] = {}
        hidden_params: set[str] = set()
        for param in flow.parameters:
            if param.type == ParameterTypeEnum.SECTION:
                # 展开 section 内的参数
                section_params = param.section_config.parameters if param.section_config else []
                for child in section_params:
                    if child.condition and not self._evaluate_condition(child.condition, raw_params):
                        hidden_params.add(child.name)
                        continue
                    child_value = raw_params.get(child.name)
                    if child_value is None and child.default is not None:
                        child_value = child.default
                    normalized_params[child.name] = child_value
                continue

            if param.condition and not self._evaluate_condition(param.condition, raw_params):
                hidden_params.add(param.name)
                if param.name in raw_params:
                    warnings.append(
                        ValidationWarningItem(
                            field=f"parameters.{param.name}",
                            code="CONDITION_NOT_MET",
                            message=f"参数 '{param.name}' 在当前条件下不适用，已自动忽略",
                        )
                    )
                continue

            value = raw_params.get(param.name)
            if value is None and param.default is not None:
                value = param.default
            normalized_params[param.name] = value

        # 4. 必填校验 + 类型校验（跳过隐藏参数）
        for param in flow.parameters:
            if param.type == ParameterTypeEnum.SECTION:
                for child in param.section_config.parameters if param.section_config else []:
                    if child.name in hidden_params:
                        continue
                    self._validate_param_value(
                        child, normalized_params.get(child.name), f"parameters.{child.name}", errors
                    )
                continue
            if param.name in hidden_params:
                continue
            self._validate_param_value(
                param,
                normalized_params.get(param.name),
                f"parameters.{param.name}",
                errors,
            )

        # 5. 样本表校验
        sample_rows: list[dict[str, Any]] = []
        sample_sheet_arg = arguments.get("sample_sheet")
        if flow.sample_sheet is not None:
            if sample_sheet_arg is None:
                errors.append(
                    ValidationErrorItem(
                        field="sample_sheet",
                        code="MISSING_REQUIRED",
                        message="该流程需要提供样本表",
                    )
                )
            elif isinstance(sample_sheet_arg, str) and sample_sheet_arg.startswith("sample_sheet_ref://"):
                try:
                    meta = await self._file_resolver.resolve(
                        context, sample_sheet_arg, require_content=True
                    )
                    sample_rows = self._parse_sample_sheet_content(meta.content or "")
                except Exception as e:  # noqa: BLE001
                    errors.append(
                        ValidationErrorItem(
                            field="sample_sheet",
                            code="SAMPLE_SHEET_READ_ERROR",
                            message=str(e),
                        )
                    )
            elif isinstance(sample_sheet_arg, list):
                sample_rows = sample_sheet_arg
            else:
                errors.append(
                    ValidationErrorItem(
                        field="sample_sheet",
                        code="INVALID_SAMPLE_SHEET",
                        message="sample_sheet 必须是样本数组或 sample_sheet_ref:// 引用",
                    )
                )

            if sample_rows:
                self._validate_sample_sheet(flow.sample_sheet, sample_rows, errors)

            if ai.max_samples is not None and len(sample_rows) > ai.max_samples:
                errors.append(
                    ValidationErrorItem(
                        field="sample_sheet",
                        code="MAX_SAMPLES_EXCEEDED",
                        message=f"样本数 {len(sample_rows)} 超过限制 {ai.max_samples}",
                    )
                )

        # 6. 比较组校验
        comparisons = arguments.get("comparisons")
        if comparisons is not None:
            if not isinstance(comparisons, list):
                errors.append(
                    ValidationErrorItem(
                        field="comparisons",
                        code="INVALID_COMPARISONS",
                        message="comparisons 必须是数组",
                    )
                )
            else:
                self._validate_comparisons(flow, comparisons, sample_rows, errors)
                if ai.max_comparisons is not None and len(comparisons) > ai.max_comparisons:
                    errors.append(
                        ValidationErrorItem(
                            field="comparisons",
                            code="MAX_COMPARISONS_EXCEEDED",
                            message=f"比较组数 {len(comparisons)} 超过限制 {ai.max_comparisons}",
                        )
                    )

        # 7. 文件引用校验
        await self._validate_file_refs(context, normalized_params, param_map, errors)

        if errors:
            return ValidationResult(valid=False, errors=errors, warnings=warnings)

        # 8. 构造 TaskSubmitRequest
        clean_params = {k: v for k, v in normalized_params.items() if v is not None}

        request = TaskSubmitRequest(
            flow_id=flow.meta.id,
            name=task_name.strip(),
            parameters=clean_params,
            sample_sheet=sample_rows,
            comparisons=comparisons,
            execution_mode=arguments.get("execution_mode", "local"),
        )

        return ValidationResult(
            valid=True,
            errors=[],
            warnings=warnings,
            normalized_request=request,
        )

    def _validate_param_value(
        self,
        param: Parameter,
        value: Any,
        field_path: str,
        errors: list[ValidationErrorItem],
    ) -> None:
        """校验单个参数值。"""
        if value is None or value == "":
            if param.required:
                errors.append(
                    ValidationErrorItem(
                        field=field_path,
                        code="MISSING_REQUIRED",
                        message=f"缺少必填参数 '{param.name}'",
                        suggestion="请在参数中提供该字段",
                    )
                )
            return

        if param.type == ParameterTypeEnum.STRING and not isinstance(value, str):
            errors.append(
                ValidationErrorItem(
                    field=field_path, code="TYPE_ERROR", message=f"参数 '{param.name}' 应为字符串"
                )
            )
        elif param.type == ParameterTypeEnum.INT and not isinstance(value, int):
            errors.append(
                ValidationErrorItem(
                    field=field_path, code="TYPE_ERROR", message=f"参数 '{param.name}' 应为整数"
                )
            )
        elif param.type == ParameterTypeEnum.FLOAT and not isinstance(value, (int, float)):
            errors.append(
                ValidationErrorItem(
                    field=field_path, code="TYPE_ERROR", message=f"参数 '{param.name}' 应为数字"
                )
            )
        elif param.type == ParameterTypeEnum.BOOLEAN and not isinstance(value, bool):
            errors.append(
                ValidationErrorItem(
                    field=field_path, code="TYPE_ERROR", message=f"参数 '{param.name}' 应为布尔值"
                )
            )
        elif param.type == ParameterTypeEnum.SELECT and param.select_config:
            options = [opt.value for opt in param.select_config.options]
            if param.select_config.multi:
                if not isinstance(value, list):
                    errors.append(
                        ValidationErrorItem(
                            field=field_path, code="TYPE_ERROR", message=f"参数 '{param.name}' 应为数组"
                        )
                    )
                else:
                    for v in value:
                        if v not in options:
                            errors.append(
                                ValidationErrorItem(
                                    field=field_path,
                                    code="INVALID_ENUM",
                                    message=f"参数 '{param.name}' 包含非法值: {v}",
                                )
                            )
            else:
                if value not in options:
                    errors.append(
                        ValidationErrorItem(
                            field=field_path,
                            code="INVALID_ENUM",
                            message=f"参数 '{param.name}' 必须是 {options} 之一，实际为 {value}",
                        )
                    )

    def _validate_sample_sheet(
        self,
        sample_sheet_config: SampleSheetConfig,
        rows: list[dict[str, Any]],
        errors: list[ValidationErrorItem],
    ) -> None:
        """校验样本表行数据。"""
        columns = {col.name: col for col in sample_sheet_config.columns}

        for idx, row in enumerate(rows):
            row_prefix = f"sample_sheet[{idx}]"
            for col_name, col in columns.items():
                val = row.get(col_name)
                if col.required and (val is None or val == ""):
                    errors.append(
                        ValidationErrorItem(
                            field=f"{row_prefix}.{col_name}",
                            code="MISSING_REQUIRED",
                            message=f"第 {idx + 1} 行缺少必填列 '{col_name}'",
                        )
                    )

        for rule in sample_sheet_config.validation_rules or []:
            if rule.type == "unique_combination":
                seen: set[tuple[str, ...]] = set()
                for idx, row in enumerate(rows):
                    key = tuple(str(row.get(c, "")) for c in rule.columns)
                    if key in seen:
                        errors.append(
                            ValidationErrorItem(
                                field=f"sample_sheet[{idx}]",
                                code="UNIQUE_VIOLATION",
                                message=rule.message,
                            )
                        )
                    seen.add(key)

    def _validate_comparisons(
        self,
        flow: FlowConfig,
        comparisons: list[dict[str, Any]],
        sample_rows: list[dict[str, Any]],
        errors: list[ValidationErrorItem],
    ) -> None:
        """校验比较组：control/treat 必须存在于样本表 group 列。"""
        mapping = flow.pipeline_mapping
        control_col = "Control"
        treat_col = "Treat"
        if mapping and mapping.comparisons:
            cols = list(mapping.comparisons.columns.keys())
            if len(cols) >= 2:
                control_col, treat_col = cols[0], cols[1]

        groups = {str(row.get("group", "")) for row in sample_rows}

        for idx, comp in enumerate(comparisons):
            prefix = f"comparisons[{idx}]"
            if not isinstance(comp, dict):
                errors.append(
                    ValidationErrorItem(
                        field=prefix, code="INVALID_COMPARISON", message="比较组必须是对象"
                    )
                )
                continue

            name = comp.get("name")
            control = comp.get(control_col)
            treat = comp.get(treat_col)

            if not name:
                errors.append(
                    ValidationErrorItem(
                        field=f"{prefix}.name", code="MISSING_REQUIRED", message="比较组名称必填"
                    )
                )
            if not control:
                errors.append(
                    ValidationErrorItem(
                        field=f"{prefix}.{control_col}", code="MISSING_REQUIRED", message="对照组必填"
                    )
                )
            if not treat:
                errors.append(
                    ValidationErrorItem(
                        field=f"{prefix}.{treat_col}", code="MISSING_REQUIRED", message="实验组必填"
                    )
                )

            if control and str(control) not in groups:
                errors.append(
                    ValidationErrorItem(
                        field=f"{prefix}.{control_col}",
                        code="GROUP_NOT_FOUND",
                        message=f"对照组 '{control}' 不存在于样本表 group 列",
                    )
                )
            if treat and str(treat) not in groups:
                errors.append(
                    ValidationErrorItem(
                        field=f"{prefix}.{treat_col}",
                        code="GROUP_NOT_FOUND",
                        message=f"实验组 '{treat}' 不存在于样本表 group 列",
                    )
                )

    async def _validate_file_refs(
        self,
        context: ToolInvocationContext,
        params: dict[str, Any],
        param_map: dict[str, Parameter],
        errors: list[ValidationErrorItem],
    ) -> None:
        """校验参数中的文件引用。"""
        for key, value in params.items():
            param = param_map.get(key)
            if param is None or param.type not in (ParameterTypeEnum.STRING, ParameterTypeEnum.FILE):
                continue

            if not isinstance(value, str):
                continue

            ref = value.strip()
            if not (
                ref.startswith("upload://")
                or ref.startswith("file://")
                or ref.startswith("directory://")
            ):
                continue

            try:
                await self._file_resolver.resolve(context, ref, require_content=False)
            except Exception as e:  # noqa: BLE001
                errors.append(
                    ValidationErrorItem(
                        field=f"parameters.{key}",
                        code="FILE_RESOLUTION_ERROR",
                        message=str(e),
                    )
                )

    def _parse_sample_sheet_content(self, content: str) -> list[dict[str, Any]]:
        """简单解析 CSV/TSV 样本表内容。"""
        import csv
        import io

        if not content.strip():
            return []

        dialect = csv.Sniffer().sniff(content[:1024], delimiters=",\t")
        reader = csv.DictReader(io.StringIO(content), dialect=dialect)
        return [dict(row) for row in reader]

    def _evaluate_condition(self, condition: ConditionRule | None, params: dict[str, Any]) -> bool:
        """评估条件规则。"""
        if condition is None:
            return True

        if condition.and_rules:
            return all(self._evaluate_condition(r, params) for r in condition.and_rules)
        if condition.or_rules:
            return any(self._evaluate_condition(r, params) for r in condition.or_rules)

        if condition.field is None or condition.operator is None:
            return True

        actual = params.get(condition.field)
        op = condition.operator.value
        expected = condition.value

        if op == "eq":
            return actual == expected
        if op == "ne":
            return actual != expected
        if op == "in":
            return actual in (expected if isinstance(expected, (list, tuple, set)) else [expected])
        if op == "not_in":
            return actual not in (
                expected if isinstance(expected, (list, tuple, set)) else [expected]
            )
        if op == "exists":
            return actual is not None and actual != ""
        if op == "gt":
            return actual is not None and actual > expected
        if op == "lt":
            return actual is not None and actual < expected
        if op == "gte":
            return actual is not None and actual >= expected
        if op == "lte":
            return actual is not None and actual <= expected

        return True

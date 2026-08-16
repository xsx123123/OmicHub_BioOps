"""通用流程输入文件构建器。

通过解析 FlowConfig.pipeline_mapping，将前端表单参数动态转换为底层
Snakemake 流程所需的主配置文件（config.yaml/analysis.yaml）、样本表
（samples.csv）以及差异比较组表（contrasts.csv）。

设计目标：新增分析流程时，仅需补充 YAML 的 pipeline_mapping 节点，
无需修改 Python 代码。
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

import yaml

from omichub.core.exceptions import ValidationError
from omichub.domain.flow.entities import FlowConfig


class GenericFlowBuilder:
    """通用流程输入文件构建器。"""

    def build_project_files(
        self,
        flow_config: FlowConfig,
        parameters: dict[str, Any],
        sample_rows: list[dict[str, Any]],
        comparisons: list[dict[str, Any]] | None,
        work_dir: str | Path,
    ) -> dict[str, Path]:
        """根据 YAML 映射规则生成流程所需的全部输入文件。

        Args:
            flow_config: 流程配置（含 pipeline_mapping）。
            parameters: 前端提交的参数字典。
            sample_rows: 样本表行数据。
            comparisons: 差异比较组数据（可选）。
            work_dir: 任务工作目录。

        Returns:
            生成文件路径字典，至少包含 "config"。
            若生成样本表/比较组，还会包含 "samples" / "contrasts"。

        Raises:
            ValidationError: 当 pipeline_mapping 缺失或必要字段未提供时。
        """
        work_path = Path(work_dir)
        work_path.mkdir(parents=True, exist_ok=True)

        mapping = flow_config.pipeline_mapping
        if mapping is None:
            raise ValidationError(
                f"流程 '{flow_config.meta.id}' 缺少 pipeline_mapping 配置，无法生成底层流程输入文件"
            )

        result: dict[str, Path] = {}

        # 1. 生成样本表 CSV
        if mapping.sample_sheet is not None:
            samples_path = work_path / mapping.sample_sheet.output_name
            self._write_csv(
                rows=sample_rows,
                path=samples_path,
                column_map=mapping.sample_sheet.columns,
            )
            result["samples"] = samples_path

        # 2. 生成差异比较组 CSV
        if mapping.comparisons is not None:
            contrasts_path = work_path / mapping.comparisons.output_name
            self._write_csv(
                rows=comparisons or [],
                path=contrasts_path,
                column_map=mapping.comparisons.columns,
            )
            result["contrasts"] = contrasts_path

        # 3. 生成主配置文件
        config_path = work_path / flow_config.execution.config_file_name
        main_config = self._build_main_config(
            mapping=mapping,
            parameters=parameters,
            work_dir=work_path,
            samples_path=result.get("samples"),
            contrasts_path=result.get("contrasts"),
        )
        with config_path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(main_config, f, sort_keys=False, allow_unicode=True)

        result["config"] = config_path
        return result

    def _build_main_config(
        self,
        mapping: Any,
        parameters: dict[str, Any],
        work_dir: Path,
        samples_path: Path | None,
        contrasts_path: Path | None,
    ) -> dict[str, Any]:
        """根据映射规则构造主配置字典。"""
        config: dict[str, Any] = {}

        # 合并默认值与前端参数（前端参数优先级高）
        merged_params: dict[str, Any] = {}
        merged_params.update(mapping.defaults)
        merged_params.update(parameters)

        # 处理 raw_data_path 等路径字段的兜底：空字符串视为未提供
        for field_name in mapping.config_fields:
            value = self._resolve_field_value(
                field_name=field_name,
                merged_params=merged_params,
                mapping=mapping,
                work_dir=work_dir,
            )
            if value is None:
                continue
            self._set_nested_value(config, field_name, value)

        # 注入动态计算字段
        placeholder_values = {
            "__work_dir__": str(work_dir),
            "__samples_csv__": str(samples_path) if samples_path else "",
            "__contrasts_csv__": str(contrasts_path) if contrasts_path else "",
        }
        for output_key, placeholder in mapping.computed_fields.items():
            resolved = placeholder_values.get(placeholder, placeholder)
            self._set_nested_value(config, output_key, resolved)

        # 通用兜底：data_deliver 为空时，默认指向工作目录父目录的 data_deliver
        if not config.get("data_deliver"):
            config["data_deliver"] = str(work_dir.parent / "data_deliver")

        return config

    def _resolve_field_value(
        self,
        field_name: str,
        merged_params: dict[str, Any],
        mapping: Any,
        work_dir: Path,
    ) -> Any:
        """解析单个配置字段的值。

        支持点号路径：取最后一个段作为输入参数字段名。
        """
        input_field = field_name.split(".")[-1]
        value = merged_params.get(input_field)

        # 空字符串视为未提供
        if value == "" or value is None:
            return None

        # 强制转换为字符串列表（如 raw_data_path）
        if input_field in mapping.list_fields:
            return self._normalize_to_string_list(value)

        return value

    @staticmethod
    def _normalize_to_string_list(value: Any) -> list[str]:
        """统一值为字符串列表。"""
        if isinstance(value, list):
            return [str(v) for v in value if v not in (None, "")]
        if isinstance(value, str):
            stripped = value.strip()
            if stripped:
                return [stripped]
        return []

    @staticmethod
    def _set_nested_value(config: dict[str, Any], dotted_key: str, value: Any) -> None:
        """按点号路径在字典中设置嵌套值。"""
        parts = dotted_key.split(".")
        current = config
        for part in parts[:-1]:
            if part not in current or not isinstance(current[part], dict):
                current[part] = {}
            current = current[part]
        current[parts[-1]] = value

    @staticmethod
    def _write_csv(
        rows: list[dict[str, Any]],
        path: Path,
        column_map: dict[str, str],
    ) -> None:
        """按列映射写入 CSV。

        Args:
            rows: 输入数据行。
            path: 输出文件路径。
            column_map: 输出列名 → 输入字段名映射。
        """
        output_columns = list(column_map.keys())
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=output_columns)
            writer.writeheader()
            for row in rows:
                output_row = {
                    output_col: str(row.get(input_field, ""))
                    for output_col, input_field in column_map.items()
                }
                writer.writerow(output_row)

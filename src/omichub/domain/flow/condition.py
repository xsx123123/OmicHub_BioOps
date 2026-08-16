"""条件规则评估器 — 后端根据表单值计算参数是否应显示。

基于 docs/modules/04_yaml_schema.md §1.2 实现。
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from omichub.domain.flow.entities import ConditionRule
from omichub.domain.flow.value_objects import ConditionOperatorEnum, ParameterTypeEnum

if TYPE_CHECKING:
    from omichub.domain.flow.entities import Parameter


class ConditionEvaluator:
    """条件规则评估器 — 递归评估简单/复合条件"""

    @staticmethod
    def evaluate(rule: ConditionRule, form_values: dict[str, Any]) -> bool:
        """评估条件规则是否满足。

        Args:
            rule: 条件规则（简单或复合）
            form_values: 当前表单所有字段的值字典

        Returns:
            bool: 条件是否满足
        """
        # 复合条件：AND
        if rule.and_rules is not None:
            return all(ConditionEvaluator.evaluate(r, form_values) for r in rule.and_rules)

        # 复合条件：OR
        if rule.or_rules is not None:
            return any(ConditionEvaluator.evaluate(r, form_values) for r in rule.or_rules)

        # 简单条件
        if rule.field is None or rule.operator is None:
            return True

        actual_value = form_values.get(rule.field)

        return ConditionEvaluator._compare(actual_value, rule.operator, rule.value)

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
            try:
                return actual > expected
            except TypeError:
                return False
        if op == ConditionOperatorEnum.LT:
            try:
                return actual < expected
            except TypeError:
                return False
        if op == ConditionOperatorEnum.GTE:
            try:
                return actual >= expected
            except TypeError:
                return False
        if op == ConditionOperatorEnum.LTE:
            try:
                return actual <= expected
            except TypeError:
                return False

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
    """条件参数校验器 — 仅校验当前可见（condition 满足）的必填参数"""

    @staticmethod
    def get_visible_params(
        parameters: list[Parameter],
        form_values: dict[str, Any],
    ) -> list[str]:
        """获取当前条件下所有可见参数的名称列表。

        GROUP 参数展开为内部参数名（带 [N]. 前缀）。
        """
        visible: list[str] = []

        def check(param: Parameter, prefix: str = "") -> None:
            full_name = f"{prefix}{param.name}"

            # 检查条件
            if param.condition is not None:
                if not ConditionEvaluator.evaluate(param.condition, form_values):
                    return  # 条件不满足，参数不可见

            visible.append(full_name)

            # 递归处理 GROUP / SECTION
            if param.type == ParameterTypeEnum.GROUP and param.group_config:
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
        parameters: list[Parameter],
        form_values: dict[str, Any],
    ) -> list[dict[str, str]]:
        """校验可见的必填参数是否已填写。

        Returns:
            list[dict]: 错误列表，每项包含 field 和 message
        """
        errors: list[dict[str, str]] = []
        visible = set(ConditionalValidator.get_visible_params(parameters, form_values))

        def check(param: Parameter, prefix: str = "") -> None:
            full_name = f"{prefix}{param.name}"

            # 跳过不可见参数
            if full_name not in visible:
                return

            # 检查必填
            if param.required:
                value = form_values.get(param.name)
                if value is None or value == "":
                    errors.append(
                        {
                            "field": full_name,
                            "message": f"'{param.label}' 是必填项",
                        }
                    )

            # 递归 GROUP
            if param.type == ParameterTypeEnum.GROUP and param.group_config:
                group_value = form_values.get(param.name, [])
                if isinstance(group_value, list):
                    for i, item in enumerate(group_value):
                        item_prefix = f"{full_name}[{i}]."
                        if not isinstance(item, dict):
                            continue
                        merged = {
                            **form_values,
                            **{sp.name: item.get(sp.name) for sp in param.group_config.parameters},
                        }
                        for sub_param in param.group_config.parameters:
                            sub_full = f"{item_prefix}{sub_param.name}"
                            if sub_full not in visible:
                                continue
                            if sub_param.required:
                                v = item.get(sub_param.name)
                                if v is None or v == "":
                                    errors.append(
                                        {
                                            "field": sub_full,
                                            "message": f"'{sub_param.label}' 是必填项",
                                        }
                                    )

            elif param.type == ParameterTypeEnum.SECTION and param.section_config:
                for sub_param in param.section_config.parameters:
                    check(sub_param, f"{full_name}.")

        for p in parameters:
            check(p)

        return errors

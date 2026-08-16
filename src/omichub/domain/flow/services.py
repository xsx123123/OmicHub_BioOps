"""流程域服务 — YAML 解析、DAG 校验、流程加载。

基于 docs/modules/04_yaml_schema.md 实现。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from omichub.core.exceptions import YAMLConfigError
from omichub.domain.flow.entities import ConditionRule, FlowConfig, Parameter


class FlowDomainService:
    """流程域服务 — YAML 解析与校验。

    职责：
      1. parse_yaml: 读取 YAML 文件为 dict
      2. load_from_yaml: 解析并校验为 FlowConfig
      3. validate_dag: 检测参数 condition 间的循环依赖
    """

    def parse_yaml(self, yaml_path: Path) -> dict[str, Any]:
        """解析 YAML 配置文件为 dict。

        Args:
            yaml_path: YAML 文件路径

        Returns:
            dict: 解析后的字典

        Raises:
            YAMLConfigError: 文件不存在或 YAML 语法错误
        """
        if not yaml_path.exists():
            raise YAMLConfigError(f"YAML 文件不存在: {yaml_path}")

        try:
            with open(yaml_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise YAMLConfigError(f"YAML 解析失败: {e}") from e

        if not isinstance(data, dict):
            raise YAMLConfigError(f"YAML 顶层必须是字典，实际为: {type(data).__name__}")

        return data

    def load_from_yaml(self, yaml_path: Path) -> FlowConfig:
        """从 YAML 文件加载并校验流程配置。

        Args:
            yaml_path: YAML 文件路径

        Returns:
            FlowConfig: 校验后的流程配置

        Raises:
            YAMLConfigError: 解析或校验失败
        """
        data = self.parse_yaml(yaml_path)

        # 1. Pydantic 校验（含参数唯一性、condition 引用、类型一致性）
        try:
            flow_config = FlowConfig.model_validate(data)
        except ValidationError as e:
            errors = self._format_validation_errors(e)
            raise YAMLConfigError(f"流程配置校验失败 ({yaml_path.name}):\n{errors}") from e

        # 2. DAG 校验（检测 condition 循环依赖）
        cycle = self.find_condition_cycle(flow_config.parameters)
        if cycle:
            cycle_str = " → ".join(cycle)
            raise YAMLConfigError(f"参数条件渲染存在循环依赖: {cycle_str}")

        return flow_config

    def validate_dag(self, parameters: list[Parameter]) -> bool:
        """校验参数条件依赖图无环（DAG）。

        返回 True 表示无环，False 表示存在环。
        """
        return self.find_condition_cycle(parameters) is None

    @staticmethod
    def find_condition_cycle(parameters: list[Parameter]) -> list[str] | None:
        """检测参数 condition 间的循环依赖。

        构建依赖图：参数 A 的 condition.field = B → 边 B → A
        用 DFS 三色标记法检测环，返回环上的参数名列表，无环返回 None。

        注：仅检测顶层参数间的 condition.field 引用（不递归 group/section），
        因为文档规范中 condition 的 field 引用是扁平的（validate_condition_references）。
        """
        # 收集参数名 → condition 引用的字段
        param_names = {p.name for p in parameters}
        deps: dict[str, list[str]] = {}

        def collect_param_deps(param: Parameter) -> list[str]:
            """递归收集参数 condition 引用的所有字段"""
            fields: list[str] = []

            def collect_from_rule(rule: ConditionRule | None) -> None:
                if rule is None:
                    return
                if rule.field:
                    fields.append(rule.field)
                if rule.and_rules:
                    for r in rule.and_rules:
                        collect_from_rule(r)
                if rule.or_rules:
                    for r in rule.or_rules:
                        collect_from_rule(r)

            collect_from_rule(param.condition)
            return fields

        for p in parameters:
            # 仅保留指向本层参数名的引用（跨层引用不会形成同层环）
            referenced = collect_param_deps(p)
            deps[p.name] = [f for f in referenced if f in param_names]

        # 三色 DFS：0=未访问，1=访问中（在当前 DFS 路径上），2=已完成
        color: dict[str, int] = {name: 0 for name in param_names}
        stack: list[str] = []

        def dfs(node: str) -> bool:
            """DFS 检测环。返回 True 表示找到环。"""
            if color[node] == 1:
                # 找到环：从 stack 中提取环
                cycle_start = stack.index(node)
                return True
            if color[node] == 2:
                return False

            color[node] = 1
            stack.append(node)

            for neighbor in deps.get(node, []):
                if dfs(neighbor):
                    return True

            stack.pop()
            color[node] = 2
            return False

        for name in param_names:
            if color[name] == 0:
                if dfs(name):
                    # stack 中已包含环（最后一个节点重复出现时被截断）
                    # 重新跑一遍以准确截取环
                    # 实际上 dfs 返回 True 时 stack 已包含完整环路径
                    return list(stack)

        return None

    @staticmethod
    def _format_validation_errors(exc: ValidationError) -> str:
        """格式化 Pydantic 校验错误为可读字符串"""
        lines: list[str] = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err["loc"])
            msg = err["msg"]
            lines.append(f"  - {loc}: {msg}")
        return "\n".join(lines)


def validate_flow_config(data: dict[str, Any]) -> FlowConfig:
    """模块级便捷函数：校验并加载 FlowConfig。

    Args:
        data: YAML 解析后的字典

    Returns:
        FlowConfig: 校验后的流程配置

    Raises:
        YAMLConfigError: 校验失败
    """
    service = FlowDomainService()
    # 临时构造 parameters list 用于 DAG 检测
    try:
        flow_config = FlowConfig.model_validate(data)
    except ValidationError as e:
        errors = FlowDomainService._format_validation_errors(e)
        raise YAMLConfigError(f"流程配置校验失败:\n{errors}") from e

    cycle = FlowDomainService.find_condition_cycle(flow_config.parameters)
    if cycle:
        raise YAMLConfigError(f"参数条件渲染存在循环依赖: {' → '.join(cycle)}")

    return flow_config

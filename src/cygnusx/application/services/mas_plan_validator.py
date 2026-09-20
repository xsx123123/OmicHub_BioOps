"""Server-side validation for LLM-produced MAS execution plans."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cygnusx.application.services.flow_registry import FlowRegistry
from cygnusx.core.exceptions import ValidationError
from cygnusx.domain.mas.models import ExecutionPlan


class MASPlanValidator:
    """Ensures every planned node targets a registered agent with matching capabilities."""

    def __init__(
        self,
        agent_capabilities: Mapping[str, set[str]],
        artifact_schemas: Mapping[str, Mapping[str, Any]] | None = None,
        flow_registry: FlowRegistry | None = None,
    ) -> None:
        self._agent_capabilities = agent_capabilities
        self._artifact_schemas = artifact_schemas or {}
        self._flow_registry = flow_registry

    def validate(self, plan: ExecutionPlan) -> ExecutionPlan:
        for node in plan.nodes:
            capabilities = self._agent_capabilities.get(node.agent_id)
            if capabilities is None:
                raise ValidationError(f"计划引用了未注册的 MAS Agent: {node.agent_id}")
            required = {str(item) for item in node.resources.get("required_capabilities", [])}
            missing = required - capabilities
            if missing:
                raise ValidationError(
                    f"Agent {node.agent_id} 不具备节点 {node.key} 所需能力: {sorted(missing)}"
                )
            self._validate_flow_executor(node, capabilities)
        self._validate_quality_gate_dependencies(plan)
        self._validate_artifact_edges(plan)
        return plan

    def _validate_flow_executor(self, node, capabilities: set[str]) -> None:
        """Apply YAML executor contracts when a plan opts into a registered executor."""
        if self._flow_registry is None:
            return
        executor_key = str(node.resources.get("executor") or "").strip()
        if not executor_key:
            return
        matched = [
            (registered.definition, executor)
            for registered in self._flow_registry.flows.values()
            for stage in registered.definition.stages
            for executor in stage.executors
            if executor.key == executor_key
        ]
        if not matched:
            return
        definition, executor = matched[0]
        if node.agent_id != definition.flow.actor:
            raise ValidationError(
                f"节点 {node.key} 的 executor {executor_key} 必须由 {definition.flow.actor} 执行"
            )
        if executor_key not in capabilities:
            raise ValidationError(f"Agent {node.agent_id} 未获 YAML executor 能力: {executor_key}")
        expected_inputs = {f"{definition.flow.id}.{key}" for key in executor.inputs}
        expected_outputs = {f"{definition.flow.id}.{key}" for key in executor.outputs}
        actual_inputs = self._artifact_types(node.input_contract, "consumes")
        actual_outputs = self._artifact_types(node.output_contract, "produces")
        if actual_inputs and actual_inputs != expected_inputs:
            raise ValidationError(f"节点 {node.key} 的输入不符合 YAML executor 契约")
        if actual_outputs and actual_outputs != expected_outputs:
            raise ValidationError(f"节点 {node.key} 的输出不符合 YAML executor 契约")

    def _validate_artifact_edges(self, plan: ExecutionPlan) -> None:
        """校验下游声明消费的产物类型由任一上游依赖节点显式产出。"""
        if not self._artifact_schemas:
            return
        nodes = {node.key: node for node in plan.nodes}
        for node in plan.nodes:
            produced = self._artifact_types(node.output_contract, "produces")
            consumed = self._artifact_types(node.input_contract, "consumes")
            unknown = (produced | consumed) - set(self._artifact_schemas)
            if unknown:
                raise ValidationError(
                    f"节点 {node.key} 引用了未注册的 artifact type: {sorted(unknown)}"
                )
            if not consumed:
                continue
            available = self._upstream_artifact_types(node, nodes)
            root_inputs = {
                artifact_type
                for artifact_type in consumed
                if str(self._artifact_schemas.get(artifact_type, {}).get("producer", ""))
                == "user_upload"
            }
            missing = consumed - available - root_inputs
            if missing:
                raise ValidationError(
                    f"节点 {node.key} 消费的 artifact type 没有上游产出: {sorted(missing)}"
                )

    @staticmethod
    def _artifact_types(contract: Mapping[str, Any], role: str) -> set[str]:
        values = contract.get("artifact_types") or contract.get(role) or []
        if isinstance(values, str):
            values = [values]
        return {str(value).strip() for value in values if str(value).strip()} if isinstance(values, list) else set()

    @classmethod
    def _upstream_artifact_types(cls, node, nodes) -> set[str]:
        available: set[str] = set()
        pending = list(node.depends_on)
        seen: set[str] = set()
        while pending:
            key = pending.pop()
            if key in seen:
                continue
            seen.add(key)
            upstream = nodes[key]
            available.update(cls._artifact_types(upstream.output_contract, "produces"))
            pending.extend(upstream.depends_on)
        return available

    @staticmethod
    def _validate_quality_gate_dependencies(plan: ExecutionPlan) -> None:
        nodes = {node.key: node for node in plan.nodes}
        quality_gate_keys = {
            node.key for node in plan.nodes if node.resources.get("executor") == "quality-gate"
        }
        for node in plan.nodes:
            if node.resources.get("executor") != "deg-volcano":
                continue
            pending = list(node.depends_on)
            seen: set[str] = set()
            while pending:
                dependency = pending.pop()
                if dependency in seen:
                    continue
                if dependency in quality_gate_keys:
                    break
                seen.add(dependency)
                pending.extend(nodes[dependency].depends_on)
            else:
                raise ValidationError(
                    f"火山图节点 {node.key} 必须依赖一个 quality-gate 节点，不能绕过 QC 阻断"
                )

"""YAML-backed registry for governed multi-agent analysis flows.

The registry deliberately models workflow *definition* only.  It does not grant
workers any new permissions and it never changes the Case or Run state machines.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from omichub.core.exceptions import BusinessError

_FORBIDDEN_REVIEW_CAPABILITIES = frozenset(
    {"shell", "docker", "file_write", "workflow_submit", "database_write", "db_write"}
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FlowMeta(_StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{1,63}$")
    version: str = Field(min_length=1, max_length=64)
    display_name: str = Field(min_length=1, max_length=128)
    domain: str = Field(min_length=1, max_length=64)
    actor: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    runtime_image: str = Field(min_length=1, max_length=128)
    bridge_workflow: str = Field(pattern=r"^[a-z][a-z0-9_]{1,127}$")
    trigger_hints: list[str] = Field(default_factory=list, max_length=40)
    previous_artifacts: list[str] = Field(default_factory=list, max_length=200)


class ArtifactDefinition(_StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{1,127}$")
    type: str = Field(pattern=r"^[a-z][a-z0-9_]{1,127}$")
    aliases: list[str] = Field(default_factory=list, max_length=20)


class ExecutorDefinition(_StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    queue: str = Field(min_length=1, max_length=128)
    resource_profile: str = Field(min_length=1, max_length=128)
    execution_mode: Literal["cluster", "workspace_execution"] = "cluster"
    fan_out: Literal["none", "per_sample", "per_group"] = "none"
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    retry_policy: str = Field(min_length=1, max_length=128)
    feature_flag: str | None = Field(default=None, max_length=128)
    admission: dict[str, str] | None = None


class ReviewDefinition(_StrictModel):
    skill: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    inputs: list[str] = Field(default_factory=list)
    output: str = Field(min_length=1, max_length=128)
    boundary: Literal["read_only"] = "read_only"


class GateDefinition(_StrictModel):
    template: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    required: bool = True


class StageDefinition(_StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    title: str = Field(min_length=1, max_length=160)
    assistant_agent_id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9_-]{1,127}$")
    trigger_hints: list[str] = Field(default_factory=list, max_length=40)
    executors: list[ExecutorDefinition] = Field(min_length=1)
    review: ReviewDefinition | None = None
    gate: GateDefinition | None = None


class DeliveryDefinition(_StrictModel):
    quality_gate: bool = True
    outputs: list[str] = Field(default_factory=list)
    thresholds: dict[str, float] = Field(default_factory=dict)


class FlowDefinition(_StrictModel):
    flow: FlowMeta
    artifacts: list[ArtifactDefinition] = Field(min_length=1)
    stages: list[StageDefinition] = Field(min_length=1)
    edges: list[tuple[str, str]] = Field(default_factory=list)
    delivery: DeliveryDefinition

    @model_validator(mode="after")
    def _validate_unique_keys(self) -> FlowDefinition:
        for label, values in (
            ("artifact", [item.key for item in self.artifacts]),
            ("stage", [item.key for item in self.stages]),
            ("executor", [item.key for stage in self.stages for item in stage.executors]),
        ):
            if len(values) != len(set(values)):
                raise ValueError(f"流程存在重复的 {label} key")
        aliases = [alias for item in self.artifacts for alias in item.aliases]
        keys = {item.key for item in self.artifacts}
        if set(aliases) & keys or len(aliases) != len(set(aliases)):
            raise ValueError("artifact aliases 不能与 key 冲突且必须全局唯一")
        return self


class RetryPolicy(_StrictModel):
    auto_retry_on: list[str] = Field(default_factory=list)
    max_attempts: int = Field(default=1, ge=1, le=10)
    escalate: str | None = None


class ApprovalTemplate(_StrictModel):
    approvers: list[str] = Field(min_length=1)
    quorum: Literal["all", "any"]
    timeout_hours: int = Field(ge=1, le=720)
    on_timeout: str = Field(min_length=1)
    never_auto_approve: bool = True
    requires_reject_reason: bool = False


class SharedPolicies(_StrictModel):
    retry_policies: dict[str, RetryPolicy] = Field(default_factory=dict)
    approval_templates: dict[str, ApprovalTemplate] = Field(default_factory=dict)


class ResourceProfile(_StrictModel):
    cpu: int = Field(ge=1)
    memory_gb: int = Field(ge=1)
    temp_disk_gb: int = Field(ge=1)
    queue: str = Field(min_length=1)
    max_project_concurrency: int = Field(ge=1)


class ArtifactType(_StrictModel):
    format: str = Field(min_length=1)
    media_types: list[str] = Field(default_factory=list)
    max_size_gb: int = Field(ge=1)
    retention_days: int = Field(ge=1)


@dataclass(frozen=True)
class RegisteredFlow:
    definition: FlowDefinition
    digest: str
    source: Path

    @property
    def id(self) -> str:
        return self.definition.flow.id


@dataclass
class FlowRegistry:
    flows_dir: Path
    policies: SharedPolicies = field(default_factory=SharedPolicies)
    resources: dict[str, ResourceProfile] = field(default_factory=dict)
    artifact_types: dict[str, ArtifactType] = field(default_factory=dict)
    flows: dict[str, RegisteredFlow] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_directory(cls, flows_dir: str | Path | None = None) -> FlowRegistry:
        directory = Path(flows_dir) if flows_dir else _default_flows_dir()
        registry = cls(directory)
        registry.reload()
        return registry

    def reload(self) -> None:
        self.flows.clear()
        self.errors.clear()
        self._load_shared()
        if not self.flows_dir.exists():
            return
        for path in sorted(self.flows_dir.glob("*.yaml")):
            if path.name == "index.yaml":
                continue
            try:
                registered = self.load_file(path)
            except (BusinessError, ValueError) as exc:
                self.errors[path.stem] = str(exc)
                continue
            if registered.id in self.flows:
                self.errors[path.stem] = f"重复的 flow.id: {registered.id}"
                continue
            if any(
                item.definition.flow.bridge_workflow == registered.definition.flow.bridge_workflow
                for item in self.flows.values()
            ):
                self.errors[path.stem] = (
                    f"重复的 bridge_workflow: {registered.definition.flow.bridge_workflow}"
                )
                continue
            self.flows[registered.id] = registered

    def load_file(self, path: str | Path) -> RegisteredFlow:
        source = Path(path)
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError) as exc:
            raise ValueError(f"无法加载流程 YAML {source}: {exc}") from exc
        stages = raw.get("stages") if isinstance(raw, dict) else None
        if not isinstance(stages, list) or not stages or any(
            not isinstance(stage, dict) or not stage.get("executors") for stage in stages
        ):
            raise BusinessError("流程定义不完整")
        try:
            definition = FlowDefinition.model_validate(raw)
        except Exception as exc:
            raise ValueError(f"流程 YAML schema 无效 {source}: {exc}") from exc
        self._validate_definition(definition)
        normalized = yaml.safe_dump(raw, allow_unicode=True, sort_keys=True)
        return RegisteredFlow(
            definition=definition, digest=sha256(normalized.encode()).hexdigest(), source=source
        )

    def _load_shared(self) -> None:
        shared = self.flows_dir / "_shared"
        self.policies = self._load_model(shared / "policies.yaml", SharedPolicies, SharedPolicies())
        self.resources = self._load_mapping(shared / "resources.yaml", ResourceProfile)
        self.artifact_types = self._load_mapping(shared / "artifact_types.yaml", ArtifactType)

    @staticmethod
    def _load_model(path: Path, model_type: type[BaseModel], default: Any) -> Any:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return model_type.model_validate(raw)
        except (OSError, yaml.YAMLError, ValueError):
            return default

    @staticmethod
    def _load_mapping(path: Path, model_type: type[BaseModel]) -> dict[str, Any]:
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            if not isinstance(raw, dict):
                return {}
            return {str(key): model_type.model_validate(value) for key, value in raw.items()}
        except (OSError, yaml.YAMLError, ValueError):
            return {}

    def _validate_definition(self, definition: FlowDefinition) -> None:
        artifacts = {item.key for item in definition.artifacts}
        aliases = {alias for item in definition.artifacts for alias in item.aliases}
        removed = set(definition.flow.previous_artifacts) - artifacts - aliases
        if removed:
            raise ValueError(
                "流程版本升级删除或改名 artifact 时必须通过 aliases 保留兼容名称: "
                f"{sorted(removed)}"
            )
        stages = {stage.key for stage in definition.stages}
        produced: set[str] = set()
        for stage in definition.stages:
            if stage.review:
                if stage.review.boundary != "read_only":
                    raise ValueError(f"阶段 {stage.key} review 必须是 read_only")
                self._reject_forbidden_review_values(stage.review.model_dump(), stage.key)
            if stage.gate and stage.gate.template not in self.policies.approval_templates:
                raise ValueError(f"阶段 {stage.key} 引用了不存在的审批模板: {stage.gate.template}")
            for executor in stage.executors:
                if executor.resource_profile not in self.resources:
                    raise ValueError(
                        f"executor {executor.key} 引用了不存在的资源档位: {executor.resource_profile}"
                    )
                if executor.retry_policy not in self.policies.retry_policies:
                    raise ValueError(
                        f"executor {executor.key} 引用了不存在的重试策略: {executor.retry_policy}"
                    )
                unknown = (set(executor.inputs) | set(executor.outputs)) - artifacts
                if unknown:
                    raise ValueError(
                        f"executor {executor.key} 引用了未声明 artifact: {sorted(unknown)}"
                    )
                produced.update(executor.outputs)
            if stage.review:
                unknown = (set(stage.review.inputs) | {stage.review.output}) - artifacts
                if unknown:
                    raise ValueError(
                        f"阶段 {stage.key} review 引用了未声明 artifact: {sorted(unknown)}"
                    )
                produced.add(stage.review.output)
        unknown_delivery = set(definition.delivery.outputs) - artifacts
        if unknown_delivery:
            raise ValueError(f"delivery 引用了未声明 artifact: {sorted(unknown_delivery)}")
        for left, right in definition.edges:
            if left not in stages or right not in stages:
                raise ValueError(f"DAG edge 引用了不存在阶段: {left} -> {right}")
        if self._has_cycle(stages, definition.edges):
            raise ValueError("流程 DAG 存在环")
        consumed = {
            artifact
            for stage in definition.stages
            for executor in stage.executors
            for artifact in executor.inputs
        }
        undeclared_source = consumed - produced
        # Unproduced consumed artifacts are legal flow inputs, but must have an artifact declaration.
        if undeclared_source - artifacts:
            raise ValueError(f"流程入口 artifact 未声明: {sorted(undeclared_source - artifacts)}")
        unsupported_types = {artifact.type for artifact in definition.artifacts} - set(
            self.artifact_types
        )
        if unsupported_types:
            raise ValueError(f"引用了不存在的 artifact 类型: {sorted(unsupported_types)}")

    @staticmethod
    def _has_cycle(stages: set[str], edges: list[tuple[str, str]]) -> bool:
        graph: dict[str, list[str]] = defaultdict(list)
        degree = {key: 0 for key in stages}
        for left, right in edges:
            graph[left].append(right)
            degree[right] += 1
        pending = deque(key for key, value in degree.items() if value == 0)
        visited = 0
        while pending:
            node = pending.popleft()
            visited += 1
            for target in graph[node]:
                degree[target] -= 1
                if degree[target] == 0:
                    pending.append(target)
        return visited != len(stages)

    @staticmethod
    def _reject_forbidden_review_values(payload: Any, stage_key: str) -> None:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if str(key).lower() in _FORBIDDEN_REVIEW_CAPABILITIES:
                    raise ValueError(f"阶段 {stage_key} review 包含禁止能力: {key}")
                FlowRegistry._reject_forbidden_review_values(value, stage_key)
        elif isinstance(payload, list):
            for value in payload:
                FlowRegistry._reject_forbidden_review_values(value, stage_key)
        elif isinstance(payload, str) and payload.lower() in _FORBIDDEN_REVIEW_CAPABILITIES:
            raise ValueError(f"阶段 {stage_key} review 包含禁止能力: {payload}")

    def get(self, flow_id: str) -> RegisteredFlow | None:
        return self.flows.get(flow_id)

    def bridge_flow_ids(self) -> set[str]:
        return {item.definition.flow.bridge_workflow for item in self.flows.values()}

    def is_bridge_flow_id(self, flow_id: str) -> bool:
        return flow_id in self.bridge_flow_ids()

    def agent_capabilities(self) -> dict[str, set[str]]:
        derived: dict[str, set[str]] = defaultdict(set)
        for registered in self.flows.values():
            derived[registered.definition.flow.actor].update(
                executor.key
                for stage in registered.definition.stages
                for executor in stage.executors
            )
        return dict(derived)

    def artifact_schemas(self) -> dict[str, dict[str, Any]]:
        schemas: dict[str, dict[str, Any]] = {}
        for registered in self.flows.values():
            flow = registered.definition
            producers = {
                output: executor.key
                for stage in flow.stages
                for executor in stage.executors
                for output in executor.outputs
            }
            for artifact in flow.artifacts:
                shared = self.artifact_types[artifact.type]
                artifact_type = f"{flow.flow.id}.{artifact.key}"
                entry = {
                    "type": artifact_type,
                    "producer": producers.get(artifact.key, "user_upload"),
                    "schema": {"format": shared.format, "media_types": shared.media_types},
                    "flow_id": flow.flow.id,
                    "aliases": [f"{flow.flow.id}.{alias}" for alias in artifact.aliases],
                }
                schemas[artifact_type] = entry
                for alias in artifact.aliases:
                    alias_entry = dict(entry)
                    alias_entry["type"] = f"{flow.flow.id}.{alias}"
                    alias_entry["alias_for"] = artifact_type
                    schemas[alias_entry["type"]] = alias_entry
        return schemas

    def review_contracts(self) -> list[dict[str, Any]]:
        contracts: list[dict[str, Any]] = []
        for registered in self.flows.values():
            flow = registered.definition
            for stage in flow.stages:
                if stage.review is None:
                    continue
                contracts.append(
                    {
                        "skill": stage.review.skill,
                        "flow_id": flow.flow.id,
                        "target": flow.flow.actor,
                        "boundary": "read_only",
                        "inputs": [f"{flow.flow.id}.{item}" for item in stage.review.inputs],
                        "output": f"{flow.flow.id}.{stage.review.output}",
                    }
                )
        return contracts

    def route_agent(self, text: str, available_agent_ids: set[str]) -> str | None:
        normalized = text.lower()
        matches: list[tuple[int, str]] = []
        for registered in self.flows.values():
            for stage in registered.definition.stages:
                if (
                    not stage.assistant_agent_id
                    or stage.assistant_agent_id not in available_agent_ids
                ):
                    continue
                hints = [hint.lower() for hint in stage.trigger_hints if hint.strip()]
                score = sum(1 for hint in hints if hint in normalized)
                if score:
                    matches.append((score, stage.assistant_agent_id))
        return max(matches, default=(0, ""))[1] or None


def _default_flows_dir() -> Path:
    return Path(__file__).resolve().parents[4] / "data" / "ai" / "flows"


@lru_cache(maxsize=1)
def get_flow_registry() -> FlowRegistry:
    """Return the process-local registry; tests may instantiate FlowRegistry directly."""
    return FlowRegistry.from_directory()

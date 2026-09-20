"""Authoritative domain anchors for Overdrive Manager planning."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cygnusx.domain.domains.schema import AssignmentRule, normalize_marker


@dataclass(frozen=True)
class ConstraintResult:
    assignments: list[dict[str, Any]]
    speech: str
    planning_mode: str
    violations: list[str]
    repair_attempted: bool


@dataclass(frozen=True)
class GenericCapabilityRule:
    """无领域锚点时的通用能力匹配规则：任务文本命中 task_markers 且指派的
    Agent 身份不含 agent_markers、且目录中另有 Agent 覆盖该能力时判为错配。

    只收录边界清晰的通用能力；领域级选派约束一律沉淀到 data/ai/domains/*.yaml。
    """

    label: str
    task_markers: tuple[str, ...]
    agent_markers: tuple[str, ...]


_GENERIC_CAPABILITY_RULES: tuple[GenericCapabilityRule, ...] = (
    GenericCapabilityRule(
        label="可视化/绘图",
        task_markers=(
            "可视化", "绘图", "画图", "绘制", "图表", "热图", "树图",
            "publication-ready", "plot", "figure", "heatmap", "ggtree", "itol",
        ),
        agent_markers=("viz", "可视化", "visualization", "绘图", "图表", "plot"),
    ),
    GenericCapabilityRule(
        label="代码/脚本执行",
        task_markers=(
            "代码", "脚本", "python", "bash", "调试", "批量处理", "自动化",
        ),
        agent_markers=("code", "代码", "脚本", "沙盒", "sandbox", "python", "bash"),
    ),
)


def authoritative_rules(rules: Sequence[AssignmentRule]) -> list[AssignmentRule]:
    return [rule for rule in rules if rule.authoritative and rule.required]


def anchor_ids(rules: Sequence[AssignmentRule]) -> list[str]:
    return [rule.task_id for rule in authoritative_rules(rules)]


def serialize_anchors(rules: Sequence[AssignmentRule]) -> list[dict[str, Any]]:
    return [
        {
            "task_id": rule.task_id,
            "depends_on": list(rule.depends_on),
            "accepts_inputs": list(rule.accepts_inputs),
            "produces_outputs": list(rule.produces_outputs),
            "allowed_agents": list(rule.agent_match),
            "allow_split": rule.allow_split,
            "allow_reorder": rule.allow_reorder,
        }
        for rule in authoritative_rules(rules)
    ]


def format_anchors(rules: Sequence[AssignmentRule]) -> str:
    anchors = serialize_anchors(rules)
    if not anchors:
        return "无。"
    return "\n".join(
        f"- {item['task_id']}: depends_on={item['depends_on']}, "
        f"accepts_inputs={item['accepts_inputs']}, produces_outputs={item['produces_outputs']}, "
        f"allowed_agents={item['allowed_agents']}, allow_split={item['allow_split']}"
        for item in anchors
    )


def _normalized_values(values: object) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {normalize_marker(str(value)) for value in values if str(value).strip()}


def _candidate_identity(candidate: Mapping[str, Any]) -> str:
    features = candidate.get("features")
    if not isinstance(features, Mapping):
        features = {}

    def _list_value(key: str) -> list[str]:
        # 目录项（build_overdrive_agent_catalog）把能力声明放在顶层，
        # Agent 原始配置则放在 features 下，两处都认。
        value = features.get(key) or candidate.get(key) or []
        if not isinstance(value, list):
            return []
        return [str(item) for item in value]

    return normalize_marker(
        " ".join(
            [
                str(candidate.get("agent_id") or ""),
                str(candidate.get("name") or ""),
                str(candidate.get("category") or ""),
                *_list_value("capability_scope"),
                *_list_value("capability_tags"),
            ]
        )
    )


def _matching_tasks(
    assignments: Sequence[Mapping[str, Any]], rule: AssignmentRule
) -> list[Mapping[str, Any]]:
    exact = [item for item in assignments if str(item.get("task_id") or "") == rule.task_id]
    if exact:
        return exact
    if rule.allow_split:
        split = [
            item
            for item in assignments
            if str(item.get("task_id") or "").startswith(f"{rule.task_id}-")
        ]
        if split:
            return split
    required_outputs = _normalized_values(rule.produces_outputs)
    if not required_outputs:
        return []
    covered: list[Mapping[str, Any]] = []
    produced: set[str] = set()
    for item in assignments:
        item_outputs = _normalized_values(item.get("produces_outputs"))
        if item_outputs & required_outputs:
            covered.append(item)
            produced.update(item_outputs)
    return covered if required_outputs <= produced else []


def _depends_transitively(
    task_id: str, upstream_ids: set[str], by_id: Mapping[str, Mapping[str, Any]]
) -> bool:
    pending = list(by_id.get(task_id, {}).get("depends_on") or [])
    seen: set[str] = set()
    while pending:
        dependency = str(pending.pop())
        if dependency in upstream_ids:
            return True
        if dependency in seen:
            continue
        seen.add(dependency)
        pending.extend(by_id.get(dependency, {}).get("depends_on") or [])
    return False


def validate_plan(
    assignments: Sequence[Mapping[str, Any]],
    rules: Sequence[AssignmentRule],
    catalog_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    anchors = authoritative_rules(rules)
    violations: list[str] = []
    matched: dict[str, list[Mapping[str, Any]]] = {}
    by_id = {str(item.get("task_id") or ""): item for item in assignments}
    for rule in anchors:
        tasks = _matching_tasks(assignments, rule)
        matched[rule.task_id] = tasks
        if not tasks:
            violations.append(f"缺失必需锚点 {rule.task_id}")
            continue
        for task in tasks:
            task_id = str(task.get("task_id") or rule.task_id)
            candidate = catalog_by_id.get(str(task.get("agent_id") or ""), {})
            identity = _candidate_identity(candidate)
            if not any(marker in identity for marker in rule.agent_match):
                violations.append(f"锚点 {task_id} 的 agent 超出允许范围")
            if not _normalized_values(task.get("accepts_inputs")):
                violations.append(f"锚点 {task_id} 缺少 accepts_inputs 契约")
            if not _normalized_values(task.get("produces_outputs")):
                violations.append(f"锚点 {task_id} 缺少 produces_outputs 契约")
    for rule in anchors:
        if rule.allow_reorder or not rule.depends_on or not matched.get(rule.task_id):
            continue
        for upstream_id in rule.depends_on:
            upstream_tasks = matched.get(upstream_id) or []
            if not upstream_tasks:
                continue
            upstream_task_ids = {str(item.get("task_id") or "") for item in upstream_tasks}
            for task in matched[rule.task_id]:
                task_id = str(task.get("task_id") or "")
                if not _depends_transitively(task_id, upstream_task_ids, by_id):
                    violations.append(f"锚点顺序错误：{upstream_id} 必须位于 {rule.task_id} 上游")
                    break
    return list(dict.fromkeys(violations))


def validate_capability_match(
    assignments: Sequence[Mapping[str, Any]],
    catalog_by_id: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    """无领域锚点时的通用能力匹配校验（软约束）。

    任务文本（task + 输入输出契约）命中某通用能力组，但指派 Agent 的身份
    （agent_id/name/category/capability_scope/capability_tags）未覆盖该能力、
    且目录中存在其他 Agent 覆盖时，记为错配。目录中无人能覆盖时不记 violation
    ——没有更优选择，错配无从修复。
    """
    identities = {
        agent_id: _candidate_identity(candidate)
        for agent_id, candidate in catalog_by_id.items()
    }
    violations: list[str] = []
    for item in assignments:
        agent_id = str(item.get("agent_id") or "")
        if agent_id not in identities:
            continue
        text = normalize_marker(
            " ".join(
                [
                    str(item.get("task") or ""),
                    *(str(value) for value in item.get("accepts_inputs") or []),
                    *(str(value) for value in item.get("produces_outputs") or []),
                ]
            )
        )
        identity = identities[agent_id]
        for rule in _GENERIC_CAPABILITY_RULES:
            if not any(marker in text for marker in rule.task_markers):
                continue
            if any(marker in identity for marker in rule.agent_markers):
                continue
            has_better_candidate = any(
                any(marker in other for marker in rule.agent_markers)
                for other_id, other in identities.items()
                if other_id != agent_id
            )
            if not has_better_candidate:
                continue
            violations.append(
                f"任务 {item.get('task_id')} 涉及{rule.label}，"
                f"但分派的 Agent 能力范围未覆盖（{agent_id}）"
            )
    return list(dict.fromkeys(violations))


def build_repair_prompt(violations: Sequence[str], authoritative_anchors: str) -> str:
    """构造 Manager 修复提示词：有领域锚点时按锚点契约修复，否则按能力错配修复。"""
    anchors = authoritative_anchors.strip()
    if anchors and anchors != "无。":
        return (
            "你刚才的执行计划缺少本领域的必需环节或违反了依赖约束：\n"
            + "\n".join(f"- {item}" for item in violations)
            + "\n\n必需环节契约（必须全部覆盖，保持依赖方向）：\n"
            + anchors
            + "\n\n请输出修正后的完整计划（与上一轮相同的 JSON 格式），"
            "保留原计划中的合理分片、并行和额外环节，只修复违规点。"
        )
    return (
        "你刚才的执行计划存在能力错配：\n"
        + "\n".join(f"- {item}" for item in violations)
        + "\n\n请输出修正后的完整计划（与上一轮相同的 JSON 格式），"
        "依据候选专家能力目录（capability_scope 与 default_role）重新选派，"
        "保留原计划中的合理分片、并行和依赖关系，只修复违规点。"
    )


def merge_with_authoritative(
    assignments: Sequence[Mapping[str, Any]],
    authoritative_assignments: Sequence[Mapping[str, Any]],
    rules: Sequence[AssignmentRule],
) -> list[dict[str, Any]]:
    anchor_task_ids = set(anchor_ids(rules))
    merged = [dict(item) for item in authoritative_assignments]
    known_ids = {str(item.get("task_id") or "") for item in merged}
    for raw in assignments:
        item = dict(raw)
        task_id = str(item.get("task_id") or "")
        if not task_id or task_id in known_ids or task_id in anchor_task_ids:
            continue
        item["depends_on"] = [
            dependency
            for dependency in item.get("depends_on") or []
            if dependency in known_ids or dependency not in anchor_task_ids
        ]
        merged.append(item)
        known_ids.add(task_id)
    return merged


async def apply_authoritative_plan(
    *,
    assignments: Sequence[Mapping[str, Any]],
    speech: str,
    authoritative_assignments: Sequence[Mapping[str, Any]],
    rules: Sequence[AssignmentRule],
    catalog_by_id: Mapping[str, Mapping[str, Any]],
    mode: str,
    repair_enabled: bool,
    repair_plan: Callable[[list[str]], Awaitable[tuple[str, list[dict[str, Any]]]]],
    capability_check_enabled: bool = True,
) -> ConstraintResult:
    current = [dict(item) for item in assignments]
    authoritative = [dict(item) for item in authoritative_assignments]
    if mode == "off":
        return ConstraintResult(current, speech, "llm", [], False)
    if not authoritative:
        return await _apply_generic_capability_check(
            current=current,
            speech=speech,
            catalog_by_id=catalog_by_id,
            repair_enabled=repair_enabled,
            repair_plan=repair_plan,
            capability_check_enabled=capability_check_enabled,
        )
    if mode == "override":
        return ConstraintResult(authoritative, speech, "rule_override", [], False)

    violations = validate_plan(current, rules, catalog_by_id)
    if not violations:
        return ConstraintResult(current, speech, "llm", [], False)
    if repair_enabled:
        repaired_speech, repaired = await repair_plan(violations)
        repaired_violations = validate_plan(repaired, rules, catalog_by_id)
        if not repaired_violations:
            return ConstraintResult(
                repaired,
                repaired_speech or speech,
                "llm_repaired",
                [],
                True,
            )
        return ConstraintResult(
            merge_with_authoritative(repaired or current, authoritative, rules),
            repaired_speech or speech,
            "rule_merge",
            repaired_violations,
            True,
        )
    return ConstraintResult(
        merge_with_authoritative(current, authoritative, rules),
        speech,
        "rule_merge",
        violations,
        False,
    )


async def _apply_generic_capability_check(
    *,
    current: list[dict[str, Any]],
    speech: str,
    catalog_by_id: Mapping[str, Mapping[str, Any]],
    repair_enabled: bool,
    repair_plan: Callable[[list[str]], Awaitable[tuple[str, list[dict[str, Any]]]]],
    capability_check_enabled: bool,
) -> ConstraintResult:
    """无领域锚点时的软校验：发现能力错配则请求 Manager 修复一次；
    修复未果不阻断通用流程，违规项随结果保留供观测。"""
    if not capability_check_enabled or not current:
        return ConstraintResult(current, speech, "llm", [], False)
    violations = validate_capability_match(current, catalog_by_id)
    if not violations:
        return ConstraintResult(current, speech, "llm", [], False)
    if not repair_enabled:
        return ConstraintResult(current, speech, "llm", violations, False)
    repaired_speech, repaired = await repair_plan(violations)
    if repaired and not validate_capability_match(repaired, catalog_by_id):
        return ConstraintResult(
            repaired,
            repaired_speech or speech,
            "llm_repaired",
            [],
            True,
        )
    return ConstraintResult(current, speech, "llm", violations, True)


__all__ = [
    "ConstraintResult",
    "apply_authoritative_plan",
    "anchor_ids",
    "authoritative_rules",
    "build_repair_prompt",
    "format_anchors",
    "merge_with_authoritative",
    "serialize_anchors",
    "validate_capability_match",
    "validate_plan",
]

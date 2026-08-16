"""Authoritative domain anchors for Overdrive Manager planning."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from omichub.domain.domains.schema import AssignmentRule, normalize_marker


@dataclass(frozen=True)
class ConstraintResult:
    assignments: list[dict[str, Any]]
    speech: str
    planning_mode: str
    violations: list[str]
    repair_attempted: bool


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
    return normalize_marker(
        " ".join(
            [
                str(candidate.get("agent_id") or ""),
                str(candidate.get("name") or ""),
                str(candidate.get("category") or ""),
                *(str(value) for value in features.get("capability_scope") or []),
                *(str(value) for value in features.get("capability_tags") or []),
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
) -> ConstraintResult:
    current = [dict(item) for item in assignments]
    authoritative = [dict(item) for item in authoritative_assignments]
    if not authoritative or mode == "off":
        return ConstraintResult(current, speech, "llm", [], False)
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


__all__ = [
    "ConstraintResult",
    "apply_authoritative_plan",
    "anchor_ids",
    "authoritative_rules",
    "format_anchors",
    "merge_with_authoritative",
    "serialize_anchors",
    "validate_plan",
]

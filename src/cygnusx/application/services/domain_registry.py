"""Domain Pack 的通用认知求值器。"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from cygnusx.domain.domains.schema import AssignmentRule, DomainPack, normalize_marker
from cygnusx.infrastructure.config.domain_pack_loader import DomainPackLoader

_PLANNING_OR_ANALYSIS_MARKERS = (
    "计划",
    "方案",
    "研究设计",
    "研究路线",
    "挖掘",
    "新颖发现",
    "分析",
    "研究",
    "差异表达",
    "通路",
    "富集",
    "工作流",
)


class DomainRegistry:
    """将 YAML Domain Pack 求值为 intake、槽位、过滤与分工规则。"""

    def __init__(self, yaml_dir: Path | None = None) -> None:
        self._loader = DomainPackLoader(yaml_dir)

    @property
    def errors(self) -> list[str]:
        return self._loader.errors

    @property
    def is_empty(self) -> bool:
        return not bool(self._loader.packs)

    def reload_if_changed(self) -> None:
        self._loader.reload_if_changed()

    def _packs(self) -> list[DomainPack]:
        return sorted(self._loader.packs.values(), key=lambda item: item.domain)

    def match_domains(self, normalized_content: str) -> list[DomainPack]:
        content = normalize_marker(normalized_content)
        matched = [
            pack
            for pack in self._packs()
            if pack.enabled and any(marker in content for marker in pack.match.domain_markers)
        ]
        return sorted(
            matched,
            key=lambda pack: (
                -sum(marker in content for marker in pack.match.domain_markers),
                -max(
                    (len(marker) for marker in pack.match.domain_markers if marker in content),
                    default=0,
                ),
                pack.domain,
            ),
        )

    def matches_any(self, normalized_content: str) -> bool:
        return bool(self.match_domains(normalized_content))

    def has_planning_marker(self, normalized_content: str) -> bool:
        content = normalize_marker(normalized_content)
        return any(
            marker in content
            for pack in self._packs()
            if pack.enabled
            for marker in pack.match.planning_markers
        )

    def intake_questions(self, content: str) -> list[dict[str, Any]]:
        packs = self.match_domains(content)
        if not packs:
            return []
        normalized = normalize_marker(content)
        questions: list[dict[str, Any]] = []
        for item in packs[0].intake.questions:
            if item.when_markers_present and not all(
                marker in normalized for marker in item.when_markers_present
            ):
                continue
            if item.when_markers_absent and any(
                marker in normalized for marker in item.when_markers_absent
            ):
                continue
            question = item.question
            options = list(item.options)
            for subject_rule in item.subject_rules:
                if any(marker in normalized for marker in subject_rule.markers):
                    question = question.replace("{subject}", subject_rule.subject)
                    if subject_rule.options:
                        options = list(subject_rule.options)
                    break
            questions.append({"question": question.replace("{subject}", ""), "options": options})
        return questions

    def extract_slots(self, content: str, existing: dict[str, Any] | None = None) -> dict[str, Any]:
        slots = dict(existing or {})
        normalized = normalize_marker(content)
        for pack in self.match_domains(content):
            for slot in pack.intake.slots:
                matched = [
                    option.value
                    for option in slot.values
                    if any(marker in normalized for marker in option.markers)
                ]
                if matched:
                    slots[slot.key] = matched[0] if slot.priority == "first_match" else matched[-1]
        return slots

    def filter_questions(
        self, questions: list[dict[str, Any]], slots: dict[str, Any]
    ) -> list[dict[str, Any]]:
        filters = [
            item for pack in self._packs() if pack.enabled for item in pack.intake.question_filters
        ]
        pending = [
            normalize_marker(str(item.get("question") or ""))
            for item in questions
            if str(item.get("question") or "").strip()
        ]
        filtered: list[dict[str, Any]] = []
        for item in questions:
            question = str(item.get("question") or "").strip()
            if not question:
                continue
            normalized = normalize_marker(question)
            should_drop = False
            for rule in filters:
                if rule.when_slot_is and not all(
                    slots.get(key) == value for key, value in rule.when_slot_is.items()
                ):
                    continue
                if rule.when_slot_present and not all(
                    key in slots for key in rule.when_slot_present
                ):
                    continue
                if rule.when_slot_missing:
                    if not all(key not in slots for key in rule.when_slot_missing):
                        continue
                    if rule.requires_pending_question_markers and not any(
                        any(
                            marker in pending_question
                            for marker in rule.requires_pending_question_markers
                        )
                        for pending_question in pending
                    ):
                        continue
                if any(marker in normalized for marker in rule.drop_question_markers):
                    should_drop = True
                    break
            if not should_drop:
                filtered.append(item)
        return filtered

    def assignment_rules(self, content: str, slots: dict[str, Any]) -> list[AssignmentRule]:
        normalized = normalize_marker(content)
        matched: list[AssignmentRule] = []
        packs = self.match_domains(content)
        for pack in self._packs():
            if (
                pack.enabled
                and pack not in packs
                and any(
                    rule.when_slot_is
                    and all(slots.get(key) == value for key, value in rule.when_slot_is.items())
                    for rule in pack.assignments.rules
                )
            ):
                packs.append(pack)
        for pack in packs:
            for rule in pack.assignments.rules:
                if rule.when == "planning_or_analysis" and not any(
                    marker in normalized for marker in _PLANNING_OR_ANALYSIS_MARKERS
                ):
                    continue
                if rule.when_slot_is and not all(
                    slots.get(key) == value for key, value in rule.when_slot_is.items()
                ):
                    continue
                if rule.when_message_markers and not any(
                    marker in normalized for marker in rule.when_message_markers
                ):
                    continue
                matched.append(rule)
        return matched

    def minimize_assignments(
        self,
        assignments: list[dict[str, Any]],
        catalog_by_id: dict[str, dict[str, Any]],
        slots: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """按声明式 minimize_to_single 规则裁剪已归一化的 Manager 分工。"""
        for rule in self.assignment_rules("", slots):
            if not rule.minimize_to_single:
                continue
            for assignment in assignments:
                candidate = catalog_by_id.get(str(assignment.get("agent_id") or "")) or {}
                identity = normalize_marker(
                    " ".join(
                        (
                            str(candidate.get("agent_id") or ""),
                            str(candidate.get("name") or ""),
                            str(candidate.get("category") or ""),
                        )
                    )
                )
                if any(marker in identity for marker in rule.agent_match):
                    return [{**assignment, "depends_on": []}]
            return []
        return assignments

    def derived_planner_hints(self) -> dict[str, tuple[str, ...]]:
        """派生注册到 Planner 评分表：planner_agent → domain_markers（唯一声明处）。"""
        derived: dict[str, tuple[str, ...]] = {}
        for pack in self._packs():
            if pack.enabled and pack.routing.planner_agent:
                derived[pack.routing.planner_agent] = tuple(pack.match.domain_markers)
        return derived

    def derived_flow_aliases(self) -> dict[str, tuple[str, ...]]:
        """派生注册到意图路由别名表：flow.id → 各声明域的 domain_markers 合集。"""
        derived: dict[str, list[str]] = {}
        for pack in self._packs():
            if not pack.enabled:
                continue
            for flow_id in pack.routing.flow_aliases:
                derived.setdefault(flow_id, []).extend(pack.match.domain_markers)
        return {flow_id: tuple(markers) for flow_id, markers in derived.items()}

    def manager_notes(self, content: str) -> str:
        return "\n\n".join(
            pack.prompt_injections.manager_notes
            for pack in self.match_domains(content)
            if pack.prompt_injections.manager_notes
        )

    def router_notes_for(self, agent_id: str, domain: str | None = None) -> str:
        """返回 Agent 路由提示；显式声明的 domain 优先于 agent_match 反查。"""
        if domain:
            normalized_domain = normalize_marker(domain)
            for pack in self._packs():
                if pack.enabled and pack.domain == normalized_domain:
                    return pack.prompt_injections.router_notes
        normalized = normalize_marker(agent_id)
        for pack in self._packs():
            if not pack.enabled:
                continue
            if any(
                marker in normalized
                for rule in pack.assignments.rules
                for marker in rule.agent_match
            ):
                return pack.prompt_injections.router_notes
        return ""


@lru_cache(maxsize=1)
def get_domain_registry() -> DomainRegistry:
    return DomainRegistry()

"""Domain Pack v1 的严格声明 schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def normalize_marker(value: str) -> str:
    """按调度匹配语义规范化 marker：去空白、小写。"""
    return "".join(str(value).split()).lower()


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MatchSpec(_StrictModel):
    domain_markers: list[str] = Field(min_length=1)
    planning_markers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_markers(self) -> MatchSpec:
        self.domain_markers = [
            marker for raw in self.domain_markers if (marker := normalize_marker(raw))
        ]
        self.planning_markers = [
            marker for raw in self.planning_markers if (marker := normalize_marker(raw))
        ]
        if not self.domain_markers:
            raise ValueError("match.domain_markers 至少包含一个有效 marker")
        return self


class SubjectRule(_StrictModel):
    markers: list[str] = Field(min_length=1)
    subject: str = ""
    options: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_markers(self) -> SubjectRule:
        self.markers = [marker for raw in self.markers if (marker := normalize_marker(raw))]
        if not self.markers:
            raise ValueError("subject_rules.markers 至少包含一个有效 marker")
        return self


class IntakeQuestion(_StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    when_markers_present: list[str] = Field(default_factory=list)
    when_markers_absent: list[str] = Field(default_factory=list)
    question: str = Field(min_length=1, max_length=1000)
    options: list[str] = Field(default_factory=list)
    subject_rules: list[SubjectRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def normalize_markers(self) -> IntakeQuestion:
        self.when_markers_present = [
            marker for raw in self.when_markers_present if (marker := normalize_marker(raw))
        ]
        self.when_markers_absent = [
            marker for raw in self.when_markers_absent if (marker := normalize_marker(raw))
        ]
        return self


class SlotValue(_StrictModel):
    value: str = Field(min_length=1, max_length=128)
    markers: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def normalize_markers(self) -> SlotValue:
        self.markers = [marker for raw in self.markers if (marker := normalize_marker(raw))]
        if not self.markers:
            raise ValueError("slots.values.markers 至少包含一个有效 marker")
        return self


class IntakeSlot(_StrictModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    values: list[SlotValue] = Field(min_length=1)
    priority: Literal["first_match", "last_match"] = "first_match"

    @model_validator(mode="after")
    def values_are_unique(self) -> IntakeSlot:
        values = [item.value for item in self.values]
        if len(values) != len(set(values)):
            raise ValueError(f"slots[{self.key}] 存在重复 value")
        return self


class QuestionFilter(_StrictModel):
    when_slot_is: dict[str, str] = Field(default_factory=dict)
    when_slot_missing: list[str] = Field(default_factory=list)
    when_slot_present: list[str] = Field(default_factory=list)
    requires_pending_question_markers: list[str] = Field(default_factory=list)
    drop_question_markers: list[str] = Field(min_length=1)

    @model_validator(mode="after")
    def normalize_markers(self) -> QuestionFilter:
        self.requires_pending_question_markers = [
            marker
            for raw in self.requires_pending_question_markers
            if (marker := normalize_marker(raw))
        ]
        self.drop_question_markers = [
            marker for raw in self.drop_question_markers if (marker := normalize_marker(raw))
        ]
        if not self.drop_question_markers:
            raise ValueError("question_filters.drop_question_markers 至少包含一个有效 marker")
        return self

    def referenced_slot_keys(self) -> set[str]:
        return set(self.when_slot_is) | set(self.when_slot_missing) | set(self.when_slot_present)


class IntakeSpec(_StrictModel):
    questions: list[IntakeQuestion] = Field(default_factory=list)
    slots: list[IntakeSlot] = Field(default_factory=list)
    question_filters: list[QuestionFilter] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_references(self) -> IntakeSpec:
        keys = [slot.key for slot in self.slots]
        if len(keys) != len(set(keys)):
            raise ValueError("intake.slots 存在重复 key")
        known = set(keys)
        unknown = sorted(
            key
            for question_filter in self.question_filters
            for key in question_filter.referenced_slot_keys()
            if key not in known
        )
        if unknown:
            raise ValueError(f"question_filters 引用了未声明 slots: {', '.join(unknown)}")
        return self


class AssignmentRule(_StrictModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    when: Literal["planning_or_analysis"] | None = None
    when_slot_is: dict[str, str] = Field(default_factory=dict)
    when_message_markers: list[str] = Field(default_factory=list)
    agent_match: list[str] = Field(min_length=1)
    minimize_to_single: bool = False
    authoritative: bool = False
    required: bool = True
    allow_split: bool = False
    allow_reorder: bool = False
    task_id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    task: str = Field(min_length=1, max_length=2000)
    depends_on: list[str] = Field(default_factory=list)
    workspace_access: bool = False
    accepts_inputs: list[str] = Field(default_factory=list)
    produces_outputs: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_condition(self) -> AssignmentRule:
        if bool(self.when) == bool(self.when_slot_is):
            raise ValueError("assignments.rules 必须且只能声明 when 或 when_slot_is")
        self.when_message_markers = [
            marker for raw in self.when_message_markers if (marker := normalize_marker(raw))
        ]
        self.agent_match = [marker for raw in self.agent_match if (marker := normalize_marker(raw))]
        if not self.agent_match:
            raise ValueError("assignments.rules.agent_match 至少包含一个有效 marker")
        return self


class AssignmentsSpec(_StrictModel):
    rules: list[AssignmentRule] = Field(default_factory=list)


class PromptInjections(_StrictModel):
    manager_notes: str = Field(default="", max_length=800)
    router_notes: str = Field(default="", max_length=800)


class DomainPack(_StrictModel):
    domain: str = Field(pattern=r"^[a-z0-9_-]+$")
    version: Literal[1]
    display_name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    match: MatchSpec
    intake: IntakeSpec = Field(default_factory=IntakeSpec)
    assignments: AssignmentsSpec = Field(default_factory=AssignmentsSpec)
    prompt_injections: PromptInjections = Field(default_factory=PromptInjections)

    @model_validator(mode="after")
    def validate_assignment_slot_references(self) -> DomainPack:
        slot_keys = {slot.key for slot in self.intake.slots}
        unknown = sorted(
            key
            for rule in self.assignments.rules
            for key in rule.when_slot_is
            if key not in slot_keys
        )
        if unknown:
            raise ValueError(f"assignments.rules 引用了未声明 slots: {', '.join(unknown)}")
        return self

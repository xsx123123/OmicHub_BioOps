"""Server-side validation for a Goal Manager's structured terminal claim."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal

_RESULT_BLOCK_RE = re.compile(r"```goal_result\s*(\{.*?\})\s*```", re.DOTALL)


@dataclass(frozen=True)
class GoalEvaluation:
    action: Literal["continue", "complete", "blocked"]
    evidence: list[dict[str, Any]]
    reason: str = ""


class GoalEvaluator:
    """Only a structured, evidence-backed contract can end a Goal."""

    def evaluate(self, success_criteria: list[Any], content: str) -> GoalEvaluation:
        match = _RESULT_BLOCK_RE.search(content)
        if match is None:
            return GoalEvaluation(action="continue", evidence=[])
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return GoalEvaluation(action="continue", evidence=[])
        action = payload.get("action")
        evidence = payload.get("evidence")
        reason = str(payload.get("reason") or "").strip()
        if action == "goal_blocked":
            return GoalEvaluation(
                action="blocked" if reason else "continue",
                evidence=[],
                reason=reason,
            )
        if action != "goal_complete" or not isinstance(evidence, list):
            return GoalEvaluation(action="continue", evidence=[])
        normalized_evidence = [item for item in evidence if isinstance(item, dict)]
        if len(normalized_evidence) != len(evidence) or not self._covers_criteria(
            success_criteria, normalized_evidence
        ):
            return GoalEvaluation(action="continue", evidence=[])
        return GoalEvaluation(action="complete", evidence=normalized_evidence, reason=reason)

    def validates_completion(self, success_criteria: list[Any], evidence: list[dict[str, Any]]) -> bool:
        return self._covers_criteria(success_criteria, evidence)

    @staticmethod
    def _covers_criteria(criteria: list[Any], evidence: list[dict[str, Any]]) -> bool:
        if not evidence:
            return False
        evidence_by_criterion = {
            str(item.get("criterion") or "").strip(): str(item.get("evidence") or "").strip()
            for item in evidence
        }
        expected = [str(item).strip() for item in criteria if str(item).strip()]
        if not expected:
            return any(evidence_by_criterion.values())
        return all(evidence_by_criterion.get(criterion) for criterion in expected)

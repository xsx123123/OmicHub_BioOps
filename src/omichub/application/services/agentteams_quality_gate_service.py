"""Deterministic AgentTeams quality gate evaluated before LLM review."""

from __future__ import annotations

from typing import Any

from omichub.application.services.flow_registry import FlowRegistry, get_flow_registry
from omichub.core.exceptions import ValidationError


class AgentTeamsQualityGateService:
    def __init__(self, registry: FlowRegistry | None = None) -> None:
        self._registry = registry or get_flow_registry()

    def evaluate(self, flow_id: str, metrics: dict[str, Any]) -> dict[str, Any]:
        registered = self._registered_flow(flow_id)
        thresholds = registered.definition.delivery.thresholds
        checks: list[dict[str, Any]] = []
        for metric_name in ("mapping_rate", "q30", "duplicate_rate"):
            if metric_name not in metrics or metric_name not in thresholds:
                continue
            value = self._rate(metrics[metric_name], metric_name)
            threshold = float(thresholds[metric_name])
            blocked = metric_name in {"mapping_rate", "q30"} and value < threshold
            warning = metric_name == "duplicate_rate" and value > threshold
            decision = "BLOCKED" if blocked else "WARNING" if warning else "PASSED"
            comparator = "低于" if metric_name in {"mapping_rate", "q30"} else "高于"
            reason = (
                f"{metric_name} {value:.1%} {comparator}阈值 {threshold:.1%}"
                if blocked or warning
                else f"{metric_name} {value:.1%} 满足阈值 {threshold:.1%}"
            )
            checks.append(
                {
                    "metric": metric_name,
                    "value": value,
                    "threshold": threshold,
                    "decision": decision,
                    "reason": reason,
                }
            )
        overall = (
            "BLOCKED"
            if any(item["decision"] == "BLOCKED" for item in checks)
            else "WARNING"
            if any(item["decision"] == "WARNING" for item in checks)
            else "PASSED"
            if checks
            else "MANUAL_REVIEW"
        )
        decisive = next(
            (item for item in checks if item["decision"] == overall),
            {
                "metric": "none",
                "value": 0.0,
                "threshold": 0.0,
                "reason": "未发现可用硬规则指标",
            },
        )
        return {
            "decision": overall,
            "checks": checks,
            "audit_event": {
                "event_type": "quality.hard_gate",
                "decision": overall,
                "reason": decisive["reason"],
                "metric": decisive["metric"],
                "value": decisive["value"],
                "threshold": decisive["threshold"],
                "flow_id": registered.definition.flow.bridge_workflow,
                "rule_version": registered.definition.flow.version,
            },
        }

    def _registered_flow(self, flow_id: str):
        self._registry.reload()
        registered = next(
            (
                flow
                for flow in self._registry.flows.values()
                if flow_id in {flow.id, flow.definition.flow.bridge_workflow}
            ),
            None,
        )
        if registered is None:
            raise ValidationError(f"未知流程: {flow_id}")
        return registered

    @staticmethod
    def _rate(value: Any, metric_name: str) -> float:
        try:
            rate = float(str(value).strip().rstrip("%"))
        except (TypeError, ValueError) as exc:
            raise ValidationError(f"指标 {metric_name} 不是有效数值") from exc
        if rate > 1:
            rate /= 100
        if not 0 <= rate <= 1:
            raise ValidationError(f"指标 {metric_name} 必须位于 0 到 1 之间")
        return rate


__all__ = ["AgentTeamsQualityGateService"]

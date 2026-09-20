"""Deterministic AgentTeams quality gate evaluated before LLM review."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from cygnusx.application.services.flow_registry import FlowRegistry, get_flow_registry
from cygnusx.core.exceptions import ValidationError


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

    def evaluate_report_delivery(
        self,
        deliverables: Sequence[Mapping[str, Any]],
        citations: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """通用域报告类交付前的轻量门控：引用完整性 + 文件可打开。

        与垂直领域的阈值硬门控（evaluate）并行存在，不读取 flow 阈值；
        任一检查失败即 BLOCKED，全部通过为 PASSED，无输入为 MANUAL_REVIEW。
        """
        checks: list[dict[str, Any]] = []
        for index, row in enumerate(citations or [], start=1):
            source = next(
                (
                    str(row.get(key) or "").strip()
                    for key in ("source", "url", "doi", "pmid", "citation")
                    if str(row.get(key) or "").strip()
                ),
                "",
            )
            label = str(row.get("claim") or row.get("entity") or f"第 {index} 条")[:80]
            checks.append(
                {
                    "metric": "citation_completeness",
                    "subject": label,
                    "decision": "PASSED" if source else "BLOCKED",
                    "reason": (
                        f"引用 {label} 带来源 {source[:120]}"
                        if source
                        else f"引用 {label} 缺少来源（source/url/doi/pmid/citation 均为空）"
                    ),
                }
            )
        for raw in deliverables:
            path = Path(str(raw.get("path") or ""))
            kind = str(raw.get("kind") or path.suffix.lstrip(".")).lower()
            openable, detail = self._file_openable(path, kind)
            checks.append(
                {
                    "metric": "file_openable",
                    "subject": path.name or "(未命名)",
                    "decision": "PASSED" if openable else "BLOCKED",
                    "reason": detail,
                }
            )
        overall = (
            "BLOCKED"
            if any(item["decision"] == "BLOCKED" for item in checks)
            else "PASSED"
            if checks
            else "MANUAL_REVIEW"
        )
        decisive = next(
            (item for item in checks if item["decision"] == overall),
            {"metric": "none", "reason": "未发现可检查的交付物或引用"},
        )
        return {
            "decision": overall,
            "checks": checks,
            "audit_event": {
                "event_type": "quality.light_gate",
                "decision": overall,
                "reason": decisive["reason"],
                "metric": decisive["metric"],
                "flow_id": "general",
                "rule_version": "general-light-v1",
            },
        }

    @staticmethod
    def _file_openable(path: Path, kind: str) -> tuple[bool, str]:
        """按交付物类型做最小可打开性嗅探，不解析完整内容。"""
        if not str(path) or not path.is_file():
            return False, f"文件不存在或不可读: {path}"
        try:
            head = path.read_bytes()[:4096]
        except OSError as exc:
            return False, f"文件读取失败: {path} ({exc})"
        if not head:
            return False, f"文件为空: {path.name}"
        if kind in {"docx", "docx_report"}:
            if head.startswith(b"PK"):
                return True, f"{path.name} 是有效的 docx（zip 容器头匹配）"
            return False, f"{path.name} 不是有效的 docx（缺少 zip 容器头）"
        if kind in {"html", "htm", "html_report"}:
            lowered = head.lower()
            if b"<html" in lowered or b"<!doctype html" in lowered:
                return True, f"{path.name} 含可识别的 html 文档头"
            if b"<" in head and b">" in head:
                return True, f"{path.name} 含标签结构，可作为 html 片段打开"
            return False, f"{path.name} 不含任何 html 标签结构"
        return True, f"{path.name} 存在且非空（{kind or '未知类型'} 未做格式嗅探）"

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

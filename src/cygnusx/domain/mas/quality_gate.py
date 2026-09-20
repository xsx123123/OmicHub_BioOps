"""Versioned RNA-seq quality gate decisions used by MAS workers and approvals."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class QualityGateStatus(StrEnum):
    PASS = "pass"
    WARNING = "warning"
    REVIEW_REQUIRED = "review_required"
    FAIL = "fail"


class QualityGateResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    policy_version: str = "1.0"
    status: QualityGateStatus
    metric_name: str
    observed_value: float
    blocking_threshold: float
    allows_downstream_visualization: bool
    reason: str


class QCOverrideRequest(BaseModel):
    """Small auditable payload required to resume a blocked run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    reason: str = Field(min_length=10, max_length=1000)


def evaluate_mapping_rate(
    median_mapping_rate: float,
    *,
    blocking_threshold: float = 0.30,
    warning_threshold: float = 0.50,
    policy_version: str = "1.0",
) -> QualityGateResult:
    """Evaluate a mapping-rate summary without exposing raw QC reports to an Agent context."""
    if not 0 <= median_mapping_rate <= 1:
        raise ValueError("median_mapping_rate must be between 0 and 1")
    if not 0 <= blocking_threshold < warning_threshold <= 1:
        raise ValueError("quality gate thresholds must satisfy 0 <= block < warning <= 1")
    if median_mapping_rate <= blocking_threshold:
        return QualityGateResult(
            policy_version=policy_version,
            status=QualityGateStatus.REVIEW_REQUIRED,
            metric_name="median_mapping_rate",
            observed_value=median_mapping_rate,
            blocking_threshold=blocking_threshold,
            allows_downstream_visualization=False,
            reason="median_mapping_rate is at or below the blocking threshold",
        )
    if median_mapping_rate < warning_threshold:
        return QualityGateResult(
            policy_version=policy_version,
            status=QualityGateStatus.WARNING,
            metric_name="median_mapping_rate",
            observed_value=median_mapping_rate,
            blocking_threshold=blocking_threshold,
            allows_downstream_visualization=True,
            reason="median_mapping_rate is below the warning threshold",
        )
    return QualityGateResult(
        policy_version=policy_version,
        status=QualityGateStatus.PASS,
        metric_name="median_mapping_rate",
        observed_value=median_mapping_rate,
        blocking_threshold=blocking_threshold,
        allows_downstream_visualization=True,
        reason="median_mapping_rate meets the configured quality threshold",
    )


def apply_qc_override(result: QualityGateResult, request: QCOverrideRequest) -> QualityGateResult:
    """Return a marked result only after a server-auditable explicit override request."""
    if result.status != QualityGateStatus.REVIEW_REQUIRED:
        raise ValueError("only review-required quality gate results can be overridden")
    return result.model_copy(
        update={
            "status": QualityGateStatus.WARNING,
            "allows_downstream_visualization": True,
            "reason": f"qc_override: {request.reason}",
        }
    )

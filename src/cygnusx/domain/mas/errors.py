"""Deterministic MAS execution error classification and retry limits."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ErrorCategory(StrEnum):
    TRANSIENT = "transient"
    INPUT = "input"
    POLICY = "policy"
    QUALITY_GATE = "quality_gate"
    INFRASTRUCTURE = "infrastructure"
    UNKNOWN = "unknown"


class RetryDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    category: ErrorCategory
    retryable: bool
    requires_approval: bool = False
    max_attempts: int = Field(ge=0, le=10)


_DECISIONS: dict[str, RetryDecision] = {
    "NETWORK_TIMEOUT": RetryDecision(
        category=ErrorCategory.TRANSIENT, retryable=True, max_attempts=3
    ),
    "RATE_LIMITED": RetryDecision(category=ErrorCategory.TRANSIENT, retryable=True, max_attempts=3),
    "INPUT_NOT_FOUND": RetryDecision(category=ErrorCategory.INPUT, retryable=False, max_attempts=0),
    "DEG_SCHEMA_MISSING_REQUIRED_COLUMNS": RetryDecision(
        category=ErrorCategory.INPUT, retryable=False, requires_approval=True, max_attempts=0
    ),
    "QUALITY_GATE_FAILED": RetryDecision(
        category=ErrorCategory.QUALITY_GATE, retryable=False, requires_approval=True, max_attempts=0
    ),
    "POLICY_DENIED": RetryDecision(category=ErrorCategory.POLICY, retryable=False, max_attempts=0),
    "CONTAINER_UNAVAILABLE": RetryDecision(
        category=ErrorCategory.INFRASTRUCTURE, retryable=True, max_attempts=2
    ),
}


def classify_error(error_code: str) -> RetryDecision:
    """Return a bounded server-owned retry policy for a structured error code."""
    return _DECISIONS.get(
        error_code,
        RetryDecision(
            category=ErrorCategory.UNKNOWN, retryable=False, requires_approval=True, max_attempts=0
        ),
    )

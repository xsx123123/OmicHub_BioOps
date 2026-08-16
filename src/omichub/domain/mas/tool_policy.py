"""Read-only execution preflight policy for MAS-controlled tools."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator


class ToolPolicyError(ValueError):
    """Raised when a tool execution request violates MAS isolation policy."""


class ExecutionPolicy(BaseModel):
    """Server-enforced execution policy, never supplied by an LLM at runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{0,127}$")
    allowed_images: tuple[str, ...]
    allowed_write_roots: tuple[str, ...]
    network_enabled: bool = False
    allow_privileged: bool = False
    docker_socket_allowed: bool = False
    apptainer_compute_only: bool = False

    @field_validator("allowed_write_roots")
    @classmethod
    def validate_write_roots(cls, roots: tuple[str, ...]) -> tuple[str, ...]:
        for root in roots:
            path = PurePosixPath(root)
            if not path.is_absolute() or path.parts[:2] != ("/", "workspace"):
                raise ValueError("write roots must be absolute paths below /workspace")
        return roots


class ToolPreflightRequest(BaseModel):
    """Execution request reduced to fields needed for safe admission control."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tool_key: str
    image: str
    write_paths: tuple[str, ...] = ()
    privileged: bool = False
    docker_socket_mounted: bool = False
    runtime: str = "container"


class PreflightResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed: bool
    reasons: tuple[str, ...] = ()


def preflight_execution(policy: ExecutionPolicy, request: ToolPreflightRequest) -> PreflightResult:
    """Evaluate an execution request without starting a container or process."""
    reasons: list[str] = []
    if request.tool_key != policy.tool_key:
        reasons.append("tool key does not match execution policy")
    if request.image not in policy.allowed_images:
        reasons.append("container image is not allowlisted")
    if request.privileged and not policy.allow_privileged:
        reasons.append("privileged containers are forbidden")
    if request.docker_socket_mounted or policy.docker_socket_allowed:
        reasons.append("Docker socket access is forbidden for MAS tools")
    if policy.apptainer_compute_only and request.runtime != "apptainer-compute-node":
        reasons.append("tool requires an Apptainer compute-node runtime")

    allowed_roots = tuple(PurePosixPath(root) for root in policy.allowed_write_roots)
    for write_path in request.write_paths:
        path = PurePosixPath(write_path)
        if not path.is_absolute() or ".." in path.parts:
            reasons.append(f"unsafe write path: {write_path}")
            continue
        if not any(path == root or root in path.parents for root in allowed_roots):
            reasons.append(f"write path is outside allowlist: {write_path}")

    return PreflightResult(allowed=not reasons, reasons=tuple(reasons))


def load_execution_policies(path: str | Path) -> dict[str, ExecutionPolicy]:
    """Load version-controlled MAS policies; malformed files fail closed to an empty registry."""
    try:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        policies = raw.get("policies", []) if isinstance(raw, dict) else []
        return {
            policy.tool_key: policy
            for policy in (ExecutionPolicy.model_validate(item) for item in policies)
        }
    except (OSError, TypeError, ValueError, yaml.YAMLError):
        return {}

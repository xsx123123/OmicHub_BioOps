"""Validation for MAS-owned RNAFlow configuration files before Apptainer execution."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import UUID

import yaml

from cygnusx.domain.mas.workspace import WorkspaceLayout


class RNAFlowPreflightError(ValueError):
    """Raised when a workflow configuration escapes the MAS workspace contract."""


def validate_mas_rnaflow_config(workspace: WorkspaceLayout, run_id: UUID) -> dict[str, object]:
    """Accept only container paths scoped to the current Run and network-free execution settings."""
    config_path = workspace.resolve_container_path(run_id, "/workspace/workflow/config.yaml")
    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise RNAFlowPreflightError("unable to read RNAFlow config.yaml") from exc
    if not isinstance(config, dict):
        raise RNAFlowPreflightError("RNAFlow config.yaml must contain a mapping")

    _require_path_list(workspace, run_id, config, "raw_data_path", "/workspace/input")
    _require_path(workspace, run_id, config, "sample_csv", "/workspace/workflow")
    _require_path(workspace, run_id, config, "paired_csv", "/workspace/workflow")
    _require_exact_path(workspace, run_id, config, "workflow", "/workspace/workflow")
    _require_exact_path(workspace, run_id, config, "data_deliver", "/workspace/results")
    if config.get("execution_mode", "local") != "local":
        raise RNAFlowPreflightError("MAS RNAFlow jobs must use the native compute-node local mode")
    if config.get("loki_url"):
        raise RNAFlowPreflightError("MAS RNAFlow jobs cannot configure external Loki egress")
    return config


def _require_path_list(
    workspace: WorkspaceLayout,
    run_id: UUID,
    config: dict[str, object],
    key: str,
    allowed_root: str,
) -> None:
    values = config.get(key)
    if not isinstance(values, list) or not values:
        raise RNAFlowPreflightError(f"RNAFlow config {key} must be a non-empty list")
    for value in values:
        _validate_path_below(workspace, run_id, key, value, allowed_root)


def _require_path(
    workspace: WorkspaceLayout,
    run_id: UUID,
    config: dict[str, object],
    key: str,
    allowed_root: str,
) -> None:
    _validate_path_below(workspace, run_id, key, config.get(key), allowed_root)


def _require_exact_path(
    workspace: WorkspaceLayout,
    run_id: UUID,
    config: dict[str, object],
    key: str,
    expected: str,
) -> None:
    value = config.get(key)
    if value != expected:
        raise RNAFlowPreflightError(f"RNAFlow config {key} must be {expected}")
    workspace.resolve_container_path(run_id, expected)


def _validate_path_below(
    workspace: WorkspaceLayout,
    run_id: UUID,
    key: str,
    value: object,
    allowed_root: str,
) -> None:
    if not isinstance(value, str):
        raise RNAFlowPreflightError(f"RNAFlow config {key} must be a /workspace path")
    path = PurePosixPath(value)
    root = PurePosixPath(allowed_root)
    if not path.is_absolute() or (path != root and root not in path.parents):
        raise RNAFlowPreflightError(f"RNAFlow config {key} must stay below {allowed_root}")
    workspace.resolve_container_path(run_id, value)

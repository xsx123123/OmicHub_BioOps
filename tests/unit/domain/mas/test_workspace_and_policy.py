from pathlib import Path
from uuid import uuid4

import pytest

from cygnusx.domain.mas.models import MASDomainError
from cygnusx.domain.mas.tool_policy import (
    ExecutionPolicy,
    ToolPreflightRequest,
    preflight_execution,
)
from cygnusx.domain.mas.workspace import WorkspaceLayout


def test_workspace_maps_container_path_without_escape(tmp_path: Path) -> None:
    run_id = uuid4()
    workspace = WorkspaceLayout(tmp_path)
    workspace.initialize_run(run_id)

    resolved = workspace.resolve_container_path(
        run_id, "/workspace/results/deg.csv", require_writable=True
    )

    assert resolved == tmp_path / "runs" / str(run_id) / "results" / "deg.csv"
    assert workspace.to_container_path(run_id, resolved) == "/workspace/results/deg.csv"
    with pytest.raises(MASDomainError, match="inside /workspace"):
        workspace.resolve_container_path(run_id, "/etc/passwd")
    with pytest.raises(MASDomainError, match="not writable"):
        workspace.resolve_container_path(
            run_id, "/workspace/input/raw.fastq.gz", require_writable=True
        )


def test_preflight_rejects_docker_socket_privileged_and_unsafe_writes() -> None:
    policy = ExecutionPolicy(
        tool_key="rnaflow.run",
        allowed_images=("cygnusx/rnaflow:latest",),
        allowed_write_roots=("/workspace/results",),
    )
    result = preflight_execution(
        policy,
        ToolPreflightRequest(
            tool_key="rnaflow.run",
            image="cygnusx/rnaflow:latest",
            write_paths=("/workspace/results/counts.csv", "/workspace/input/overwrite.fastq.gz"),
            privileged=True,
            docker_socket_mounted=True,
        ),
    )

    assert not result.allowed
    assert "privileged containers are forbidden" in result.reasons
    assert "Docker socket access is forbidden for MAS tools" in result.reasons
    assert any("outside allowlist" in reason for reason in result.reasons)

from uuid import uuid4

import pytest

from cygnusx.domain.mas.workspace import WorkspaceLayout
from cygnusx.infrastructure.mas.scanpy import ScanpyQCError, build_scanpy_qc_command


def test_scanpy_qc_command_is_workspace_scoped(tmp_path):
    workspace = WorkspaceLayout(tmp_path)
    run_id = uuid4()
    workspace.initialize_run(run_id)
    workspace.resolve_container_path(run_id, "/workspace/input/cells.h5ad").touch()

    command = build_scanpy_qc_command(
        workspace, run_id, "/workspace/input/cells.h5ad", 200, 3, "scanpy:test"
    )

    assert command[:6] == ["docker", "run", "--rm", "--network", "none", "-v"]
    assert "/workspace/results/scrna_qc_filtered.h5ad" in command


def test_scanpy_qc_rejects_path_outside_input(tmp_path):
    workspace = WorkspaceLayout(tmp_path)
    run_id = uuid4()
    workspace.initialize_run(run_id)

    with pytest.raises(ScanpyQCError, match="below /workspace/input"):
        build_scanpy_qc_command(workspace, run_id, "/workspace/results/x.h5ad", 200, 3, "scanpy:test")

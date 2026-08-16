"""Safe command construction for MAS jobs executed by a native Apptainer worker."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from omichub.domain.mas.workspace import WorkspaceLayout


class ApptainerExecutionError(ValueError):
    """Raised when a requested native compute invocation violates the MAS bind contract."""


def build_rnaflow_command(
    *,
    binary: str,
    image: str | Path,
    workspace: WorkspaceLayout,
    run_id: UUID,
    pipeline_root: str | Path,
) -> list[str]:
    """Build the fixed RNAFlow command without accepting host paths or shell fragments from an Agent."""
    image_path = Path(image)
    if not str(image).strip():
        raise ApptainerExecutionError("MAS Apptainer image is not configured")
    if image_path.name in {".", ".."}:
        raise ApptainerExecutionError("MAS Apptainer image path is invalid")

    run_root = workspace.run_root(run_id)
    pipeline_path = Path(pipeline_root).resolve()
    if not pipeline_path.is_dir():
        raise ApptainerExecutionError("RNAFlow pipeline root does not exist on the compute node")
    if not run_root.is_dir():
        raise ApptainerExecutionError("MAS run workspace does not exist on the compute node")

    return [
        binary,
        "exec",
        "--containall",
        "--cleanenv",
        "--no-home",
        "--pwd",
        "/workspace/workflow",
        "--bind",
        f"{run_root}:/workspace:rw",
        "--bind",
        f"{pipeline_path}:/opt/omichub/pipelines/RNAFlow:ro",
        str(image_path),
        "snakemake",
        "--snakefile",
        "/opt/omichub/pipelines/RNAFlow/snakefile",
        "--directory",
        "/workspace/workflow",
        "--config",
        "analysisyaml=/workspace/workflow/config.yaml",
        "--use-conda",
        "--conda-frontend",
        "mamba",
        "--cores",
        "1",
    ]

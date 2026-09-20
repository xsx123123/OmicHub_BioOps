"""受限的 Scanpy QC 容器命令构造。"""

from __future__ import annotations

from pathlib import PurePosixPath
from uuid import UUID

from cygnusx.domain.mas.workspace import WorkspaceLayout


class ScanpyQCError(ValueError):
    pass


def build_scanpy_qc_command(
    workspace: WorkspaceLayout, run_id: UUID, input_path: str, min_genes: int, min_cells: int, image: str
) -> list[str]:
    path = PurePosixPath(input_path)
    if not input_path.endswith(".h5ad") or not path.is_absolute() or PurePosixPath("/workspace/input") not in path.parents:
        raise ScanpyQCError("input_h5ad_path must be a .h5ad file below /workspace/input")
    workspace.resolve_container_path(run_id, input_path)
    if not 0 <= min_genes <= 10000 or not 0 <= min_cells <= 100000:
        raise ScanpyQCError("min_genes/min_cells are outside safe ranges")
    script = (
        "import json,scanpy as sc,sys;"
        "a=sc.read_h5ad(sys.argv[1]);before=[a.n_obs,a.n_vars];"
        "sc.pp.filter_cells(a,min_genes=int(sys.argv[3]));sc.pp.filter_genes(a,min_cells=int(sys.argv[4]));"
        "a.write_h5ad(sys.argv[2]);json.dump({'cells_before':before[0],'genes_before':before[1],"
        "'cells_after':a.n_obs,'genes_after':a.n_vars},open(sys.argv[5],'w'))"
    )
    root = str(workspace.run_root(run_id))
    return ["docker", "run", "--rm", "--network", "none", "-v", f"{root}:/workspace:rw", image, "python", "-c", script,
            input_path, "/workspace/results/scrna_qc_filtered.h5ad", str(min_genes), str(min_cells), "/workspace/results/scrna_qc_metrics.json"]

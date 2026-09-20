"""Safe server-side and container-side MAS workspace mapping."""

from __future__ import annotations

from pathlib import Path, PurePosixPath
from uuid import UUID

from cygnusx.domain.mas.models import MASDomainError


class WorkspaceLayout:
    """Owns the fixed per-run directory contract and path safety checks."""

    directories = (
        "input",
        "staging",
        "workflow",
        "results",
        "plots",
        "logs",
        "manifests",
        "scratch",
    )
    writable_directories = frozenset(
        {"staging", "workflow", "results", "plots", "logs", "manifests", "scratch"}
    )

    def __init__(self, root: str | Path = "/data/cygnusx") -> None:
        self.root = Path(root).resolve()
        self.runs_root = self.root / "runs"
        self.cache_root = self.root / "artifact-cache" / "raw" / "sha256"

    def run_root(self, run_id: UUID | str) -> Path:
        return (self.runs_root / str(run_id)).resolve()

    def initialize_run(self, run_id: UUID | str) -> Path:
        run_root = self.run_root(run_id)
        for directory in self.directories:
            (run_root / directory).mkdir(parents=True, exist_ok=True)
        return run_root

    def resolve_container_path(
        self, run_id: UUID | str, container_path: str, *, require_writable: bool = False
    ) -> Path:
        path = PurePosixPath(container_path)
        if not path.is_absolute() or path.parts[:1] != ("/",) or len(path.parts) < 2:
            raise MASDomainError("container path must be inside /workspace")
        if path.parts[1] != "workspace" or any(part in {".", ".."} for part in path.parts):
            raise MASDomainError("container path must be inside /workspace")

        run_root = self.run_root(run_id)
        relative = Path(*path.parts[2:])
        resolved = (run_root / relative).resolve()
        try:
            resolved.relative_to(run_root)
        except ValueError as exc:
            raise MASDomainError("container path escapes run workspace") from exc

        if require_writable and (
            not relative.parts or relative.parts[0] not in self.writable_directories
        ):
            raise MASDomainError("path is not writable in MAS workspace")
        return resolved

    def to_container_path(self, run_id: UUID | str, workspace_path: str | Path) -> str:
        run_root = self.run_root(run_id)
        resolved = Path(workspace_path).resolve()
        try:
            relative = resolved.relative_to(run_root)
        except ValueError as exc:
            raise MASDomainError("workspace path is outside run workspace") from exc
        return str(PurePosixPath("/workspace", *relative.parts))

    def cache_payload_path(self, sha256: str) -> Path:
        if len(sha256) != 64 or any(char not in "0123456789abcdef" for char in sha256):
            raise MASDomainError("sha256 must be a lowercase 64-character digest")
        return self.cache_root / sha256 / "payload.fastq.gz"

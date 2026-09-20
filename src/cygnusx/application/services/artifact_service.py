"""Artifact Registry validation for MAS shared workspaces."""

from __future__ import annotations

import hashlib
from pathlib import Path

from cygnusx.core.exceptions import ValidationError
from cygnusx.domain.mas.models import ArtifactKind, ArtifactState, MASArtifact
from cygnusx.domain.mas.workspace import WorkspaceLayout


class ArtifactService:
    def __init__(self, workspace: WorkspaceLayout) -> None:
        self._workspace = workspace

    def validate(self, artifact: MASArtifact) -> MASArtifact:
        """Validate file artifacts before they may be exposed to downstream nodes."""
        workspace_path = self._workspace.resolve_container_path(
            artifact.run_id,
            self._workspace.to_container_path(artifact.run_id, artifact.workspace_path),
        )
        if artifact.kind == ArtifactKind.DIRECTORY:
            if not workspace_path.is_dir():
                raise ValidationError("Artifact 目录不存在或类型不匹配")
            return artifact.model_copy(update={"state": ArtifactState.VALIDATED})
        if not workspace_path.is_file():
            raise ValidationError("Artifact 文件不存在或类型不匹配")
        size_bytes = workspace_path.stat().st_size
        if size_bytes != artifact.size_bytes:
            raise ValidationError("Artifact 文件大小与登记元数据不一致")
        digest = self._sha256(workspace_path)
        if digest != artifact.sha256:
            raise ValidationError("Artifact SHA-256 与登记元数据不一致")
        return artifact.model_copy(update={"state": ArtifactState.VALIDATED})

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

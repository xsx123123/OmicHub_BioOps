import hashlib
from pathlib import Path
from uuid import uuid4

import pytest

from omichub.application.services.artifact_service import ArtifactService
from omichub.core.exceptions import ValidationError
from omichub.domain.mas.models import ArtifactKind, ArtifactState, MASArtifact
from omichub.domain.mas.workspace import WorkspaceLayout


def test_validates_file_artifact_against_workspace_metadata(tmp_path: Path) -> None:
    run_id = uuid4()
    workspace = WorkspaceLayout(tmp_path)
    result_dir = workspace.initialize_run(run_id) / "results"
    artifact_path = result_dir / "deg.csv"
    artifact_path.write_text("gene_id,padj\nA,0.01\n")
    content = artifact_path.read_bytes()
    artifact = MASArtifact(
        run_id=run_id,
        logical_name="deg_results",
        kind=ArtifactKind.FILE,
        workspace_path=str(artifact_path),
        media_type="text/csv",
        size_bytes=len(content),
        sha256=hashlib.sha256(content).hexdigest(),
    )

    validated = ArtifactService(workspace).validate(artifact)

    assert validated.state == ArtifactState.VALIDATED
    with pytest.raises(ValidationError, match="SHA-256"):
        ArtifactService(workspace).validate(artifact.model_copy(update={"sha256": "0" * 64}))

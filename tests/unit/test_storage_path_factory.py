from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from omichub.infrastructure.config.storage_config import StorageConfig
from omichub.infrastructure.storage.path_factory import StoragePathFactory, project_slug
from omichub.tools.fastq_qc.schema import CreateQCTaskRequest
from omichub.tools.phylogenetic_tree.schema import PhyloSubmitRequest


@pytest.mark.unit
def test_project_slug_keeps_readable_project_name() -> None:
    assert project_slug(" TnpD / reference: gt05 ") == "TnpD_reference_gt05"
    assert project_slug("../") == "untitled-project"


@pytest.mark.unit
def test_project_runs_are_visible_and_do_not_use_uuid_paths(tmp_path: Path) -> None:
    factory = StoragePathFactory(StorageConfig(data_root=str(tmp_path), users_subdir="users"))

    first_run = factory.create_project_run_dir("user-1", "TnpD 建树项目", "phylogenetic-tree")
    second_run = factory.create_project_run_dir("user-1", "TnpD 建树项目", "phylogenetic-tree")

    assert first_run.parent.name == "runs"
    assert first_run.parent.parent.name == "TnpD_建树项目"
    assert first_run.name.startswith("phylogenetic-tree-")
    assert second_run != first_run
    assert {path.name for path in first_run.iterdir()} == {"input", "output", "work", "logs"}
    assert not (tmp_path / "users" / "user-1" / "tasks").exists()


@pytest.mark.unit
def test_analysis_requests_require_project_name() -> None:
    with pytest.raises(ValidationError):
        PhyloSubmitRequest(file_id="input-1")
    with pytest.raises(ValidationError):
        PhyloSubmitRequest(file_id="input-1", project_name=" ")
    with pytest.raises(ValidationError):
        CreateQCTaskRequest(samples=[])

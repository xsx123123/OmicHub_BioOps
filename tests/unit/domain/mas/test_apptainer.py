from pathlib import Path
from uuid import uuid4

import pytest

from cygnusx.domain.mas.workspace import WorkspaceLayout
from cygnusx.infrastructure.mas.apptainer import ApptainerExecutionError, build_rnaflow_command
from cygnusx.infrastructure.mas.rnaflow import RNAFlowPreflightError, validate_mas_rnaflow_config
from cygnusx.infrastructure.mas.volcano import render_deg_volcano
from cygnusx.infrastructure.mas.ebi import build_ebi_download_command, write_download_manifest


def test_apptainer_command_uses_only_run_and_pipeline_binds(tmp_path: Path) -> None:
    workspace = WorkspaceLayout(tmp_path / "data")
    run_id = uuid4()
    workspace.initialize_run(run_id)
    pipeline_root = tmp_path / "RNAFlow"
    pipeline_root.mkdir()

    command = build_rnaflow_command(
        binary="apptainer",
        image="/images/rnaflow.sif",
        workspace=workspace,
        run_id=run_id,
        pipeline_root=pipeline_root,
    )

    assert "--containall" in command
    assert "--no-home" in command
    assert "/var/run/docker.sock" not in " ".join(command)
    assert f"{workspace.run_root(run_id)}:/workspace:rw" in command
    assert f"{pipeline_root.resolve()}:/opt/cygnusx/pipelines/RNAFlow:ro" in command
    assert "analysisyaml=/workspace/workflow/config.yaml" in command


def test_apptainer_command_requires_existing_workspace_and_pipeline(tmp_path: Path) -> None:
    workspace = WorkspaceLayout(tmp_path / "data")
    with pytest.raises(ApptainerExecutionError, match="pipeline root"):
        build_rnaflow_command(
            binary="apptainer",
            image="/images/rnaflow.sif",
            workspace=workspace,
            run_id=uuid4(),
            pipeline_root=tmp_path / "missing",
        )


def test_rnaflow_preflight_rejects_host_paths_and_network_egress(tmp_path: Path) -> None:
    workspace = WorkspaceLayout(tmp_path / "data")
    run_id = uuid4()
    workspace.initialize_run(run_id)
    config = workspace.resolve_container_path(run_id, "/workspace/workflow/config.yaml")
    config.write_text(
        "raw_data_path: [/data/host]\n"
        "sample_csv: /workspace/workflow/samples.csv\n"
        "paired_csv: /workspace/workflow/contrasts.csv\n"
        "workflow: /workspace/workflow\n"
        "data_deliver: /workspace/results\n"
        "loki_url: https://outside.example\n"
    )

    with pytest.raises(RNAFlowPreflightError, match="raw_data_path"):
        validate_mas_rnaflow_config(workspace, run_id)


def test_rnaflow_preflight_accepts_workspace_only_config(tmp_path: Path) -> None:
    workspace = WorkspaceLayout(tmp_path / "data")
    run_id = uuid4()
    workspace.initialize_run(run_id)
    config = workspace.resolve_container_path(run_id, "/workspace/workflow/config.yaml")
    config.write_text(
        "raw_data_path: [/workspace/input]\n"
        "sample_csv: /workspace/workflow/samples.csv\n"
        "paired_csv: /workspace/workflow/contrasts.csv\n"
        "workflow: /workspace/workflow\n"
        "data_deliver: /workspace/results\n"
        "execution_mode: local\n"
        "loki_url: ''\n"
    )

    assert validate_mas_rnaflow_config(workspace, run_id)["data_deliver"] == "/workspace/results"


def test_static_volcano_renderer_generates_png_and_pdf(tmp_path: Path) -> None:
    input_path = tmp_path / "deg.csv"
    input_path.write_text("gene,log2FoldChange,padj\nA,2,0.001\nB,-2,0.002\nC,0.1,0.9\n")

    result = render_deg_volcano(input_path, tmp_path / "plots")

    assert result.total == 3
    assert result.up == 1
    assert result.down == 1
    assert result.png_path.is_file()
    assert result.pdf_path.is_file()


def test_ebi_command_and_manifest_are_workspace_scoped(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    staging.mkdir()
    (staging / "reads.fastq.gz").write_bytes(b"reads")
    command = build_ebi_download_command(
        binary="EBIDownload",
        yaml_path="/etc/ebi.yaml",
        accession="SRR123456",
        output_directory=staging,
    )
    manifest = write_download_manifest(staging, staging / "fastq-manifest.json", "SRR123456")

    assert command[command.index("-o") + 1] == str(staging)
    assert manifest["accession"] == "SRR123456"
    assert (staging / "fastq-manifest.json").is_file()

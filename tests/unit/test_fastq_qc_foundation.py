from pathlib import Path

import pytest

from omichub.tools.fastq_qc.config import (
    FastpConfig,
    FastpParameters,
    FastqQcConfigManager,
    MultiqcConfig,
)
from omichub.tools.fastq_qc.runner import (
    FastpSamplePaths,
    build_fastp_command,
    build_multiqc_command,
)


def test_loads_repository_fastq_qc_configuration() -> None:
    manager = FastqQcConfigManager("tool_configs/fastq_qc/config.yaml")

    config = manager.get_config()

    assert config.queue.name == "qc"
    assert config.resources.fastp.threads == 8
    assert config.fastp.overridable == ["qualified_quality_phred", "trim_to_len", "adapter_trim"]


def test_merges_only_whitelisted_fastp_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "fastq-qc.yaml"
    config_path.write_text(
        "fastp:\n  defaults:\n    qualified_quality_phred: 19\n  overridable:\n    - qualified_quality_phred\n",
        encoding="utf-8",
    )
    manager = FastqQcConfigManager(config_path)

    parameters = manager.merge_fastp_parameters({"qualified_quality_phred": 25})

    assert parameters.qualified_quality_phred == 25
    with pytest.raises(ValueError, match="not overridable"):
        manager.merge_fastp_parameters({"compression_level": 9})


def test_build_fastp_command_for_paired_end_sample() -> None:
    command = build_fastp_command(
        sample=FastpSamplePaths("sample-1", Path("/input/r1.fq.gz"), Path("/input/r2.fq.gz")),
        parameters=FastpParameters(trim_to_len=120, correction=True),
        config=FastpConfig(extra_args=["--dont_eval_duplication"]),
        threads=8,
        output_dir=Path("/task/output"),
        reports_dir=Path("/task/reports"),
    )

    assert command[:5] == [
        "fastp",
        "-i",
        "/input/r1.fq.gz",
        "-o",
        "/task/output/sample-1.clean_R1.fastq.gz",
    ]
    assert command[command.index("-I") : command.index("-I") + 2] == ["-I", "/input/r2.fq.gz"]
    assert "--detect_adapter_for_pe" in command
    assert "--trim_to_len" in command
    assert "--correction" in command
    assert command[-1] == "--dont_eval_duplication"


def test_build_fastp_command_disables_adapter_trimming_for_single_end() -> None:
    command = build_fastp_command(
        sample=FastpSamplePaths("sample_1", Path("/input/r1.fq.gz")),
        parameters=FastpParameters(adapter_trim=False),
        config=FastpConfig(),
        threads=1,
        output_dir=Path("/task/output"),
        reports_dir=Path("/task/reports"),
    )

    assert "--disable_adapter_trimming" in command
    assert "-I" not in command
    assert "--detect_adapter_for_pe" not in command


def test_build_multiqc_command_is_limited_to_configured_modules() -> None:
    command = build_multiqc_command(
        reports_dir=Path("/task/reports"),
        output_dir=Path("/task/multiqc"),
        config=MultiqcConfig(modules=["fastp"], extra_args=["--quiet"]),
    )

    assert command == [
        "multiqc",
        "/task/reports",
        "-o",
        "/task/multiqc",
        "-n",
        "multiqc_report.html",
        "--no-ansi",
        "-f",
        "-m",
        "fastp",
        "--quiet",
    ]

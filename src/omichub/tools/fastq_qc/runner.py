"""安全构造 FASTQ QC 外部命令，调用方必须使用 shell=False 执行。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import FastpConfig, FastpParameters, MultiqcConfig


@dataclass(frozen=True)
class FastpSamplePaths:
    sample: str
    read1: Path
    read2: Path | None = None

    @property
    def is_paired_end(self) -> bool:
        return self.read2 is not None


def _validate_sample_name(sample: str) -> None:
    if not sample or not all(character.isalnum() or character in "._-" for character in sample):
        raise ValueError("sample may only contain letters, numbers, '.', '_' and '-'")


def build_fastp_command(
    *,
    sample: FastpSamplePaths,
    parameters: FastpParameters,
    config: FastpConfig,
    threads: int,
    output_dir: Path,
    reports_dir: Path,
) -> list[str]:
    """返回单样本 fastp argv；所有动态路径以独立 argv 元素传入。"""
    _validate_sample_name(sample.sample)
    if threads < 1:
        raise ValueError("threads must be positive")

    command = [
        config.bin,
        "-i",
        str(sample.read1),
        "-o",
        str(output_dir / f"{sample.sample}.clean_R1.fastq.gz"),
        "-j",
        str(reports_dir / f"{sample.sample}.fastp.json"),
        "-h",
        str(reports_dir / f"{sample.sample}.fastp.html"),
        "-w",
        str(threads),
        "-q",
        str(parameters.qualified_quality_phred),
        "-u",
        str(parameters.unqualified_percent_limit),
        "-n",
        str(parameters.n_base_limit),
        "-l",
        str(parameters.length_required),
        "-z",
        str(parameters.compression_level),
    ]
    if parameters.trim_to_len:
        command.extend(["--trim_to_len", str(parameters.trim_to_len)])
    if not parameters.adapter_trim:
        command.append("--disable_adapter_trimming")
    if parameters.correction:
        command.append("--correction")
    if sample.read2 is not None:
        command.extend(
            ["-I", str(sample.read2), "-O", str(output_dir / f"{sample.sample}.clean_R2.fastq.gz")]
        )
        if parameters.detect_adapter_for_pe:
            command.append("--detect_adapter_for_pe")
    return [*command, *config.extra_args]


def build_multiqc_command(
    *, reports_dir: Path, output_dir: Path, config: MultiqcConfig
) -> list[str]:
    """返回限定为 fastp 模块的 MultiQC argv。"""
    command = [
        "multiqc",
        str(reports_dir),
        "-o",
        str(output_dir),
        "-n",
        config.report_name,
        "--no-ansi",
    ]
    if config.force:
        command.append("-f")
    for module in config.modules:
        command.extend(["-m", module])
    return [*command, *config.extra_args]

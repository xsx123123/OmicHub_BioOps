#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import glob
from pathlib import Path
from typing import Dict, List, Union
from snakemake.io import expand


def qc_clean(samples: Dict = None, data_deliver: List = None) -> List:
    """
    Handle quality control and cleaning steps.

    Args:
        samples: Dictionary of sample information
        data_deliver: List of deliverable files to extend

    Returns:
        Updated list of deliverable files
    """
    if samples is None:
        samples = {}
    if data_deliver is None:
        data_deliver = []

    data_deliver.append("01.qc/short_read_multiqc/multiqc_raw-data_report.html")
    data_deliver.append(
        "01.qc/multiqc_short_read_trim/multiqc_short_read_trim_report.html"
    )
    data_deliver.append("01.qc/multiqc_merge_qc/multiqc_merge_qc_report.html")
    data_deliver.append("01.qc/fastq_screen_multiqc/multiqc_fastq_screen_report.html")
    return data_deliver


def mapping(
    samples: Dict = None, data_deliver: List = None, config: Dict = None
) -> List:
    """
    Handle ATAC-seq sequence alignment and related outputs.

    Args:
        samples: Dictionary of sample information
        data_deliver: List of deliverable files to extend
        config: Configuration dictionary

    Returns:
        Updated list of deliverable files
    """
    if samples is None:
        samples = {}
    if data_deliver is None:
        data_deliver = []
    if config is None:
        config = {}

    data_deliver.extend(expand("02.mapping/cram/{sample}.cram", sample=samples.keys()))
    data_deliver.extend(
        expand("02.mapping/cram/{sample}.cram.crai", sample=samples.keys())
    )
    # data_deliver.extend(
    #     expand("02.mapping/preseq/{sample}.lc_extrap.txt", sample=samples.keys())
    # )
    # data_deliver.extend(
    #     expand("02.mapping/preseq/{sample}.c_curve.txt", sample=samples.keys())
    # )
    # data_deliver.extend(expand("02.mapping/filter_pe/{sample}.filter_pe.sorted.bam", sample=samples.keys()))
    # data_deliver.extend(expand("02.mapping/filter_pe/{sample}.filter_pe.sorted.bam.bai",sample=samples.keys()))
    data_deliver.extend(
        expand("02.mapping/shifted/{sample}.shifted.sorted.bam", sample=samples.keys())
    )
    data_deliver.extend(
        expand(
            "02.mapping/shifted/{sample}.shifted.sorted.bam.bai", sample=samples.keys()
        )
    )
    # bamCoverage & tss enrichment plot
    data_deliver.extend(expand("02.mapping/bamCoverage/{sample}_RPKM.bw", sample=samples.keys()))
    data_deliver.extend(expand("02.mapping/computeMatrix/{sample}_TSS_matrix.gz", sample=samples.keys()))
    data_deliver.extend(expand("02.mapping/plots/{sample}_TSS_enrichment.png", sample=samples.keys()))
    # samtools stats & flagstat
    data_deliver.extend(expand(
            "02.mapping/samtools_flagstat/{sample}_bam_flagstat.tsv",
            sample=samples.keys()))
    
    data_deliver.extend(expand(
            "02.mapping/samtools_flagstat/{sample}_bam_dedup_flagstat.tsv",
            sample=samples.keys()))

    data_deliver.extend(expand(
            "02.mapping/samtools_stats/{sample}_bam_stats.tsv", sample=samples.keys()))

    return data_deliver


def peak_calling(samples: Dict = None, data_deliver: List = None) -> List:
    """
    Handle ATAC-seq peak calling with MACS2.

    Args:
        samples: Dictionary of sample information
        data_deliver: List of deliverable files to extend

    Returns:
        Updated list of deliverable files
    """
    if samples is None:
        samples = {}
    if data_deliver is None:
        data_deliver = []

    # MACS2 single sample peaks
    data_deliver.extend(
        expand(
            "03.peak_calling/single_macs2/{sample}/{sample}_peaks.narrowPeak",
            sample=samples.keys(),
        )
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/single_macs2/{sample}/{sample}_peaks.xls", sample=samples.keys()
        )
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/single_macs2/{sample}/{sample}_summits.bed",
            sample=samples.keys(),
        )
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/single_macs2/{sample}/{sample}_treat_pileup.bdg",
            sample=samples.keys(),
        )
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/single_macs2_HOMER/{sample}_annotation.txt",
            sample=samples.keys(),
        )
    )
    data_deliver.extend(
        expand("03.peak_calling/single_macs2_HOMER/{sample}_stats.txt", sample=samples.keys())
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/single_macs2/{sample}/{sample}_frip.txt", sample=samples.keys()
        )
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/single_macs3/{sample}/{sample}_peaks.narrowPeak", sample=samples.keys()
        )
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/single_macs3/{sample}/{sample}_peaks.xls", sample=samples.keys()
        )
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/single_macs3/{sample}/{sample}_summits.bed", sample=samples.keys()
        )
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/single_macs3/{sample}/{sample}_treat_pileup.bdg", sample=samples.keys()
        )
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/single_macs3/{sample}/{sample}_frip.txt", sample=samples.keys()
        )
    )

    
    return data_deliver


def motif_analysis(samples: Dict = None, data_deliver: List = None) -> List:
    """
    Handle ATAC-seq motif analysis with HOMER.
    Note: HOMER annotation is now integrated into peak_calling function.

    Args:
        samples: Dictionary of sample information
        data_deliver: List of deliverable files to extend

    Returns:
        Updated list of deliverable files
    """
    if samples is None:
        samples = {}
    if data_deliver is None:
        data_deliver = []

    return data_deliver


def consensus_peaks(samples: Dict = None, data_deliver: List = None) -> List:
    """
    Handle consensus peak calling and count matrix generation.
    Uses single sample consensus peaks (from all samples merged).

    Args:
        samples: Dictionary of sample information
        data_deliver: List of deliverable files to extend

    Returns:
        Updated list of deliverable files
    """
    if samples is None:
        samples = {}
    if data_deliver is None:
        data_deliver = []

    data_deliver.append("04.consensus/single_macs2/all_samples_consensus_peaks.bed")
    data_deliver.append("04.consensus/single_macs2/all_samples_consensus_peaks_annotation.txt")
    data_deliver.append("04.consensus/single_macs2/consensus_counts_matrix.txt")
    data_deliver.append("04.consensus/single_macs2/matrix_description.txt")
    data_deliver.append("04.consensus/single_macs2/consensus_counts_matrix_ann.txt")

    data_deliver.append("04.consensus/single_macs3/all_samples_consensus_peaks.bed")
    data_deliver.append("04.consensus/single_macs3/all_samples_consensus_peaks_annotation.txt")
    data_deliver.append("04.consensus/single_macs3/consensus_counts_matrix.txt")
    data_deliver.append("04.consensus/single_macs3/matrix_description.txt")
    data_deliver.append("04.consensus/single_macs3/consensus_counts_matrix_ann.txt")

    return data_deliver

def diff_peaks(
    samples: Dict = None, data_deliver: List = None, run_pooled: bool = False
) -> List:
    """
    Handle differential peak analysis.

    Args:
        samples: Dictionary of sample information
        data_deliver: List of deliverable files to extend
        run_pooled: Whether pooled analysis is running

    Returns:
        Updated list of deliverable files

    Note:
        When run_pooled=True: uses pooled consensus peaks (more robust)
        When run_pooled=False: uses single-sample consensus peaks
    """
    if samples is None:
        samples = {}
    if data_deliver is None:
        data_deliver = []

    if run_pooled:
        data_deliver.append("06.deg_enrich/DEG_merge/Global_PCA.pdf")
        data_deliver.append(
            "06.deg_enrich/DEG_merge/All_Contrast_Differential_Peaks_Statistics.csv"
        )
        data_deliver.append("06.deg_enrich/merge_enrich/")
    else:
        data_deliver.append("06.deg_enrich/DEG/Global_PCA.pdf")
        data_deliver.append(
            "06.deg_enrich/DEG/All_Contrast_Differential_Peaks_Statistics.csv"
        )
        data_deliver.append("06.deg_enrich/enrich/")

    return data_deliver


def get_diff_analysis_input(config: Dict = None, merge_group: bool = False) -> str:
    """
    Get the correct consensus count matrix path for differential analysis.

    Args:
        config: Configuration dictionary
        merge_group: Whether all groups have >1 samples (auto-detected)

    Returns:
        Path to the consensus count matrix annotation file

    Priority:
        1. If config['peak_calling']['use_pooled_peaks'] is True AND merge_group is True, use pooled
        2. Otherwise, use single sample consensus (fallback)
    """
    use_pooled = (
        config.get("peak_calling", {}).get("use_pooled_peaks", True) if config else True
    )

    if use_pooled and merge_group:
        return "04.consensus/pooled_macs3/consensus_counts_matrix_ann.txt"
    else:
        return "04.consensus/single/consensus_counts_matrix_ann.txt"


def should_run_pooled_analysis(config: Dict = None, merge_group: bool = False) -> bool:
    """
    Determine whether to run pooled (group-level) analysis.

    Args:
        config: Configuration dictionary
        merge_group: Whether all groups have >1 samples (auto-detected)

    Returns:
        True if pooled analysis should be run
    """
    use_pooled = (
        config.get("peak_calling", {}).get("use_pooled_peaks", True) if config else True
    )

    if not use_pooled:
        return False

    if not merge_group:
        return False

    return True


def merge_group_analysis(groups: Dict = None, data_deliver: List = None) -> List:
    """
    Handle merge group specific analysis.

    Includes:
    - Pooled peak calling (merged BAM files)
    - IDR analysis (reproducible peaks)
    - Pooled consensus peaks for differential analysis

    Args:
        groups: Dictionary of group information
        data_deliver: List of deliverable files to extend

    Returns:
        Updated list of deliverable files
    """
    if groups is None:
        groups = {}
    if data_deliver is None:
        data_deliver = []

    data_deliver.extend(
        expand("02.mapping/merged/{group}.merged.bam", group=groups.keys())
    )
    data_deliver.extend(
        expand("02.mapping/merged/{group}.merged.bam.bai", group=groups.keys())
    )

    data_deliver.extend(
        expand(
            "03.peak_calling/pooled_macs3/{group}/{group}_peaks.narrowPeak",
            group=groups.keys(),
        )
    )
    data_deliver.extend(
        expand("03.peak_calling/pooled_macs3/{group}/{group}_peaks.xls", group=groups.keys())
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/pooled_macs3/{group}/{group}_summits.bed",
            group=groups.keys(),
        )
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/pooled_macs3/{group}/{group}_treat_pileup.bdg",
            group=groups.keys(),
        )
    )
    data_deliver.extend(
        expand(
            "03.peak_calling/pooled_macs3_HOMER/{group}_annotation.txt", group=groups.keys()
        )
    )
    data_deliver.extend(
        expand("03.peak_calling/pooled_macs3_HOMER/{group}_stats.txt", group=groups.keys())
    )

    # IDR analysis disabled
    # data_deliver.extend(
    #     expand(
    #         "03.peak_calling/idr/{group}/Final_Consensus_Peaks.bed",
    #         group=groups.keys(),
    #     )
    # )
    # data_deliver.extend(
    #     expand(
    #         "03.peak_calling/idr_HOMER/{group}_annotation.txt",
    #         group=groups.keys(),
    #     )
    # )
    # data_deliver.extend(
    #     expand("03.peak_calling/idr_HOMER/{group}_stats.txt", group=groups.keys())
    # )

    data_deliver.append("04.consensus/pooled_macs3/all_groups_consensus_peaks.bed")
    data_deliver.append("04.consensus/pooled_macs3/consensus_peaks_annotation.txt")
    data_deliver.append("04.consensus/pooled_macs3/consensus_counts_matrix.txt")
    data_deliver.append("04.consensus/pooled_macs3/matrix_description.txt")
    data_deliver.append("04.consensus/pooled_macs3/consensus_counts_matrix_ann.txt")

    data_deliver.append("05.ATAC_QC/multiqc_Pooled_report.html")

    return data_deliver


def atac_qc(
    samples: Dict = None, data_deliver: List = None, run_pooled: bool = False
) -> List:
    """
    Handle ATAC-seq specific QC reports.

    Args:
        samples: Dictionary of sample information
        data_deliver: List of deliverable files to extend
        run_pooled: Whether pooled analysis is running

    Returns:
        Updated list of deliverable files
    """
    if samples is None:
        samples = {}
    if data_deliver is None:
        data_deliver = []

    data_deliver.append("05.ATAC_QC/multiqc_ATAC_report.html")
    data_deliver.append("05.ATAC_QC/multiqc_MACS2_Samples_report.html")
    data_deliver.append("05.ATAC_QC/multiqc_MACS3_Samples_report.html")

    if run_pooled:
        data_deliver.append("05.ATAC_QC/multiqc_Pooled_report.html")

    return data_deliver

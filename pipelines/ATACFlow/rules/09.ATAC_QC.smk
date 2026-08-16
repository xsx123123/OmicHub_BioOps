#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
"""
ATACFlow Pipeline - ATAC-seq Quality Control Module

This module provides comprehensive quality control assessment specifically tailored
for ATAC-seq experiments, evaluating key metrics that indicate the success of
the transposase accessibility assay and the quality of the resulting sequencing data.

Key Components:
- get_organelle_filter_expr: Helper function to retrieve organellar chromosome names
- ataqv_qc: Performs comprehensive ATAC-seq QC using the Ataqv tool
- multiqc_ATAC_QC: Aggregates all ATAC-specific QC reports using MultiQC
- multiqc_macs2_samples: Aggregates MACS2 reports from individual samples
- multiqc_macs2_group: Aggregates MACS2 reports including group-level analyses

This module generates quality control metrics that are specific to ATAC-seq,
including TSS enrichment scores, fragment length distributions, nucleosome
positioning patterns, and library complexity estimates, providing a comprehensive
assessment of experiment quality.
"""

def get_organelle_filter_expr(wildcards):
    """
    Retrieve organellar chromosome names (mitochondrial and plastid) from configuration.

    This helper function extracts the names of organellar chromosomes (mitochondria
    and chloroplasts/plastids) from the genome configuration, which are used for
    specialized QC metrics and filtering in ATAC-seq analysis. Organellar reads
    are often highly abundant in ATAC-seq data and require special handling.

    Args:
        wildcards: Snakemake wildcards object containing sample information

    Returns:
        str: Name of the mitochondrial chromosome, or empty string if not configured
    """
    build = config.get("Genome_Version")
    chrMID = config.get("genome_info", {}).get(build, {}).get("chrMID", {})

    if isinstance(chrMID, list):
        # Return the first element if it's a list
        return chrMID[0] if chrMID else ""
    else:
        # Return the value directly if it's not a list
        return chrMID

rule ataqv_qc_macs3:
    """
    Perform comprehensive ATAC-seq QC using Ataqv with MACS3 peaks.
    """
    input:
        shifted_sort_bam = '02.mapping/shifted/{sample}.shifted.sorted.bam',
        shifted_sort_bam_bai = '02.mapping/shifted/{sample}.shifted.sorted.bam.bai',
        narrow_peak = "03.peak_calling/single_macs3/{sample}/{sample}_peaks.narrowPeak",
    output:
        json = "02.mapping/ataqv_macs3/{sample}.ataqv.json",
        log_out = "02.mapping/ataqv_macs3/{sample}.ataqv.out"
    benchmark:
        "benchmarks/05.ATAC_QC/ataqv_qc_macs3_{sample}.txt",
    conda:
        workflow.source_path("../envs/ataqv.yaml"),
    resources:
        **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger),
    log:
        "logs/05.ATAC_QC/ataqv_qc_macs3_{sample}.log",
    message:
        "Running ataqv QC (MACS3) on {wildcards.sample}",
    params:
        tss = config['Bowtie2_index'][config['Genome_Version']]['tss_bed'],
        autosomes = config['Bowtie2_index'][config['Genome_Version']]['autosomes'],
        mito_name = lambda wildcards:get_organelle_filter_expr(wildcards),
        organism = config['species']
    threads:
        1
    shell:
        """
        ataqv \
            --peak-file {input.narrow_peak} \
            --name {wildcards.sample} \
            --metrics-file {output.json} \
            --tss-file {params.tss} \
            --autosomal-reference-file {params.autosomes} \
            --mitochondrial-reference-name {params.mito_name} \
            --ignore-read-groups \
            {params.organism} \
            {input.shifted_sort_bam} > {output.log_out} 2> {log}
        """

rule ataqv_qc_macs2:
    """
    Perform comprehensive ATAC-seq QC using Ataqv with MACS2 peaks.
    """
    input:
        shifted_sort_bam = '02.mapping/shifted/{sample}.shifted.sorted.bam',
        shifted_sort_bam_bai = '02.mapping/shifted/{sample}.shifted.sorted.bam.bai',
        narrow_peak = "03.peak_calling/single_macs2/{sample}/{sample}_peaks.narrowPeak",
    output:
        json = "02.mapping/ataqv_macs2/{sample}.ataqv.json",
        log_out = "02.mapping/ataqv_macs2/{sample}.ataqv.out"
    benchmark:
        "benchmarks/05.ATAC_QC/ataqv_qc_macs2_{sample}.txt",
    conda:
        workflow.source_path("../envs/ataqv.yaml"),
    resources:
        **rule_resource(config, 'low_resource', skip_queue_on_local=True, logger=logger),
    log:
        "logs/05.ATAC_QC/ataqv_qc_macs2_{sample}.log",
    message:
        "Running ataqv QC (MACS2) on {wildcards.sample}",
    params:
        tss = config['Bowtie2_index'][config['Genome_Version']]['tss_bed'],
        autosomes = config['Bowtie2_index'][config['Genome_Version']]['autosomes'],
        mito_name = lambda wildcards:get_organelle_filter_expr(wildcards),
        organism = config['species']
    threads:
        1
    shell:
        """
        ataqv \
            --peak-file {input.narrow_peak} \
            --name {wildcards.sample} \
            --metrics-file {output.json} \
            --tss-file {params.tss} \
            --autosomal-reference-file {params.autosomes} \
            --mitochondrial-reference-name {params.mito_name} \
            --ignore-read-groups \
            {params.organism} \
            {input.shifted_sort_bam} > {output.log_out} 2> {log}
        """

rule multiqc_ATAC_QC:
    """
    Aggregate all ATAC-seq quality control reports into a unified summary using MultiQC.

    This rule collects all ATAC-seq specific quality control outputs and synthesizes
    them into a single interactive HTML report that provides a comprehensive overview
    of experiment quality across all samples. MultiQC parses outputs from Ataqv,
    Preseq, Samtools, and GATK to present a unified view of ATAC-seq data quality.

    Key QC metrics aggregated in this report include:
    - Ataqv ATAC-seq specific metrics (TSS enrichment, fragment lengths, etc.)
    - Library complexity estimates from Preseq
    - Mapping statistics from Samtools flagstat and stats
    - Duplication metrics from GATK MarkDuplicates
    - Sample-to-sample comparison of all quality metrics

    The aggregated report enables rapid identification of:
    - Outlier samples with quality issues
    - Systematic biases affecting multiple samples
    - Batch effects or plate-based patterns
    - Overall experiment quality and success

    This comprehensive QC summary is essential for quality assurance, providing a
    clear audit trail of data quality for publication and ensuring that only
    high-quality samples proceed to downstream analysis.
    """
    input:
        json_macs3 = expand("02.mapping/ataqv_macs3/{sample}.ataqv.json",sample=samples.keys()),
        log_out_macs3 = expand("02.mapping/ataqv_macs3/{sample}.ataqv.out",sample=samples.keys()),
        json_macs2 = expand("02.mapping/ataqv_macs2/{sample}.ataqv.json",sample=samples.keys()),
        log_out_macs2 = expand("02.mapping/ataqv_macs2/{sample}.ataqv.out",sample=samples.keys()),
        samtools_flagstat = expand('02.mapping/samtools_flagstat/{sample}_bam_flagstat.tsv',sample=samples.keys()),
        samtools_stats = expand('02.mapping/samtools_stats/{sample}_bam_stats.tsv',sample=samples.keys()),
    output:
        report = '05.ATAC_QC/multiqc_ATAC_report.html',
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/multiqc.yaml"),
    message:
        "Running MultiQC to aggregate fastp reports",
    benchmark:
        "benchmarks/05.ATAC_QC/multiqc_ATAC_QC.txt",
    params:
        origin_reports = "02.mapping/",
        report_dir = "05.ATAC_QC/",
        report = "multiqc_ATAC_report.html",
        title = "ATAC_report",
    log:
        "logs/05.ATAC_QC/multiqc_ATAC_QC.log",
    threads:
        config['parameter']['threads']['multiqc'],
    shell:
        """
        multiqc {params.origin_reports} \
                --force \
                --outdir {params.report_dir} \
                -i {params.title} \
                -n {params.report} &> {log}
        """

rule multiqc_macs2_samples:
    """
    Aggregate MACS2 single-sample peak calling reports using MultiQC.
    """
    input:
        xls = expand("03.peak_calling/single_macs2/{sample}/{sample}_peaks.xls",sample=samples.keys())
    output:
        report = '05.ATAC_QC/multiqc_MACS2_Samples_report.html',
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/multiqc.yaml"),
    message:
        "Running MultiQC to aggregate MACS2 single-sample reports",
    benchmark:
        "benchmarks/05.ATAC_QC/multiqc_macs2_samples.txt",
    params:
        origin_reports = "03.peak_calling/single_macs2/",
        report_dir = "05.ATAC_QC/",
        report = "multiqc_MACS2_Samples_report.html",
        title = "MACS2_Samples_report",
    log:
        "logs/05.ATAC_QC/multiqc_macs2_samples.log",
    threads:
        config['parameter']['threads']['multiqc'],
    shell:
        """
        multiqc {params.origin_reports} \
                --force \
                --outdir {params.report_dir} \
                -i {params.title} \
                -n {params.report} &> {log}
        """

rule multiqc_macs3_samples:
    """
    Aggregate MACS3 single-sample peak calling reports using MultiQC.
    """
    input:
        narrow_peak = expand("03.peak_calling/single_macs3/{sample}/{sample}_peaks.narrowPeak",sample=samples.keys())
    output:
        report = '05.ATAC_QC/multiqc_MACS3_Samples_report.html',
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/multiqc.yaml"),
    message:
        "Running MultiQC to aggregate MACS3 single-sample reports",
    benchmark:
        "benchmarks/05.ATAC_QC/multiqc_macs3_samples.txt",
    params:
        origin_reports = "03.peak_calling/single_macs3/",
        report_dir = "05.ATAC_QC/",
        report = "multiqc_MACS3_Samples_report.html",
        title = "MACS3_Samples_report",
    log:
        "logs/05.ATAC_QC/multiqc_macs3_samples.log",
    threads:
        config['parameter']['threads']['multiqc'],
    shell:
        """
        multiqc {params.origin_reports} \
                --force \
                --outdir {params.report_dir} \
                -i {params.title} \
                -n {params.report} &> {log}
        """

rule multiqc_pooled:
    """
    Aggregate pooled group-level peak calling reports using MultiQC.
    """
    input:
        group_xls = expand("03.peak_calling/pooled_macs3/{group}/{group}_peaks.xls",group=groups.keys())
    output:
        report = '05.ATAC_QC/multiqc_Pooled_report.html',
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/multiqc.yaml"),
    message:
        "Running MultiQC to aggregate pooled group reports",
    benchmark:
        "benchmarks/05.ATAC_QC/multiqc_pooled.txt",
    params:
        origin_reports = "03.peak_calling/pooled_macs3/",
        report_dir = "05.ATAC_QC/",
        report = "multiqc_Pooled_report.html",
        title = "Pooled_report",
    log:
        "logs/05.ATAC_QC/multiqc_pooled.log",
    threads:
        config['parameter']['threads']['multiqc'],
    shell:
        """
        multiqc {params.origin_reports} \
                --force \
                --outdir {params.report_dir} \
                -i {params.title} \
                -n {params.report} &> {log}
        """
# ----- end of rules ----- #
#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
import os

rule generate_fastq_screen_conf:
    """
    Generate FastQ Screen configuration file with properly formatted database paths.

    This rule dynamically creates the configuration file required for FastQ Screen
    contamination detection by substituting database path placeholders in a template
    configuration file with actual paths from the workflow configuration. This ensures
    that the tool can locate all necessary reference databases for comprehensive
    contamination screening.

    The template contains stubs for various reference genome databases typically
    screened for contamination, including common model organisms, microbial genomes,
    and potential laboratory contaminants. By dynamically resolving paths, this
    rule ensures flexibility across different computing environments and reference
    database installations without requiring manual configuration edits.
    """
    input:
        template = workflow.source_path(config['parameter']['validate_fastq_screen']['path_conf']),
    output:
        conf = "01.qc/fastq_screen.conf"
    message:
        "Running generate_fastq_screen_conf",
    params:
        db_path = config.get("fastq_screen_db_path", "/data/jzhang/reference/"),
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    log:
        "logs/04.Contamination_check/generate_fastq_screen_conf.log",
    benchmark:
        "benchmarks/04.Contamination_check/generate_fastq_screen_conf.txt",
    localrule: True
    shell:
        """
        sed "s|__FASTQ_SCREEN_DB_PATH__|{params.db_path}|g" {input.template} > {output.conf} 2> {log}
        """

rule check_fastq_screen_conf:
    """
    Validate the FastQ Screen configuration file and verify database accessibility.

    This rule performs a comprehensive validation of the generated FastQ Screen
    configuration file to ensure all specified reference databases exist, are
    accessible, and are properly formatted. This validation step catches potential
    issues early in the workflow before attempting time-consuming contamination
    screening analysis.

    The validation process checks:
    - Configuration file syntax and structure
    - Existence of all specified reference database files
    - Read permissions for database files
    - Proper formatting of database indices
    - Compatibility with the selected alignment tool

    By validating the configuration upfront, this rule prevents wasted computation
    and provides clear error messages about any missing or misconfigured resources,
    enabling rapid troubleshooting and ensuring smooth workflow execution.
    """
    input:
        conf = "01.qc/fastq_screen.conf",
    output:
        log = "01.qc/fastq_screen_config_check.log",
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    message:
        "Running check_fastq_screen_conf",
    params:
        validate_fastq_screen = workflow.source_path(config['parameter']['validate_fastq_screen']['path']),
    log:
        "logs/04.Contamination_check/check_fastq_screen_conf.log",
    benchmark:
        "benchmarks/04.Contamination_check/check_fastq_screen_conf.txt",
    threads:
        1
    shell:
        """
        chmod +x {params.validate_fastq_screen} && \
        {params.validate_fastq_screen} {input.conf} --log {output.log} &> {log}
        """

rule short_read_fastq_screen_r1:
    """
    Screen R1 (forward) reads for contamination using FastQ Screen.

    This rule performs comprehensive contamination detection on the forward reads
    by aligning a subset of reads against a panel of reference genomes that represent
    common sources of contamination in sequencing experiments. FastQ Screen provides
    valuable insights into the purity of the sequencing library by identifying
    reads that map to unexpected reference genomes.

    The contamination screening panel typically includes:
    - The target reference genome (expected primary mapping)
    - Common model organisms (potential cross-sample contamination)
    - Microbial genomes (bacterial, fungal, viral contamination)
    - Organellar genomes (mitochondrial, chloroplast for plants)
    - Common laboratory contaminants (e.g., E. coli, yeast)

    This analysis generates a detailed text report showing the percentage of reads
    mapping to each reference database, multi-mapping reads, and unmapped reads.
    The results help identify:
    - Significant contamination from unexpected sources
    - Sample mix-ups or cross-contamination
    - Library preparation artifacts
    - Potential issues with sample collection or processing

    For ATAC-seq experiments, this is particularly important for detecting organellar
    contamination (chloroplast/mitochondria in plants) which can be substantial and
    requires special handling in downstream filtering steps.
    """
    input:
        md5_check = "01.qc/md5_check.tsv",
        log = "01.qc/fastq_screen_config_check.log",
        conf = "01.qc/fastq_screen.conf"
    output:
        fastq_screen_result = "01.qc/fastq_screen/{sample}_R1_screen.txt",
    resources:
        **rule_resource(config, 'high_resource',  skip_queue_on_local=True,logger = logger),
    log:
        "logs/04.Contamination_check/short_read_fastq_screen_r1_{sample}.log",
    conda:
        workflow.source_path('../envs/fastq_screen.yaml'),
    params:
        out_dir = "01.qc/fastq_screen/",
        link_r1_dir = os.path.join("00.raw_data",
                                      config['convert_md5'],
                                      "{sample}/{sample}_R1.fq.gz"),
        subset = config['parameter'][ 'fastq_screen']['subset'],
        aligner = config['parameter']['fastq_screen']['aligner'],
    message:
        "Running fastq_screen on {wildcards.sample} r1",
    benchmark:
        "benchmarks/04.Contamination_check/short_read_fastq_screen_r1_{sample}.txt",
    threads:
        config['parameter']['threads']['fastq_screen'],
    shell:
        """
        fastq_screen --threads  {threads} \
                     --force \
                     --subset  {params.subset} \
                     --aligner  {params.aligner} \
                     --conf {input.conf} \
                     --outdir {params.out_dir} \
                     {params.link_r1_dir} &> {log}
        """

rule short_read_fastq_screen_r2:
    """
    Screen R2 (reverse) reads for contamination using FastQ Screen.

    This rule performs comprehensive contamination detection on the reverse reads
    by aligning a subset of reads against a panel of reference genomes that represent
    common sources of contamination in sequencing experiments. FastQ Screen provides
    valuable insights into the purity of the sequencing library by identifying
    reads that map to unexpected reference genomes.

    The contamination screening panel typically includes:
    - The target reference genome (expected primary mapping)
    - Common model organisms (potential cross-sample contamination)
    - Microbial genomes (bacterial, fungal, viral contamination)
    - Organellar genomes (mitochondrial, chloroplast for plants)
    - Common laboratory contaminants (e.g., E. coli, yeast)

    This analysis generates a detailed text report showing the percentage of reads
    mapping to each reference database, multi-mapping reads, and unmapped reads.
    The results help identify:
    - Significant contamination from unexpected sources
    - Sample mix-ups or cross-contamination
    - Library preparation artifacts
    - Potential issues with sample collection or processing

    For ATAC-seq experiments, this is particularly important for detecting organellar
    contamination (chloroplast/mitochondria in plants) which can be substantial and
    requires special handling in downstream filtering steps.
    """
    input:
        md5_check = "01.qc/md5_check.tsv",
        log = "01.qc/fastq_screen_config_check.log",
        conf = "01.qc/fastq_screen.conf"
    output:
        fastq_screen_result = "01.qc/fastq_screen/{sample}_R2_screen.txt",
    resources:
        **rule_resource(config, 'high_resource',  skip_queue_on_local=True,logger = logger),
    log:
        "logs/04.Contamination_check/short_read_fastq_screen_r2_{sample}.log",
    conda:
        workflow.source_path('../envs/fastq_screen.yaml'),
    params:
        out_dir = "01.qc/fastq_screen/",
        subset = config['parameter'][ 'fastq_screen']['subset'],
        aligner = config['parameter']['fastq_screen']['aligner'],
        link_r2_dir = os.path.join("00.raw_data",
                                      config['convert_md5'],
                                      "{sample}/{sample}_R2.fq.gz"),
    message:
        "Running fastq_screen on {wildcards.sample} r2",
    benchmark:
        "benchmarks/04.Contamination_check/short_read_fastq_screen_r2_{sample}.txt",
    threads:
        config['parameter']['threads']['fastq_screen'],
    shell:
        """
        fastq_screen --threads  {threads} \
                     --force \
                     --subset  {params.subset} \
                     --aligner  {params.aligner} \
                     --conf {input.conf} \
                     --outdir {params.out_dir} \
                     {params.link_r2_dir} &> {log}
        """

rule fastq_screen_multiqc:
    """
    Aggregate R1 FastQ Screen contamination reports into a unified summary using MultiQC.

    This rule collects all individual R1 FastQ Screen reports and synthesizes them
    into a single interactive HTML report that enables cross-sample comparison of
    contamination profiles. MultiQC parses the FastQ Screen output and presents
    contamination statistics in an intuitive visual format.

    The aggregated report features:
    - Heatmaps showing contamination levels across all samples and reference databases
    - Bar charts displaying the composition of each sample's read mapping
    - Summary statistics highlighting samples with exceptional contamination levels
    - Interactive plots that allow zooming and filtering for detailed exploration
    - Exportable tables for further statistical analysis

    By aggregating contamination results from all samples, this report makes it easy
    to identify:
    - Systematic contamination affecting multiple samples
    - Individual outliers with severe contamination issues
    - Batch effects or plate-based contamination patterns
    - Trends that may indicate laboratory or reagent contamination

    This comprehensive view is essential for quality control and provides critical
    information for deciding whether samples can be safely included in downstream
    ATAC-seq analysis or require additional filtering.
    """
    input:
        fastqc_files_r1 = expand("01.qc/fastq_screen/{sample}_R1_screen.txt",\
                                  sample=samples.keys()),
        fastqc_files_r2 = expand("01.qc/fastq_screen/{sample}_R2_screen.txt",\
                                  sample=samples.keys()),
    output:
        report = "01.qc/fastq_screen_multiqc/multiqc_fastq_screen_report.html",
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/multiqc.yaml"),
    message:
        "Running MultiQC to aggregate R1 fastq screen reports",
    params:
        fastqc_reports = "01.qc/fastq_screen",
        report_dir = "01.qc/fastq_screen_multiqc/",
        report = "multiqc_fastq_screen_report.html",
        title = "fastq-screen-multiqc-report",
    log:
        "logs/04.Contamination_check/fastq_screen_multiqc.log",
    benchmark:
        "benchmarks/04.Contamination_check/fastq_screen_multiqc.txt",
    threads:
        config['parameter']['threads']['multiqc'],
    shell:
        """
        multiqc {params.fastqc_reports} \
                --force \
                --outdir {params.report_dir} \
                -i {params.title} \
                -n {params.report} &> {log}
        """
# ----- end of rules ----- #

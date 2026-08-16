#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
import os

rule short_read_qc_r1:
    """
    Perform quality control assessment on R1 (forward) reads using FastQC.

    This rule generates a comprehensive quality control report for the forward reads
    of each sample, evaluating key sequencing metrics that indicate data quality.
    FastQC performs a series of analytical modules to identify potential issues
    that may affect downstream analysis.

    Key metrics evaluated include:
    - Per-base sequence quality scores across the read length
    - Per-sequence quality score distributions
    - Per-base sequence content and GC composition
    - Adapter contamination levels
    - Sequence duplication levels
    - Overrepresented sequences (potential contaminants)
    - K-mer content analysis

    The HTML report provides visualizations for each metric, enabling rapid
    identification of quality issues that may require trimming or filtering
    in subsequent processing steps. This is the first step in assessing
    overall data quality before proceeding with more complex analysis.
    """
    input:
        md5_check = "01.qc/md5_check.tsv",
        link_r1_dir = os.path.join("00.raw_data",
                                      config['convert_md5'],
                                      "{sample}/{sample}_R1.fq.gz"),
    output:
        r1_html = "01.qc/short_read_qc/{sample}_R1_fastqc.html",
        r1_zip = "01.qc/short_read_qc/{sample}_R1_fastqc.zip",
    resources:
        **rule_resource(config,'low_resource', skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/fastqc.yaml"),
    log:
        "logs/03.short_read_qc/short_read_qc_r1_{sample}.log",
    params:
        out_dir = "01.qc/short_read_qc/",
        r1 = "00.link_dir/{sample}/{sample}_R1.fq.gz",
    message:
        "Running short_read_qc_r1",
    benchmark:
        "benchmarks/03.short_read_qc/short_read_qc_r1_{sample}.txt",
    threads:
        config['parameter']['threads']['fastqc'],
    shell:
        """
        fastqc {input.link_r1_dir} \
               -o {params.out_dir} \
               --threads {threads} &> {log}
        """

rule short_read_qc_r2:
    """
    Perform quality control assessment on R2 (reverse) reads using FastQC.

    This rule generates a comprehensive quality control report for the reverse reads
    of each sample, evaluating the same key sequencing metrics as the R1 analysis.
    Analyzing both read directions independently provides a complete picture of
    sequencing quality across the entire fragment.

    Comparing R1 and R2 quality metrics can reveal:
    - Systematic quality degradation in reverse reads (common in Illumina sequencing)
    - Direction-specific biases or contamination
    - Differences in adapter content between read pairs
    - Asymmetric sequence composition issues

    Like the R1 analysis, this generates both HTML and ZIP format reports. The HTML
    report enables interactive visualization of quality metrics, while the ZIP file
    contains the raw data for downstream aggregation with MultiQC. This paired
    analysis ensures comprehensive quality assessment before sequence trimming.
    """
    input:
        md5_check = "01.qc/md5_check.tsv",
        link_r2_dir = os.path.join("00.raw_data",
                                      config['convert_md5'],
                                      "{sample}/{sample}_R2.fq.gz"),
    output:
        r2_html = "01.qc/short_read_qc/{sample}_R2_fastqc.html",
        r2_zip = "01.qc/short_read_qc/{sample}_R2_fastqc.zip",
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/fastqc.yaml"),
    log:
        "logs/03.short_read_qc/short_read_qc_r2_{sample}.log",
    params:
        out_dir = "01.qc/short_read_qc",
        r2 = "00.link_dir/{sample}/{sample}_R2.fq.gz",
    message:
        "Running short_read_qc_r2",
    benchmark:
        "benchmarks/03.short_read_qc/short_read_qc_r2_{sample}.txt",
    threads:
        config['parameter']['threads']['fastqc'],
    shell:
        """
        fastqc {input.link_r2_dir} \
               -o {params.out_dir} \
               --threads {threads} &> {log}
        """

# logger.info('Run MultiQC to summarize R1 fastqc QC reports')
rule short_read_multiqc:
    """
    Aggregate R1 FastQC reports into a unified quality control summary using MultiQC.

    This rule collects all individual R1 FastQC reports and synthesizes them into
    a single interactive HTML report that enables cross-sample comparison of quality
    metrics. MultiQC parses the output from numerous bioinformatics tools and
    presents the results in a coherent, visual format.

    Key features of this aggregated report include:
    - Side-by-side comparison of quality metrics across all samples
    - Interactive plots that can be customized and downloaded
    - Summary statistics for each quality module
    - Identification of outlier samples with potential quality issues
    - Exportable data tables for further analysis

    By aggregating results from all samples, this report makes it easy to identify
    batch effects, systematic biases, or individual sample anomalies that might
    require attention. The unified view simplifies quality assessment across the
    entire experiment and facilitates informed decision-making about sample
    inclusion or exclusion in downstream analyses.
    """
    input:
        fastqc_files_r1 = expand("01.qc/short_read_qc/{sample}_R1_fastqc.zip", sample=samples.keys()),
    output:
        report_dir = "01.qc/short_read_multiqc/multiqc_raw-data_report.html",
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/multiqc.yaml"),
    message:
        "Running MultiQC to aggregate FastQC reports",
    params:
        fastqc_reports = "01.qc/short_read_qc",
        multiqc_dir = '01.qc/short_read_multiqc/',
        report = "multiqc_raw-data_report.html",
        title = "raw-data-multiqc-report",
    log:
        "logs/03.short_read_qc/multiqc.log",
    benchmark:
        "benchmarks/03.short_read_qc/multiqc.txt",
    threads:
        config['parameter']['threads']['multiqc'],
    shell:
        """
        multiqc {params.fastqc_reports} \
                --force \
                --outdir {params.multiqc_dir} \
                -i {params.title} \
                -n {params.report} &> {log}
        """
# ----- end of rules ----- #

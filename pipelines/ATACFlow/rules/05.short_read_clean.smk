#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
import os

rule short_read_fastp:
    """
    Perform comprehensive adapter trimming and quality filtering on paired-end reads using Fastp.

    This rule processes raw sequencing reads to remove adapter sequences, low-quality bases,
    and short fragments, generating high-quality cleaned reads for downstream ATAC-seq analysis.
    Fastp is an ultra-fast all-in-one preprocessing tool that provides exceptional performance
    and comprehensive quality control statistics.

    Key processing steps performed include:
    - Adapter sequence trimming using a curated adapter database
    - Quality-based trimming of low-quality bases from read ends
    - Global trimming by quality threshold (sliding window approach)
    - Filtering of reads below minimum length requirements
    - PolyG tail trimming (for NovaSeq/NextSeq data)
    - Quality filtering based on overall read quality

    Fastp generates comprehensive HTML and JSON reports documenting:
    - Pre- and post-processing quality statistics
    - Adapter content and trimming efficiency
    - Quality score distributions before and after filtering
    - GC content and sequence composition analysis
    - Duplication rate estimation
    - Insert size distribution (for paired-end data)

    For ATAC-seq experiments, proper trimming is critical because:
    - Adapter contamination can severely impact mapping efficiency
    - Low-quality reads introduce noise in peak calling
    - Proper fragment length selection improves nucleosome positioning analysis
    - Clean data is essential for accurate Tn5 insertion site correction

    The cleaned reads serve as input for all downstream analysis steps including
    read alignment, peak calling, and transcription factor footprinting analysis.
    """
    input:
        md5_check = "01.qc/md5_check.tsv",
        link_r1_dir =  os.path.join("00.raw_data",
                                      config['convert_md5'],
                                      "{sample}/{sample}_R1.fq.gz"),
        link_r2_dir =  os.path.join("00.raw_data",
                                      config['convert_md5'],
                                      "{sample}/{sample}_R2.fq.gz"),
    output:
        r1_trimmed = "01.qc/short_read_trim/{sample}.R1.trimed.fq.gz",
        r2_trimmed = "01.qc/short_read_trim/{sample}.R2.trimed.fq.gz",
        html_report = "01.qc/short_read_trim/{sample}.trimed.html",
        json_report = "01.qc/short_read_trim/{sample}.trimed.json",
    resources:
        **rule_resource(config, 'high_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/fastp.yaml"),
    log:
        "logs/05.short_read_clean/short_read_fastp_{sample}.log",
    message:
        "Running Fastp on {wildcards.sample} r1 and {wildcards.sample} r2",
    benchmark:
        "benchmarks/05.short_read_clean/short_read_fastp_{sample}.txt",
    params:
        length_required = config['parameter']["trim"]["length_required"],
        quality_threshold = config['parameter']["trim"]["quality_threshold"],
        adapter_fasta = workflow.source_path(config['parameter']["trim"]["adapter_fasta"]),
    threads:
        config['parameter']["threads"]["fastp"],
    shell:
        """
        fastp -i {input.link_r1_dir} -I {input.link_r2_dir} \
              -o {output.r1_trimmed} -O {output.r2_trimmed} \
              --thread {threads} \
              --length_required  {params.length_required} \
              --qualified_quality_phred {params.quality_threshold} \
              --adapter_fasta {params.adapter_fasta} \
              -g -V \
              -h {output.html_report} \
              -j {output.json_report} &> {log}
        """

rule multiqc_trim:
    """
    Aggregate Fastp trimming reports into a unified quality control summary using MultiQC.

    This rule collects all individual Fastp trimming reports and synthesizes them into
    a single interactive HTML report that enables cross-sample comparison of trimming
    statistics and quality improvements. MultiQC parses the Fastp JSON output and
    presents the preprocessing results in a coherent, visual format.

    Key features of this aggregated report include:
    - Side-by-side comparison of pre- and post-trimming quality metrics
    - Summary of adapter content and trimming efficiency across all samples
    - Visualization of read length distributions after quality filtering
    - Assessment of how many reads were retained or discarded
    - Identification of samples with exceptional trimming patterns
    - Interactive plots that can be customized and downloaded
    - Exportable data tables for further analysis

    By aggregating trimming results from all samples, this report enables:
    - Evaluation of overall trimming effectiveness across the experiment
    - Detection of systematic issues affecting library preparation
    - Identification of outlier samples that may require reprocessing
    - Documentation of data processing steps for publication and reproducibility
    - Quality assurance before proceeding to read alignment

    This report, together with the raw and trimmed FastQC reports, provides a
    comprehensive audit trail of data quality improvements through the preprocessing
    pipeline, ensuring transparency and reproducibility of the ATAC-seq analysis.
    """
    input:
        md5_check = "01.qc/md5_check.tsv",
        r1_trimmed = expand("01.qc/short_read_trim/{sample}.R1.trimed.fq.gz",
                            sample=samples.keys()),
        r2_trimmed = expand("01.qc/short_read_trim/{sample}.R2.trimed.fq.gz",
                            sample=samples.keys()),
        fastp_report = expand("01.qc/short_read_trim/{sample}.trimed.html",
                              sample=samples.keys()),
    output:
        report = '01.qc/multiqc_short_read_trim/multiqc_short_read_trim_report.html',
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    conda:
        workflow.source_path("../envs/multiqc.yaml"),
    message:
        "Running MultiQC to aggregate fastp reports",
    benchmark:
        "benchmarks/05.short_read_clean/multiqc_trim.txt",
    params:
        fastqc_reports = "01.qc/short_read_trim/",
        report_dir = "01.qc/multiqc_short_read_trim/",
        report = "multiqc_short_read_trim_report.html",
        title = "short_read_trim-multiqc-report",
    log:
        "logs/05.short_read_clean/multiqc_trim.log",
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

rule merge_qc_report:
    """
    Aggregate all preprocessing quality control reports into a comprehensive summary.

    This rule collects all quality control outputs from the preprocessing pipeline
    and synthesizes them into a single interactive HTML report using MultiQC.
    This comprehensive report provides a unified view of data quality across all
    samples and all preprocessing steps, from raw data through cleaning and
    initial quality assessment.

    Key quality control metrics aggregated in this report include:
    - Raw read quality statistics from FastQC (both R1 and R2 reads)
    - Trimming statistics and quality improvements from Fastp
    - Adapter content and trimming efficiency
    - Read length distributions after quality filtering
    - Overall quality metrics before and after preprocessing
    - Sample-to-sample comparison of all quality metrics

    The aggregated report enables rapid identification of:
    - Outlier samples with quality issues at any preprocessing step
    - Systematic biases affecting multiple samples
    - Batch effects or plate-based quality patterns
    - Overall success of the preprocessing pipeline
    - Trends in quality improvements through the pipeline

    This comprehensive preprocessing QC summary is essential for quality assurance,
    providing a clear audit trail of data quality improvements and ensuring that
    only high-quality, properly processed data proceeds to downstream analysis
    steps including read alignment and peak calling. The report also serves as
    valuable documentation for publication and reproducibility.
    """
    input:
        md5_check = "01.qc/md5_check.tsv",
        fastqc_files_r1 = expand("01.qc/short_read_qc/{sample}_R1_fastqc.zip", sample=samples.keys()),
        fastqc_files_r2 = expand("01.qc/short_read_qc/{sample}_R2_fastqc.zip", sample=samples.keys()),
        fastq_screen_result_r1 = expand("01.qc/fastq_screen/{sample}_R1_screen.txt",sample=samples.keys()),
        fastq_screen_result_r2 = expand("01.qc/fastq_screen/{sample}_R2_screen.txt",sample=samples.keys()),
        r1_trimmed = expand("01.qc/short_read_trim/{sample}.R1.trimed.fq.gz", sample=samples.keys()),
        r2_trimmed = expand("01.qc/short_read_trim/{sample}.R2.trimed.fq.gz", sample=samples.keys()),
        fastp_report = expand("01.qc/short_read_trim/{sample}.trimed.html", sample=samples.keys()),
    output:
        report = '01.qc/multiqc_merge_qc/multiqc_merge_qc_report.html',
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    benchmark:
        "benchmarks/05.short_read_clean/merge_qc_report_benchmarks.txt",
    message:
        "Running merge_qc_report",
    conda:
        workflow.source_path("../envs/multiqc.yaml"),
    params:
        search_dir = "01.qc",
        out_dir = "01.qc/multiqc_merge_qc",
        report_name = "multiqc_merge_qc_report.html",
        title = "merge qc report",
    log:
        "logs/05.short_read_clean/merge_qc_report.log",
    threads:
        config['parameter']['threads']['multiqc'],
    shell:
        """
        mkdir -p {params.out_dir}
        multiqc ./{params.search_dir} \
                --force \
                --outdir {params.out_dir} \
                --title "{params.title}" \
                --filename {params.report_name} \
                &> {log}
        """
# ----- end of rules ----- #
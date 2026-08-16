#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
"""
ATACFlow Pipeline - Report Generation Module

This module handles the generation of the final comprehensive HTML report for
ATAC-seq analysis results. It creates a structured, interactive report that
summarizes all key findings, quality metrics, and analysis results in a
user-friendly format suitable for sharing and publication.

Key Components:
- generate_docker_json: Prepares project metadata and summary information for reporting
- Report: Generates the final interactive HTML report using a Docker container

This module creates a professional, comprehensive report that includes all
essential analysis results, quality control metrics, and visualizations,
providing a complete summary of the ATAC-seq experiment and analysis.
"""

rule generate_docker_json:
    """
    Generate project metadata and summary information for the final report.

    This rule prepares a structured JSON file containing comprehensive project
    metadata, sample statistics, and file path information required for generating
    the final interactive ATAC-seq analysis report. The JSON file serves as the
    primary configuration and data source for the report generation container.

    Key information included in the project summary:
    - Project metadata (client name, species, genome version, analysis date)
    - Pipeline version information for reproducibility
    - Sample statistics (total number of samples, number of experimental groups)
    - File path mappings for all analysis results and visualizations
    - Configuration for the report generation container

    The generated JSON file includes:
    - project_meta: Comprehensive project information and metadata
    - stats: Sample and group statistics
    - input_files: File path mappings for all report components

    This configuration file is essential for the report generation process, as it
    provides the container with all necessary information to locate, organize, and
    display the analysis results in the final interactive HTML report. The JSON
    file ensures that the report generation process is reproducible and configurable.
    """
    input:
        manifest_json = os.path.join(config['data_deliver'],'report_data','delivery_manifest.json'),
        manifest_md5 = os.path.join(config['data_deliver'],'report_data','delivery_manifest.md5'),
        manifest_log = os.path.join(config['data_deliver'],'report_data','delivery_details.log'),
        sample_sheet = config['sample_csv'],
    output:
        json_file = os.path.join(config['data_deliver'], "report_data/project_summary.json")
    resources:
        **rule_resource(config, 'low_resource',  skip_queue_on_local=True,logger = logger),
    log:
        "logs/08.Report/generate_docker_json.log",
    benchmark:
        "benchmarks/08.Report/generate_docker_json.txt",
    message:
        "Running generate_docker_json",
    conda:
        workflow.source_path("../envs/py3.12.yaml"),
    params:
        client = config["client"],
        species = config["species"],
        Genome_Version = config["Genome_Version"], 
        pipeline_version = config["pipeline_version"],
        docker_prefix = "/data",
    threads:
        1
    run:
        import pandas as pd
        import datetime  
        import json      
        import os        

        df = pd.read_csv(input.sample_sheet)
        calculated_sample_count = len(df)
        calculated_group_count = df['group'].nunique()
        analysis_date = datetime.date.today().strftime("%Y-%m-%d")
        project_meta = {
            "client": params.client,
            "species": params.species,
            "genome_version": params.Genome_Version,
            "pipeline_version": params.pipeline_version,
            "analysis_date": analysis_date
        }
        stats = {
            "total_samples": int(calculated_sample_count),
            "group_count": int(calculated_group_count)
        }
        input_files = {
            "data_dir": f"{params.docker_prefix}/index/",
            "qc_file": f"{params.docker_prefix}/index/multiqc_qc_general_stats.txt",
            "mapping_file": f"{params.docker_prefix}/index/multiqc_mapping_general_stats.txt",
            "tpm_file": f"{params.docker_prefix}/index/merge_rsem_tpm.tsv",
            "sample_file": f"{params.docker_prefix}/index/sample.csv",
            "fastp_report_dir": f"{params.docker_prefix}/fastp_trim_report/multiqc_short_read_trim_report_data",
            "fastp_stats_file": f"{params.docker_prefix}/fastp_trim_report/multiqc_general_stats.txt",
            "fastq_screen_r1_dir": f"{params.docker_prefix}/fastq_screen_report/fastq_screen_multiqc_r1/multiqc_r1_fastq_screen_report_data",
            "fastq_screen_r2_dir": f"{params.docker_prefix}/fastq_screen_report/fastq_screen_multiqc_r2/multiqc_r2_fastq_screen_report_data",
            "qualimap_dir": f"{params.docker_prefix}/QualiMap/multiqc_data/",
            "contrasts_file": f"{params.docker_prefix}/index/contrasts.csv",
            "deg_dir": f"{params.docker_prefix}/res/DEG",
            "enrichment_dir": f"{params.docker_prefix}/res/Enrichments"
        }
        final_data = {
            "project_meta": project_meta,
            "stats": stats,
            "input_files": input_files
        }
        os.makedirs(os.path.dirname(output.json_file), exist_ok=True)
        with open(output.json_file, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, indent=2, ensure_ascii=False)

rule Report:
    """
    Generate the final comprehensive interactive HTML report for ATAC-seq analysis.

    This rule creates a professional, interactive HTML report that summarizes all
    key findings from the ATAC-seq analysis, including quality control metrics,
    read alignment statistics, peak calling results, differential accessibility
    analysis, and functional enrichment results. The report is generated using
    a specialized Docker container that packages all necessary reporting tools
    and templates.

    Key report components typically include:
    - Executive summary with project overview and key findings
    - Quality control metrics and visualizations for all samples
    - Read alignment statistics and mapping quality assessments
    - Peak calling results and genomic distribution of accessible regions
    - Differential accessibility analysis with statistical summaries
    - Functional enrichment analysis for differentially accessible regions
    - Interactive visualizations for exploring the data
    - Detailed methods section describing the analysis pipeline

    The report generation process:
    1. Uses Apptainer (Singularity) to run the reporting Docker container
    2. Mounts all necessary analysis results and configuration files
    3. Executes the reporting pipeline within the container environment
    4. Generates a self-contained HTML report with embedded visualizations

    The final HTML report is completely self-contained, meaning it can be viewed
    in any modern web browser without requiring additional software or data files.
    This makes it ideal for sharing with collaborators, including in publications,
    or for archival purposes. The report provides a complete and reproducible
    summary of the entire ATAC-seq analysis workflow and results.
    """
    input:
        DataDeliver(config),
        json_file = os.path.join(config['data_deliver'], "report_data/project_summary.json"),
        manifest_json = os.path.join(config['data_deliver'],'report_data','delivery_manifest.json'),
        manifest_md5 = os.path.join(config['data_deliver'],'report_data','delivery_manifest.md5'),
        manifest_log = os.path.join(config['data_deliver'],'report_data','delivery_details.log'),
    output:
        Report_html =  os.path.join(config['data_deliver'], "Analysis_Report/index.html")
    resources:
        **rule_resource(config, 'high_resource',  skip_queue_on_local=True,logger = logger),
    message:
        "Running Report",
    conda:
        workflow.source_path("../envs/py3.12.yaml"),
    params:
        data_dir = os.path.join(config['data_deliver'],'report_data','data'),
        Report_dir = os.path.join(config['data_deliver'], "Analysis_Report"),
        docker_version = config['parameter']['Report']['docker_version'],
    log:
        "logs/08.Report/Report.log",
    benchmark:
        "benchmarks/08.Report/Report.txt",
    threads:
        config['parameter']['threads']['Report'],
    shell:
        """
        ( 
        # 1. 创建输出目录
        mkdir -p {params.Report_dir} && \\
        
        # 2. 运行 Apptainer 容器
        # 使用 docker:// 协议直接加载 Docker 镜像，Apptainer 会自动处理转换和缓存
        # --cleanenv: 防止主机环境变量污染容器
        # --bind: 挂载目录 (Apptainer 默认读写挂载)
        
        apptainer run --cleanenv \\
               --bind {params.data_dir}:/data \\
               --bind {input.json_file}:/app/project_summary.json \\
               --bind {params.Report_dir}:/workspace/ \\
               docker://{params.docker_version}
        ) &>{log}
        """
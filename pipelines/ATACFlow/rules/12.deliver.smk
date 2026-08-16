#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
"""
ATACFlow Pipeline - Results Delivery and Reporting Module

This module handles the final stage of the ATAC-seq analysis pipeline, focusing on
organizing, packaging, and delivering analysis results to users. It coordinates
the generation of comprehensive reports, data summaries, and structured output
that enables researchers to understand their results and access their data easily.

Key Components:
- run_data_deliver: Orchestrates the delivery of processed data and results
- generate_report: Creates comprehensive analysis reports with visualizations
- generate_summary: Produces project-level summary statistics and documentation

This module serves as the final quality checkpoint and delivery mechanism,
ensuring that all analysis results are properly organized, documented, and
accessible for downstream interpretation and publication.
"""
import os
import pandas as pd

rule delivery:
    input:
        DataDeliver(config = config, samples = samples, merge_group = merge_group, groups = groups, run_pooled = run_pooled)
    output:
        manifest_json = os.path.join(config['data_deliver'],'delivery_manifest.json'),
        manifest_md5 = os.path.join(config['data_deliver'],'delivery_manifest.md5'),
        manifest_log = os.path.join(config['data_deliver'],'delivery_details.log'),
    resources:
        **rule_resource(config, 'high_resource',  skip_queue_on_local=True,logger = logger),
    message:
        "Running delivery",
    conda:
        workflow.source_path("../envs/py3.12.yaml"),
    params:
        out_dir = config['data_deliver'],
        config_path = workflow.source_path(config['parameter']['ATACFlow_Deliver_Tool']['config_path']),
        source_dir = config['workflow'],
    log:
        "logs/07.deliver/delivery.log",
    benchmark:
        "benchmarks/07.deliver/delivery.txt",
    threads:
        config['parameter']['threads']['rnaflow-cli'],
    shell:
        """
        ( rnaflow-cli deliver \
                    -d {params.source_dir} \
                    -o {params.out_dir} \
                    -c {params.config_path} ) &>{log}
        """

rule delivery_report:
    input:
        ReportData(config)
    output:
        manifest_json = os.path.join(config['data_deliver'],'report_data','delivery_manifest.json'),
        manifest_md5 = os.path.join(config['data_deliver'],'report_data','delivery_manifest.md5'),
        manifest_log = os.path.join(config['data_deliver'],'report_data','delivery_details.log'),
    resources:
        **rule_resource(config, 'high_resource',  skip_queue_on_local=True,logger = logger),
    message:
        "Running delivery_report",
    conda:
        workflow.source_path("../envs/py3.12.yaml"),
    params:
        out_dir =  os.path.join(config['data_deliver'],'report_data'),
        config_path = workflow.source_path(config['parameter']['ATACFlow_Deliver_Tool']['config_path_report']),
        source_dir = config['workflow'],
    log:
        "logs/07.deliver/delivery_report.log",
    benchmark:
        "benchmarks/07.deliver/delivery_report.txt",
    threads:
        config['parameter']['threads']['rnaflow-cli'],
    shell:
        """
        ( rnaflow-cli deliver \
                    -d {params.source_dir} \
                    -o {params.out_dir} \
                    -c {params.config_path}  ) &>{log}
        """
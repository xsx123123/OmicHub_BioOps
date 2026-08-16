#!/usr/bin/snakemake
# -*- coding: utf-8 -*-
"""
ATACFlow Pipeline - Raw Data Processing and MD5 Validation Module

This module handles the initial processing of raw sequencing data by creating symbolic
links to the original files and performing comprehensive MD5 checksum validation to
ensure data integrity throughout the analysis pipeline.

Key Components:
- seq_preprocessor: Creates organized symbolic links and generates MD5 checksums
- check_md5: Validates MD5 checksums against the generated reference file

The module ensures that all raw data files are properly organized, accessible, and
verified for integrity before proceeding to downstream quality control and analysis steps.
This is critical for maintaining reproducibility and detecting any data corruption issues
early in the pipeline.
"""

import os

rule seq_preprocessor:
    """
    Process raw data and create symbolic links with MD5 validation
    """
    input:
        md5 = get_all_input_dirs(samples.keys(),config = config),
    output:
        md5_check = directory(os.path.join('00.raw_data',config['convert_md5'])),
        md5_check_json = os.path.join('00.raw_data',config['convert_md5'],"raw_data_md5.json"),
        link_r1 = expand(os.path.join('00.raw_data',
                                      config['convert_md5'],
                                      "{sample}/{sample}_R1.fq.gz"),
                                      sample=samples.keys()),
        link_r2 = expand(os.path.join('00.raw_data',
                                      config['convert_md5'],
                                      "{sample}/{sample}_R2.fq.gz"),
                                      sample=samples.keys()),
    message:
        "Running seq_preprocessor on raw data data",
    benchmark:
        "benchmarks/02.file_convert_md5/seq_preprocessor.txt",
    resources:
        **rule_resource(config, 'high_resource',  skip_queue_on_local=True,logger = logger),
    params:
        raw_data_path = config['raw_data_path'],
        md5 = config['raw_data']['md5'],
        seq_preprocessor =  workflow.source_path(config['software']['seq_preprocessor']),
    log:
        "logs/02.file_convert_md5/seq_preprocessor.log",
    threads: 1
    shell:
        """
        chmod +x {params.seq_preprocessor} && \
        {params.seq_preprocessor} -i  {params.raw_data_path} \
                                  -o {output.md5_check} \
                                  --md5-name {params.md5} \
                                  --json-report {output.md5_check_json} &> {log}
        """

rule check_md5:
    """
    Verify MD5 checksums of processed raw data files
    """
    input:
        md5_check_json = os.path.join('00.raw_data',config['convert_md5'],"raw_data_md5.json"),
        link_r1 = expand(os.path.join('00.raw_data',
                                      config['convert_md5'],
                                      "{sample}/{sample}_R1.fq.gz"),
                                      sample=samples.keys()),
        link_r2 = expand(os.path.join('00.raw_data',
                                      config['convert_md5'],
                                      "{sample}/{sample}_R2.fq.gz"),
                                      sample=samples.keys()),
    output:
        md5_check = "01.qc/md5_check.tsv",
    resources:
        **rule_resource(config, 'high_resource',  skip_queue_on_local=True,logger = logger),
    message:
        "Running md5 check on raw data files on {input.md5_check_json}",
    benchmark:
        "benchmarks/02.file_convert_md5/check_md5.txt",
    log:
        "logs/02.file_convert_md5/check_md5.log",
    params:
        md5_check = os.path.join('00.raw_data',config['convert_md5']),
        log_file = "logs/01.qc/md5_check.log",
        json_md5_verifier =  workflow.source_path(config['software']['json_md5_verifier']),
    threads:
        config['parameter']['threads']['json_md5_verifier'],
    shell:
        """
        chmod +x {params.json_md5_verifier} && \
        {params.json_md5_verifier} -t  {threads} \
                -i {input.md5_check_json} \
                -b {params.md5_check} \
                -o {output.md5_check} \
                --log-file {params.log_file} &> {log}
        """
# ----- end of rules ----- #
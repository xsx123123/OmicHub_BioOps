#!/usr/bin/env python3
# *---utf-8---*
# Version: ATACFlow v0.0.3
# Author : JZHANG

import sys
import os
from snakemake.utils import min_version, validate

# ------- Import Custom Modules ------- #
from rules.utils.id_convert import load_samples, load_contrasts,parse_groups
from rules.utils.validate import check_reference_paths,load_user_config,validate_genome_version,validate_species
from rules.utils.reference_update import resolve_reference_paths
from rules.utils.resource_manager import rule_resource

# Lock Snakemake Version
min_version("9.9.0")

# --------- 1. Config Loading --------- #
# Load default configs
configfile: "config/config.yaml"
configfile: "config/reference.yaml"
configfile: "config/run_parameter.yaml"
configfile: "config/cluster_config.yaml" 
# configfile: "config.yaml"

# Load CLI argument config (Highest Priority)
load_user_config(config, cmd_arg_name='analysisyaml')

# --------- 2. Processing & Validation --------- #
# Update absolute paths for references
resolve_reference_paths(config,
                        config.get('can_use_genome_version', []),
                        base_path=config.get('reference_path'))
# Validate schema and file existence
validate(config, "schema/config.schema.yaml")
check_reference_paths(config.get("Bowtie2_index", {}))
# Get logger instance for validation
from snakemake_logger_plugin_rich_loguru import get_analysis_logger
logger = get_analysis_logger()
validate_genome_version(config=config, logger=logger)
# Check analysis config species
validate_species(config=config, logger=logger)
# --------- 3. Workspaces & Samples --------- #
# setting analysis workdir
workdir: config["workflow"]
# Load samples and contrasts infor
merge_group,samples = load_samples(config["sample_csv"],required_cols=["sample", "sample_name", "group"],
                                   logger = logger)
groups = parse_groups(samples)
ALL_CONTRASTS, CONTRAST_MAP = load_contrasts(config["paired_csv"], samples)
# --------- 4. Pooled Analysis Config --------- #
run_pooled = config['peak_calling']['use_pooled_peaks'] and merge_group
config['_merge_group'] = merge_group
config['_run_pooled'] = run_pooled
# --------- 5. Rules Import --------- #
include: 'rules/01.common.smk'
include: 'rules/02.file_convert_md5.smk'
include: 'rules/03.short_read_qc.smk'
include: 'rules/04.Contamination_check.smk'
include: 'rules/05.short_read_clean.smk'
include: 'rules/06.mapping.smk'
include: 'rules/07.MACS2.smk'
include: 'rules/07.MACS3.smk'
include: 'rules/08.MergeMACS3.smk'
include: 'rules/09.ATAC_QC.smk'
include: 'rules/10.DEG.smk'
include: 'rules/11.motifs.smk'
include: 'rules/12.deliver.smk'
include: 'rules/13.Report.smk'
# --------- 6. Target Rule --------- #
rule all:
    input:
        DataDeliver(config = config, samples = samples,
                    merge_group = merge_group, groups = groups,
                    run_pooled = run_pooled)
# --------------- END -------------- #
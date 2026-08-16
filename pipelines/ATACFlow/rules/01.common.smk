#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ATACFlow Pipeline - Common Utility Functions Module

This module provides essential utility functions that are used across multiple
rules in the ATAC-seq analysis pipeline. It handles core functionality including:

Key Components:
- Data delivery orchestration (DataDeliver function)
- Report data collection (ReportData function)
- Sample data directory resolution
- Reference index validation
- Genome version compatibility checking
"""

import sys
import os
import platform
from datetime import datetime

# Import the data delivery functions
from utils.datadeliver import (
    qc_clean, mapping, peak_calling, motif_analysis, 
    consensus_peaks, diff_peaks, merge_group_analysis, atac_qc
)

# Import the common utility functions
from utils.common import (
    DataDeliver,
    ReportData,
    get_sample_data_dir,
    get_all_input_dirs,
    judge_bwa_index,
    judge_star_index,
    check_gene_version,
)

# Import the unified logger from the plugin
from snakemake_logger_plugin_rich_loguru import get_analysis_logger

# Get the logger instance
logger = get_analysis_logger()

_qc_warning_logged = False
#!/usr/bin/env python3
"""
Services module for ATACFlow MCP
"""

from services.project_mgr import (
    list_supported_genomes,
    get_config_template,
    create_project_structure,
    generate_config_file,
    create_sample_csv,
    create_contrasts_csv,
    validate_config,
    get_project_structure,
    setup_complete_project,
    run_simple_qc_analysis,
)
from services.snakemake import run_atacflow
from services.system import (
    check_conda_environment,
    check_system_resources,
    list_runs,
    get_run_details,
    get_run_statistics,
    check_project_name_conflict,
    check_snakemake_status,
    get_snakemake_log,
)

__all__ = [
    # project_mgr
    "list_supported_genomes",
    "get_config_template",
    "create_project_structure",
    "generate_config_file",
    "create_sample_csv",
    "create_contrasts_csv",
    "validate_config",
    "get_project_structure",
    "setup_complete_project",
    "run_simple_qc_analysis",
    # snakemake
    "run_atacflow",
    # system
    "check_conda_environment",
    "check_system_resources",
    "list_runs",
    "get_run_details",
    "get_run_statistics",
    "check_project_name_conflict",
    "check_snakemake_status",
    "get_snakemake_log",
]

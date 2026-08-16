#!/usr/bin/env python3
"""
Legacy Dispatcher - unified routing for backward-compatible tool names
Reduces tool count from 40+ to ~20 by consolidating legacy tools
"""

import asyncio
import inspect
from typing import Any, Dict

from core.logger import logger


# Legacy tool name to current handler mapping
LEGACY_MAP = {
    "atacflowRunRnaflow": "run_atacflow_tool",
    "atacflowCheckSnakemakeStatusTool": "check_snakemake_status_tool",
    "atacflowCheckSystemResourcesTool": "check_system_resources_tool",
    "atacflowCheckCondaEnvironmentTool": "check_conda_environment_tool",
    "atacflowListRunsTool": "list_runs_tool",
    "atacflowGetRunDetailsTool": "get_run_details_tool",
    "atacflowGetRunStatisticsTool": "get_run_statistics_tool",
    "atacflowCheckProjectNameConflictTool": "check_project_name_conflict_tool",
    "atacflowGetSnakemakeLogTool": "get_snakemake_log_tool",
    "atacflowListSupportedGenomesTool": "list_supported_genomes_tool",
    "atacflowGetConfigTemplateTool": "get_config_template_tool",
    "atacflowCreateProjectStructureTool": "create_project_structure_tool",
    "atacflowGenerateConfigFileTool": "generate_config_file_tool",
    "atacflowCreateSampleCsvTool": "create_sample_csv_tool",
    "atacflowCreateContrastsCsvTool": "create_contrasts_csv_tool",
    "atacflowValidateConfigTool": "validate_config_tool",
    "atacflowGetProjectStructureTool": "get_project_structure_tool",
    "atacflowSetupCompleteProjectTool": "setup_complete_project_tool",
    "atacflowRunSimpleQcAnalysisTool": "run_simple_qc_analysis_tool",
}


async def legacy_dispatcher(
    tool_name: str, params: Dict[str, Any], handler_globals: Dict[str, Any]
) -> Any:
    """
    Route legacy tool names to current implementations

    Args:
        tool_name: Legacy tool name (e.g., "atacflowRunRnaflow")
        params: Parameters to pass to the handler
        handler_globals: Global namespace to find handlers in

    Returns:
        Handler function result

    Raises:
        ValueError: If tool_name not in LEGACY_MAP
    """
    handler_name = LEGACY_MAP.get(tool_name)

    if not handler_name:
        logger.warning(f"Unknown legacy tool requested: {tool_name}")
        return {"error": f"Unknown legacy tool: {tool_name}"}

    handler = handler_globals.get(handler_name)
    if not handler:
        logger.error(f"Handler not found for {tool_name} -> {handler_name}")
        return {"error": f"Handler not found: {handler_name}"}

    logger.info(f"[Legacy Dispatcher] Routing {tool_name} -> {handler_name}")

    # Handle sync/async automatically
    if inspect.iscoroutinefunction(handler):
        return await handler(**params)
    else:
        return handler(**params)

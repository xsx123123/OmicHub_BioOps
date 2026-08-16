"""omichub-pipelines 内置 MCP 预设。"""

from __future__ import annotations

import uuid
from typing import Any

from omichub.application.schemas.pipeline import PipelinePrepareRequest
from omichub.application.schemas.tool_invocation import ToolInvocationContext
from omichub.application.services.pipeline_controller import PipelineController

OMICHUB_PIPELINES_SERVER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "omichub-pipelines.builtin")
OMICHUB_PIPELINES_SERVER_NAME = "omichub-pipelines"


def _prepare_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "raw_data_path": {"type": "string", "description": "当前用户工作区内的 FASTQ 数据目录"},
            "species": {"type": "string", "description": "物种名称"},
            "genome_version": {"type": "string", "description": "参考基因组版本"},
            "sample_sheet": {"type": "array", "items": {"type": "object"}},
            "comparisons": {"type": "array", "items": {"type": "object"}, "default": []},
            "library_type": {"type": "string", "description": "文库链特异性"},
            "task_name": {
                "type": "string",
                "description": "用户必须提供的分析任务名称",
                "minLength": 1,
                "maxLength": 128,
            },
            "project_name": {"type": "string", "description": "项目名称"},
            "extra_parameters": {"type": "object", "default": {}},
        },
        "required": [
            "raw_data_path",
            "species",
            "genome_version",
            "sample_sheet",
            "library_type",
            "task_name",
            "project_name",
        ],
    }


PIPELINE_TOOLS: list[dict[str, Any]] = [
    {
        "name": f"{pipeline_type}_{action}",
        "description": description,
        "inputSchema": schema,
    }
    for pipeline_type, action, description, schema in [
        ("rna_seq", "prepare", "校验 RNA-seq 参数、数据完整性并预估资源", _prepare_schema()),
        (
            "rna_seq",
            "submit",
            "提交已预检的 RNA-seq 任务",
            {
                "type": "object",
                "properties": {"prepared_params": {"type": "object"}},
                "required": ["prepared_params"],
            },
        ),
        (
            "rna_seq",
            "status",
            "查询 RNA-seq 任务状态",
            {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
        (
            "rna_seq",
            "results",
            "获取 RNA-seq 任务结果摘要和产物",
            {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "result_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["summary", "artifacts"],
                    },
                },
                "required": ["task_id"],
            },
        ),
        ("atac_seq", "prepare", "校验 ATAC-seq 参数、数据完整性并预估资源", _prepare_schema()),
        (
            "atac_seq",
            "submit",
            "提交已预检的 ATAC-seq 任务",
            {
                "type": "object",
                "properties": {"prepared_params": {"type": "object"}},
                "required": ["prepared_params"],
            },
        ),
        (
            "atac_seq",
            "status",
            "查询 ATAC-seq 任务状态",
            {
                "type": "object",
                "properties": {"task_id": {"type": "string"}},
                "required": ["task_id"],
            },
        ),
        (
            "atac_seq",
            "results",
            "获取 ATAC-seq 任务结果摘要和产物",
            {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "result_types": {
                        "type": "array",
                        "items": {"type": "string"},
                        "default": ["summary", "artifacts"],
                    },
                },
                "required": ["task_id"],
            },
        ),
    ]
]

PIPELINE_TOOLS.extend(
    [
        {
            "name": "list_available_pipelines",
            "description": "列出当前平台可通过 MCP 调用的完整分析流程",
            "inputSchema": {"type": "object", "properties": {}},
        },
        {
            "name": "check_workspace_data",
            "description": "检查当前用户工作区数据是否符合分析要求",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "analysis_type": {"type": "string", "enum": ["rna_seq", "atac_seq"]},
                    "data_path": {"type": "string"},
                },
                "required": ["analysis_type", "data_path"],
            },
        },
    ]
)


async def _pipeline_handler(
    arguments: dict[str, Any],
    tool_name: str = "",
    context: ToolInvocationContext | None = None,
    **_kwargs: Any,
) -> dict[str, Any]:
    if context is None:
        raise RuntimeError("omichub-pipelines 仅允许在带用户上下文的调用中执行")
    controller = PipelineController(context)

    if tool_name == "list_available_pipelines":
        data = await controller.list_available()
        return {"llm_payload": {"pipelines": data}, "ui_payload": {"pipelines": data}}
    if tool_name == "check_workspace_data":
        data = await controller.check_workspace_data(
            str(arguments.get("analysis_type", "")), str(arguments.get("data_path", ""))
        )
        return {"llm_payload": data, "ui_payload": {"workspace_report": data}}

    pipeline_type, action = tool_name.rsplit("_", 1)
    if action == "prepare":
        data = await controller.prepare(pipeline_type, PipelinePrepareRequest(**arguments))
        return {
            "llm_payload": data,
            "ui_payload": {
                "type": "pipeline_prepare",
                "pipeline_type": pipeline_type,
                "valid": data.get("valid", False),
                "errors": data.get("errors", []),
                "warnings": data.get("warnings", []),
                "resource_hint": data.get("resource_hint", {}),
            },
        }
    if action == "submit":
        data = await controller.submit(pipeline_type, arguments.get("prepared_params") or {})
    elif action == "status":
        data = await controller.status(pipeline_type, str(arguments.get("task_id", "")))
    elif action == "results":
        data = await controller.results(
            pipeline_type,
            str(arguments.get("task_id", "")),
            list(arguments.get("result_types") or ["summary", "artifacts"]),
        )
    else:
        raise RuntimeError(f"不支持的流水线动作: {action}")
    return {"llm_payload": data, "ui_payload": data}


PIPELINE_HANDLERS = {tool["name"]: _pipeline_handler for tool in PIPELINE_TOOLS}


def build_pipeline_preset() -> dict[str, Any]:
    return {
        "name": OMICHUB_PIPELINES_SERVER_NAME,
        "description": "OmicHub 完整分析流程 MCP - RNA-seq、ATAC-seq 预检、提交、状态和结果",
        "transport": "builtin",
        "tools": PIPELINE_TOOLS,
        "handlers": PIPELINE_HANDLERS,
    }

"""MCP 分析流水线请求模型。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from cygnusx.application.schemas.base import CygnusXBaseSchema

PipelineType = Literal["rna_seq", "atac_seq"]


class PipelinePrepareRequest(CygnusXBaseSchema):
    raw_data_path: str
    species: str
    genome_version: str
    sample_sheet: list[dict[str, Any]]
    comparisons: list[dict[str, Any]] = Field(default_factory=list)
    library_type: str
    task_name: str = Field(min_length=1, max_length=128, description="用户提供的分析任务名称")
    project_name: str
    extra_parameters: dict[str, Any] = Field(default_factory=dict)


class PipelineSubmitRequest(CygnusXBaseSchema):
    prepared_params: dict[str, Any]
    # 外部 MCP 通道的人类确认凭证（CLI 侧 user_confirmed 确认后由 mcp-server 置 True）。
    # 为 True 时平台允许一步消费 PENDING 确认记录；否则要求记录已被人类点卡置 APPROVED。
    user_confirmed: bool = False


class PipelineResultsRequest(CygnusXBaseSchema):
    result_types: list[str] = Field(default_factory=lambda: ["summary", "artifacts"])


class WorkspaceCheckRequest(CygnusXBaseSchema):
    analysis_type: PipelineType
    data_path: str

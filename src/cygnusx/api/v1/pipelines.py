"""用户级 MCP 分析流水线桥接 API。"""

from __future__ import annotations

from fastapi import APIRouter

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.application.schemas.pipeline import (
    PipelinePrepareRequest,
    PipelineResultsRequest,
    PipelineSubmitRequest,
    PipelineType,
    WorkspaceCheckRequest,
)
from cygnusx.application.schemas.tool_invocation import ToolInvocationContext
from cygnusx.application.services.pipeline_controller import PipelineController

router = APIRouter()


def _controller(user_id: str, db: DbSession, *, human_confirmed: bool = False) -> PipelineController:
    return PipelineController(
        ToolInvocationContext(
            user_id=user_id,
            session_id="pipeline-api",
            db=db,
            extra={"human_confirmed": True} if human_confirmed else {},
        )
    )


@router.get("", summary="列出可用 MCP 分析流程")
async def list_available_pipelines(current_user_id: CurrentUserId, db: DbSession):
    return await _controller(current_user_id, db).list_available()


@router.post("/check-workspace", summary="检查工作区分析数据")
async def check_workspace_data(
    request: WorkspaceCheckRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
):
    return await _controller(current_user_id, db).check_workspace_data(
        request.analysis_type, request.data_path
    )


@router.post("/{pipeline_type}/prepare", summary="预检分析流程参数")
async def prepare_pipeline(
    pipeline_type: PipelineType,
    request: PipelinePrepareRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
):
    return await _controller(current_user_id, db).prepare(pipeline_type, request)


@router.post("/{pipeline_type}/submit", summary="提交已预检分析流程")
async def submit_pipeline(
    pipeline_type: PipelineType,
    request: PipelineSubmitRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
):
    return await _controller(
        current_user_id, db, human_confirmed=request.user_confirmed
    ).submit(pipeline_type, request.prepared_params)


@router.get("/{pipeline_type}/{task_id}/status", summary="查询分析流程任务状态")
async def pipeline_status(
    pipeline_type: PipelineType,
    task_id: str,
    current_user_id: CurrentUserId,
    db: DbSession,
):
    return await _controller(current_user_id, db).status(pipeline_type, task_id)


@router.post("/{pipeline_type}/{task_id}/results", summary="读取分析流程结果")
async def pipeline_results(
    pipeline_type: PipelineType,
    task_id: str,
    request: PipelineResultsRequest,
    current_user_id: CurrentUserId,
    db: DbSession,
):
    return await _controller(current_user_id, db).results(
        pipeline_type, task_id, request.result_types
    )

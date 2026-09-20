"""Authenticated metadata API for the opt-in multi-agent system."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import FileResponse, StreamingResponse

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.application.schemas.mas import (
    MASApprovalResolveRequest,
    MASApprovalResponse,
    MASArtifactRegisterRequest,
    MASArtifactResponse,
    MASRunCreateRequest,
    MASRunProgressResponse,
    MASRunResponse,
)
from cygnusx.application.services.mas_service import MASService

router = APIRouter()


def get_mas_service(db: DbSession) -> MASService:
    return MASService(db)


MASServiceDep = Annotated[MASService, Depends(get_mas_service)]


@router.post("/runs", response_model=MASRunResponse, status_code=status.HTTP_201_CREATED)
async def create_run(
    request: MASRunCreateRequest, current_user_id: CurrentUserId, service: MASServiceDep
) -> MASRunResponse:
    return await service.create_run(current_user_id, request)


@router.get("/runs", response_model=list[MASRunResponse])
async def list_runs(current_user_id: CurrentUserId, service: MASServiceDep) -> list[MASRunResponse]:
    return await service.list_runs(current_user_id)


@router.get("/runs/{run_id}", response_model=MASRunResponse)
async def get_run(
    run_id: UUID, current_user_id: CurrentUserId, service: MASServiceDep
) -> MASRunResponse:
    return await service.get_run(current_user_id, run_id)


@router.delete("/runs/{run_id}", response_model=MASRunResponse)
async def cancel_run(
    run_id: UUID, current_user_id: CurrentUserId, service: MASServiceDep
) -> MASRunResponse:
    return await service.cancel_run(current_user_id, run_id)


@router.post("/runs/{run_id}/approve", response_model=MASRunResponse)
async def approve_run(
    run_id: UUID, current_user_id: CurrentUserId, service: MASServiceDep
) -> MASRunResponse:
    return await service.approve_run(current_user_id, run_id)


@router.post("/runs/{run_id}/nodes/{node_key}/retry", response_model=MASRunResponse)
async def retry_failed_node(
    run_id: UUID,
    node_key: str,
    current_user_id: CurrentUserId,
    service: MASServiceDep,
) -> MASRunResponse:
    return await service.retry_failed_node(current_user_id, run_id, node_key)


@router.get("/runs/{run_id}/progress", response_model=MASRunProgressResponse)
async def get_run_progress(
    run_id: UUID, current_user_id: CurrentUserId, service: MASServiceDep
) -> MASRunProgressResponse:
    return await service.get_progress(current_user_id, run_id)


@router.get("/runs/{run_id}/events", response_class=StreamingResponse)
async def stream_run_progress(
    run_id: UUID, current_user_id: CurrentUserId, service: MASServiceDep
) -> StreamingResponse:
    return StreamingResponse(
        service.stream_progress(current_user_id, run_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/runs/{run_id}/approvals", response_model=list[MASApprovalResponse])
async def list_approvals(
    run_id: UUID, current_user_id: CurrentUserId, service: MASServiceDep
) -> list[MASApprovalResponse]:
    return await service.list_approvals(current_user_id, run_id)


@router.post("/runs/{run_id}/approvals/{approval_id}", response_model=MASRunResponse)
async def resolve_approval(
    run_id: UUID,
    approval_id: UUID,
    request: MASApprovalResolveRequest,
    current_user_id: CurrentUserId,
    service: MASServiceDep,
) -> MASRunResponse:
    return await service.resolve_approval(current_user_id, run_id, approval_id, request)


@router.post(
    "/runs/{run_id}/artifacts",
    response_model=MASArtifactResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_artifact(
    run_id: UUID,
    request: MASArtifactRegisterRequest,
    current_user_id: CurrentUserId,
    service: MASServiceDep,
) -> MASArtifactResponse:
    return await service.register_artifact(current_user_id, run_id, request)


@router.get("/runs/{run_id}/artifacts", response_model=list[MASArtifactResponse])
async def list_artifacts(
    run_id: UUID, current_user_id: CurrentUserId, service: MASServiceDep
) -> list[MASArtifactResponse]:
    return await service.list_artifacts(current_user_id, run_id)


@router.get("/runs/{run_id}/artifacts/{artifact_id}/download", summary="下载 MAS 产物")
async def download_artifact(
    run_id: UUID,
    artifact_id: UUID,
    current_user_id: CurrentUserId,
    service: MASServiceDep,
) -> FileResponse:
    artifact, path = await service.resolve_artifact_download(current_user_id, run_id, artifact_id)
    return FileResponse(path, media_type=artifact.media_type, filename=path.name)

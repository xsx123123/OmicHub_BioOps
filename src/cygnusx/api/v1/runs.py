"""Unified Run read/confirm endpoints (Snakemake MVP)."""

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from cygnusx.api.deps import CurrentUserId, DbSession
from cygnusx.application.schemas.run_plan import SnakemakePlanSubmit, SnakemakePlanView
from cygnusx.application.services.run_plan_service import RunPlanService

router = APIRouter()


def get_service(db: DbSession) -> RunPlanService:
    return RunPlanService(db)


ServiceDep = Annotated[RunPlanService, Depends(get_service)]


class RunConfirmRequest(BaseModel):
    user_confirmed: bool


@router.post("/snakemake/plan", response_model=SnakemakePlanView, status_code=201)
async def submit_snakemake_plan(
    req: SnakemakePlanSubmit, current_user_id: CurrentUserId, service: ServiceDep
) -> SnakemakePlanView:
    return await service.submit(UUID(current_user_id), req)


@router.get("", response_model=list[SnakemakePlanView])
async def list_runs(
    current_user_id: CurrentUserId,
    service: ServiceDep,
    project_slug: str | None = Query(default=None),
    status: str | None = Query(default=None),
) -> list[SnakemakePlanView]:
    return await service.list_runs(UUID(current_user_id), project_slug=project_slug, status=status)


@router.post("/{run_id}/confirm", response_model=SnakemakePlanView)
async def confirm_run(
    run_id: UUID,
    req: RunConfirmRequest,
    current_user_id: CurrentUserId,
    service: ServiceDep,
) -> SnakemakePlanView:
    return await service.confirm(UUID(current_user_id), run_id, req.user_confirmed)


@router.get("/{run_id}/events")
async def get_run_events(
    run_id: UUID,
    current_user_id: CurrentUserId,
    service: ServiceDep,
    limit: int = Query(default=200, ge=1, le=500),
) -> dict:
    return {"run_id": str(run_id), "events": await service.events(UUID(current_user_id), run_id, limit)}


@router.get("/{run_id}/artifacts")
async def get_run_artifacts(run_id: UUID, current_user_id: CurrentUserId, service: ServiceDep) -> dict:
    return {"run_id": str(run_id), "artifacts": await service.artifacts(UUID(current_user_id), run_id)}


@router.get("/{run_id}", response_model=SnakemakePlanView)
async def get_run(run_id: UUID, current_user_id: CurrentUserId, service: ServiceDep):
    return await service.get(UUID(current_user_id), run_id)

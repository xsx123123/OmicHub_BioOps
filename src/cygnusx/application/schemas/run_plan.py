"""Bounded platform Run plan contracts."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import Field, ConfigDict

from cygnusx.application.schemas.base import CygnusXBaseSchema


class SnakemakePlanSubmit(CygnusXBaseSchema):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["cygnusx.snakemake_plan.v1"]
    project_slug: str = Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    flow_id: str = Field(min_length=1, max_length=100)
    release_id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=128)
    parameters: dict[str, Any] = Field(default_factory=dict)
    sample_sheet: list[dict[str, Any]] = Field(default_factory=list)
    comparisons: list[dict[str, Any]] = Field(default_factory=list)
    request_key: str = Field(min_length=1, max_length=128)


class SnakemakePlanView(CygnusXBaseSchema):
    run_id: UUID
    project_slug: str
    flow_id: str
    release_id: str
    name: str
    status: str
    plan_digest: str
    task_id: UUID | None
    created_at: datetime

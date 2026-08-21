from datetime import datetime
from typing import Literal

from pydantic import Field

from omichub.application.schemas.base import OmicsHubBaseSchema


class GseaTermDTO(OmicsHubBaseSchema):
    id: str
    description: str
    nes: float
    p_adjust: float
    qvalue: float | None = None


class GseaTaskDTO(OmicsHubBaseSchema):
    task_id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: int = 0
    message: str = ""
    error_message: str | None = None
    project_name: str = ""
    species_id: str = ""
    gene_set: str = ""
    gene_count: int = 0
    top_terms: list[GseaTermDTO] = Field(default_factory=list)
    running_score: list[dict[str, float | int]] = Field(default_factory=list)
    result_download_url: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None

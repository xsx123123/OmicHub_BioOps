from datetime import datetime
from typing import Literal

from pydantic import Field

from omichub.application.schemas.base import OmicsHubBaseSchema


class SyntenyBlockDTO(OmicsHubBaseSchema):
    block_id: str
    chromosome_a: str
    chromosome_b: str
    gene_pairs: int


class SyntenyPointDTO(OmicsHubBaseSchema):
    query_gene: str
    subject_gene: str
    chromosome_a: str
    chromosome_b: str
    x: int
    y: int


class SyntenyTaskDTO(OmicsHubBaseSchema):
    task_id: str
    status: Literal["queued", "running", "completed", "failed"]
    progress: int = 0
    message: str = ""
    error_message: str | None = None
    block_count: int = 0
    max_block_size: int = 0
    chromosome_pairs: list[str] = Field(default_factory=list)
    blocks: list[SyntenyBlockDTO] = Field(default_factory=list)
    points: list[SyntenyPointDTO] = Field(default_factory=list)
    result_download_url: str | None = None
    created_at: datetime | None = None
    finished_at: datetime | None = None

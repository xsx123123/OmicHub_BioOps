"""FASTQ 极速质控 API 与 Worker 共享的数据契约。"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QCTaskStatus(StrEnum):
    PENDING = "PENDING"
    QUEUED = "QUEUED"
    RUNNING_FASTP = "RUNNING_FASTP"
    RUNNING_MULTIQC = "RUNNING_MULTIQC"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"
    CANCELED = "CANCELED"


class FastqSampleInput(BaseModel):
    """由已上传文件 ID 组成的单个 SE/PE 样本输入。"""

    model_config = ConfigDict(extra="forbid")

    sample: str = Field(min_length=1, max_length=128)
    r1_file_id: UUID
    r2_file_id: UUID | None = None

    @field_validator("sample")
    @classmethod
    def validate_sample(cls, value: str) -> str:
        if not all(character.isalnum() or character in "._-" for character in value):
            raise ValueError("sample may only contain letters, numbers, '.', '_' and '-'")
        return value


class CreateQCTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=255, description="用户提供的项目名称")
    samples: list[FastqSampleInput] = Field(min_length=1, max_length=500)
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("samples")
    @classmethod
    def require_unique_samples(cls, values: list[FastqSampleInput]) -> list[FastqSampleInput]:
        names = [sample.sample for sample in values]
        if len(names) != len(set(names)):
            raise ValueError("sample names must be unique")
        return values


class QCTaskProgress(BaseModel):
    model_config = ConfigDict(extra="forbid")

    done: int = Field(default=0, ge=0)
    total: int = Field(default=0, ge=0)
    current_sample: str | None = None


class QCTaskResponse(BaseModel):
    id: UUID
    name: str
    status: QCTaskStatus
    progress: QCTaskProgress
    params_snapshot: dict[str, Any] = Field(default_factory=dict)
    summary: dict[str, Any] = Field(default_factory=dict)
    failed_samples: list[dict[str, str]] = Field(default_factory=list)
    celery_task_id: str | None = None
    error_message: str | None = None

"""下载进度 DTO — EBIDownload HTTP Progress API 解密后的结构"""

from omichub.application.schemas.base import OmicsHubBaseSchema


class StageProgressDTO(OmicsHubBaseSchema):
    """单阶段进度"""

    bytes_done: int
    bytes_total: int
    weight: float
    percent: float


class RunProgressDTO(OmicsHubBaseSchema):
    """单个 run（SRR）的三阶段进度"""

    run_id: str
    stage: str  # pending | downloading | extracting | compressing | completed | failed
    overall_percent: float
    download: StageProgressDTO
    extraction: StageProgressDTO
    compression: StageProgressDTO


class DownloadProgressResponse(OmicsHubBaseSchema):
    """下载进度 API 响应"""

    task_id: str
    runs: dict[str, RunProgressDTO]
    overall_percent: float
    source: str  # "progress_api" | "unavailable"

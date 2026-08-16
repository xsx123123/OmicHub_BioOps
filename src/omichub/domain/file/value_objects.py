"""文件域值对象"""

from enum import Enum


class FileType(str, Enum):
    """文件类型"""

    FASTQ = "fastq"
    BAM = "bam"
    VCF = "vcf"
    COUNT_MATRIX = "count_matrix"
    H5AD = "h5ad"
    RDS = "rds"
    META = "meta"
    REPORT = "report"
    IMAGE = "image"
    OTHER = "other"


class FileSource(str, Enum):
    """文件来源 — 标识产生该文件的模块"""

    UPLOAD = "upload"
    PIPELINE = "pipeline"
    BLAST = "blast"
    ENRICHMENT = "enrichment"
    FASTQ_QC = "fastq_qc"
    PHYLOGENETIC = "phylogenetic"
    DOWNLOAD = "download"
    AI_CHAT = "ai_chat"
    SANDBOX = "sandbox"
    REPORT = "report"
    STUDIO = "studio"
    CHAT_SANDBOX = "chat_sandbox"
    AGENTTEAMS = "agentteams"


class OwnerScope(str, Enum):
    """文件权属范围"""

    PERSONAL = "personal"
    TEAM = "team"


class LifecycleStatus(str, Enum):
    """文件生命周期状态"""

    ACTIVE = "active"
    ARCHIVED = "archived"
    PENDING_DELETE = "pending_delete"


class UploadStatus(str, Enum):
    """上传状态"""

    PENDING = "pending"
    UPLOADING = "uploading"
    COMPLETED = "completed"
    FAILED = "failed"

from typing import List, Dict, Optional, Union, Any
from pydantic import BaseModel, Field

class ProjectInfo(BaseModel):
    id: str
    comparison: str
    organism: str
    tissue_type: Optional[str] = None
    goal: Optional[str] = None
    language: str = "Chinese"
    extra_params: Dict[str, Any] = Field(default_factory=dict)

class QCSummary(BaseModel):
    total_reads: str
    mapping_rate: str
    conclusion: str

class DEGStats(BaseModel):
    total_degs: int
    up_regulated: int
    down_regulated: int
    threshold: str

class Gene(BaseModel):
    symbol: str
    log2FC: float
    padj: Union[str, float]
    function: Optional[str] = "Unknown function"

class Enrichment(BaseModel):
    top_pathways: List[str]

class RNASeqResult(BaseModel):
    """
    RNA-Seq 分析结果的严格数据模型。
    用于验证输入 JSON 的完整性。
    """
    project_info: ProjectInfo
    qc_summary: QCSummary
    deg_stats: DEGStats
    top_genes: List[Gene]
    enrichment: Enrichment

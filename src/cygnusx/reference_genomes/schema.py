"""参考基因组模块 Schema —— 响应 DTO（alias 输出 camelCase，与前端 TypeScript 类型对齐）。

约定（对齐平台现有 API，如 tools/jbrowse）：
- 响应为裸模型，不包 {"data": ...} 信封；前端 axios 层自行取 response.data；
- 字段 snake_case 定义，经 alias_generator=to_camel 统一输出 camelCase；
- service 层返回 dict / DTO 均可，response_model 负责校验与别名序列化。
"""

from __future__ import annotations

from pydantic import ConfigDict, Field
from pydantic.alias_generators import to_camel

from cygnusx.application.schemas.base import CygnusXBaseSchema


class RefGenBase(CygnusXBaseSchema):
    """模块内 DTO 基类：camelCase 别名输出。"""

    model_config = ConfigDict(
        from_attributes=True,
        populate_by_name=True,
        str_strip_whitespace=True,
        alias_generator=to_camel,
    )


# ============================================================
# 物种 / 版本（替换前端卡片数据源）
# ============================================================


class DataFileDTO(RefGenBase):
    """数据文件审计项（对齐前端 DatabaseDataFile）。"""

    type: str  # fasta | gff | go | kegg | cds | protein | go_obo ...
    label: str = ""
    path: str = ""
    index_path: str | None = None
    db_path: str | None = None
    format: str = ""
    size: str = "-"
    build_required: bool = False
    build_tool: str | None = None
    build_status: str = "missing"  # ready | building | missing | error


class VersionStatsDTO(RefGenBase):
    """版本统计（对齐前端 GenomeVersionStats）。"""

    chromosomes: int = 0
    total_genes: int = 0
    protein_coding: int = 0
    genome_size: str = ""
    n50: str = ""


class GenomeVersionDTO(RefGenBase):
    """基因组版本卡片（对齐前端 GenomeVersion）。"""

    version_id: str
    version_name: str = ""
    assembly_name: str = ""
    is_default: bool = False
    status: str = "active"
    release_date: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    stats: VersionStatsDTO = Field(default_factory=VersionStatsDTO)
    data_files: dict[str, DataFileDTO] = Field(default_factory=dict)


class VersionMappingDTO(RefGenBase):
    """跨版本映射声明（对齐前端 VersionMapping）。"""

    source: str
    target: str
    mapping_tool: str = ""
    mapping_file: str = ""
    build_status: str = "missing"
    mapped_genes: int = 0
    average_quality: float = 0.0


class SpeciesDTO(RefGenBase):
    """物种卡片（对齐前端 SpeciesDatabase；scientific_name 对应前端 scientificName）。"""

    id: str
    scientific_name: str = ""
    common_name: str = ""
    taxonomy_id: str = ""
    description: str = ""
    icon: str = ""
    category: str = "plant"
    gradient: str = ""
    genome_versions: list[GenomeVersionDTO] = Field(default_factory=list)
    version_mappings: list[VersionMappingDTO] = Field(default_factory=list)


class SpeciesListResponse(RefGenBase):
    """GET /species。"""

    species: list[SpeciesDTO] = Field(default_factory=list)


# ============================================================
# 版本详情
# ============================================================


class ChromosomeDTO(RefGenBase):
    name: str
    length: int
    color: str = "#165DFF"


class GeneTypeStatDTO(RefGenBase):
    name: str
    value: int
    color: str = "#165DFF"


class VersionDetailDTO(RefGenBase):
    """GET /versions/{version_id}：版本详情（染色体数组 + 基因类型统计 + 文件审计）。"""

    species_id: str = ""
    version_id: str
    version_name: str = ""
    assembly_name: str = ""
    is_default: bool = False
    status: str = "active"
    release_date: str = ""
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    stats: VersionStatsDTO = Field(default_factory=VersionStatsDTO)
    chromosomes: list[ChromosomeDTO] = Field(default_factory=list)
    gene_type_stats: list[GeneTypeStatDTO] = Field(default_factory=list)
    data_files: dict[str, DataFileDTO] = Field(default_factory=dict)
    build_status: str = "missing"  # ready | building | missing | error
    indexed: bool = False
    built_at: str | None = None
    gene_count: int = 0
    transcript_count: int = 0


# ============================================================
# 基因
# ============================================================


class GeneDTO(RefGenBase):
    """基因搜索列表行（含 hasGo/hasKegg/hasSequence 布尔位供前端标灰）。"""

    gene_id: str
    gene_name: str = ""  # symbol（如 NAC001），无 symbol 时回退 gene_id
    annotation: str = ""
    gene_type: str = "protein_coding"
    chromosome: str = ""
    start: int = 0
    end: int = 0
    strand: str = "+"
    length: int = 0
    exons: int = 0
    has_go: bool = False
    has_kegg: bool = False
    has_sequence: bool = False


class GeneListResponse(RefGenBase):
    """GET /versions/{id}/genes。"""

    total: int = 0
    page: int = 1
    page_size: int = 20
    items: list[GeneDTO] = Field(default_factory=list)


class ExonDTO(RefGenBase):
    start: int
    end: int
    rank: int = 0


class TranscriptDTO(RefGenBase):
    transcript_id: str
    gene_id: str = ""
    chromosome: str = ""
    start: int = 0
    end: int = 0
    strand: str = "+"
    biotype: str = "protein_coding"
    length: int = 0  # 外显子总长（剪接后转录本长度）
    exon_count: int = 0
    exons: list[ExonDTO] = Field(default_factory=list)
    # 结构特征区间（GFF3 CDS/UTR）：{"cds": [[s,e],...], "five_prime_utr": [...], "three_prime_utr": [...]}
    features: dict[str, list[list[int]]] = Field(default_factory=dict)
    cds_id: str | None = None
    pep_id: str | None = None
    canonical: bool = False


class GoSlimDTO(RefGenBase):
    """基因 → GO Slim 功能分类行。"""

    go_id: str
    name: str = ""
    namespace: str = "BP"
    slim_category: str = ""
    evidence: str = ""


class GoAnnotationDTO(RefGenBase):
    """基因 → GO 注释行（namespace 输出 BP/MF/CC）。"""

    go_id: str
    term: str = ""
    namespace: str = "BP"
    evidence_code: str = ""
    source: str = ""
    definition: str = ""


class KeggKoDTO(RefGenBase):
    ko_id: str
    name: str = ""
    definition: str = ""
    gene_count: int = 0


class KeggPathwayDTO(RefGenBase):
    pathway_id: str
    name: str = ""
    gene_count: int = 0


class GeneKeggDTO(RefGenBase):
    """基因详情 KEGG 聚合段。"""

    kos: list[KeggKoDTO] = Field(default_factory=list)
    pathways: list[KeggPathwayDTO] = Field(default_factory=list)


class SequenceAvailabilityDTO(RefGenBase):
    genomic: bool = False
    cds: bool = False
    protein: bool = False
    promoter: bool = False


class GeneDetailDTO(RefGenBase):
    """GET /versions/{id}/genes/{gene_id}：基因抽屉五 Tab 聚合数据源。"""

    gene: GeneDTO
    transcripts: list[TranscriptDTO] = Field(default_factory=list)
    go: list[GoAnnotationDTO] = Field(default_factory=list)
    goslim: list[GoSlimDTO] = Field(default_factory=list)
    kegg: GeneKeggDTO = Field(default_factory=GeneKeggDTO)
    sequence_available: SequenceAvailabilityDTO = Field(default_factory=SequenceAvailabilityDTO)


# ============================================================
# 序列
# ============================================================


class SequenceDTO(RefGenBase):
    """format=json 的序列响应。"""

    header: str = ""
    sequence: str = ""
    length: int = 0
    seq_type: str = "genomic"  # genomic | cds | protein
    transcript_id: str | None = None
    chromosome: str | None = None
    start: int | None = None
    end: int | None = None
    strand: str | None = None


# ============================================================
# GO / KEGG 检索
# ============================================================


class GoTermDTO(RefGenBase):
    go_id: str
    name: str = ""
    aspect: str = ""  # F | P | C
    definition: str = ""
    gene_count: int = 0


class GoTermListResponse(RefGenBase):
    total: int = 0
    page: int = 1
    page_size: int = 20
    items: list[GoTermDTO] = Field(default_factory=list)


class KeggPathwayListResponse(RefGenBase):
    total: int = 0
    page: int = 1
    page_size: int = 20
    items: list[KeggPathwayDTO] = Field(default_factory=list)


class GoGeneListResponse(RefGenBase):
    """GET /versions/{id}/go/{go_id}/genes（反查）。"""

    go_id: str
    name: str = ""
    total: int = 0
    page: int = 1
    page_size: int = 20
    items: list[GeneDTO] = Field(default_factory=list)


class PathwayGeneListResponse(RefGenBase):
    pathway_id: str
    name: str = ""
    total: int = 0
    page: int = 1
    page_size: int = 20
    items: list[GeneDTO] = Field(default_factory=list)


# ============================================================
# 统一搜索
# ============================================================


class GeneSearchHitDTO(RefGenBase):
    gene_id: str
    gene_name: str = ""
    annotation: str = ""
    chromosome: str = ""
    version_id: str = ""
    species_id: str = ""


class GoTermSearchHitDTO(RefGenBase):
    go_id: str
    name: str = ""
    aspect: str = ""
    gene_count: int = 0
    version_id: str = ""
    species_id: str = ""


class KeggSearchHitDTO(RefGenBase):
    id: str
    kind: str = "ko"  # ko | pathway
    name: str = ""
    gene_count: int = 0
    version_id: str = ""
    species_id: str = ""


class SpeciesSearchHitDTO(RefGenBase):
    species_id: str
    common_name: str = ""
    match: str = ""  # 命中字段：common_name | latin_name | taxonomy_id


class SearchResponse(RefGenBase):
    """GET /search 与 GET /versions/{id}/search 的聚合结果。"""

    genes: list[GeneSearchHitDTO] = Field(default_factory=list)
    go_terms: list[GoTermSearchHitDTO] = Field(default_factory=list)
    kegg: list[KeggSearchHitDTO] = Field(default_factory=list)
    species: list[SpeciesSearchHitDTO] = Field(default_factory=list)


# ============================================================
# 批量注释
# ============================================================


class BatchGeneRequest(RefGenBase):
    gene_ids: list[str] = Field(default_factory=list, max_length=500)


class BatchGeneAnnotationDTO(RefGenBase):
    gene_id: str
    found: bool = False
    gene_name: str = ""
    annotation: str = ""
    go_count: int = 0
    kegg_count: int = 0


class BatchAnnotationResponse(RefGenBase):
    total: int = 0
    found: int = 0
    items: list[BatchGeneAnnotationDTO] = Field(default_factory=list)


# ============================================================
# 版本映射 / 管理
# ============================================================


class MapIdsRequest(RefGenBase):
    target_version_id: str
    ids: list[str] = Field(default_factory=list)


class MapIdsResultItem(RefGenBase):
    input: str
    output: str | None = None
    status: str = "fail"  # success | fail


class MapIdsResponse(RefGenBase):
    results: list[MapIdsResultItem] = Field(default_factory=list)
    success_count: int = 0
    total_count: int = 0


class ReloadResponse(RefGenBase):
    ok: bool = True
    species_count: int = 0
    version_count: int = 0

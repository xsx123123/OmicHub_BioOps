"""参考基因组模块 Service —— SQLite 只读查询 + 文件审计。

SQLite 连接策略：按请求开关（不跨请求缓存），以 ``?mode=ro`` URI 打开确保只读；
数据库不存在或打开失败时该版本视为「未构建」，查询接口抛 NotFoundError。
所有函数为同步，FastAPI 自动丢线程池执行（sqlite 阻塞 IO 无碍）。
"""

from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any

from omichub.core.exceptions import BusinessError, NotFoundError, ValidationError
from omichub.reference_genomes.config import (
    ConfigManager,
    VersionConfig,
    config_manager,
    gene_index_path,
    resolve_file_path,
)
from omichub.reference_genomes.schema import (
    BatchAnnotationResponse,
    BatchGeneAnnotationDTO,
    ChromosomeDTO,
    DataFileDTO,
    GeneDTO,
    GeneDetailDTO,
    GeneKeggDTO,
    GeneListResponse,
    GeneSearchHitDTO,
    GeneTypeStatDTO,
    GoAnnotationDTO,
    GoGeneListResponse,
    GoTermDTO,
    GoTermListResponse,
    GoTermSearchHitDTO,
    KeggKoDTO,
    KeggPathwayDTO,
    KeggPathwayListResponse,
    KeggSearchHitDTO,
    MapIdsResponse,
    MapIdsResultItem,
    PathwayGeneListResponse,
    SearchResponse,
    SequenceAvailabilityDTO,
    SequenceDTO,
    SpeciesDTO,
    SpeciesListResponse,
    SpeciesSearchHitDTO,
    TranscriptDTO,
    ExonDTO,
    VersionDetailDTO,
    VersionMappingDTO,
    VersionStatsDTO,
    GenomeVersionDTO,
    ReloadResponse,
)
from omichub.reference_genomes.sequence import (
    fetch_kv,
    fetch_region,
    open_index,
    parse_fai,
)

# 调色板（按序分配给染色体 / 基因类型）
_PALETTE = [
    "#165DFF", "#0FC6C2", "#722ED1", "#F77234", "#F7BA1E",
    "#14C9C9", "#86909C", "#00B42A", "#4E5969", "#F53F3F",
]


def _human_size(nbytes: int) -> str:
    """文件大小人类可读格式化（b/Kb/Mb/Gb/Tb）。"""
    if nbytes < 1024:
        return f"{nbytes} b"
    for unit in ("Kb", "Mb", "Gb", "Tb"):
        nbytes_f = nbytes / 1024.0
        if nbytes_f < 1024 or unit == "Tb":
            return f"{nbytes_f:.1f} {unit}"
        nbytes = int(nbytes_f)
    return f"{nbytes} b"


def _open_db(version: VersionConfig) -> sqlite3.Connection:
    """只读打开 gene_index.db；不存在 / 打开失败抛 NotFoundError。"""
    db_path = gene_index_path(version)
    if db_path is None or not db_path.exists():
        raise NotFoundError(f"基因索引未构建：版本 {version.id} 的 gene_index.db 不存在")
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.Error as e:
        raise NotFoundError(f"基因索引打开失败：版本 {version.id}，{e}") from e


def _get_meta(conn: sqlite3.Connection, key: str, default: str = "") -> str:
    """读 meta 表单值；键不存在返回 default。"""
    try:
        row = conn.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default
    except sqlite3.Error:
        return default


def _escape_like(s: str) -> str:
    """LIKE 模式转义：% _ \\ 前加反斜杠。"""
    s = s.replace("\\", "\\\\")
    s = s.replace("%", "\\%")
    s = s.replace("_", "\\_")
    return s


def _fts_tokens(q: str) -> str:
    """构造 FTS5 MATCH 表达式：拆空白为 token，各加 * 通配，AND 连接；双引号替换掉。"""
    tokens = q.split()
    parts = []
    for t in tokens:
        t = t.replace('"', "").strip()
        if t:
            parts.append(f'"{t}"*')
    return " AND ".join(parts) if parts else ""


# ========================= 文件审计 =========================


def _audit_data_files(version: VersionConfig) -> dict[str, DataFileDTO]:
    """审计 version.files 每项 → DataFileDTO。

    特殊处理：fasta（.gz）检查解压产物 .fas 与 .fas.fai；
    cds/protein 的 db_path 指向 gene_index.db。
    """
    result: dict[str, DataFileDTO] = {}
    for key, entry in version.files.items():
        resolved = resolve_file_path(version, key)
        display_path = str(resolved) if resolved else entry.path
        index_path: str | None = None
        db_path: str | None = None
        build_status = "missing"
        size_str = "-"

        if key == "fasta":
            # yaml 指向 .gz，运行期用解压产物
            if resolved:
                unzipped = resolved.with_suffix("") if resolved.suffix == ".gz" else resolved
                fai_path = Path(str(unzipped) + ".fai")
                display_path = str(unzipped)
                index_path = str(fai_path)
                if unzipped.exists() and fai_path.exists():
                    build_status = "ready"
                    size_str = _human_size(unzipped.stat().st_size)
                else:
                    build_status = "missing"
        elif key in ("cds", "protein"):
            db_p = gene_index_path(version)
            db_path = str(db_p) if db_p else None
            if resolved and resolved.exists():
                build_status = "ready"
                size_str = _human_size(resolved.stat().st_size)
        else:
            if resolved and resolved.exists():
                build_status = "ready"
                size_str = _human_size(resolved.stat().st_size)

        result[key] = DataFileDTO(
            type=key,
            label=key,
            path=display_path,
            index_path=index_path,
            db_path=db_path,
            format=entry.format or "",
            size=size_str,
            build_required=key in ("fasta", "gff3"),
            build_tool=entry.format,
            build_status=build_status,
        )
    return _normalize_audit_keys(result)


# yaml 文件键 → 前端规范类型（fasta/gff/go/kegg 四类 + cds/protein）
_FILE_LABELS = {
    "fasta": "FASTA 序列",
    "gff": "GFF 注释",
    "go": "GO 注释",
    "kegg": "KEGG 通路",
    "cds": "CDS 序列",
    "protein": "蛋白序列",
}
_KEGG_SUBKEYS = ("kegg_ko", "kegg_pathway", "kegg_pathway_name", "kegg_gene")


def _normalize_audit_keys(audit: dict[str, DataFileDTO]) -> dict[str, DataFileDTO]:
    """把 yaml 文件键归一为前端规范键。

    - gff3 → gff；go 保留；kegg_ko/kegg_pathway/... 聚合为单个 kegg 条目
      （全部子文件就绪才 ready）；
    - 保留 cds/protein 供序列 Tab 展示；functional/go_obo 等并入 go/kegg 聚合，
      不再单独出行。
    """
    out: dict[str, DataFileDTO] = {}
    for key, dto in audit.items():
        if key == "gff3":
            out["gff"] = dto.model_copy(update={"type": "gff"})
        elif key in _KEGG_SUBKEYS:
            continue  # 聚合处理
        elif key in ("fasta", "go", "cds", "protein"):
            out[key] = dto
        # 其余（functional/go_obo/...）不单独出行

    kegg_parts = [audit[k] for k in _KEGG_SUBKEYS if k in audit]
    if kegg_parts:
        primary = audit.get("kegg_ko") or kegg_parts[0]
        all_ready = all(p.build_status == "ready" for p in kegg_parts)
        total_bytes = 0
        for p in kegg_parts:
            try:
                total_bytes += Path(p.path).stat().st_size
            except OSError:
                pass
        out["kegg"] = DataFileDTO(
            type="kegg",
            label=_FILE_LABELS["kegg"],
            path=primary.path,
            format="kegg_list",
            size=_human_size(total_bytes) if total_bytes else "-",
            build_required=False,
            build_tool="indexer",
            build_status="ready" if all_ready else "missing",
        )

    for key, label in _FILE_LABELS.items():
        if key in out:
            out[key] = out[key].model_copy(update={"label": label})
    return out


def _version_build_status(version: VersionConfig) -> str:
    """版本级 build_status：gene_index.db + meta.build_status。"""
    db_path = gene_index_path(version)
    if db_path is None or not db_path.exists():
        return "missing"
    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        status = _get_meta(conn, "build_status", "")
        conn.close()
        if status == "ready":
            return "ready"
        return "building"
    except sqlite3.Error:
        return "building"


# ========================= 物种列表 =========================


def list_species(cm: ConfigManager | None = None) -> SpeciesListResponse:
    """GET /species：全量物种 → 版本列表（含文件审计与映射声明）。"""
    cm = cm or config_manager
    cfg = cm.get_config()
    species_list: list[SpeciesDTO] = []

    for sp in cfg.species:
        versions_dto: list[GenomeVersionDTO] = []
        for ver in sp.versions:
            versions_dto.append(GenomeVersionDTO(
                version_id=ver.id,
                version_name=ver.version_name,
                assembly_name=ver.assembly_name or "",
                is_default=ver.is_default,
                status=ver.status,
                release_date=ver.release_date or "",
                description=ver.description,
                tags=list(ver.tags),
                stats=VersionStatsDTO(
                    chromosomes=ver.stats.chromosomes,
                    total_genes=ver.stats.total_genes,
                    protein_coding=ver.stats.protein_coding,
                    genome_size=ver.stats.genome_size,
                    n50=ver.stats.n50,
                ),
                data_files=_audit_data_files(ver),
            ))

        mappings: list[VersionMappingDTO] = []
        for ver in sp.versions:
            for m in ver.id_mapping:
                m_path = resolve_file_path(ver, "") if False else None
                # id_mapping path 相对 data_dir
                mp = Path(m.path) if m.path else None
                if mp and not mp.is_absolute() and ver.data_dir:
                    mp = Path(ver.data_dir) / mp
                exists = mp is not None and mp.exists()
                mappings.append(VersionMappingDTO(
                    source=ver.id,
                    target=m.to,
                    mapping_tool="",
                    mapping_file=str(mp) if mp else "",
                    build_status="ready" if exists else "missing",
                    mapped_genes=0,
                    average_quality=0.0,
                ))

        species_list.append(SpeciesDTO(
            id=sp.id,
            scientific_name=sp.latin_name,
            common_name=sp.common_name,
            taxonomy_id=sp.taxonomy_id,
            description=sp.description,
            icon=sp.icon,
            category=sp.category,
            gradient=sp.gradient,
            genome_versions=versions_dto,
            version_mappings=mappings,
        ))

    return SpeciesListResponse(species=species_list)


# ========================= 版本详情 =========================


def get_version_detail(version_id: str) -> VersionDetailDTO:
    """GET /versions/{version_id}。"""
    found = config_manager.get_version(version_id)
    if found is None:
        raise NotFoundError(f"版本不存在：{version_id}")
    sp, ver = found

    data_files = _audit_data_files(ver)
    build_status = _version_build_status(ver)
    indexed = build_status == "ready"

    chromosomes: list[ChromosomeDTO] = []
    gene_type_stats: list[GeneTypeStatDTO] = []
    stats = VersionStatsDTO(
        chromosomes=ver.stats.chromosomes,
        total_genes=ver.stats.total_genes,
        protein_coding=ver.stats.protein_coding,
        genome_size=ver.stats.genome_size,
        n50=ver.stats.n50,
    )
    gene_count = 0
    transcript_count = 0
    built_at: str | None = None

    # 染色体：优先 .fai
    fasta_path = resolve_file_path(ver, "fasta")
    if fasta_path:
        unzipped = fasta_path.with_suffix("") if fasta_path.suffix == ".gz" else fasta_path
        fai_path = Path(str(unzipped) + ".fai")
        if fai_path.exists():
            try:
                fai = parse_fai(fai_path)
                for i, (name, rec) in enumerate(fai.items()):
                    chromosomes.append(ChromosomeDTO(
                        name=name,
                        length=rec.length,
                        color=_PALETTE[i % len(_PALETTE)],
                    ))
            except (OSError, ValueError):
                pass

    if not chromosomes and ver.stats.chromosomes:
        # fallback: yaml stats 只给数量，无具体名
        pass

    if indexed:
        try:
            conn = _open_db(ver)
            # gene_type 统计
            rows = conn.execute(
                "SELECT gene_type, COUNT(*) as cnt FROM genes GROUP BY gene_type ORDER BY cnt DESC"
            ).fetchall()
            for i, r in enumerate(rows):
                gene_type_stats.append(GeneTypeStatDTO(
                    name=r["gene_type"] or "unknown",
                    value=r["cnt"],
                    color=_PALETTE[i % len(_PALETTE)],
                ))
            # meta 取值
            gene_count = int(_get_meta(conn, "gene_count", "0") or 0)
            transcript_count = int(_get_meta(conn, "transcript_count", "0") or 0)
            built_at = _get_meta(conn, "built_at", "") or None
            # protein_coding 计数
            pc_row = conn.execute(
                "SELECT COUNT(*) as cnt FROM genes WHERE gene_type='protein_coding'"
            ).fetchone()
            protein_coding = pc_row["cnt"] if pc_row else 0
            stats = VersionStatsDTO(
                chromosomes=len(chromosomes) if chromosomes else ver.stats.chromosomes,
                total_genes=gene_count,
                protein_coding=protein_coding,
                genome_size=ver.stats.genome_size,
                n50=ver.stats.n50,
            )
            conn.close()
        except NotFoundError:
            pass

    return VersionDetailDTO(
        species_id=sp.id,
        version_id=ver.id,
        version_name=ver.version_name,
        assembly_name=ver.assembly_name or "",
        is_default=ver.is_default,
        status=ver.status,
        release_date=ver.release_date or "",
        description=ver.description,
        tags=list(ver.tags),
        stats=stats,
        chromosomes=chromosomes,
        gene_type_stats=gene_type_stats,
        data_files=data_files,
        build_status=build_status,
        indexed=indexed,
        built_at=built_at,
        gene_count=gene_count,
        transcript_count=transcript_count,
    )


# ========================= 基因搜索 =========================

_GO_RE = re.compile(r"^GO:\d+$", re.IGNORECASE)
_KO_RE = re.compile(r"^K\d+$")
_PATHWAY_RE = re.compile(r"^ath\d+$", re.IGNORECASE)

_GENE_FIELDS = (
    "gene_id, gene_name, chromosome, start, end, strand, length, annotation, exons, gene_type"
)


def _gene_row_to_dto(row: sqlite3.Row, conn: sqlite3.Connection, has_seq_ready: bool) -> GeneDTO:
    """基因行 → GeneDTO，附带 has_go/has_kegg/has_sequence。"""
    gid = row["gene_id"]
    has_go = bool(conn.execute(
        "SELECT 1 FROM go_annotations WHERE gene_id=? LIMIT 1", (gid,)
    ).fetchone())
    has_kegg = bool(conn.execute(
        "SELECT 1 FROM kegg_annotations WHERE gene_id=? AND (ko_id != '' OR pathway_id != '') LIMIT 1",
        (gid,),
    ).fetchone())
    return GeneDTO(
        gene_id=gid,
        gene_name=row["gene_name"] or gid,
        annotation=row["annotation"] or "",
        gene_type=row["gene_type"] or "unknown",
        chromosome=row["chromosome"] or "",
        start=row["start"] or 0,
        end=row["end"] or 0,
        strand=row["strand"] or "+",
        length=row["length"] or 0,
        exons=int(row["exons"] or 0),
        has_go=has_go,
        has_kegg=has_kegg,
        has_sequence=has_seq_ready,
    )


def _search_genes(
    conn: sqlite3.Connection,
    field: str,
    q: str,
    chromosome: str | None,
    page: int,
    page_size: int,
    has_seq_ready: bool,
) -> GeneListResponse:
    """基因搜索核心（field=gene_id/gene_name/annotation/go/kegg/all）。

    q 为空 = 浏览模式（分页列出全部基因，仅受 chromosome 过滤）；
    go/kegg 反查由 api 层保证 q 非空。
    """
    q = (q or "").strip()
    offset = (page - 1) * page_size
    where_clauses: list[str] = []
    params: list[Any] = []

    if not q:
        pass  # 浏览模式：无关键词过滤
    elif field == "gene_id":
        where_clauses.append("gene_id LIKE ? ESCAPE '\\'")
        params.append(f"%{_escape_like(q)}%")
    elif field in ("gene_name", "annotation"):
        # 先试 FTS5
        fts_expr = _fts_tokens(q)
        if fts_expr:
            try:
                conn.execute(f"SELECT 1 FROM genes WHERE {field} MATCH ? LIMIT 1", (fts_expr,))
                where_clauses.append(f"{field} MATCH ?")
                params.append(fts_expr)
            except sqlite3.Error:
                where_clauses.append(f"{field} LIKE ? ESCAPE '\\'")
                params.append(f"%{_escape_like(q)}%")
        else:
            where_clauses.append(f"{field} LIKE ? ESCAPE '\\'")
            params.append(f"%{_escape_like(q)}%")
    elif field == "go":
        if _GO_RE.match(q):
            # go_id 精确反查
            where_clauses.append(
                "gene_id IN (SELECT gene_id FROM go_annotations WHERE go_id=?)"
            )
            params.append(q.upper())
        else:
            where_clauses.append(
                "gene_id IN (SELECT ga.gene_id FROM go_annotations ga "
                "JOIN go_terms gt ON ga.go_id=gt.go_id WHERE gt.name LIKE ? ESCAPE '\\')"
            )
            params.append(f"%{_escape_like(q)}%")
    elif field == "kegg":
        if _KO_RE.match(q):
            where_clauses.append(
                "gene_id IN (SELECT gene_id FROM kegg_annotations WHERE ko_id=?)"
            )
            params.append(q.upper())
        elif _PATHWAY_RE.match(q):
            where_clauses.append(
                "gene_id IN (SELECT gene_id FROM kegg_annotations WHERE pathway_id=?)"
            )
            params.append(q.lower())
        else:
            where_clauses.append(
                "gene_id IN ("
                "SELECT ka.gene_id FROM kegg_annotations ka "
                "JOIN kegg_kos kk ON ka.ko_id=kk.ko_id WHERE kk.name LIKE ? ESCAPE '\\' "
                "UNION "
                "SELECT ka.gene_id FROM kegg_annotations ka "
                "JOIN kegg_pathways kp ON ka.pathway_id=kp.pathway_id WHERE kp.name LIKE ? ESCAPE '\\'"
                ")"
            )
            params.extend([f"%{_escape_like(q)}%", f"%{_escape_like(q)}%"])
    elif field == "all":
        fts_expr = _fts_tokens(q)
        like_q = f"%{_escape_like(q)}%"
        if fts_expr:
            try:
                # FTS5 MATCH 不能在 OR 表达式中，用 UNION 子查询合并
                conn.execute("SELECT 1 FROM genes WHERE gene_name MATCH ? LIMIT 1", (fts_expr,))
                where_clauses.append(
                    "gene_id IN ("
                    "SELECT gene_id FROM genes WHERE gene_id LIKE ? ESCAPE '\\' "
                    "UNION "
                    "SELECT gene_id FROM genes WHERE gene_name MATCH ? "
                    "UNION "
                    "SELECT gene_id FROM genes WHERE annotation MATCH ?"
                    ")"
                )
                params.extend([like_q, fts_expr, fts_expr])
            except sqlite3.Error:
                where_clauses.append(
                    "(gene_id LIKE ? ESCAPE '\\' OR gene_name LIKE ? ESCAPE '\\' "
                    "OR annotation LIKE ? ESCAPE '\\')"
                )
                params.extend([like_q, like_q, like_q])
        else:
            where_clauses.append(
                "(gene_id LIKE ? ESCAPE '\\' OR gene_name LIKE ? ESCAPE '\\' "
                "OR annotation LIKE ? ESCAPE '\\')"
            )
            params.extend([like_q, like_q, like_q])
    else:
        raise ValidationError(f"不支持的搜索字段：{field}")

    if chromosome:
        where_clauses.append("chromosome=?")
        params.append(chromosome)

    where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
    count_row = conn.execute(f"SELECT COUNT(*) as cnt FROM genes WHERE {where_sql}", params).fetchone()
    total = count_row["cnt"] if count_row else 0

    rows = conn.execute(
        f"SELECT {_GENE_FIELDS} FROM genes WHERE {where_sql} ORDER BY gene_id LIMIT ? OFFSET ?",
        params + [page_size, offset],
    ).fetchall()

    items = [_gene_row_to_dto(r, conn, has_seq_ready) for r in rows]
    return GeneListResponse(total=total, page=page, page_size=page_size, items=items)


def search_genes(
    version_id: str,
    field: str = "all",
    q: str = "",
    chromosome: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> GeneListResponse:
    """GET /versions/{version_id}/genes。"""
    found = config_manager.get_version(version_id)
    if found is None:
        raise NotFoundError(f"版本不存在：{version_id}")
    _sp, ver = found
    conn = _open_db(ver)
    try:
        # has_sequence: fasta 审计 ready
        fasta_path = resolve_file_path(ver, "fasta")
        has_seq = False
        if fasta_path:
            unzipped = fasta_path.with_suffix("") if fasta_path.suffix == ".gz" else fasta_path
            has_seq = unzipped.exists() and Path(str(unzipped) + ".fai").exists()
        return _search_genes(conn, field, q, chromosome, page, min(page_size, 100), has_seq)
    finally:
        conn.close()


# ========================= 基因详情 =========================


def get_gene_detail(version_id: str, gene_id: str) -> GeneDetailDTO:
    """GET /versions/{version_id}/genes/{gene_id}。"""
    found = config_manager.get_version(version_id)
    if found is None:
        raise NotFoundError(f"版本不存在：{version_id}")
    _sp, ver = found
    conn = _open_db(ver)
    try:
        row = conn.execute(
            f"SELECT {_GENE_FIELDS} FROM genes WHERE gene_id=?", (gene_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError(f"基因不存在：{gene_id}")

        # 审计 fasta
        fasta_path = resolve_file_path(ver, "fasta")
        has_seq = False
        if fasta_path:
            unzipped = fasta_path.with_suffix("") if fasta_path.suffix == ".gz" else fasta_path
            has_seq = unzipped.exists() and Path(str(unzipped) + ".fai").exists()

        gene = _gene_row_to_dto(row, conn, has_seq)

        # 转录本
        txns = conn.execute(
            "SELECT * FROM transcripts WHERE gene_id=? ORDER BY canonical DESC, start",
            (gene_id,),
        ).fetchall()
        transcripts: list[TranscriptDTO] = []
        for t in txns:
            exons_raw = t["exon_ranges"]
            exon_list: list[ExonDTO] = []
            if exons_raw:
                try:
                    pairs = json.loads(exons_raw)
                    for rank, pair in enumerate(pairs, 1):
                        if isinstance(pair, (list, tuple)) and len(pair) >= 2:
                            exon_list.append(ExonDTO(start=int(pair[0]), end=int(pair[1]), rank=rank))
                except (json.JSONDecodeError, TypeError, ValueError):
                    pass
            transcripts.append(TranscriptDTO(
                transcript_id=t["transcript_id"],
                gene_id=t["gene_id"],
                chromosome=t["chrom"] or "",
                start=t["start"] or 0,
                end=t["end"] or 0,
                strand=t["strand"] or "+",
                biotype="protein_coding",
                length=max(0, (t["end"] or 0) - (t["start"] or 0)),
                exon_count=t["exon_count"] or 0,
                exons=exon_list,
                cds_id=t["cds_id"],
                pep_id=t["pep_id"],
                canonical=bool(t["canonical"]),
            ))

        # GO 注释（join go_terms）
        go_rows = conn.execute(
            "SELECT ga.go_id, gt.name, gt.aspect, ga.evidence, ga.source "
            "FROM go_annotations ga "
            "JOIN go_terms gt ON ga.go_id=gt.go_id "
            "WHERE ga.gene_id=? LIMIT 100",
            (gene_id,),
        ).fetchall()
        go_annotations = [
            GoAnnotationDTO(
                go_id=r["go_id"],
                term=r["name"] or "",
                namespace=_aspect_to_namespace(r["aspect"]),
                evidence_code=r["evidence"] or "",
                source=r["source"] or "",
            )
            for r in go_rows
        ]

        # KEGG
        ko_rows = conn.execute(
            "SELECT DISTINCT ka.ko_id, kk.name, kk.definition "
            "FROM kegg_annotations ka "
            "LEFT JOIN kegg_kos kk ON ka.ko_id=kk.ko_id "
            "WHERE ka.gene_id=? AND ka.ko_id != '' LIMIT 100",
            (gene_id,),
        ).fetchall()
        kos: list[KeggKoDTO] = []
        for r in ko_rows:
            gc = conn.execute(
                "SELECT COUNT(DISTINCT gene_id) as cnt FROM kegg_annotations WHERE ko_id=? AND ko_id != ''",
                (r["ko_id"],),
            ).fetchone()
            kos.append(KeggKoDTO(
                ko_id=r["ko_id"],
                name=r["name"] or "",
                definition=r["definition"] or "",
                gene_count=gc["cnt"] if gc else 0,
            ))

        pw_rows = conn.execute(
            "SELECT DISTINCT ka.pathway_id, kp.name "
            "FROM kegg_annotations ka "
            "LEFT JOIN kegg_pathways kp ON ka.pathway_id=kp.pathway_id "
            "WHERE ka.gene_id=? AND ka.pathway_id != '' LIMIT 100",
            (gene_id,),
        ).fetchall()
        pathways: list[KeggPathwayDTO] = []
        for r in pw_rows:
            gc = conn.execute(
                "SELECT COUNT(DISTINCT gene_id) as cnt FROM kegg_annotations WHERE pathway_id=? AND pathway_id != ''",
                (r["pathway_id"],),
            ).fetchone()
            pathways.append(KeggPathwayDTO(
                pathway_id=r["pathway_id"],
                name=r["name"] or "",
                gene_count=gc["cnt"] if gc else 0,
            ))

        kegg = GeneKeggDTO(kos=kos, pathways=pathways)

        # 序列可用性
        genomic_avail = has_seq
        cds_avail = False
        protein_avail = False
        # 查 canonical 转录本，否则取 cds_length/pep_length 最大
        canon = conn.execute(
            "SELECT cds_id, pep_id FROM transcripts WHERE gene_id=? AND canonical=1 LIMIT 1",
            (gene_id,),
        ).fetchone()
        if canon is None:
            canon = conn.execute(
                "SELECT cds_id, pep_id FROM transcripts WHERE gene_id=? "
                "ORDER BY cds_length DESC, pep_length DESC LIMIT 1",
                (gene_id,),
            ).fetchone()
        if canon:
            if canon["cds_id"]:
                cds_avail = bool(conn.execute(
                    "SELECT 1 FROM fasta_records WHERE kind='cds' AND seq_id=? LIMIT 1",
                    (canon["cds_id"],),
                ).fetchone())
            if canon["pep_id"]:
                protein_avail = bool(conn.execute(
                    "SELECT 1 FROM fasta_records WHERE kind='pep' AND seq_id=? LIMIT 1",
                    (canon["pep_id"],),
                ).fetchone())

        seq_avail = SequenceAvailabilityDTO(
            genomic=genomic_avail, cds=cds_avail, protein=protein_avail
        )

        return GeneDetailDTO(
            gene=gene,
            transcripts=transcripts,
            go=go_annotations,
            kegg=kegg,
            sequence_available=seq_avail,
        )
    finally:
        conn.close()


def _aspect_to_namespace(aspect: str) -> str:
    return {"F": "MF", "P": "BP", "C": "CC"}.get((aspect or "").upper(), "BP")


# ========================= 序列 =========================


def get_gene_sequence(
    version_id: str,
    gene_id: str,
    seq_type: str = "genomic",
    fmt: str = "json",
) -> SequenceDTO | str:
    """GET /versions/{version_id}/genes/{gene_id}/sequence。"""
    found = config_manager.get_version(version_id)
    if found is None:
        raise NotFoundError(f"版本不存在：{version_id}")
    _sp, ver = found
    conn = _open_db(ver)
    try:
        if seq_type == "genomic":
            row = conn.execute(
                "SELECT gene_id, chromosome, start, end, strand FROM genes WHERE gene_id=?",
                (gene_id,),
            ).fetchone()
            if row is None:
                raise NotFoundError(f"基因不存在：{gene_id}")
            fasta_path = resolve_file_path(ver, "fasta")
            if fasta_path is None:
                raise NotFoundError("基因组 FASTA 未配置")
            unzipped = fasta_path.with_suffix("") if fasta_path.suffix == ".gz" else fasta_path
            try:
                _, index = open_index(unzipped)
            except FileNotFoundError:
                raise NotFoundError("基因组 FASTA 索引不存在")
            try:
                seq = fetch_region(unzipped, index, row["chromosome"], row["start"], row["end"], row["strand"])
            except KeyError:
                raise NotFoundError(f"染色体不在 FASTA 索引中：{row['chromosome']}")
            except ValueError as exc:
                raise NotFoundError(f"序列区间无效：{exc}")
            header = f"{gene_id} {row['chromosome']}:{row['start']}-{row['end']}({row['strand']})"
            if fmt == "fasta":
                return _to_fasta(header, seq)
            return SequenceDTO(
                header=header, sequence=seq, length=len(seq), seq_type="genomic",
                chromosome=row["chromosome"], start=row["start"], end=row["end"], strand=row["strand"],
            )
        elif seq_type in ("cds", "protein"):
            kind = "cds" if seq_type == "cds" else "pep"
            # 取 canonical 转录本
            tx = conn.execute(
                "SELECT transcript_id, cds_id, pep_id FROM transcripts "
                "WHERE gene_id=? AND canonical=1 LIMIT 1",
                (gene_id,),
            ).fetchone()
            if tx is None:
                tx = conn.execute(
                    "SELECT transcript_id, cds_id, pep_id FROM transcripts "
                    "WHERE gene_id=? ORDER BY cds_length DESC, pep_length DESC LIMIT 1",
                    (gene_id,),
                ).fetchone()
            if tx is None:
                raise NotFoundError(f"无转录本记录：基因 {gene_id}")
            seq_id = tx["cds_id"] if kind == "cds" else tx["pep_id"]
            if not seq_id:
                raise NotFoundError(f"无 {seq_type} 序列 ID：基因 {gene_id}")
            rec = conn.execute(
                "SELECT byte_offset, seq_length, linebases, linewidth "
                "FROM fasta_records WHERE kind=? AND seq_id=?",
                (kind, seq_id),
            ).fetchone()
            if rec is None:
                raise NotFoundError(f"sequence file not registered: {seq_id}")
            fasta_key = "cds" if kind == "cds" else "protein"
            fasta_path = resolve_file_path(ver, fasta_key)
            if fasta_path is None or not fasta_path.exists():
                raise NotFoundError(f"no {seq_type} for gene {gene_id}")
            seq = fetch_kv(fasta_path, rec["byte_offset"], rec["seq_length"], rec["linebases"], rec["linewidth"])
            header = f"{seq_id} {tx['transcript_id']} {gene_id}"
            if fmt == "fasta":
                return _to_fasta(header, seq)
            return SequenceDTO(
                header=header, sequence=seq, length=len(seq), seq_type=seq_type,
                transcript_id=tx["transcript_id"],
            )
        else:
            raise ValidationError(f"不支持的序列类型：{seq_type}")
    finally:
        conn.close()


def get_region_sequence(
    version_id: str,
    chrom: str,
    start: int,
    end: int,
    strand: str = "+",
    fmt: str = "json",
) -> SequenceDTO | str:
    """GET /versions/{version_id}/sequence（区间序列）。"""
    if end - start + 1 > 1_000_000:
        raise BusinessError("查询区间上限 1 Mb（end - start + 1 ≤ 1,000,000）")
    found = config_manager.get_version(version_id)
    if found is None:
        raise NotFoundError(f"版本不存在：{version_id}")
    _sp, ver = found
    fasta_path = resolve_file_path(ver, "fasta")
    if fasta_path is None:
        raise NotFoundError("基因组 FASTA 未配置")
    unzipped = fasta_path.with_suffix("") if fasta_path.suffix == ".gz" else fasta_path
    try:
        _, index = open_index(unzipped)
    except FileNotFoundError:
        raise NotFoundError("基因组 FASTA 索引不存在")
    try:
        seq = fetch_region(unzipped, index, chrom, start, end, strand)
    except KeyError:
        raise NotFoundError(f"染色体不在 FASTA 索引中：{chrom}")
    except ValueError as exc:
        raise BusinessError(f"序列区间无效：{exc}")
    header = f"{chrom}:{start}-{end}({strand})"
    if fmt == "fasta":
        return _to_fasta(header, seq)
    return SequenceDTO(
        header=header, sequence=seq, length=len(seq), seq_type="genomic",
        chromosome=chrom, start=start, end=end, strand=strand,
    )


def _to_fasta(header: str, seq: str) -> str:
    """序列 → FASTA 文本（每 60 字符换行）。"""
    lines = [f">{header}"]
    for i in range(0, len(seq), 60):
        lines.append(seq[i:i + 60])
    return "\n".join(lines) + "\n"


# ========================= GO =========================


def list_go_terms(
    version_id: str,
    q: str = "",
    aspect: str = "",
    page: int = 1,
    page_size: int = 20,
) -> GoTermListResponse:
    """GET /versions/{version_id}/go。"""
    found = config_manager.get_version(version_id)
    if found is None:
        raise NotFoundError(f"版本不存在：{version_id}")
    _sp, ver = found
    conn = _open_db(ver)
    try:
        where_clauses: list[str] = []
        params: list[Any] = []
        if q:
            where_clauses.append("(gt.go_id LIKE ? OR gt.name LIKE ? ESCAPE '\\')")
            params.extend([f"{_escape_like(q)}%", f"%{_escape_like(q)}%"])
        if aspect:
            where_clauses.append("gt.aspect=?")
            params.append(aspect.upper())

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        count_sql = (
            f"SELECT COUNT(*) as cnt FROM go_terms gt WHERE {where_sql}"
        )
        count_row = conn.execute(count_sql, params).fetchone()
        total = count_row["cnt"] if count_row else 0

        offset = (page - 1) * page_size
        query_sql = (
            "SELECT gt.go_id, gt.name, gt.aspect, gt.definition, "
            "  (SELECT COUNT(*) FROM go_annotations WHERE go_id=gt.go_id) as gene_count "
            "FROM go_terms gt "
            f"WHERE {where_sql} "
            "ORDER BY gene_count DESC, gt.go_id "
            "LIMIT ? OFFSET ?"
        )
        rows = conn.execute(query_sql, params + [page_size, offset]).fetchall()
        items = [
            GoTermDTO(
                go_id=r["go_id"],
                name=r["name"] or "",
                aspect=r["aspect"] or "",
                definition=r["definition"] or "",
                gene_count=r["gene_count"],
            )
            for r in rows
        ]
        return GoTermListResponse(total=total, page=page, page_size=page_size, items=items)
    finally:
        conn.close()


def list_go_genes(
    version_id: str,
    go_id: str,
    page: int = 1,
    page_size: int = 20,
) -> GoGeneListResponse:
    """GET /versions/{version_id}/go/{go_id}/genes。"""
    found = config_manager.get_version(version_id)
    if found is None:
        raise NotFoundError(f"版本不存在：{version_id}")
    _sp, ver = found
    conn = _open_db(ver)
    try:
        term = conn.execute("SELECT * FROM go_terms WHERE go_id=?", (go_id,)).fetchone()
        if term is None:
            raise NotFoundError(f"GO term 不存在：{go_id}")

        count_row = conn.execute(
            "SELECT COUNT(*) as cnt FROM go_annotations WHERE go_id=?", (go_id,)
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT g.gene_id, g.gene_name, g.chromosome, g.start, g.end, g.strand, "
            "g.length, g.annotation, g.exons, g.gene_type "
            "FROM genes g "
            "JOIN go_annotations ga ON g.gene_id=ga.gene_id "
            "WHERE ga.go_id=? ORDER BY g.gene_id LIMIT ? OFFSET ?",
            (go_id, page_size, offset),
        ).fetchall()

        fasta_path = resolve_file_path(ver, "fasta")
        has_seq = False
        if fasta_path:
            unzipped = fasta_path.with_suffix("") if fasta_path.suffix == ".gz" else fasta_path
            has_seq = unzipped.exists() and Path(str(unzipped) + ".fai").exists()

        items = [_gene_row_to_dto(r, conn, has_seq) for r in rows]
        return GoGeneListResponse(
            go_id=go_id, name=term["name"] or "",
            total=total, page=page, page_size=page_size, items=items,
        )
    finally:
        conn.close()


# ========================= KEGG =========================


def list_kegg_pathways(
    version_id: str,
    q: str = "",
    page: int = 1,
    page_size: int = 20,
) -> KeggPathwayListResponse:
    """GET /versions/{version_id}/kegg/pathways。"""
    found = config_manager.get_version(version_id)
    if found is None:
        raise NotFoundError(f"版本不存在：{version_id}")
    _sp, ver = found
    conn = _open_db(ver)
    try:
        where_clauses: list[str] = []
        params: list[Any] = []
        if q:
            where_clauses.append("(kp.pathway_id LIKE ? OR kp.name LIKE ? ESCAPE '\\')")
            params.extend([f"%{_escape_like(q)}%", f"%{_escape_like(q)}%"])

        where_sql = " AND ".join(where_clauses) if where_clauses else "1=1"
        count_row = conn.execute(
            f"SELECT COUNT(*) as cnt FROM kegg_pathways kp WHERE {where_sql}", params
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT kp.pathway_id, kp.name, "
            "  (SELECT COUNT(DISTINCT gene_id) FROM kegg_annotations WHERE pathway_id=kp.pathway_id AND pathway_id != '') as gene_count "
            "FROM kegg_pathways kp "
            f"WHERE {where_sql} "
            "ORDER BY kp.pathway_id LIMIT ? OFFSET ?",
            params + [page_size, offset],
        ).fetchall()
        items = [
            KeggPathwayDTO(pathway_id=r["pathway_id"], name=r["name"] or "", gene_count=r["gene_count"])
            for r in rows
        ]
        return KeggPathwayListResponse(total=total, page=page, page_size=page_size, items=items)
    finally:
        conn.close()


def list_pathway_genes(
    version_id: str,
    pathway_id: str,
    page: int = 1,
    page_size: int = 20,
) -> PathwayGeneListResponse:
    """GET /versions/{version_id}/kegg/pathways/{pathway_id}/genes。"""
    found = config_manager.get_version(version_id)
    if found is None:
        raise NotFoundError(f"版本不存在：{version_id}")
    _sp, ver = found
    conn = _open_db(ver)
    try:
        pw = conn.execute("SELECT * FROM kegg_pathways WHERE pathway_id=?", (pathway_id,)).fetchone()
        if pw is None:
            raise NotFoundError(f"KEGG pathway 不存在：{pathway_id}")

        count_row = conn.execute(
            "SELECT COUNT(DISTINCT gene_id) as cnt FROM kegg_annotations WHERE pathway_id=? AND pathway_id != ''",
            (pathway_id,),
        ).fetchone()
        total = count_row["cnt"] if count_row else 0

        offset = (page - 1) * page_size
        rows = conn.execute(
            "SELECT g.gene_id, g.gene_name, g.chromosome, g.start, g.end, g.strand, g.length, g.annotation, g.exons, g.gene_type "
            "FROM genes g "
            "JOIN kegg_annotations ka ON g.gene_id=ka.gene_id "
            "WHERE ka.pathway_id=? AND ka.pathway_id != '' "
            "ORDER BY g.gene_id LIMIT ? OFFSET ?",
            (pathway_id, page_size, offset),
        ).fetchall()

        fasta_path = resolve_file_path(ver, "fasta")
        has_seq = False
        if fasta_path:
            unzipped = fasta_path.with_suffix("") if fasta_path.suffix == ".gz" else fasta_path
            has_seq = unzipped.exists() and Path(str(unzipped) + ".fai").exists()

        items = [_gene_row_to_dto(r, conn, has_seq) for r in rows]
        return PathwayGeneListResponse(
            pathway_id=pathway_id, name=pw["name"] or "",
            total=total, page=page, page_size=page_size, items=items,
        )
    finally:
        conn.close()


# ========================= 搜索 =========================


def search_version(
    version_id: str,
    q: str = "",
    limit: int = 10,
) -> SearchResponse:
    """GET /versions/{version_id}/search（单版本内搜索）。"""
    if not q or not q.strip():
        raise ValidationError("查询参数 q 不能为空")
    found = config_manager.get_version(version_id)
    if found is None:
        raise NotFoundError(f"版本不存在：{version_id}")
    sp, ver = found
    conn = _open_db(ver)
    try:
        limit = min(max(1, limit), 50)
        genes = _search_hits(conn, q, limit, ver.id, sp.id)
        go_terms = _go_search_hits(conn, q, limit, ver.id, sp.id)
        kegg = _kegg_search_hits(conn, q, limit, ver.id, sp.id)
        return SearchResponse(genes=genes, go_terms=go_terms, kegg=kegg, species=[])
    finally:
        conn.close()


def search_global(
    q: str = "",
    species_id: str | None = None,
    limit: int = 10,
) -> SearchResponse:
    """GET /search（跨版本聚合 + 物种命中）。"""
    if not q or not q.strip():
        raise ValidationError("查询参数 q 不能为空")
    limit = min(max(1, limit), 50)
    cfg = config_manager.get_config()
    all_genes: list[GeneSearchHitDTO] = []
    all_go: list[GoTermSearchHitDTO] = []
    all_kegg: list[KeggSearchHitDTO] = []
    all_species: list[SpeciesSearchHitDTO] = []

    for sp in cfg.species:
        if species_id and sp.id != species_id:
            continue
        # 物种命中
        ql = q.lower()
        for field_name, val in [
            ("common_name", sp.common_name),
            ("latin_name", sp.latin_name),
            ("taxonomy_id", sp.taxonomy_id),
            ("id", sp.id),
        ]:
            if val and ql in val.lower():
                all_species.append(SpeciesSearchHitDTO(
                    species_id=sp.id, common_name=sp.common_name, match=field_name
                ))
                break

        for ver in sp.versions:
            try:
                conn = _open_db(ver)
            except NotFoundError:
                continue
            try:
                all_genes.extend(_search_hits(conn, q, limit, ver.id, sp.id))
                all_go.extend(_go_search_hits(conn, q, limit, ver.id, sp.id))
                all_kegg.extend(_kegg_search_hits(conn, q, limit, ver.id, sp.id))
            finally:
                conn.close()

    return SearchResponse(genes=all_genes, go_terms=all_go, kegg=all_kegg, species=all_species)


def _search_hits(
    conn: sqlite3.Connection, q: str, limit: int, version_id: str, species_id: str
) -> list[GeneSearchHitDTO]:
    like_q = f"%{_escape_like(q)}%"
    fts_expr = _fts_tokens(q)
    where = "gene_id LIKE ? ESCAPE '\\'"
    params: list[Any] = [like_q]
    if fts_expr:
        try:
            conn.execute("SELECT 1 FROM genes WHERE gene_name MATCH ? LIMIT 1", (fts_expr,))
            where = (
                "gene_id IN ("
                "SELECT gene_id FROM genes WHERE gene_id LIKE ? ESCAPE '\\' "
                "UNION SELECT gene_id FROM genes WHERE gene_name MATCH ? "
                "UNION SELECT gene_id FROM genes WHERE annotation MATCH ?)"
            )
            params = [like_q, fts_expr, fts_expr]
        except sqlite3.Error:
            where = "(gene_id LIKE ? ESCAPE '\\' OR gene_name LIKE ? ESCAPE '\\' OR annotation LIKE ? ESCAPE '\\')"
            params = [like_q, like_q, like_q]
    rows = conn.execute(
        f"SELECT gene_id, gene_name, annotation, chromosome FROM genes WHERE {where} ORDER BY gene_id LIMIT ?",
        params + [limit],
    ).fetchall()
    return [
        GeneSearchHitDTO(
            gene_id=r["gene_id"],
            gene_name=r["gene_name"] or "",
            annotation=r["annotation"] or "",
            chromosome=r["chromosome"] or "",
            version_id=version_id,
            species_id=species_id,
        )
        for r in rows
    ]


def _go_search_hits(
    conn: sqlite3.Connection, q: str, limit: int, version_id: str, species_id: str
) -> list[GoTermSearchHitDTO]:
    like_q = f"%{_escape_like(q)}%"
    rows = conn.execute(
        "SELECT gt.go_id, gt.name, gt.aspect, "
        "  (SELECT COUNT(*) FROM go_annotations WHERE go_id=gt.go_id) as gene_count "
        "FROM go_terms gt "
        "WHERE gt.go_id LIKE ? OR gt.name LIKE ? ESCAPE '\\' "
        "ORDER BY gene_count DESC LIMIT ?",
        (f"{_escape_like(q)}%", like_q, limit),
    ).fetchall()
    return [
        GoTermSearchHitDTO(
            go_id=r["go_id"], name=r["name"] or "", aspect=r["aspect"] or "",
            gene_count=r["gene_count"], version_id=version_id, species_id=species_id,
        )
        for r in rows
    ]


def _kegg_search_hits(
    conn: sqlite3.Connection, q: str, limit: int, version_id: str, species_id: str
) -> list[KeggSearchHitDTO]:
    like_q = f"%{_escape_like(q)}%"
    results: list[KeggSearchHitDTO] = []
    # KO hits
    ko_rows = conn.execute(
        "SELECT kk.ko_id, kk.name, "
        "  (SELECT COUNT(DISTINCT gene_id) FROM kegg_annotations WHERE ko_id=kk.ko_id AND ko_id != '') as gene_count "
        "FROM kegg_kos kk "
        "WHERE kk.ko_id LIKE ? OR kk.name LIKE ? ESCAPE '\\' "
        "LIMIT ?",
        (f"{_escape_like(q)}%", like_q, limit),
    ).fetchall()
    for r in ko_rows:
        results.append(KeggSearchHitDTO(
            id=r["ko_id"], kind="ko", name=r["name"] or "",
            gene_count=r["gene_count"], version_id=version_id, species_id=species_id,
        ))
    # pathway hits
    pw_rows = conn.execute(
        "SELECT kp.pathway_id, kp.name, "
        "  (SELECT COUNT(DISTINCT gene_id) FROM kegg_annotations WHERE pathway_id=kp.pathway_id AND pathway_id != '') as gene_count "
        "FROM kegg_pathways kp "
        "WHERE kp.pathway_id LIKE ? OR kp.name LIKE ? ESCAPE '\\' "
        "LIMIT ?",
        (f"{_escape_like(q)}%", like_q, limit),
    ).fetchall()
    for r in pw_rows:
        results.append(KeggSearchHitDTO(
            id=r["pathway_id"], kind="pathway", name=r["name"] or "",
            gene_count=r["gene_count"], version_id=version_id, species_id=species_id,
        ))
    return results[:limit]


# ========================= 批量 / 映射 =========================


def batch_gene_annotation(version_id: str, gene_ids: list[str]) -> BatchAnnotationResponse:
    """POST /versions/{version_id}/genes/batch。"""
    if len(gene_ids) > 500:
        raise BusinessError("gene_ids 上限 500")
    found = config_manager.get_version(version_id)
    if found is None:
        raise NotFoundError(f"版本不存在：{version_id}")
    _sp, ver = found
    conn = _open_db(ver)
    try:
        items: list[BatchGeneAnnotationDTO] = []
        found_count = 0
        for gid in gene_ids:
            row = conn.execute(
                "SELECT gene_id, gene_name, annotation FROM genes WHERE gene_id=?", (gid,)
            ).fetchone()
            if row is None:
                items.append(BatchGeneAnnotationDTO(gene_id=gid, found=False))
            else:
                found_count += 1
                go_cnt = conn.execute(
                    "SELECT COUNT(DISTINCT go_id) as cnt FROM go_annotations WHERE gene_id=?", (gid,)
                ).fetchone()["cnt"]
                kegg_cnt = conn.execute(
                    "SELECT COUNT(DISTINCT CASE WHEN ko_id != '' THEN ko_id ELSE pathway_id END) as cnt "
                    "FROM kegg_annotations WHERE gene_id=? AND (ko_id != '' OR pathway_id != '')",
                    (gid,),
                ).fetchone()["cnt"]
                items.append(BatchGeneAnnotationDTO(
                    gene_id=gid, found=True,
                    gene_name=row["gene_name"] or "",
                    annotation=row["annotation"] or "",
                    go_count=go_cnt, kegg_count=kegg_cnt,
                ))
        return BatchAnnotationResponse(total=len(gene_ids), found=found_count, items=items)
    finally:
        conn.close()


def map_ids(version_id: str, target_version_id: str, ids: list[str]) -> MapIdsResponse:
    """POST /versions/{version_id}/map-ids。"""
    found = config_manager.get_version(version_id)
    if found is None:
        raise NotFoundError(f"版本不存在：{version_id}")
    _sp, ver = found
    conn = _open_db(ver)
    try:
        results: list[MapIdsResultItem] = []
        success = 0
        for sid in ids:
            row = conn.execute(
                "SELECT target_id FROM id_mapping WHERE source_id=? AND target_genome=?",
                (sid, target_version_id),
            ).fetchone()
            if row:
                results.append(MapIdsResultItem(input=sid, output=row["target_id"], status="success"))
                success += 1
            else:
                results.append(MapIdsResultItem(input=sid, output=None, status="fail"))
        return MapIdsResponse(results=results, success_count=success, total_count=len(ids))
    finally:
        conn.close()


def reload_config() -> ReloadResponse:
    """POST /reload（管理员）。"""
    cfg = config_manager.reload()
    version_count = sum(len(sp.versions) for sp in cfg.species)
    return ReloadResponse(
        ok=True, species_count=len(cfg.species), version_count=version_count
    )

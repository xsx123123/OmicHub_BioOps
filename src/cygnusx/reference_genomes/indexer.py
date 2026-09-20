"""离线构建管线：解析物种原始数据文件 → gene_index.db（SQLite FTS5）。

CLI 用法::

    python -m cygnusx.reference_genomes.indexer build --version tair10
    python -m cygnusx.reference_genomes.indexer build --version tair10 --only gff3
    python -m cygnusx.reference_genomes.indexer audit

全量构建先写 ``<db>.tmp`` 再 ``os.replace`` 原子替换；``--only`` 增量模式直接打开既有 db
更新对应表（db 不存在时报错提示先全量）。

解析器清单（每种 format 一个函数，全部纯 Python、流式读 gzip）：

- ``genomic_fasta``：解压 gz + build_fai
- ``gff3``：gene / mRNA / exon / CDS / UTR → genes + transcripts（feature_ranges JSON）
- ``tair_functional``：TAIR functional_descriptions TSV → genes.annotation
- ``kegg_gene``：ath_gene.list 4 列 → genes.gene_name
- ``gaf``：gene_association.tair.gz → go_annotations
- ``obo``：go-basic.obo → go_terms
- ``goslim``：ATH_GO_GOSLIM.txt.gz → goslim_annotations
- ``kegg_ko``：ath_ko.list → kegg_annotations + kegg_kos
- ``kegg_pathway``：ath_pathway.list → kegg_annotations
- ``kegg_pathway_name``：ath_pathway_name.list → kegg_pathways
- ``fasta_kv``：CDS/pep FASTA → fasta_records + transcripts.cds_id/pep_id
- ``canonical``：每基因选 cds_length 最大的转录本
- ``meta``：写 build_status / built_at / gene_count / transcript_count

设计文档：docs/26.8.4/常用物种基因数据库_实施方案.md §4.2 / §6
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import shutil
import sqlite3
import sys
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from cygnusx.reference_genomes.config import (
    ConfigManager,
    SpeciesConfig,
    VersionConfig,
    gene_index_path,
    resolve_file_path,
)
from cygnusx.reference_genomes.sequence import build_fai

__all__ = ["build_index", "audit_all"]

# ---------- 常量 ----------

# --only 分组 → 对应解析器列表
_STAGE_GROUPS: dict[str, list[str]] = {
    "fasta": ["genomic_fasta"],
    "gff3": ["gff3"],
    "functional": ["tair_functional"],
    "go": ["gaf", "obo", "goslim"],
    "kegg": ["kegg_ko", "kegg_pathway", "kegg_pathway_name", "kegg_gene"],
    "cds": ["fasta_kv"],
}

# 全量构建顺序
_FULL_ORDER = [
    "genomic_fasta",
    "gff3",
    "tair_functional",
    "kegg_gene",
    "gaf",
    "obo",
    "goslim",
    "kegg_ko",
    "kegg_pathway",
    "kegg_pathway_name",
    "fasta_kv",
    "canonical",
    "meta",
]

# 批量插入大小
_BATCH = 20_000


def _gene_rowid_map(conn: sqlite3.Connection) -> dict[str, int]:
    """Build gene_id → rowid map for efficient FTS5 UPDATE."""
    result: dict[str, int] = {}
    for rowid, gene_id in conn.execute("SELECT rowid, gene_id FROM genes"):
        result[gene_id] = rowid
    return result

# GAF 列索引（0-based）
_GAF_DB_OBJ_ID = 1
_GAF_DB_OBJ_SYMBOL = 2
_GAF_GO_ID = 4
_GAF_EVIDENCE = 6
_GAF_ASPECT = 8
_GAF_ASSIGNED_BY = 14

# namespace → aspect
_NS2ASPECT = {
    "biological_process": "P",
    "molecular_function": "F",
    "cellular_component": "C",
}


# ============================================================
# SQLite DDL
# ============================================================


_SCHEMA_SQL = """\
CREATE VIRTUAL TABLE IF NOT EXISTS genes USING fts5(
    gene_id, gene_name, chromosome,
    start UNINDEXED, end UNINDEXED, strand UNINDEXED, length UNINDEXED,
    annotation, exons UNINDEXED, gene_type UNINDEXED,
    tokenize = "unicode61 remove_diacritics 2"
);

CREATE TABLE IF NOT EXISTS transcripts(
    transcript_id TEXT PRIMARY KEY, gene_id TEXT NOT NULL,
    chrom TEXT, start INT, end INT, strand TEXT,
    exon_count INT DEFAULT 0, exon_ranges TEXT,
    feature_ranges TEXT,
    cds_id TEXT, pep_id TEXT, cds_length INT DEFAULT 0, pep_length INT DEFAULT 0,
    canonical INT DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_tr_gene ON transcripts(gene_id);

CREATE TABLE IF NOT EXISTS go_terms(
    go_id TEXT PRIMARY KEY, name TEXT, aspect TEXT, definition TEXT
);
CREATE TABLE IF NOT EXISTS go_annotations(
    gene_id TEXT NOT NULL, go_id TEXT NOT NULL, evidence TEXT, source TEXT,
    PRIMARY KEY(gene_id, go_id)
);
CREATE INDEX IF NOT EXISTS idx_go_term ON go_annotations(go_id);

CREATE TABLE IF NOT EXISTS goslim_annotations(
    gene_id TEXT NOT NULL, go_id TEXT NOT NULL, name TEXT,
    aspect TEXT, slim_category TEXT, evidence TEXT,
    PRIMARY KEY(gene_id, go_id)
);
CREATE INDEX IF NOT EXISTS idx_goslim_term ON goslim_annotations(go_id);

CREATE TABLE IF NOT EXISTS kegg_kos(
    ko_id TEXT PRIMARY KEY, name TEXT, definition TEXT
);
CREATE TABLE IF NOT EXISTS kegg_pathways(
    pathway_id TEXT PRIMARY KEY, name TEXT
);
CREATE TABLE IF NOT EXISTS kegg_annotations(
    gene_id TEXT NOT NULL, ko_id TEXT NOT NULL DEFAULT '',
    pathway_id TEXT NOT NULL DEFAULT '',
    PRIMARY KEY(gene_id, ko_id, pathway_id)
);
CREATE INDEX IF NOT EXISTS idx_kegg_ko ON kegg_annotations(ko_id);
CREATE INDEX IF NOT EXISTS idx_kegg_pw ON kegg_annotations(pathway_id);

CREATE TABLE IF NOT EXISTS id_mapping(
    source_id TEXT NOT NULL, target_id TEXT NOT NULL,
    target_genome TEXT NOT NULL,
    PRIMARY KEY(source_id, target_genome)
);
CREATE INDEX IF NOT EXISTS idx_map_target ON id_mapping(target_id);

CREATE TABLE IF NOT EXISTS fasta_records(
    kind TEXT NOT NULL, seq_id TEXT NOT NULL,
    byte_offset INT NOT NULL, seq_length INT NOT NULL,
    linebases INT NOT NULL, linewidth INT NOT NULL,
    PRIMARY KEY(kind, seq_id)
);

CREATE TABLE IF NOT EXISTS meta(
    key TEXT PRIMARY KEY, value TEXT
);
"""


def _create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(_SCHEMA_SQL)


# ============================================================
# 解析器
# ============================================================


def _parse_genomic_fasta(
    conn: sqlite3.Connection, version: VersionConfig, _log: Any
) -> None:
    """解压 gz FASTA（若需要）+ 生成 .fai。"""
    gz_path = resolve_file_path(version, "fasta")
    if gz_path is None:
        _log("  [skip] fasta 未声明")
        return
    if not gz_path.exists():
        _log(f"  [warn] fasta 文件不存在：{gz_path}")
        return

    # 解压
    if gz_path.suffix == ".gz":
        out_path = gz_path.with_suffix("")  # 去掉 .gz
        if out_path.exists() and out_path.stat().st_mtime >= gz_path.stat().st_mtime:
            _log(f"  [skip] 已解压且更新：{out_path.name}")
        else:
            _log(f"  解压 {gz_path.name} → {out_path.name}")
            with gzip.open(gz_path, "rb") as fin, open(out_path, "wb") as fout:
                shutil.copyfileobj(fin, fout, length=1 << 20)
    else:
        out_path = gz_path

    # build fai
    fai_path = out_path.with_name(out_path.name + ".fai")
    if fai_path.exists() and fai_path.stat().st_mtime >= out_path.stat().st_mtime:
        _log(f"  [skip] .fai 已存在且更新：{fai_path.name}")
    else:
        _log(f"  构建 .fai：{out_path.name}")
        build_fai(out_path)


def _parse_gff_attributes(attr_str: str) -> dict[str, str]:
    """正规解析 GFF3 第 9 列属性（按 ; 分割 → key=value，urllib.parse.unquote）。"""
    attrs: dict[str, str] = {}
    for pair in attr_str.split(";"):
        pair = pair.strip()
        if not pair or "=" not in pair:
            continue
        key, _, value = pair.partition("=")
        attrs[key.strip()] = unquote(value.strip())
    return attrs


def _map_gene_type(note: str) -> str:
    """由 Note 属性映射 gene_type。"""
    lower = note.lower()
    if "protein_coding" in lower:
        return "protein_coding"
    if "transposable_element" in lower:
        return "transposable_element"
    if "pseudogene" in lower:
        return "pseudogene"
    return "other"


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
    """增量构建在旧库上补列（幂等）。"""
    cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
        conn.commit()


def _open_text_auto(fpath: Path) -> Any:
    """按魔数嗅探压缩格式，返回文本流（gzip / zip 首成员 / 纯文本）。

    TAIR 部分 ``.gz`` 实为 ZIP 封装（如 ATH_GO_GOSLIM.txt.gz），仅看扩展名会踩坑。
    """
    with open(fpath, "rb") as fh:
        magic = fh.read(4)
    if magic[:2] == b"\x1f\x8b":
        return gzip.open(fpath, "rt", encoding="utf-8")
    if magic[:2] == b"PK":
        zf = zipfile.ZipFile(fpath)
        inner = zf.open(zf.namelist()[0], "r")
        return io.TextIOWrapper(inner, encoding="utf-8")
    return open(fpath, "rt", encoding="utf-8")


# GFF3 feature → feature_ranges JSON 键
_STRUCTURE_FEATURES = {
    "CDS": "cds",
    "five_prime_UTR": "five_prime_utr",
    "three_prime_UTR": "three_prime_utr",
}


def _parse_gff3(conn: sqlite3.Connection, version: VersionConfig, _log: Any) -> None:
    """解析 GFF3：gene / mRNA / exon / CDS / UTR → genes + transcripts。

    transcripts.feature_ranges 存 JSON：{"cds": [[s,e],...], "five_prime_utr": [...],
    "three_prime_utr": [...]}，供前端绘制 UTR/CDS 分段的基因模型图。
    """
    gff_path = resolve_file_path(version, "gff3")
    if gff_path is None or not gff_path.exists():
        _log(f"  [skip] gff3 文件不存在：{gff_path}")
        return

    _log(f"  解析 GFF3：{gff_path.name}")

    # 清空目标表
    conn.execute("DELETE FROM genes")
    conn.execute("DELETE FROM transcripts")
    _ensure_column(conn, "transcripts", "feature_ranges", "TEXT")

    # 两遍扫描：第一遍收集 mRNA 和 exon 信息，第二遍写库
    # 实际上一遍就够，用字典缓冲

    gene_rows: list[tuple] = []
    # transcript_id → {gene_id, chrom, start, end, strand}
    transcripts: dict[str, dict[str, Any]] = {}
    # transcript_id → list of (exon_start, exon_end)
    exon_map: dict[str, list[tuple[int, int]]] = {}
    # transcript_id → {feature_key: [(start, end), ...]}（cds / five_prime_utr / three_prime_utr）
    feature_map: dict[str, dict[str, list[tuple[int, int]]]] = {}

    with open(gff_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.startswith("#") or not line.strip():
                continue
            cols = line.rstrip("\n\r").split("\t")
            if len(cols) < 9:
                continue
            chrom, _source, feature, start_s, end_s, _score, strand, _phase, attr_str = (
                cols[:9]
            )
            start = int(start_s)
            end = int(end_s)
            attrs = _parse_gff_attributes(attr_str)

            if feature == "gene":
                gene_id = attrs.get("ID", "")
                gene_name = attrs.get("Name", gene_id)
                note = attrs.get("Note", "")
                gene_type = _map_gene_type(note)
                length = end - start + 1
                gene_rows.append(
                    (gene_id, gene_name, chrom, start, end, strand, length, "", 0, gene_type)
                )

            elif feature == "mRNA":
                tr_id = attrs.get("ID", "")
                parent = attrs.get("Parent", "")
                # Parent 可多值（逗号分隔），取第一个
                gene_id = parent.split(",")[0] if parent else ""
                transcripts[tr_id] = {
                    "gene_id": gene_id,
                    "chrom": chrom,
                    "start": start,
                    "end": end,
                    "strand": strand,
                }
                exon_map[tr_id] = []

            elif feature == "exon":
                parents_str = attrs.get("Parent", "")
                parents = [p.strip() for p in parents_str.split(",") if p.strip()]
                for p in parents:
                    if p in exon_map:
                        exon_map[p].append((start, end))

            elif feature in _STRUCTURE_FEATURES:
                key = _STRUCTURE_FEATURES[feature]
                parents_str = attrs.get("Parent", "")
                parents = [p.strip() for p in parents_str.split(",") if p.strip()]
                for p in parents:
                    if p in exon_map:
                        feature_map.setdefault(p, {}).setdefault(key, []).append((start, end))

    # 构建 transcript rows
    tr_rows: list[tuple] = []
    for tr_id, info in transcripts.items():
        exons = exon_map.get(tr_id, [])
        exons_sorted = sorted(exons, key=lambda e: e[0])
        exon_count = len(exons_sorted)
        exon_ranges = json.dumps(exons_sorted) if exons_sorted else "[]"
        features = feature_map.get(tr_id, {})
        feature_ranges = (
            json.dumps({k: sorted(v) for k, v in features.items()}) if features else ""
        )
        tr_rows.append(
            (
                tr_id,
                info["gene_id"],
                info["chrom"],
                info["start"],
                info["end"],
                info["strand"],
                exon_count,
                exon_ranges,
                feature_ranges,
                None,  # cds_id
                None,  # pep_id
                0,     # cds_length
                0,     # pep_length
                0,     # canonical
            )
        )

    # 更新 gene 的 exons 列：取所有子 mRNA 中 exon 最多的那个
    # 先从 gene_rows 建 dict
    gene_dict: dict[str, list] = {}
    for row in gene_rows:
        gene_dict[row[0]] = list(row)

    for tr_id, info in transcripts.items():
        gid = info["gene_id"]
        if gid in gene_dict:
            ec = len(exon_map.get(tr_id, []))
            if ec > gene_dict[gid][8]:
                gene_dict[gid][8] = ec

    gene_rows = [tuple(v) for v in gene_dict.values()]

    _log(f"  genes: {len(gene_rows)}, transcripts: {len(tr_rows)}")

    conn.executemany(
        "INSERT INTO genes VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", gene_rows
    )
    conn.executemany(
        "INSERT INTO transcripts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        tr_rows,
    )
    conn.commit()


def _parse_tair_functional(
    conn: sqlite3.Connection, version: VersionConfig, _log: Any
) -> None:
    """TAIR functional_descriptions TSV → UPDATE genes SET annotation。

    TSV 有表头：Model_name / Type / Short_description / Curator_summary / Computational_description
    gene_id = Model_name 去掉 .N 后缀。
    每基因选注释：优先非空 Curator_summary，其次非空 Short_description。
    """
    fpath = resolve_file_path(version, "functional")
    if fpath is None or not fpath.exists():
        _log(f"  [skip] tair_functional 文件不存在：{fpath}")
        return

    _log(f"  解析 functional descriptions：{fpath.name}")

    # gene_id → best annotation
    annotations: dict[str, str] = {}

    with open(fpath, "r", encoding="utf-8") as f:
        header = f.readline()  # skip header
        for line in f:
            line = line.rstrip("\n\r")
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) < 5:
                continue
            model_name = cols[0]
            # _type = cols[1]
            short_desc = cols[2].strip()
            curator = cols[3].strip()
            # _comp = cols[4]

            # gene_id = 去掉 .N 后缀
            gene_id = re.sub(r"\.\d+$", "", model_name)

            # 选注释：优先 Curator_summary
            best = curator if curator else short_desc
            if not best:
                continue

            if gene_id not in annotations:
                annotations[gene_id] = best
            # 同基因多个模型时，如果当前没 curator 但新的有，升级
            elif curator and not annotations[gene_id]:
                annotations[gene_id] = best

    # UPDATE genes SET annotation=? WHERE rowid=?
    rowid_map = _gene_rowid_map(conn)
    updates = [
        (ann, rowid_map[gid])
        for gid, ann in annotations.items()
        if gid in rowid_map
    ]
    _log(f"  annotations: {len(updates)}")

    batch_size = 5000
    for i in range(0, len(updates), batch_size):
        batch = updates[i : i + batch_size]
        conn.executemany(
            "UPDATE genes SET annotation = ? WHERE rowid = ?",
            batch,
        )
    conn.commit()


def _parse_kegg_gene(
    conn: sqlite3.Connection, version: VersionConfig, _log: Any
) -> None:
    """ath_gene.list 4 列 TSV → UPDATE genes SET gene_name。

    kegg_gene_id / feature_type / location / description
    剥离 ath: 前缀得 gene_id；description 第一个分号前为 symbol。
    """
    fpath = resolve_file_path(version, "kegg_gene")
    if fpath is None or not fpath.exists():
        _log(f"  [skip] kegg_gene 文件不存在：{fpath}")
        return

    _log(f"  解析 kegg_gene：{fpath.name}")

    updates: list[tuple[str, str]] = []  # (symbol, gene_id)

    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) < 4:
                continue
            kegg_id = cols[0]  # ath:AT1G01010
            description = cols[3]  # NAC001; NAC domain containing protein 1

            gene_id = re.sub(r"^ath:", "", kegg_id)
            # symbol = description 第一个分号前
            symbol = description.split(";")[0].strip()
            if symbol:
                updates.append((symbol, gene_id))

    _log(f"  kegg symbols: {len(updates)}")

    rowid_map = _gene_rowid_map(conn)
    rowid_updates = [
        (symbol, rowid_map[gid])
        for symbol, gid in updates
        if gid in rowid_map
    ]
    conn.executemany(
        "UPDATE genes SET gene_name = ? WHERE rowid = ?",
        rowid_updates,
    )
    conn.commit()


def _parse_gaf(conn: sqlite3.Connection, version: VersionConfig, _log: Any) -> None:
    """gene_association.tair.gz（gzip GAF 2.2）→ go_annotations。

    '!' 开头为注释行。
    第 2 列 db_object_id → gene_id
    第 5 列 go_id
    第 7 列 evidence
    第 9 列 aspect
    第 15 列 assigned_by → source
    第 3 列 db_object_symbol → 补充 gene_name（仅当 genes.gene_name == gene_id 时）
    """
    fpath = resolve_file_path(version, "go")
    if fpath is None or not fpath.exists():
        _log(f"  [skip] gaf 文件不存在：{fpath}")
        return

    _log(f"  解析 GAF：{fpath.name}")

    conn.execute("DELETE FROM go_annotations")

    go_rows: list[tuple[str, str, str, str]] = []  # gene_id, go_id, evidence, source
    # symbol candidates: gene_id → first non-trivial symbol
    symbol_candidates: dict[str, str] = {}

    count = 0
    with _open_text_auto(fpath) as f:
        for line in f:
            if line.startswith("!") or not line.strip():
                continue
            cols = line.rstrip("\n\r").split("\t")
            if len(cols) < 16:
                continue

            gene_id = cols[_GAF_DB_OBJ_ID]
            symbol = cols[_GAF_DB_OBJ_SYMBOL]
            go_id = cols[_GAF_GO_ID]
            evidence = cols[_GAF_EVIDENCE]
            # _aspect = cols[_GAF_ASPECT]
            source = cols[_GAF_ASSIGNED_BY] if len(cols) > _GAF_ASSIGNED_BY else ""

            go_rows.append((gene_id, go_id, evidence, source))

            # symbol 补充：仅当 symbol 非空且不等于 gene_id 时，取首次出现的
            if symbol and symbol != gene_id and gene_id not in symbol_candidates:
                symbol_candidates[gene_id] = symbol

            count += 1
            if count % _BATCH == 0:
                conn.executemany(
                    "INSERT OR IGNORE INTO go_annotations VALUES (?, ?, ?, ?)",
                    go_rows,
                )
                go_rows.clear()

    if go_rows:
        conn.executemany(
            "INSERT OR IGNORE INTO go_annotations VALUES (?, ?, ?, ?)",
            go_rows,
        )

    _log(f"  go_annotations: {count}")

    # symbol 补充：kegg_gene 先跑过（kegg symbol 优先），这里只补还没有 symbol 的
    # 先查出哪些 gene 还需要 symbol（gene_name == gene_id）
    if symbol_candidates:
        rowid_map = _gene_rowid_map(conn)
        updates: list[tuple[str, int]] = []
        for gid, symbol in symbol_candidates.items():
            rid = rowid_map.get(gid)
            if rid is None:
                continue
            # Check current gene_name
            row = conn.execute(
                "SELECT gene_name FROM genes WHERE rowid = ?", (rid,)
            ).fetchone()
            if row and row[0] == gid:
                updates.append((symbol, rid))

        if updates:
            conn.executemany(
                "UPDATE genes SET gene_name = ? WHERE rowid = ?",
                updates,
            )
            _log(f"  symbol supplements: {len(updates)}")

    conn.commit()


def _parse_obo(conn: sqlite3.Connection, version: VersionConfig, _log: Any) -> None:
    """go-basic.obo → go_terms。

    解析 [Term] 段：id / name / namespace / def（引号内文本）/ is_obsolete。
    namespace → aspect：biological_process → P，molecular_function → F，cellular_component → C。
    跳过 is_obsolete: true 的 term。
    """
    fpath = resolve_file_path(version, "go_obo")
    if fpath is None or not fpath.exists():
        _log(f"  [skip] obo 文件不存在：{fpath}")
        return

    _log(f"  解析 OBO：{fpath.name}")

    conn.execute("DELETE FROM go_terms")

    rows: list[tuple[str, str, str, str]] = []  # go_id, name, aspect, definition
    count = 0

    with open(fpath, "r", encoding="utf-8") as f:
        in_term = False
        term_id = ""
        term_name = ""
        term_ns = ""
        term_def = ""
        term_obsolete = False

        for line in f:
            line = line.rstrip("\n\r")

            if line == "[Term]":
                # flush previous term
                if in_term and term_id and not term_obsolete:
                    aspect = _NS2ASPECT.get(term_ns, "")
                    if aspect:
                        rows.append((term_id, term_name, aspect, term_def))
                        count += 1
                        if count % _BATCH == 0:
                            conn.executemany(
                                "INSERT OR IGNORE INTO go_terms VALUES (?, ?, ?, ?)",
                                rows,
                            )
                            rows.clear()
                in_term = True
                term_id = ""
                term_name = ""
                term_ns = ""
                term_def = ""
                term_obsolete = False
                continue

            if line.startswith("["):
                # 新 section 开始（如 [Typedef]），flush
                if in_term and term_id and not term_obsolete:
                    aspect = _NS2ASPECT.get(term_ns, "")
                    if aspect:
                        rows.append((term_id, term_name, aspect, term_def))
                        count += 1
                in_term = line == "[Term]"
                if in_term:
                    term_id = ""
                    term_name = ""
                    term_ns = ""
                    term_def = ""
                    term_obsolete = False
                continue

            if not in_term:
                continue

            if line.startswith("id: "):
                term_id = line[4:].strip()
            elif line.startswith("name: "):
                term_name = line[6:].strip()
            elif line.startswith("namespace: "):
                term_ns = line[11:].strip()
            elif line.startswith("def: "):
                # 引号内文本
                m = re.match(r'def:\s*"([^"]*)"', line)
                if m:
                    term_def = m.group(1)
            elif line.startswith("is_obsolete: true"):
                term_obsolete = True

        # flush last term
        if in_term and term_id and not term_obsolete:
            aspect = _NS2ASPECT.get(term_ns, "")
            if aspect:
                rows.append((term_id, term_name, aspect, term_def))
                count += 1

    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO go_terms VALUES (?, ?, ?, ?)",
            rows,
        )

    _log(f"  go_terms: {count}")
    conn.commit()


def _parse_goslim(conn: sqlite3.Connection, version: VersionConfig, _log: Any) -> None:
    """ATH_GO_GOSLIM.txt.gz（TAIR GOSLIM GAF 变体，18 列 TSV，可 gzip）→ goslim_annotations。

    列位（0-based）：
    第 1 列 gene_id（AT1G01010）
    第 5 列 slim term 名（regulation of DNA-templated transcription）
    第 6 列 slim GO ID（GO:0006355）
    第 8 列 aspect（P/F/C）
    第 9 列 slim 大类（other cellular processes）
    第 10 列 evidence（IBA/...）
    '!' 开头为注释行。
    """
    fpath = resolve_file_path(version, "goslim")
    if fpath is None or not fpath.exists():
        _log(f"  [skip] goslim 文件不存在：{fpath}")
        return

    _log(f"  解析 GOSLIM：{fpath.name}")

    conn.execute("""\
        CREATE TABLE IF NOT EXISTS goslim_annotations(
            gene_id TEXT NOT NULL, go_id TEXT NOT NULL, name TEXT,
            aspect TEXT, slim_category TEXT, evidence TEXT,
            PRIMARY KEY(gene_id, go_id)
        )""")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_goslim_term ON goslim_annotations(go_id)"
    )
    conn.execute("DELETE FROM goslim_annotations")

    rows: list[tuple[str, str, str, str, str, str]] = []
    count = 0
    with _open_text_auto(fpath) as f:
        for line in f:
            if line.startswith("!") or not line.strip():
                continue
            cols = line.rstrip("\n\r").split("\t")
            if len(cols) < 10:
                continue
            gene_id = cols[0].strip()
            go_id = cols[5].strip()
            if not gene_id or not go_id:
                continue
            rows.append(
                (gene_id, go_id, cols[4].strip(), cols[7].strip(),
                 cols[8].strip(), cols[9].strip())
            )
            count += 1
            if len(rows) >= _BATCH:
                conn.executemany(
                    "INSERT OR IGNORE INTO goslim_annotations VALUES (?, ?, ?, ?, ?, ?)",
                    rows,
                )
                rows.clear()

    if rows:
        conn.executemany(
            "INSERT OR IGNORE INTO goslim_annotations VALUES (?, ?, ?, ?, ?, ?)",
            rows,
        )

    _log(f"  goslim_annotations: {count}")
    conn.commit()


def _parse_kegg_ko(
    conn: sqlite3.Connection, version: VersionConfig, _log: Any
) -> None:
    """ath_ko.list 两列（ath:AT1G01010\\tko:K28554）→ kegg_annotations + kegg_kos。"""
    fpath = resolve_file_path(version, "kegg_ko")
    if fpath is None or not fpath.exists():
        _log(f"  [skip] kegg_ko 文件不存在：{fpath}")
        return

    _log(f"  解析 kegg_ko：{fpath.name}")

    ann_rows: list[tuple[str, str, str]] = []
    ko_set: set[str] = set()

    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            gene_id = re.sub(r"^ath:", "", cols[0])
            ko_id = re.sub(r"^ko:", "", cols[1])
            ann_rows.append((gene_id, ko_id, ""))
            ko_set.add(ko_id)

    conn.executemany(
        "INSERT OR IGNORE INTO kegg_annotations VALUES (?, ?, ?)",
        ann_rows,
    )

    ko_rows = [(k, "", "") for k in ko_set]
    conn.executemany(
        "INSERT OR IGNORE INTO kegg_kos VALUES (?, ?, ?)",
        ko_rows,
    )

    _log(f"  kegg_annotations (ko): {len(ann_rows)}, kegg_kos: {len(ko_rows)}")
    conn.commit()


def _parse_kegg_pathway(
    conn: sqlite3.Connection, version: VersionConfig, _log: Any
) -> None:
    """ath_pathway.list 两列（ath:...\\tpath:ath00010）→ kegg_annotations。"""
    fpath = resolve_file_path(version, "kegg_pathway")
    if fpath is None or not fpath.exists():
        _log(f"  [skip] kegg_pathway 文件不存在：{fpath}")
        return

    _log(f"  解析 kegg_pathway：{fpath.name}")

    rows: list[tuple[str, str, str]] = []

    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            gene_id = re.sub(r"^ath:", "", cols[0])
            pathway_id = re.sub(r"^path:", "", cols[1])
            rows.append((gene_id, "", pathway_id))

    conn.executemany(
        "INSERT OR IGNORE INTO kegg_annotations VALUES (?, ?, ?)",
        rows,
    )

    _log(f"  kegg_annotations (pathway): {len(rows)}")
    conn.commit()


def _parse_kegg_pathway_name(
    conn: sqlite3.Connection, version: VersionConfig, _log: Any
) -> None:
    """ath_pathway_name.list 两列 → kegg_pathways。名称去掉尾部 ' - Arabidopsis thaliana (thale cress)'。"""
    fpath = resolve_file_path(version, "kegg_pathway_name")
    if fpath is None or not fpath.exists():
        _log(f"  [skip] kegg_pathway_name 文件不存在：{fpath}")
        return

    _log(f"  解析 kegg_pathway_name：{fpath.name}")

    rows: list[tuple[str, str]] = []

    with open(fpath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) < 2:
                continue
            pathway_id = cols[0]
            name = re.sub(
                r"\s*-\s*Arabidopsis thaliana\s*\(thale cress\)\s*$", "", cols[1]
            )
            rows.append((pathway_id, name))

    conn.executemany(
        "INSERT OR REPLACE INTO kegg_pathways VALUES (?, ?)",
        rows,
    )

    _log(f"  kegg_pathways: {len(rows)}")
    conn.commit()


def _parse_fasta_kv(
    conn: sqlite3.Connection, version: VersionConfig, _log: Any
) -> None:
    """CDS / pep FASTA → fasta_records + UPDATE transcripts。

    rb 流式读，每条记录：seq_id = header 第一个 token（如 AT1G51370.2）；
    记录该序列第一条序列行的字节偏移 byte_offset、序列总长 seq_length、
    linebases（第一条序列行字符数）、linewidth（该行含换行字节数）。
    """
    # CDS
    cds_path = resolve_file_path(version, "cds")
    if cds_path and cds_path.exists():
        _scan_fasta_kv(conn, cds_path, "cds", _log)
    else:
        _log(f"  [skip] cds 文件不存在：{cds_path}")

    # pep (protein)
    pep_path = resolve_file_path(version, "protein")
    if pep_path and pep_path.exists():
        _scan_fasta_kv(conn, pep_path, "pep", _log)
    else:
        _log(f"  [skip] protein 文件不存在：{pep_path}")


def _scan_fasta_kv(
    conn: sqlite3.Connection, fasta_path: Path, kind: str, _log: Any
) -> None:
    """扫描单个 FASTA 文件，写 fasta_records + UPDATE transcripts。"""
    _log(f"  扫描 FASTA ({kind})：{fasta_path.name}")

    records: list[tuple[str, str, int, int, int, int]] = []
    tr_updates: list[tuple[str, int, str]] = []  # (cds_id/pep_id, length, transcript_id)

    name: str | None = None
    seq_length = 0
    byte_offset = 0
    linebases = 0
    linewidth = 0
    have_first_line = False
    pos = 0

    update_col = "cds_id" if kind == "cds" else "pep_id"
    length_col = "cds_length" if kind == "cds" else "pep_length"

    with open(fasta_path, "rb") as f:
        for raw in f:
            stripped = raw.strip()
            if raw.startswith(b">"):
                # flush previous
                if name is not None:
                    records.append(
                        (kind, name, byte_offset, seq_length, linebases, linewidth)
                    )
                    tr_updates.append(
                        (name, seq_length, name)
                    )
                # new record
                header = stripped[1:].decode("utf-8", "replace")
                name = header.split(" ", 1)[0].split("\t", 1)[0]
                seq_length = 0
                have_first_line = False
            elif stripped and name is not None:
                slen = len(stripped)
                if not have_first_line:
                    byte_offset = pos
                    linebases = slen
                    linewidth = len(raw)
                    have_first_line = True
                seq_length += slen
            pos += len(raw)

        # flush last
        if name is not None:
            records.append(
                (kind, name, byte_offset, seq_length, linebases, linewidth)
            )
            tr_updates.append(
                (name, seq_length, name)
            )

    # Write fasta_records
    batch_size = 5000
    for i in range(0, len(records), batch_size):
        conn.executemany(
            "INSERT OR REPLACE INTO fasta_records VALUES (?, ?, ?, ?, ?, ?)",
            records[i : i + batch_size],
        )

    # Update transcripts in bulk using executemany
    for i in range(0, len(tr_updates), batch_size):
        batch = tr_updates[i : i + batch_size]
        conn.executemany(
            f"UPDATE transcripts SET {update_col} = ?, {length_col} = ? "
            f"WHERE transcript_id = ?",
            batch,
        )

    _log(f"  {kind} records: {len(records)}")
    conn.commit()


def _mark_canonical(
    conn: sqlite3.Connection, _version: VersionConfig, _log: Any
) -> None:
    """每个基因选 cds_length 最大的转录本 canonical=1（平手取 transcript_id 字典序最小）。"""
    _log("  标记 canonical 转录本")

    conn.execute("UPDATE transcripts SET canonical = 0")

    # 用窗口函数选出每基因的最优转录本
    conn.execute("""\
        UPDATE transcripts SET canonical = 1
        WHERE rowid IN (
            SELECT rowid FROM (
                SELECT rowid,
                       ROW_NUMBER() OVER (
                           PARTITION BY gene_id
                           ORDER BY cds_length DESC, transcript_id ASC
                       ) AS rn
                FROM transcripts
            ) WHERE rn = 1
        )
    """)

    count = conn.execute(
        "SELECT COUNT(*) FROM transcripts WHERE canonical = 1"
    ).fetchone()[0]
    _log(f"  canonical: {count}")
    conn.commit()


def _write_meta(
    conn: sqlite3.Connection, _version: VersionConfig, _log: Any
) -> None:
    """写 meta 表：build_status / built_at / gene_count / transcript_count。"""
    gene_count = conn.execute("SELECT COUNT(*) FROM genes").fetchone()[0]
    transcript_count = conn.execute(
        "SELECT COUNT(*) FROM transcripts"
    ).fetchone()[0]

    now = datetime.now(timezone.utc).isoformat()

    meta_rows = [
        ("build_status", "ready"),
        ("built_at", now),
        ("gene_count", str(gene_count)),
        ("transcript_count", str(transcript_count)),
    ]
    conn.executemany("INSERT OR REPLACE INTO meta VALUES (?, ?)", meta_rows)
    conn.commit()

    _log(f"  meta: gene_count={gene_count}, transcript_count={transcript_count}")


# ============================================================
# 解析器调度
# ============================================================

_PARSERS: dict[str, Any] = {
    "genomic_fasta": _parse_genomic_fasta,
    "gff3": _parse_gff3,
    "tair_functional": _parse_tair_functional,
    "kegg_gene": _parse_kegg_gene,
    "gaf": _parse_gaf,
    "obo": _parse_obo,
    "goslim": _parse_goslim,
    "kegg_ko": _parse_kegg_ko,
    "kegg_pathway": _parse_kegg_pathway,
    "kegg_pathway_name": _parse_kegg_pathway_name,
    "fasta_kv": _parse_fasta_kv,
    "canonical": _mark_canonical,
    "meta": _write_meta,
}


def _resolve_stages(only: list[str] | None) -> list[str]:
    """根据 --only 参数解析要执行的阶段列表。"""
    if not only:
        return list(_FULL_ORDER)

    stages: list[str] = []
    for group in only:
        group = group.strip().lower()
        if group in _STAGE_GROUPS:
            stages.extend(_STAGE_GROUPS[group])
        elif group in _PARSERS:
            stages.append(group)
        else:
            print(f"[error] 未知阶段/分组：{group}", file=sys.stderr)
            print(f"  可用分组：{', '.join(sorted(_STAGE_GROUPS))}", file=sys.stderr)
            print(f"  可用阶段：{', '.join(sorted(_PARSERS))}", file=sys.stderr)
            sys.exit(1)
    # 去重，保持顺序
    seen: set[str] = set()
    result: list[str] = []
    for s in stages:
        if s not in seen:
            seen.add(s)
            result.append(s)
    return result


# ============================================================
# 构建入口
# ============================================================


def build_index(
    version_id: str,
    only: list[str] | None = None,
    config_path: str | None = None,
) -> Path:
    """构建指定版本的 gene_index.db。

    Args:
        version_id: 版本 ID（如 tair10）
        only: 仅执行的阶段/分组列表；None 表示全量
        config_path: 配置文件路径覆盖（测试用）

    Returns:
        gene_index.db 的绝对路径
    """
    mgr = ConfigManager(config_path)
    result = mgr.get_version(version_id)
    if result is None:
        raise ValueError(f"版本 {version_id!r} 未在配置中注册")

    species, version = result
    db_path = gene_index_path(version)
    if db_path is None:
        raise ValueError(f"版本 {version_id!r} 的 gene_index 路径无法解析")

    stages = _resolve_stages(only)
    is_full = only is None

    def log(msg: str) -> None:
        print(msg, flush=True)

    log(f"[build] version={version_id}, stages={stages}")

    if is_full:
        # 全量：写临时文件再原子替换
        tmp_path = db_path.with_suffix(db_path.suffix + ".tmp")
        if tmp_path.exists():
            tmp_path.unlink()
        if db_path.exists():
            db_path.unlink()

        conn = sqlite3.connect(str(tmp_path))
        conn.execute("PRAGMA journal_mode=OFF")
        conn.execute("PRAGMA synchronous=OFF")
        conn.execute("PRAGMA temp_store=MEMORY")
        conn.execute("PRAGMA cache_size=-200000")  # 200MB

        _create_schema(conn)

        for stage in stages:
            parser = _PARSERS[stage]
            t1 = time.time()
            log(f"  [{stage}]")
            parser(conn, version, log)
            log(f"  [{stage}] done in {time.time()-t1:.1f}s")

        conn.close()
        os.replace(tmp_path, db_path)
        log(f"[done] {db_path}")

    else:
        # 增量：直接打开既有 db
        if not db_path.exists():
            raise FileNotFoundError(
                f"增量构建需要既有 db：{db_path}\n请先执行全量构建：\n"
                f"  python -m cygnusx.reference_genomes.indexer build --version {version_id}"
            )

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")

        for stage in stages:
            parser = _PARSERS[stage]
            log(f"  [{stage}]")
            parser(conn, version, log)

        conn.close()
        log(f"[done] {db_path}")

    return db_path


# ============================================================
# 审计
# ============================================================


def audit_all(config_path: str | None = None) -> None:
    """打印全物种文件审计结果。"""
    mgr = ConfigManager(config_path)
    cfg = mgr.get_config()

    for sp in cfg.species:
        print(f"\n{'='*60}")
        print(f"物种：{sp.common_name} ({sp.latin_name}) [{sp.id}]")
        for ver in sp.versions:
            print(f"\n  版本：{ver.id} ({ver.version_name})")
            print(f"  data_dir: {ver.data_dir}")

            # gene_index.db
            gi = gene_index_path(ver)
            if gi and gi.exists():
                try:
                    conn = sqlite3.connect(f"file:{gi}?mode=ro", uri=True)
                    status = conn.execute(
                        "SELECT value FROM meta WHERE key='build_status'"
                    ).fetchone()
                    built = conn.execute(
                        "SELECT value FROM meta WHERE key='built_at'"
                    ).fetchone()
                    gc = conn.execute(
                        "SELECT value FROM meta WHERE key='gene_count'"
                    ).fetchone()
                    conn.close()
                    print(
                        f"  gene_index.db: {status[0] if status else '?'} "
                        f"(built: {built[0] if built else '?'}, "
                        f"genes: {gc[0] if gc else '?'})"
                    )
                except Exception as e:
                    print(f"  gene_index.db: error ({e})")
            else:
                print("  gene_index.db: missing")

            # files
            for key, entry in ver.files.items():
                fp = resolve_file_path(ver, key)
                if fp and fp.exists():
                    size = fp.stat().st_size
                    size_h = _human_size(size)
                    print(f"    {key:20s} ✓ {fp.name} ({size_h})")
                else:
                    print(f"    {key:20s} ✗ {entry.path}")


def _human_size(nbytes: int) -> str:
    for unit in ["b", "Kb", "Mb", "Gb", "Tb"]:
        if nbytes < 1024:
            return f"{nbytes:.1f} {unit}"
        nbytes /= 1024
    return f"{nbytes:.1f} Pb"


# ============================================================
# CLI
# ============================================================


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="python -m cygnusx.reference_genomes.indexer",
        description="参考基因组离线构建管线",
    )
    sub = parser.add_subparsers(dest="command")

    # build
    build_p = sub.add_parser("build", help="构建 gene_index.db")
    build_p.add_argument("--version", required=True, help="版本 ID（如 tair10）")
    build_p.add_argument(
        "--only",
        nargs="+",
        help="仅执行指定阶段/分组（fasta/gff3/functional/go/kegg/cds）",
    )
    build_p.add_argument("--config", help="配置文件路径覆盖")

    # audit
    audit_p = sub.add_parser("audit", help="全物种文件审计")
    audit_p.add_argument("--config", help="配置文件路径覆盖")

    args = parser.parse_args()

    if args.command == "build":
        t0 = time.time()
        db = build_index(args.version, args.only, args.config)
        elapsed = time.time() - t0
        print(f"\n构建完成：{db}（{elapsed:.1f}s）")
    elif args.command == "audit":
        audit_all(args.config)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()

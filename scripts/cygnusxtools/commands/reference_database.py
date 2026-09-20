"""Build CygnusX reference database assets offline.

This script is intentionally independent from the web platform. It turns raw
FASTA/GFF/GO/KO/KEGG files into a local SQLite database plus a FASTA .fai index
and registration snippets. The CygnusX service should only read the generated
files; it should not run this conversion in request/worker paths.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from cygnusxtools.utils.argparse import CygnusXHelpFormatter

SCHEMA_VERSION = "1.0"
TRANSCRIPT_TYPES = {
    "mrna",
    "transcript",
    "ncrna",
    "lncrna",
    "mirna",
    "rrna",
    "trna",
    "snrna",
    "snorna",
    "primary_transcript",
}
GENE_ID_FIELDS = ("gene_id", "gene", "geneid", "gene_name", "locus_tag", "id", "query")
GO_ID_FIELDS = ("go_id", "go", "go_term", "term_id")
GO_TERM_FIELDS = ("term", "name", "go_term", "go_name")
GO_DEFINITION_FIELDS = ("definition", "def", "go_definition")
KO_ID_FIELDS = ("ko_id", "ko", "kegg_orthology", "orthology")
KEGG_ID_FIELDS = ("kegg_id", "kegg", "kegg_entry", "entry")
PATHWAY_ID_FIELDS = ("pathway_id", "pathway", "map_id", "kegg_pathway", "path")
KNOWN_HEADER_FIELDS = {
    *GENE_ID_FIELDS,
    *GO_ID_FIELDS,
    *GO_TERM_FIELDS,
    *GO_DEFINITION_FIELDS,
    *KO_ID_FIELDS,
    *KEGG_ID_FIELDS,
    *PATHWAY_ID_FIELDS,
    "namespace",
    "ontology",
    "aspect",
    "evidence",
    "evidence_code",
    "source",
    "description",
    "pathway_name",
    "category",
    "ec_number",
    "ec",
}


class BuildError(RuntimeError):
    """Raised for user-facing build failures."""


def normalize_key(value: str) -> str:
    return value.strip().lower().replace("-", "_").replace(" ", "_")


def as_abs(path: str | Path | None) -> str | None:
    if path is None:
        return None
    return str(Path(path).expanduser().resolve())


def open_text(path: Path):  # type: ignore[no-untyped-def]
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return path.open("r", encoding="utf-8", errors="replace")


def split_delimited_line(line: str, delimiter: str | None = None) -> list[str]:
    line = line.rstrip("\n\r")
    if delimiter is None:
        delimiter = "\t" if "\t" in line else "," if "," in line else None
    if delimiter is None:
        return line.split()
    return next(csv.reader([line], delimiter=delimiter))


def detect_header(parts: list[str]) -> bool:
    normalized = [normalize_key(part) for part in parts]
    return any(part in KNOWN_HEADER_FIELDS for part in normalized)


def iter_table(path: Path):  # type: ignore[no-untyped-def]
    """Yield flexible TSV/CSV rows as normalized dicts.

    Headerless files are exposed as _0, _1, ... so loaders can use positional
    fallbacks. Lines beginning with # are ignored.
    """
    delimiter: str | None = None
    header: list[str] | None = None
    first_data_seen = False
    with open_text(path) as handle:
        for raw_line in handle:
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            if delimiter is None:
                delimiter = "\t" if "\t" in raw_line else "," if "," in raw_line else None
            parts = [part.strip() for part in split_delimited_line(raw_line, delimiter)]
            if not first_data_seen:
                first_data_seen = True
                if detect_header(parts):
                    header = [normalize_key(part) for part in parts]
                    continue
            if header is not None:
                row = {header[i]: parts[i] if i < len(parts) else "" for i in range(len(header))}
            else:
                row = {f"_{i}": part for i, part in enumerate(parts)}
            yield row


def pick(row: dict[str, str], names: tuple[str, ...], index: int | None = None) -> str:
    for name in names:
        value = row.get(name)
        if value:
            return value.strip()
    if index is not None:
        return row.get(f"_{index}", "").strip()
    return ""


def split_identifier_values(value: str) -> list[str]:
    """Split compact annotation cells such as GO:1;GO:2 or K1,K2."""
    if not value:
        return []
    seen: set[str] = set()
    values: list[str] = []
    for item in re.split(r"[;,|]", value):
        item = item.strip()
        if not item or item in {"-", "."}:
            continue
        if item not in seen:
            seen.add(item)
            values.append(item)
    return values


def normalize_go_namespace(value: str) -> str:
    normalized = value.strip()
    key = normalized.lower().replace(" ", "_")
    return {
        "biological_process": "BP",
        "molecular_function": "MF",
        "cellular_component": "CC",
        "bp": "BP",
        "mf": "MF",
        "cc": "CC",
        "p": "BP",
        "f": "MF",
        "c": "CC",
    }.get(key, normalized)


def normalize_kegg_value(value: str) -> str:
    normalized = value.strip()
    for prefix in ("ko:", "path:", "pathway:"):
        if normalized.lower().startswith(prefix):
            return normalized[len(prefix):]
    return normalized


def parse_attributes(raw: str) -> dict[str, str]:
    raw = raw.strip()
    if not raw or raw == ".":
        return {}

    attrs: dict[str, str] = {}
    # GFF3: ID=gene1;Parent=mrna1;Name=ABC
    if "=" in raw:
        for item in raw.split(";"):
            item = item.strip()
            if not item or "=" not in item:
                continue
            key, value = item.split("=", 1)
            attrs[key.strip()] = unquote(value.strip())
        return attrs

    # GTF: gene_id "gene1"; transcript_id "tx1";
    for item in raw.split(";"):
        item = item.strip()
        if not item:
            continue
        if " " not in item:
            attrs[item] = ""
            continue
        key, value = item.split(" ", 1)
        attrs[key.strip()] = value.strip().strip('"')
    return attrs


def attr_first(attrs: dict[str, str], names: tuple[str, ...]) -> str:
    for name in names:
        value = attrs.get(name)
        if value:
            return value
    return ""


def create_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        PRAGMA foreign_keys = OFF;

        CREATE TABLE metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE input_files (
            kind TEXT PRIMARY KEY,
            path TEXT NOT NULL,
            size_bytes INTEGER,
            mtime REAL
        );

        CREATE TABLE fasta_sequences (
            name TEXT PRIMARY KEY,
            length INTEGER NOT NULL,
            offset INTEGER NOT NULL,
            line_bases INTEGER NOT NULL,
            line_width INTEGER NOT NULL
        );

        CREATE TABLE features (
            id TEXT PRIMARY KEY,
            seqid TEXT NOT NULL,
            source TEXT,
            featuretype TEXT NOT NULL,
            start INTEGER NOT NULL,
            end INTEGER NOT NULL,
            score TEXT,
            strand TEXT,
            phase TEXT,
            name TEXT,
            gene_id TEXT,
            transcript_id TEXT,
            parent_ids TEXT,
            attributes_json TEXT NOT NULL
        );

        CREATE TABLE relations (
            parent TEXT NOT NULL,
            child TEXT NOT NULL,
            relation_type TEXT NOT NULL DEFAULT 'parent_child',
            PRIMARY KEY (parent, child, relation_type)
        );

        CREATE TABLE genes (
            gene_id TEXT PRIMARY KEY,
            symbol TEXT,
            name TEXT,
            seqid TEXT NOT NULL,
            start INTEGER NOT NULL,
            end INTEGER NOT NULL,
            strand TEXT,
            biotype TEXT,
            description TEXT,
            attributes_json TEXT NOT NULL
        );

        CREATE TABLE transcripts (
            transcript_id TEXT PRIMARY KEY,
            gene_id TEXT,
            seqid TEXT NOT NULL,
            start INTEGER NOT NULL,
            end INTEGER NOT NULL,
            strand TEXT,
            biotype TEXT,
            attributes_json TEXT NOT NULL
        );

        CREATE TABLE exons (
            id TEXT PRIMARY KEY,
            transcript_id TEXT,
            seqid TEXT NOT NULL,
            start INTEGER NOT NULL,
            end INTEGER NOT NULL,
            strand TEXT,
            rank INTEGER
        );

        CREATE TABLE go_terms (
            go_id TEXT PRIMARY KEY,
            term TEXT,
            namespace TEXT,
            definition TEXT,
            source TEXT
        );

        CREATE TABLE go_annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gene_id TEXT NOT NULL,
            go_id TEXT NOT NULL,
            term TEXT,
            namespace TEXT,
            evidence_code TEXT,
            source TEXT
        );

        CREATE TABLE ko_annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gene_id TEXT NOT NULL,
            ko_id TEXT NOT NULL,
            description TEXT,
            source TEXT
        );

        CREATE TABLE ko_pathway_links (
            ko_id TEXT NOT NULL,
            pathway_id TEXT NOT NULL,
            pathway_name TEXT,
            category TEXT,
            source TEXT,
            PRIMARY KEY (ko_id, pathway_id)
        );

        CREATE TABLE kegg_annotations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            gene_id TEXT NOT NULL,
            pathway_id TEXT NOT NULL,
            pathway_name TEXT,
            category TEXT,
            ko_id TEXT,
            ec_number TEXT,
            source TEXT
        );

        CREATE INDEX idx_features_type ON features(featuretype);
        CREATE INDEX idx_features_region ON features(seqid, start, end);
        CREATE INDEX idx_features_gene ON features(gene_id);
        CREATE INDEX idx_features_transcript ON features(transcript_id);
        CREATE INDEX idx_genes_region ON genes(seqid, start, end);
        CREATE INDEX idx_transcripts_gene ON transcripts(gene_id);
        CREATE INDEX idx_exons_transcript ON exons(transcript_id, rank);
        CREATE INDEX idx_go_terms_namespace ON go_terms(namespace);
        CREATE INDEX idx_go_gene ON go_annotations(gene_id);
        CREATE INDEX idx_go_id ON go_annotations(go_id);
        CREATE INDEX idx_ko_gene ON ko_annotations(gene_id);
        CREATE INDEX idx_ko_id ON ko_annotations(ko_id);
        CREATE INDEX idx_kegg_gene ON kegg_annotations(gene_id);
        CREATE INDEX idx_kegg_pathway ON kegg_annotations(pathway_id);
        """
    )


def record_metadata(conn: sqlite3.Connection, args: argparse.Namespace) -> None:
    items = {
        "schema_version": SCHEMA_VERSION,
        "species_id": args.species_id,
        "scientific_name": args.scientific_name or "",
        "common_name": args.common_name or "",
        "taxonomy_id": args.taxonomy_id or "",
        "version_id": args.version_id,
        "version_name": args.version_name or args.version_id,
        "assembly_name": args.assembly_name or args.version_id,
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "builder": "cygnusxtools refdb build",
    }
    conn.executemany(
        "INSERT INTO metadata(key, value) VALUES (?, ?)",
        sorted(items.items()),
    )


def record_input_file(conn: sqlite3.Connection, kind: str, path: Path | None) -> None:
    if path is None:
        return
    stat = path.stat()
    conn.execute(
        """
        INSERT OR REPLACE INTO input_files(kind, path, size_bytes, mtime)
        VALUES (?, ?, ?, ?)
        """,
        (kind, str(path.resolve()), stat.st_size, stat.st_mtime),
    )


def run_samtools_faidx(fasta: Path) -> Path:
    samtools = shutil.which("samtools")
    if samtools is None:
        raise BuildError("FASTA 是压缩文件或需要外部索引，但未找到 samtools")
    result = subprocess.run([samtools, "faidx", str(fasta)], check=False, text=True)
    if result.returncode != 0:
        raise BuildError(f"samtools faidx 执行失败: {fasta}")
    fai = Path(f"{fasta}.fai")
    if not fai.exists():
        raise BuildError(f"samtools faidx 未生成索引: {fai}")
    return fai


def build_plain_fai(fasta: Path, fai: Path) -> list[tuple[str, int, int, int, int]]:
    rows: list[tuple[str, int, int, int, int]] = []
    current_name: str | None = None
    current_length = 0
    current_offset = 0
    current_line_bases = 0
    current_line_width = 0

    def flush() -> None:
        nonlocal current_name, current_length, current_offset, current_line_bases, current_line_width
        if current_name is None:
            return
        rows.append(
            (
                current_name,
                current_length,
                current_offset,
                current_line_bases,
                current_line_width,
            )
        )

    with fasta.open("rb") as handle:
        while True:
            line_start = handle.tell()
            line = handle.readline()
            if not line:
                flush()
                break
            if line.startswith(b">"):
                flush()
                header = line[1:].strip().split(None, 1)[0]
                current_name = header.decode("utf-8", errors="replace")
                current_length = 0
                current_offset = 0
                current_line_bases = 0
                current_line_width = 0
                continue
            if current_name is None:
                raise BuildError(f"FASTA 首个序列前存在非 header 行: {fasta}")
            bases = line.rstrip(b"\r\n")
            if not bases:
                continue
            if current_line_bases == 0:
                current_offset = line_start
                current_line_bases = len(bases)
                current_line_width = len(line)
            current_length += len(bases)

    fai.parent.mkdir(parents=True, exist_ok=True)
    with fai.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write("\t".join(str(value) for value in row) + "\n")
    return rows


def read_fai(fai: Path) -> list[tuple[str, int, int, int, int]]:
    rows: list[tuple[str, int, int, int, int]] = []
    with fai.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 5:
                raise BuildError(f"FAI 格式不完整: {fai}: {line.strip()}")
            rows.append((parts[0], int(parts[1]), int(parts[2]), int(parts[3]), int(parts[4])))
    return rows


def build_fasta(conn: sqlite3.Connection, fasta: Path, out_dir: Path, fai_arg: str | None) -> Path:
    if fai_arg:
        fai = Path(fai_arg).expanduser().resolve()
        if not fai.exists():
            raise BuildError(f"指定的 FAI 不存在: {fai}")
        rows = read_fai(fai)
    elif fasta.suffix == ".gz":
        fai = run_samtools_faidx(fasta)
        rows = read_fai(fai)
    else:
        fai = out_dir / f"{fasta.name}.fai"
        rows = build_plain_fai(fasta, fai)

    conn.executemany(
        """
        INSERT OR REPLACE INTO fasta_sequences(name, length, offset, line_bases, line_width)
        VALUES (?, ?, ?, ?, ?)
        """,
        rows,
    )
    record_input_file(conn, "fasta", fasta)
    record_input_file(conn, "fasta_index", fai)
    return fai.resolve()


def unique_feature_id(base_id: str, seen: Counter[str]) -> str:
    seen[base_id] += 1
    if seen[base_id] == 1:
        return base_id
    return f"{base_id}.dup{seen[base_id]}"


def parse_gff(conn: sqlite3.Connection, gff: Path | None) -> dict[str, int]:
    if gff is None:
        return {}

    feature_rows: list[tuple[Any, ...]] = []
    relation_rows: list[tuple[str, str, str]] = []
    gene_rows: dict[str, tuple[Any, ...]] = {}
    transcript_rows: dict[str, tuple[Any, ...]] = {}
    exon_rows: list[tuple[Any, ...]] = []
    feature_type_counts: Counter[str] = Counter()
    seen_ids: Counter[str] = Counter()
    exon_rank: Counter[str] = Counter()

    with open_text(gff) as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip() or line.startswith("#"):
                continue
            parts = line.rstrip("\n\r").split("\t")
            if len(parts) != 9:
                print(f"[WARN] 跳过非 9 列 GFF 行 {line_no}: {gff}", file=sys.stderr)
                continue
            seqid, source, featuretype, start, end, score, strand, phase, raw_attrs = parts
            attrs = parse_attributes(raw_attrs)
            featuretype_norm = featuretype.lower()
            base_id = attr_first(attrs, ("ID", "id"))
            gene_id = attr_first(attrs, ("gene_id", "gene", "locus_tag"))
            transcript_id = attr_first(attrs, ("transcript_id", "transcript"))
            parent_ids = attr_first(attrs, ("Parent", "parent"))
            name = attr_first(attrs, ("Name", "gene_name", "product", "description"))

            if not base_id:
                base_id = gene_id or transcript_id or name or f"{featuretype}:{seqid}:{start}:{end}:{line_no}"
            feature_id = unique_feature_id(base_id, seen_ids)
            if featuretype_norm == "gene" and not gene_id:
                gene_id = feature_id
            if featuretype_norm in TRANSCRIPT_TYPES and not transcript_id:
                transcript_id = feature_id

            attrs_json = json.dumps(attrs, ensure_ascii=False, sort_keys=True)
            feature_rows.append(
                (
                    feature_id,
                    seqid,
                    source,
                    featuretype,
                    int(start),
                    int(end),
                    score,
                    strand,
                    phase,
                    name,
                    gene_id,
                    transcript_id,
                    parent_ids,
                    attrs_json,
                )
            )
            feature_type_counts[featuretype] += 1

            parents = [item.strip() for item in parent_ids.split(",") if item.strip()]
            if not parents and gene_id and transcript_id and gene_id != transcript_id:
                parents = [gene_id]
            for parent in parents:
                relation_rows.append((parent, feature_id, "parent_child"))

            biotype = attr_first(
                attrs,
                ("biotype", "gene_biotype", "gene_type", "transcript_biotype", "transcript_type"),
            )
            description = attr_first(attrs, ("description", "product", "Note", "note"))

            if featuretype_norm == "gene":
                gene_key = gene_id or feature_id
                gene_rows[gene_key] = (
                    gene_key,
                    attr_first(attrs, ("gene_name", "Name", "gene", "locus_tag")),
                    name,
                    seqid,
                    int(start),
                    int(end),
                    strand,
                    biotype,
                    description,
                    attrs_json,
                )
            elif featuretype_norm in TRANSCRIPT_TYPES:
                tx_key = transcript_id or feature_id
                tx_gene_id = gene_id or (parents[0] if parents else "")
                transcript_rows[tx_key] = (
                    tx_key,
                    tx_gene_id,
                    seqid,
                    int(start),
                    int(end),
                    strand,
                    biotype,
                    attrs_json,
                )
            elif featuretype_norm == "exon":
                tx_id = parents[0] if parents else transcript_id
                if tx_id:
                    exon_rank[tx_id] += 1
                    rank = exon_rank[tx_id]
                else:
                    rank = None
                exon_rows.append((feature_id, tx_id, seqid, int(start), int(end), strand, rank))

    conn.executemany(
        """
        INSERT OR REPLACE INTO features(
            id, seqid, source, featuretype, start, end, score, strand, phase,
            name, gene_id, transcript_id, parent_ids, attributes_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        feature_rows,
    )
    conn.executemany(
        "INSERT OR IGNORE INTO relations(parent, child, relation_type) VALUES (?, ?, ?)",
        relation_rows,
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO genes(
            gene_id, symbol, name, seqid, start, end, strand, biotype, description, attributes_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        gene_rows.values(),
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO transcripts(
            transcript_id, gene_id, seqid, start, end, strand, biotype, attributes_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        transcript_rows.values(),
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO exons(id, transcript_id, seqid, start, end, strand, rank)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        exon_rows,
    )
    record_input_file(conn, "gff", gff)
    return dict(feature_type_counts)


def _flush_obo_term(
    terms: dict[str, tuple[str, str, str, str]],
    current: dict[str, str] | None,
) -> None:
    if not current or current.get("is_obsolete") == "true":
        return
    go_id = current.get("id", "")
    if not go_id:
        return
    terms[go_id] = (
        current.get("name", ""),
        normalize_go_namespace(current.get("namespace", "")),
        current.get("definition", ""),
        "GO",
    )


def parse_go_obo(path: Path) -> dict[str, tuple[str, str, str, str]]:
    terms: dict[str, tuple[str, str, str, str]] = {}
    current: dict[str, str] | None = None
    with open_text(path) as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            if line == "[Term]":
                _flush_obo_term(terms, current)
                current = {}
                continue
            if line.startswith("["):
                _flush_obo_term(terms, current)
                current = None
                continue
            if current is None or ":" not in line:
                continue
            key, value = line.split(":", 1)
            value = value.strip()
            if key == "id":
                current["id"] = value
            elif key == "name":
                current["name"] = value
            elif key == "namespace":
                current["namespace"] = value
            elif key == "def":
                current["definition"] = value.split('"')[1] if '"' in value else value
            elif key == "is_obsolete":
                current["is_obsolete"] = value.lower()
    _flush_obo_term(terms, current)
    return terms


def load_go_terms(
    conn: sqlite3.Connection,
    go_terms_path: Path | None,
) -> dict[str, tuple[str, str, str, str]]:
    if go_terms_path is None:
        return {}
    if go_terms_path.suffix.lower() == ".obo":
        terms = parse_go_obo(go_terms_path)
    else:
        terms = {}
        for row in iter_table(go_terms_path):
            go_id = pick(row, GO_ID_FIELDS, 0)
            if not go_id:
                continue
            terms[go_id] = (
                pick(row, GO_TERM_FIELDS, 1),
                normalize_go_namespace(pick(row, ("namespace", "ontology", "aspect"), 2)),
                pick(row, GO_DEFINITION_FIELDS, 3),
                pick(row, ("source",), 4) or "GO",
            )
    conn.executemany(
        """
        INSERT OR REPLACE INTO go_terms(go_id, term, namespace, definition, source)
        VALUES (?, ?, ?, ?, ?)
        """,
        [(go_id, *values) for go_id, values in terms.items()],
    )
    record_input_file(conn, "go_terms", go_terms_path)
    return terms


def load_go(
    conn: sqlite3.Connection,
    go_path: Path | None,
    go_terms: dict[str, tuple[str, str, str, str]] | None = None,
) -> int:
    if go_path is None:
        return 0
    terms = go_terms or {}
    rows: list[tuple[str, str, str, str, str, str]] = []
    for row in iter_table(go_path):
        gene_id = pick(row, GENE_ID_FIELDS, 0)
        go_ids = split_identifier_values(pick(row, GO_ID_FIELDS, 1))
        if not gene_id or not go_ids:
            continue
        row_term = pick(row, GO_TERM_FIELDS + ("description",), 2)
        row_namespace = normalize_go_namespace(pick(row, ("namespace", "ontology", "aspect"), 3))
        evidence_code = pick(row, ("evidence_code", "evidence", "ev"), 4)
        row_source = pick(row, ("source",), 5)
        for go_id in go_ids:
            term, namespace, _definition, source = terms.get(go_id, ("", "", "", ""))
            rows.append(
                (
                    gene_id,
                    go_id,
                    row_term or term,
                    row_namespace or namespace,
                    evidence_code,
                    row_source or source,
                )
            )
    conn.executemany(
        """
        INSERT INTO go_annotations(gene_id, go_id, term, namespace, evidence_code, source)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        rows,
    )
    record_input_file(conn, "go", go_path)
    return len(rows)


def load_ko(conn: sqlite3.Connection, ko_path: Path | None) -> int:
    if ko_path is None:
        return 0
    rows: list[tuple[str, str, str, str]] = []
    for row in iter_table(ko_path):
        gene_id = pick(row, GENE_ID_FIELDS, 0)
        ko_ids = split_identifier_values(pick(row, KO_ID_FIELDS + KEGG_ID_FIELDS, 1))
        if not gene_id or not ko_ids:
            continue
        description = pick(row, ("description", "name", "term"), 2)
        source = pick(row, ("source",), 3)
        for ko_id in ko_ids:
            rows.append((gene_id, normalize_kegg_value(ko_id), description, source))
    conn.executemany(
        "INSERT INTO ko_annotations(gene_id, ko_id, description, source) VALUES (?, ?, ?, ?)",
        rows,
    )
    record_input_file(conn, "ko", ko_path)
    return len(rows)


def looks_like_ko(value: str) -> bool:
    normalized = normalize_kegg_value(value)
    return normalized.startswith("K") and normalized[1:].isdigit()


def looks_like_pathway(value: str) -> bool:
    normalized = normalize_kegg_value(value)
    return bool(re.match(r"^(?:map|ko|[a-zA-Z]{2,5})\d{5}$", normalized))


def load_kegg(conn: sqlite3.Connection, kegg_path: Path | None) -> dict[str, int]:
    if kegg_path is None:
        return {"direct": 0, "links": 0, "gene_ko": 0}
    direct_rows: list[tuple[str, str, str, str, str, str, str]] = []
    link_rows: list[tuple[str, str, str, str, str]] = []
    gene_ko_rows: list[tuple[str, str, str, str, str, str]] = []
    for row in iter_table(kegg_path):
        has_positional_columns = "_0" in row
        first = normalize_kegg_value(row.get("_0", ""))
        second = normalize_kegg_value(row.get("_1", ""))
        gene_id = pick(row, GENE_ID_FIELDS, 0 if has_positional_columns else None)
        pathway_raw = pick(row, PATHWAY_ID_FIELDS, 1 if has_positional_columns else None)
        ko_raw = pick(row, KO_ID_FIELDS, 4 if has_positional_columns else None)
        kegg_raw = pick(row, KEGG_ID_FIELDS, 1 if has_positional_columns else None)
        pathway_name = pick(row, ("pathway_name", "name", "description"), 2)
        category = pick(row, ("category",), 3)
        source = pick(row, ("source",), 6 if has_positional_columns else None)
        link_source = pick(row, ("source",), 4 if has_positional_columns else None) or source

        if not pathway_raw and kegg_raw and looks_like_pathway(kegg_raw):
            pathway_raw = kegg_raw
        if not ko_raw and kegg_raw and looks_like_ko(kegg_raw):
            ko_raw = kegg_raw

        is_header_ko_pathway = bool(ko_raw and pathway_raw and not gene_id)
        is_positional_ko_pathway = bool(looks_like_ko(first) and second)
        if is_header_ko_pathway or is_positional_ko_pathway:
            ko_values = split_identifier_values(ko_raw or first)
            pathway_values = split_identifier_values(pathway_raw or second)
            for ko_id in ko_values:
                for pathway_id in pathway_values:
                    link_rows.append(
                        (
                            normalize_kegg_value(ko_id),
                            normalize_kegg_value(pathway_id),
                            pathway_name,
                            category,
                            link_source,
                        )
                    )
            continue

        if not gene_id:
            continue

        ko_values = [normalize_kegg_value(value) for value in split_identifier_values(ko_raw)]
        pathway_values = [normalize_kegg_value(value) for value in split_identifier_values(pathway_raw)]
        if not pathway_values and ko_values:
            description = pick(row, ("description", "name", "term"), 2)
            row_source = pick(row, ("source",), 3) or source
            for ko_id in ko_values:
                gene_ko_rows.append((gene_id, ko_id, description, row_source, gene_id, ko_id))
            continue
        if not pathway_values:
            continue
        ko_id = ko_values[0] if ko_values else ""
        for pathway_id in pathway_values:
            direct_rows.append(
                (
                    gene_id,
                    pathway_id,
                    pathway_name,
                    category,
                    ko_id,
                    pick(row, ("ec_number", "ec"), 5),
                    source,
                )
            )

    conn.executemany(
        """
        INSERT INTO kegg_annotations(
            gene_id, pathway_id, pathway_name, category, ko_id, ec_number, source
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        direct_rows,
    )
    conn.executemany(
        """
        INSERT OR REPLACE INTO ko_pathway_links(
            ko_id, pathway_id, pathway_name, category, source
        ) VALUES (?, ?, ?, ?, ?)
        """,
        link_rows,
    )
    conn.executemany(
        """
        INSERT INTO ko_annotations(gene_id, ko_id, description, source)
        SELECT ?, ?, ?, ?
        WHERE NOT EXISTS (
            SELECT 1 FROM ko_annotations existing
            WHERE existing.gene_id = ? AND existing.ko_id = ?
        )
        """,
        gene_ko_rows,
    )
    conn.execute(
        """
        INSERT INTO kegg_annotations(gene_id, pathway_id, pathway_name, category, ko_id, ec_number, source)
        SELECT ko.gene_id, link.pathway_id, link.pathway_name, link.category, ko.ko_id, '', link.source
        FROM ko_annotations ko
        JOIN ko_pathway_links link ON link.ko_id = ko.ko_id
        WHERE NOT EXISTS (
            SELECT 1 FROM kegg_annotations existing
            WHERE existing.gene_id = ko.gene_id
              AND existing.pathway_id = link.pathway_id
              AND IFNULL(existing.ko_id, '') = ko.ko_id
        )
        """
    )
    record_input_file(conn, "kegg", kegg_path)
    return {"direct": len(direct_rows), "links": len(link_rows), "gene_ko": len(gene_ko_rows)}


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def collect_stats(conn: sqlite3.Connection, feature_counts: dict[str, int]) -> dict[str, Any]:
    genome_size = int(conn.execute("SELECT COALESCE(SUM(length), 0) FROM fasta_sequences").fetchone()[0])
    protein_coding = int(
        conn.execute(
            """
            SELECT COUNT(*) FROM genes
            WHERE lower(COALESCE(biotype, '')) IN ('protein_coding', 'protein coding')
               OR lower(COALESCE(description, '')) LIKE '%protein%'
            """
        ).fetchone()[0]
    )
    return {
        "chromosomes": table_count(conn, "fasta_sequences"),
        "genome_size_bp": genome_size,
        "total_features": table_count(conn, "features"),
        "total_genes": table_count(conn, "genes"),
        "protein_coding": protein_coding,
        "total_transcripts": table_count(conn, "transcripts"),
        "total_exons": table_count(conn, "exons"),
        "go_terms": table_count(conn, "go_terms"),
        "go_annotations": table_count(conn, "go_annotations"),
        "ko_annotations": table_count(conn, "ko_annotations"),
        "kegg_annotations": table_count(conn, "kegg_annotations"),
        "feature_types": feature_counts,
    }


def quote_yaml(value: str | None) -> str:
    return json.dumps(value or "", ensure_ascii=False)


def size_label(size_bytes: int) -> str:
    if size_bytes >= 1024**3:
        return f"{size_bytes / 1024**3:.2f} Gb"
    if size_bytes >= 1024**2:
        return f"{size_bytes / 1024**2:.2f} Mb"
    if size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} Kb"
    return f"{size_bytes} b"


def write_manifest(
    args: argparse.Namespace,
    out_dir: Path,
    db_path: Path,
    fasta: Path,
    fai: Path,
    stats: dict[str, Any],
) -> Path:
    manifest_path = out_dir / "database_manifest.json"
    files: dict[str, dict[str, Any]] = {
        "fasta": {
            "path": str(fasta.resolve()),
            "index_path": str(fai.resolve()),
            "format": "fasta",
            "db_path": str(db_path.resolve()),
            "build_status": "ready",
        }
    }
    for kind in ("gff", "go", "go_terms", "ko", "kegg"):
        raw = getattr(args, kind)
        if not raw:
            continue
        path = Path(raw).expanduser().resolve()
        files[kind] = {
            "path": str(path),
            "format": "gff3" if kind == "gff" else "obo" if path.suffix.lower() == ".obo" else "tsv",
            "db_path": str(db_path.resolve()),
            "build_status": "ready",
        }
    manifest = {
        "version": SCHEMA_VERSION,
        "species": {
            "id": args.species_id,
            "scientific_name": args.scientific_name,
            "common_name": args.common_name,
            "taxonomy_id": args.taxonomy_id,
        },
        "genome_version": {
            "version_id": args.version_id,
            "version_name": args.version_name or args.version_id,
            "assembly_name": args.assembly_name or args.version_id,
            "data_files": files,
            "stats": stats,
        },
        "outputs": {
            "database": str(db_path.resolve()),
            "fai": str(fai.resolve()),
            "jbrowse_snippet": str((out_dir / "jbrowse_assembly_snippet.yaml").resolve()),
        },
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def write_jbrowse_snippet(
    args: argparse.Namespace,
    out_dir: Path,
    db_path: Path,
    fasta: Path,
    fai: Path,
    stats: dict[str, Any],
) -> Path:
    snippet_path = out_dir / "jbrowse_assembly_snippet.yaml"
    genome_size = size_label(int(stats.get("genome_size_bp", 0)))
    lines = [
        "# Append this item under tool_configs/jbrowse/jbrowse_config.yaml assemblies:",
        f"- id: {quote_yaml(args.version_id)}",
        f"  name: {quote_yaml(args.display_name or args.version_id)}",
        f"  species: {quote_yaml(args.scientific_name)}",
        f"  common_name: {quote_yaml(args.common_name)}",
        f"  taxonomy_id: {quote_yaml(args.taxonomy_id)}",
        f"  version_id: {quote_yaml(args.version_id)}",
        f"  version_name: {quote_yaml(args.version_name or args.version_id)}",
        f"  assembly_name: {quote_yaml(args.assembly_name or args.version_id)}",
        f"  category: {quote_yaml(args.category)}",
        f"  icon: {quote_yaml(args.icon)}",
        "  is_default: false",
        "  status: \"active\"",
        f"  release_date: {quote_yaml(args.release_date)}",
        f"  description: {quote_yaml(args.description)}",
        "  stats:",
        f"    chromosomes: {stats.get('chromosomes', 0)}",
        f"    total_genes: {stats.get('total_genes', 0)}",
        f"    protein_coding: {stats.get('protein_coding', 0)}",
        f"    genome_size: {quote_yaml(genome_size)}",
        "  data_files:",
        "    fasta:",
        f"      path: {quote_yaml(str(fasta.resolve()))}",
        f"      index_path: {quote_yaml(str(fai.resolve()))}",
        "      format: \"fasta\"",
        "      build_required: false",
        "      build_tool: \"offline-build-reference-database\"",
        "      build_status: \"ready\"",
    ]
    optional_files = [
        ("gff", args.gff, "gff3"),
        ("go", args.go, "tsv"),
        ("go_terms", args.go_terms, "obo" if args.go_terms and Path(args.go_terms).suffix.lower() == ".obo" else "tsv"),
        ("kegg", args.kegg or args.ko, "tsv"),
    ]
    for kind, raw_path, file_format in optional_files:
        if not raw_path:
            continue
        lines.extend(
            [
                f"    {kind}:",
                f"      path: {quote_yaml(str(Path(raw_path).expanduser().resolve()))}",
                f"      db_path: {quote_yaml(str(db_path.resolve()))}",
                f"      format: {quote_yaml(file_format)}",
                "      build_required: false",
                "      build_tool: \"offline-build-reference-database\"",
                "      build_status: \"ready\"",
            ]
        )
    lines.extend(
        [
            f"  fasta: {quote_yaml(str(fasta.resolve()))}",
            f"  fai: {quote_yaml(str(fai.resolve()))}",
        ]
    )
    snippet_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return snippet_path


def validate_paths(args: argparse.Namespace) -> None:
    for name in ("fasta", "gff", "go", "go_terms", "ko", "kegg", "fai"):
        raw = getattr(args, name)
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.exists():
            raise BuildError(f"输入文件不存在 --{name}: {path}")
        if not path.is_file():
            raise BuildError(f"输入路径不是文件 --{name}: {path}")


def build_database(args: argparse.Namespace) -> dict[str, Any]:
    validate_paths(args)
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    fasta = Path(args.fasta).expanduser().resolve()
    db_path = out_dir / args.db_name
    tmp_path = out_dir / f".{args.db_name}.tmp"
    if db_path.exists() and not args.force:
        raise BuildError(f"输出数据库已存在，使用 --force 覆盖: {db_path}")
    if tmp_path.exists():
        tmp_path.unlink()

    conn = sqlite3.connect(tmp_path)
    try:
        conn.execute("PRAGMA journal_mode = OFF")
        conn.execute("PRAGMA synchronous = OFF")
        create_schema(conn)
        record_metadata(conn, args)
        fai = build_fasta(conn, fasta, out_dir, args.fai)
        feature_counts = parse_gff(conn, Path(args.gff).expanduser().resolve() if args.gff else None)
        go_terms = load_go_terms(
            conn,
            Path(args.go_terms).expanduser().resolve() if args.go_terms else None,
        )
        go_count = load_go(conn, Path(args.go).expanduser().resolve() if args.go else None, go_terms)
        ko_count = load_ko(conn, Path(args.ko).expanduser().resolve() if args.ko else None)
        kegg_counts = load_kegg(
            conn,
            Path(args.kegg).expanduser().resolve() if args.kegg else None,
        )
        conn.commit()
        stats = collect_stats(conn, feature_counts)
        conn.execute("VACUUM")
        conn.commit()
    finally:
        conn.close()

    if db_path.exists():
        db_path.unlink()
    tmp_path.replace(db_path)
    manifest_path = write_manifest(args, out_dir, db_path, fasta, fai, stats)
    snippet_path = write_jbrowse_snippet(args, out_dir, db_path, fasta, fai, stats)
    report = {
        "database": str(db_path),
        "manifest": str(manifest_path),
        "jbrowse_snippet": str(snippet_path),
        "fai": str(fai),
        "go_rows_loaded": go_count,
        "ko_rows_loaded": ko_count,
        "kegg_direct_rows_loaded": kegg_counts["direct"],
        "kegg_ko_pathway_links_loaded": kegg_counts["links"],
        "kegg_gene_ko_rows_loaded": kegg_counts["gene_ko"],
        "stats": stats,
    }
    (out_dir / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report



def add_build_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument("--species-id", required=True, help="Species identifier, e.g. Lsat")
    parser.add_argument("--version-id", required=True, help="Genome version identifier, e.g. Lsat_v11")
    parser.add_argument("--fasta", required=True, help="Reference FASTA file")
    parser.add_argument("--out-dir", required=True, help="Output directory for SQLite DB and reports")
    parser.add_argument("--gff", help="GFF3/GTF annotation file")
    parser.add_argument("--go", help="GO annotation TSV/CSV file")
    parser.add_argument("--go-terms", help="GO term metadata TSV/CSV/OBO file used to fill term and namespace")
    parser.add_argument("--ko", help="Gene to KO annotation TSV/CSV file")
    parser.add_argument("--kegg", help="Gene to KEGG pathway, gene to KO, or KO to pathway TSV/CSV file")
    parser.add_argument("--fai", help="Existing FASTA .fai index; if omitted, script builds one")
    parser.add_argument("--db-name", default="database.sqlite", help="Output SQLite file name")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing output database")

    parser.add_argument("--scientific-name", default="", help="Scientific species name")
    parser.add_argument("--common-name", default="", help="Common species name")
    parser.add_argument("--taxonomy-id", default="", help="NCBI taxonomy id")
    parser.add_argument("--version-name", default="", help="Display version name")
    parser.add_argument("--assembly-name", default="", help="Assembly name")
    parser.add_argument("--display-name", default="", help="Display name for JBrowse assembly snippet")
    parser.add_argument("--category", default="plant", help="Database category")
    parser.add_argument("--icon", default="🧬", help="Display icon")
    parser.add_argument("--release-date", default="", help="Release date text")
    parser.add_argument("--description", default="", help="Description text")
    return parser


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Offline builder for CygnusX FA/GFF/GO/KO/KEGG reference database assets.",
        formatter_class=CygnusXHelpFormatter,
    )
    return add_build_arguments(parser)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_parser().parse_args(argv)


def run_build(args: argparse.Namespace) -> int:
    try:
        report = build_database(args)
    except BuildError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    print("Offline database build finished.")
    print(f"  database:        {report['database']}")
    print(f"  fasta index:     {report['fai']}")
    print(f"  manifest:        {report['manifest']}")
    print(f"  jbrowse snippet: {report['jbrowse_snippet']}")
    print("  stats:")
    for key, value in report["stats"].items():
        if key == "feature_types":
            continue
        print(f"    {key}: {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run_build(parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())

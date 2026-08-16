"""indexer.py 解析器单元测试 —— 全部使用真实 TAIR10 文件切片的 fixture。

fixture：tests/unit/reference_genomes/fixtures/（由真实文件 head/grep 截取）。
构建策略测试在 tmp_path 下用迷你数据跑通 build_index 全流程。
"""

from __future__ import annotations

import gzip
import json
import shutil
import sqlite3
from pathlib import Path

import pytest
import yaml

from omichub.reference_genomes import indexer
from omichub.reference_genomes.config import VersionConfig, gene_index_path
from omichub.reference_genomes.sequence import fetch_kv

FIXTURE_DIR = Path(__file__).parent / "reference_genomes" / "fixtures"

pytestmark = pytest.mark.skipif(
    not FIXTURE_DIR.exists(), reason="reference_genomes fixtures 缺失"
)


def _noop_log(*_args, **_kwargs) -> None:
    pass


@pytest.fixture()
def conn(tmp_path: Path):
    db = tmp_path / "test.db"
    c = sqlite3.connect(db)
    indexer._create_schema(c)
    yield c
    c.close()


@pytest.fixture()
def version(tmp_path: Path) -> VersionConfig:
    """data_dir 指向 fixtures，gene_index 落 tmp_path。"""
    return VersionConfig(
        id="fixture",
        version_name="fixture",
        data_dir=str(FIXTURE_DIR),
        gene_index=str(tmp_path / "gene_index.db"),
        files={
            "fasta": {"path": "genome.fa", "format": "genomic_fasta"},
            "gff3": {"path": "tair10_genes.gff", "format": "gff3"},
            "cds": {"path": "tair10_cds.fa", "format": "fasta_kv"},
            "protein": {"path": "tair10_pep.fa", "format": "fasta_kv"},
            "functional": {"path": "tair10_functional.tsv", "format": "tair_functional"},
            "go": {"path": "tair10_gaf.tsv", "format": "gaf"},
            "go_obo": {"path": "go_terms.obo", "format": "obo"},
            "kegg_ko": {"path": "kegg_ko.list", "format": "kegg_ko"},
            "kegg_pathway": {"path": "kegg_pathway.list", "format": "kegg_pathway"},
            "kegg_pathway_name": {
                "path": "kegg_pathway_name.list",
                "format": "kegg_pathway_name",
            },
            "kegg_gene": {"path": "kegg_gene.list", "format": "kegg_gene"},
        },
    )


class TestGff3:
    def test_gene_and_mrna_counts(self, conn, version) -> None:
        indexer._parse_gff3(conn, version, _noop_log)
        genes = conn.execute("SELECT COUNT(*) FROM genes").fetchone()[0]
        trs = conn.execute("SELECT COUNT(*) FROM transcripts").fetchone()[0]
        assert genes >= 2  # fixture 至少含 AT1G01010/AT1G01020
        assert trs >= 2

    def test_gene_fields(self, conn, version) -> None:
        indexer._parse_gff3(conn, version, _noop_log)
        row = conn.execute(
            "SELECT gene_id, gene_name, chromosome, start, end, strand, length, gene_type"
            " FROM genes WHERE gene_id='AT1G01010'"
        ).fetchone()
        assert row is not None
        assert row[2] == "Chr1"
        assert row[3] == 3631
        assert row[4] == 5899
        assert row[5] == "+"
        assert row[6] == 5899 - 3631 + 1
        assert row[7] == "protein_coding"

    def test_exon_ranges_and_multiparent(self, conn, version) -> None:
        indexer._parse_gff3(conn, version, _noop_log)
        row = conn.execute(
            "SELECT exon_count, exon_ranges FROM transcripts WHERE transcript_id='AT1G01010.1'"
        ).fetchone()
        assert row is not None
        exon_count, exon_ranges = row
        ranges = json.loads(exon_ranges)
        assert exon_count == len(ranges) == 6  # AT1G01010 有 6 个 exon
        # 按基因组坐标升序
        assert ranges == sorted(ranges, key=lambda r: r[0])
        assert ranges[0] == [3631, 3913]
        # 多 Parent 的 CDS 行（Parent=AT1G01010.1,AT1G01010.1-Protein）不应产生
        # protein 为 key 的转录本，也不重复计数 exon
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM transcripts WHERE transcript_id LIKE '%Protein%'"
            ).fetchone()[0]
            == 0
        )

    def test_gene_exons_is_max_of_transcripts(self, conn, version) -> None:
        indexer._parse_gff3(conn, version, _noop_log)
        exons = conn.execute(
            "SELECT exons FROM genes WHERE gene_id='AT1G01010'"
        ).fetchone()[0]
        assert int(exons) == 6


class TestTairFunctional:
    def test_annotation_strips_suffix(self, conn, version) -> None:
        indexer._parse_gff3(conn, version, _noop_log)
        indexer._parse_tair_functional(conn, version, _noop_log)
        ann = conn.execute(
            "SELECT annotation FROM genes WHERE gene_id='AT1G01010'"
        ).fetchone()[0]
        # Curator_summary 为空 → 用 Short_description
        assert ann == "NAC domain containing protein 1"

    def test_multi_model_first_nonempty(self, conn, version) -> None:
        indexer._parse_gff3(conn, version, _noop_log)
        indexer._parse_tair_functional(conn, version, _noop_log)
        ann = conn.execute(
            "SELECT annotation FROM genes WHERE gene_id='AT1G01020'"
        ).fetchone()[0]
        assert ann == "Arv1-like protein"


class TestFastaKv:
    def test_offsets_roundtrip(self, conn, version) -> None:
        indexer._parse_gff3(conn, version, _noop_log)
        indexer._parse_fasta_kv(conn, version, _noop_log)
        rows = conn.execute(
            "SELECT kind, seq_id, byte_offset, seq_length, linebases, linewidth"
            " FROM fasta_records ORDER BY kind, seq_id"
        ).fetchall()
        assert len(rows) >= 4  # cds + pep 各至少 2 条
        by_id = {(r[0], r[1]): r for r in rows}
        assert ("cds", "AT1G51370.2") in by_id
        kind, seq_id, off, ln, lb, lw = by_id[("cds", "AT1G51370.2")]
        seq = fetch_kv(FIXTURE_DIR / "tair10_cds.fa", off, ln, lb, lw)
        assert seq.startswith("ATGGTGGGTGGCAAGAAG")
        pep = by_id[("pep", "AT1G51370.2")]
        pseq = fetch_kv(FIXTURE_DIR / "tair10_pep.fa", pep[2], pep[3], pep[4], pep[5])
        assert pseq.startswith("MVGGKKKTKICDKVSHEE")

    def test_transcript_cds_fields_updated(self, conn, version) -> None:
        indexer._parse_gff3(conn, version, _noop_log)
        indexer._parse_fasta_kv(conn, version, _noop_log)
        row = conn.execute(
            "SELECT cds_id, cds_length FROM transcripts WHERE transcript_id='AT1G51370.2'"
        ).fetchone()
        if row is not None:  # fixture GFF 若含该转录本
            assert row[0] == "AT1G51370.2"
            assert row[1] > 0


class TestGaf:
    def test_skip_comments_and_extract_columns(self, conn, version) -> None:
        indexer._parse_gaf(conn, version, _noop_log)
        n = conn.execute("SELECT COUNT(*) FROM go_annotations").fetchone()[0]
        assert n > 0
        row = conn.execute(
            "SELECT gene_id, go_id, evidence, source FROM go_annotations LIMIT 1"
        ).fetchone()
        assert row[0].startswith("AT")
        assert row[1].startswith("GO:")

    def test_dedup_gene_go_pair(self, conn, version) -> None:
        indexer._parse_gaf(conn, version, _noop_log)
        dup = conn.execute(
            "SELECT gene_id, go_id, COUNT(*) c FROM go_annotations"
            " GROUP BY gene_id, go_id HAVING c > 1"
        ).fetchall()
        assert dup == []


class TestObo:
    def test_terms_parsed(self, conn, version) -> None:
        indexer._parse_obo(conn, version, _noop_log)
        row = conn.execute(
            "SELECT name, aspect FROM go_terms WHERE go_id='GO:0000001'"
        ).fetchone()
        assert row is not None
        assert row[0] == "mitochondrion inheritance"
        assert row[1] == "P"  # biological_process → P

    def test_obsolete_skipped(self, conn, version) -> None:
        indexer._parse_obo(conn, version, _noop_log)
        row = conn.execute(
            "SELECT COUNT(*) FROM go_terms WHERE go_id='GO:0000002'"
        ).fetchone()[0]
        assert row == 0  # is_obsolete: true → 跳过

    def test_definition_extracted(self, conn, version) -> None:
        indexer._parse_obo(conn, version, _noop_log)
        d = conn.execute(
            "SELECT definition FROM go_terms WHERE go_id='GO:0000001'"
        ).fetchone()[0]
        assert d and "mitochondria" in d


class TestKegg:
    def test_ko_prefix_stripped(self, conn, version) -> None:
        indexer._parse_kegg_ko(conn, version, _noop_log)
        row = conn.execute(
            "SELECT gene_id, ko_id, pathway_id FROM kegg_annotations"
            " WHERE gene_id='AT1G01010'"
        ).fetchone()
        assert row is not None
        assert row[1] == "K28554"  # ko: 前缀剥离
        assert row[2] == ""
        assert (
            conn.execute("SELECT COUNT(*) FROM kegg_kos WHERE ko_id='K28554'").fetchone()[0]
            == 1
        )

    def test_pathway_prefix_stripped(self, conn, version) -> None:
        indexer._parse_kegg_pathway(conn, version, _noop_log)
        row = conn.execute(
            "SELECT gene_id, ko_id, pathway_id FROM kegg_annotations"
            " WHERE pathway_id != '' LIMIT 1"
        ).fetchone()
        assert row is not None
        assert not row[2].startswith("path:")
        assert row[2].startswith("ath")

    def test_pathway_name_suffix_stripped(self, conn, version) -> None:
        indexer._parse_kegg_pathway_name(conn, version, _noop_log)
        rows = conn.execute("SELECT pathway_id, name FROM kegg_pathways").fetchall()
        assert rows
        for pid, name in rows:
            assert not pid.startswith("path:")
            assert "Arabidopsis thaliana (thale cress)" not in name

    def test_gene_symbol_extracted(self, conn, version) -> None:
        indexer._parse_gff3(conn, version, _noop_log)
        indexer._parse_kegg_gene(conn, version, _noop_log)
        name = conn.execute(
            "SELECT gene_name FROM genes WHERE gene_id='AT1G01010'"
        ).fetchone()[0]
        assert name == "NAC001"  # description 分号前为 symbol


class TestCanonicalAndMeta:
    def test_canonical_marks_longest_cds(self, conn, version) -> None:
        indexer._parse_gff3(conn, version, _noop_log)
        indexer._parse_fasta_kv(conn, version, _noop_log)
        indexer._mark_canonical(conn, version, _noop_log)
        rows = conn.execute(
            "SELECT gene_id, COUNT(*) FROM transcripts WHERE canonical=1 GROUP BY gene_id"
        ).fetchall()
        for _gid, cnt in rows:
            assert cnt == 1  # 每基因至多一个 canonical

    def test_meta_counts(self, conn, version) -> None:
        indexer._parse_gff3(conn, version, _noop_log)
        indexer._write_meta(conn, version, _noop_log)
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        assert meta["build_status"] == "ready"
        assert int(meta["gene_count"]) == conn.execute(
            "SELECT COUNT(*) FROM genes"
        ).fetchone()[0]
        assert int(meta["transcript_count"]) == conn.execute(
            "SELECT COUNT(*) FROM transcripts"
        ).fetchone()[0]


class TestBuildIndexAtomic:
    """迷你全量构建：临时 yaml + fixture 数据 → 验证原子替换与 meta。"""

    def test_full_build_mini(self, tmp_path: Path) -> None:
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        # 复制 fixtures 并 gzip 一个基因组 fasta
        for fx in FIXTURE_DIR.iterdir():
            if fx.name.startswith("genome.fa") and fx.suffix == ".fai":
                continue
            shutil.copy(fx, data_dir / fx.name)
        raw = data_dir / "genome.fa"
        if not raw.exists():
            shutil.copy(FIXTURE_DIR / "genome.fa", raw)
        with open(raw, "rb") as fin, gzip.open(data_dir / "genome.fa.gz", "wb") as fout:
            fout.writelines(fin)
        raw.unlink()

        cfg = {
            "species": [
                {
                    "id": "fixture-species",
                    "common_name": "测试物种",
                    "versions": [
                        {
                            "id": "fixture",
                            "version_name": "fixture",
                            "data_dir": str(data_dir),
                            "gene_index": "gene_index.db",
                            "files": {
                                "fasta": {"path": "genome.fa.gz", "format": "genomic_fasta"},
                                "gff3": {"path": "tair10_genes.gff", "format": "gff3"},
                                "cds": {"path": "tair10_cds.fa", "format": "fasta_kv"},
                                "protein": {"path": "tair10_pep.fa", "format": "fasta_kv"},
                                "functional": {
                                    "path": "tair10_functional.tsv",
                                    "format": "tair_functional",
                                },
                                "go": {"path": "tair10_gaf.tsv", "format": "gaf"},
                                "go_obo": {"path": "go_terms.obo", "format": "obo"},
                                "kegg_ko": {"path": "kegg_ko.list", "format": "kegg_ko"},
                                "kegg_pathway": {
                                    "path": "kegg_pathway.list",
                                    "format": "kegg_pathway",
                                },
                                "kegg_pathway_name": {
                                    "path": "kegg_pathway_name.list",
                                    "format": "kegg_pathway_name",
                                },
                                "kegg_gene": {"path": "kegg_gene.list", "format": "kegg_gene"},
                            },
                        }
                    ],
                }
            ]
        }
        yaml_path = tmp_path / "reference_genomes.yaml"
        yaml_path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")

        indexer.build_index("fixture", only=None, config_path=str(yaml_path))

        db_path = data_dir / "gene_index.db"
        assert db_path.exists()
        assert not (data_dir / "gene_index.db.tmp").exists()  # 原子替换后无残留
        # 解压产物 + fai
        assert (data_dir / "genome.fa").exists()
        assert (data_dir / "genome.fa.fai").exists()

        conn = sqlite3.connect(db_path)
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        assert meta["build_status"] == "ready"
        assert int(meta["gene_count"]) > 0
        # 关键数据抽查
        ann = conn.execute(
            "SELECT annotation FROM genes WHERE gene_id='AT1G01010'"
        ).fetchone()
        assert ann and ann[0] == "NAC domain containing protein 1"
        ko = conn.execute(
            "SELECT ko_id FROM kegg_annotations WHERE gene_id='AT1G01010' AND ko_id!=''"
        ).fetchall()
        assert ("K28554",) in ko
        conn.close()

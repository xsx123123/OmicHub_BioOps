"""sequence.py 纯 Python faidx 读取器单元测试。

fixture：tests/unit/reference_genomes/fixtures/genome.fa（2 条短序列，10bp/行）
与手工计算的 genome.fa.expected.json。fixture 缺失时回退 tmp_path 现造等价文件。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from omichub.reference_genomes.sequence import (
    build_fai,
    fetch_kv,
    fetch_region,
    open_index,
    parse_fai,
    reverse_complement,
)

FIXTURE_DIR = Path(__file__).parent / "reference_genomes" / "fixtures"

GENOME_FA = """>seq1 test chromosome
AAAAAAAAAA
CCCCCCCCCC
GGGGG
>seq2
TTTTTTTTTT
GGGGGGGGGG
CCCCCAAAAA
"""

EXPECTED = {
    "seq1": {"length": 25, "offset": 22, "linebases": 10, "linewidth": 11},
    "seq2": {"length": 30, "offset": 56, "linebases": 10, "linewidth": 11},
}


@pytest.fixture()
def genome_fa(tmp_path: Path) -> Path:
    """优先使用仓库 fixture；不存在则现造。"""
    fx = FIXTURE_DIR / "genome.fa"
    if fx.exists():
        return fx
    p = tmp_path / "genome.fa"
    p.write_text(GENOME_FA, encoding="utf-8")
    return p


@pytest.fixture()
def expected() -> dict:
    fx = FIXTURE_DIR / "genome.fa.expected.json"
    if fx.exists():
        return json.loads(fx.read_text(encoding="utf-8"))
    return EXPECTED


class TestBuildFai:
    def test_matches_expected(self, genome_fa: Path, expected: dict) -> None:
        fai = build_fai(genome_fa)
        assert fai.name == genome_fa.name + ".fai"
        idx = parse_fai(fai)
        assert set(idx) == set(expected)
        for name, exp in expected.items():
            rec = idx[name]
            assert rec.length == exp["length"]
            assert rec.offset == exp["offset"]
            assert rec.linebases == exp["linebases"]
            assert rec.linewidth == exp["linewidth"]

    def test_idempotent(self, genome_fa: Path, expected: dict) -> None:
        build_fai(genome_fa)
        idx = parse_fai(build_fai(genome_fa))
        assert idx["seq1"].length == expected["seq1"]["length"]


class TestFetchRegion:
    @pytest.fixture(autouse=True)
    def _setup(self, genome_fa: Path) -> None:
        self.fa = genome_fa
        self.idx = parse_fai(build_fai(genome_fa))

    def test_full_span(self) -> None:
        assert fetch_region(self.fa, self.idx, "seq1", 1, 25) == "A" * 10 + "C" * 10 + "G" * 5

    def test_cross_line(self) -> None:
        # 跨第一/二行
        assert fetch_region(self.fa, self.idx, "seq1", 5, 14) == "AAAAAACCCC"

    def test_line_boundaries(self) -> None:
        assert fetch_region(self.fa, self.idx, "seq1", 11, 20) == "C" * 10
        assert fetch_region(self.fa, self.idx, "seq1", 11, 12) == "CC"

    def test_single_base(self) -> None:
        assert fetch_region(self.fa, self.idx, "seq1", 3, 3) == "A"
        assert fetch_region(self.fa, self.idx, "seq1", 25, 25) == "G"

    def test_last_partial_line(self) -> None:
        # seq1 第三行（不满宽）：GGGGG
        assert fetch_region(self.fa, self.idx, "seq1", 21, 25) == "G" * 5
        # seq2 第三行 CCCCCAAAAA 的后半段（26-30）
        assert fetch_region(self.fa, self.idx, "seq2", 26, 30) == "AAAAA"

    def test_clamp_over_end(self) -> None:
        assert fetch_region(self.fa, self.idx, "seq1", 20, 100000) == "CGGGGG"

    def test_clamp_below_start(self) -> None:
        assert fetch_region(self.fa, self.idx, "seq1", -5, 3) == "AAA"

    def test_reverse_strand(self) -> None:
        assert fetch_region(self.fa, self.idx, "seq1", 1, 10, "-") == "T" * 10
        rc = fetch_region(self.fa, self.idx, "seq1", 1, 25, "-")
        assert rc == reverse_complement("A" * 10 + "C" * 10 + "G" * 5)

    def test_unknown_chrom_raises(self) -> None:
        with pytest.raises(KeyError):
            fetch_region(self.fa, self.idx, "ChrX", 1, 5)

    def test_invalid_range_raises(self) -> None:
        with pytest.raises(ValueError):
            fetch_region(self.fa, self.idx, "seq1", 10, 1)


class TestFetchKv:
    def test_cross_line(self, genome_fa: Path) -> None:
        # seq2 第一条序列行 offset=56（expected.json 记录）
        assert fetch_kv(genome_fa, 56, 30, 10, 11) == "T" * 10 + "G" * 10 + "CCCCCAAAAA"

    def test_partial_last_line(self, genome_fa: Path) -> None:
        assert fetch_kv(genome_fa, 56, 12, 10, 11) == "T" * 10 + "GG"

    def test_zero_length(self, genome_fa: Path) -> None:
        assert fetch_kv(genome_fa, 56, 0, 10, 11) == ""


class TestReverseComplement:
    def test_basic(self) -> None:
        assert reverse_complement("ATGC") == "GCAT"

    def test_iupac_and_case(self) -> None:
        assert reverse_complement("ATGCNnatgc") == "gcatnNGCAT"

    def test_empty(self) -> None:
        assert reverse_complement("") == ""


class TestOpenIndex:
    def test_missing_fai_raises(self, tmp_path: Path) -> None:
        fa = tmp_path / "x.fa"
        fa.write_text(">a\nACGT\n", encoding="utf-8")
        with pytest.raises(FileNotFoundError):
            open_index(fa)

    def test_roundtrip(self, genome_fa: Path) -> None:
        build_fai(genome_fa)
        path, idx = open_index(genome_fa)
        assert path == genome_fa
        assert "seq1" in idx

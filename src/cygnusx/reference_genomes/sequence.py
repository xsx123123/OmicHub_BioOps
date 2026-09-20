"""纯 Python FASTA 序列读取器（faidx 兼容，不引入 pysam/pyfaidx 依赖）。

设计决策（设计文档 §4.3）：
- 基因组序列不入库：构建期把 gzip FASTA 解压为普通文本并生成 samtools 兼容的
  ``.fai`` 索引（name/length/offset/linebases/linewidth），运行期按坐标 O(1) seek
  随机读取，120 Mb 基因组零内存常驻；
- CDS/蛋白序列同样不整库入库：TAIR10 这类已按转录本拆好的多记录 FASTA，构建期
  在 gene_index.db 的 ``fasta_records`` 表记录每条序列的字节偏移
  （byte_offset/seq_length/linebases/linewidth），运行期 :func:`fetch_kv` 单次 seek
  读回。不选 seq_kv 全序列入库：3.5 万条序列会让 SQLite 膨胀 ~50 MB，而偏移表
  不到 2 MB，读取同样是 O(1) seek，构建也更快；
- faidx 偏移公式与 samtools .fai 规范一致：
  first_byte = offset + (start-1)//linebases*linewidth + (start-1)%linebases。
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

__all__ = [
    "FaiRecord",
    "parse_fai",
    "build_fai",
    "open_index",
    "fetch_region",
    "fetch_kv",
    "reverse_complement",
]


class FaiRecord(NamedTuple):
    """.fai 一行：与 samtools faidx 输出格式一致。"""

    name: str
    length: int  # 序列总碱基数
    offset: int  # 第一条序列行首字节的绝对偏移
    linebases: int  # 每条序列行的碱基数（最后一行可能更短）
    linewidth: int  # 每条序列行含行尾换行的字节数


# IUPAC 简并码互补表（含 gap/掩码），未收录字符原样保留
_COMPLEMENT = str.maketrans(
    "ACGTURYSWKMBDHVNacgturyswkmbdhvn",
    "TGCAAYRSWMKVHDBNtgcaayrswmkvhdbn",
)


def reverse_complement(seq: str) -> str:
    """反向互补；支持 IUPAC 简并码，未识别字符原样保留。"""
    return seq.translate(_COMPLEMENT)[::-1]


def parse_fai(fai_path: str | Path) -> dict[str, FaiRecord]:
    """解析 .fai 索引文件为 name→FaiRecord 映射。"""
    index: dict[str, FaiRecord] = {}
    with open(fai_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.rstrip("\n\r")
            if not line:
                continue
            cols = line.split("\t")
            if len(cols) < 5:
                continue
            index[cols[0]] = FaiRecord(
                name=cols[0],
                length=int(cols[1]),
                offset=int(cols[2]),
                linebases=int(cols[3]),
                linewidth=int(cols[4]),
            )
    return index


def build_fai(fasta_path: str | Path) -> Path:
    """纯 Python 扫描 FASTA 生成同名 ``.fai``，返回 fai 路径。

    流式按行读取（rb 模式以字节精确记账），容忍空行；每条序列的 linebases/
    linewidth 取其第一条序列行的值（末行允许不满宽）。
    """
    fasta_path = Path(fasta_path)
    fai_path = fasta_path.with_name(fasta_path.name + ".fai")

    rows: list[FaiRecord] = []
    name: str | None = None
    length = 0
    offset = 0  # 当前序列第一条序列行首字节偏移
    linebases = 0
    linewidth = 0
    have_first_line = False
    pos = 0  # 当前行首字节偏移

    with open(fasta_path, "rb") as f:
        for raw in f:
            stripped = raw.strip()
            if raw.startswith(b">"):
                if name is not None:
                    rows.append(FaiRecord(name, length, offset, linebases, linewidth))
                name = stripped[1:].split(b" ", 1)[0].decode("utf-8", "replace")
                length = 0
                have_first_line = False
            elif stripped:
                seq_len = len(stripped)
                if not have_first_line:
                    offset = pos
                    linebases = seq_len
                    linewidth = len(raw)
                    have_first_line = True
                length += seq_len
            pos += len(raw)
    if name is not None:
        rows.append(FaiRecord(name, length, offset, linebases, linewidth))

    with open(fai_path, "w", encoding="utf-8") as out:
        for r in rows:
            out.write(f"{r.name}\t{r.length}\t{r.offset}\t{r.linebases}\t{r.linewidth}\n")
    return fai_path


def open_index(fasta_path: str | Path) -> tuple[Path, dict[str, FaiRecord]]:
    """定位 FASTA 相邻的 .fai 并解析；不存在抛 FileNotFoundError。"""
    fasta_path = Path(fasta_path)
    fai_path = fasta_path.with_name(fasta_path.name + ".fai")
    if not fai_path.exists():
        raise FileNotFoundError(f"缺少 FASTA 索引：{fai_path}")
    return fasta_path, parse_fai(fai_path)


def fetch_region(
    fasta_path: str | Path,
    index: dict[str, FaiRecord],
    chrom: str,
    start: int,
    end: int,
    strand: str = "+",
) -> str:
    """按 1-based 闭区间读取基因组区间序列。

    - 越界自动 clamp 到 [1, length]；clamp 后 start>end 抛 ValueError；
    - chrom 不在索引中抛 KeyError；
    - strand='-'（大小写不敏感）返回反向互补。
    """
    if chrom not in index:
        raise KeyError(chrom)
    rec = index[chrom]
    start = max(1, int(start))
    end = min(rec.length, int(end))
    if start > end:
        raise ValueError(f"无效区间：{chrom}:{start}-{end}")

    # 目标序列行内（0-based）起止
    s = start - 1
    e = end - 1
    s_line, s_off = divmod(s, rec.linebases)
    e_line, e_off = divmod(e, rec.linebases)

    first_byte = rec.offset + s_line * rec.linewidth + s_off
    last_byte = rec.offset + e_line * rec.linewidth + e_off + 1  # 不含

    with open(fasta_path, "rb") as f:
        f.seek(first_byte)
        raw = f.read(last_byte - first_byte)

    seq = raw.replace(b"\r", b"").replace(b"\n", b"").decode("ascii", "replace")
    if strand.strip().lower() == "-":
        seq = reverse_complement(seq)
    return seq


def fetch_kv(
    fasta_path: str | Path,
    byte_offset: int,
    seq_length: int,
    linebases: int,
    linewidth: int,
) -> str:
    """按 fasta_records 表记录的偏移读取单条序列（CDS/蛋白）。

    byte_offset 为该序列第一条序列行首字节；读入足够覆盖 seq_length 个碱基的
    字节块（含行间换行），去换行后截断到 seq_length。
    """
    if seq_length <= 0:
        return ""
    linebases = max(1, int(linebases))
    linewidth = max(linebases, int(linewidth))
    nlines = seq_length // linebases + 1
    nbytes = seq_length + nlines * (linewidth - linebases) + linewidth
    with open(fasta_path, "rb") as f:
        f.seek(int(byte_offset))
        raw = f.read(nbytes)
    seq = raw.replace(b"\r", b"").replace(b"\n", b"").decode("ascii", "replace")
    return seq[:seq_length]

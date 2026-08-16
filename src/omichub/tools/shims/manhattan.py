"""曼哈顿图后端轻量 shim。

支持 CSV/TSV 格式的 GWAS 摘要统计表，自动识别 SNP / Chromosome / Position / P-value 列，
输出简化 Plotly 曼哈顿图。

注意：本 shim 仅覆盖对话内快速出图的核心路径，完整样式与交互请前往工具页。
"""

from __future__ import annotations

import csv
import io
import math
from typing import Any


def _parse_delimited(text: str) -> list[dict[str, str]]:
    """解析 CSV/TSV/空白分隔表。"""
    lines = [line for line in text.replace("\r\n", "\n").split("\n") if line.strip()]
    if not lines:
        return []

    first = lines[0]
    if "\t" in first:
        delim = "\t"
    elif "," in first:
        delim = ","
    else:
        # 任意空白：先拆分为空格分隔，再按逗号重新组装
        parsed_lines: list[list[str]] = [line.split() for line in lines]
        reader = csv.DictReader(
            io.StringIO("\n".join(",".join(cells) for cells in parsed_lines)),
            delimiter=",",
        )
        return [row for row in reader if any(v.strip() for v in row.values())]

    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delim)
    return [row for row in reader if any(v.strip() for v in row.values())]


def _normalize_col(col: str) -> str:
    return "".join(c for c in col.lower() if c.isalnum())


def _find_column(cols: list[str], patterns: list[str]) -> str:
    norm_cols = [_normalize_col(c) for c in cols]
    for pattern in patterns:
        for idx, norm in enumerate(norm_cols):
            if pattern in norm:
                return cols[idx]
    return ""


def _auto_detect_columns(cols: list[str]) -> dict[str, str]:
    snp = _find_column(cols, ["snp", "rsid", "rs", "id", "variant", "marker", "snpid"])
    chromosome = _find_column(cols, ["chr", "chrom", "chromosome", "scaffold", "lg"])
    position = _find_column(cols, ["pos", "position", "bp", "coord", "posi", "location"])
    pvalue = _find_column(cols, ["pvalue", "pval", "pvalue", "pvalue"])
    gene = _find_column(cols, ["gene", "nearestgene", "geneid"])
    return {
        "snp": snp or (cols[0] if cols else ""),
        "chromosome": chromosome,
        "position": position,
        "pvalue": pvalue,
        "gene": gene,
    }


def _to_float(value: str) -> float:
    if not value or value.strip().lower() in {"na", "nan", "null", "-", ""}:
        return math.nan
    try:
        n = float(value.strip())
        return n if math.isfinite(n) else math.nan
    except ValueError:
        return math.nan


def _normalize_chromosome(chr_value: str) -> str:
    cleaned = str(chr_value).upper().replace("CHR", "").strip()
    return cleaned


def _chromosome_order(chrs: set[str]) -> list[str]:
    numeric = sorted([c for c in chrs if c.isdigit()], key=int)
    string_order = ["X", "Y", "MT", "M"]
    string_chrs = sorted(
        [c for c in chrs if not c.isdigit()],
        key=lambda c: (string_order.index(c) if c in string_order else 999, c),
    )
    return numeric + string_chrs


async def execute(
    user_id: str,
    data_text: str,
    suggestive_line: float = 5.0,
    genome_wide_line: float = 8.0,
) -> dict[str, Any]:
    """曼哈顿图 shim 执行入口。"""
    if not data_text or not data_text.strip():
        raise ValueError("GWAS 数据表为空")

    raw_rows = _parse_delimited(data_text)
    if not raw_rows:
        raise ValueError("无法解析表格内容")

    cols = list(raw_rows[0].keys())
    col_map = _auto_detect_columns(cols)
    if not col_map["chromosome"] or not col_map["position"] or not col_map["pvalue"]:
        raise ValueError(f"未能自动识别染色体/位置/P-value 列，当前列：{cols}")

    rows: list[dict[str, Any]] = []
    for raw in raw_rows:
        snp = raw.get(col_map["snp"], "").strip()
        chromosome = _normalize_chromosome(raw.get(col_map["chromosome"], ""))
        position = _to_float(raw.get(col_map["position"], ""))
        p = _to_float(raw.get(col_map["pvalue"], ""))
        gene = raw.get(col_map["gene"], "").strip() if col_map["gene"] else ""

        if not snp or not chromosome or math.isnan(position) or math.isnan(p):
            continue
        if p <= 0 or p > 1:
            continue
        neg_log_p = -math.log10(p)
        rows.append(
            {
                "snp": snp,
                "chromosome": chromosome,
                "position": int(position),
                "pvalue": p,
                "neg_log_p": neg_log_p,
                "gene": gene,
                "is_significant": neg_log_p >= genome_wide_line,
                "is_suggestive": suggestive_line <= neg_log_p < genome_wide_line,
            }
        )

    if not rows:
        raise ValueError("没有可用的 GWAS 数据行")

    chromosome_order = _chromosome_order(set(r["chromosome"] for r in rows))

    # 按染色体分组并计算累积 X 坐标
    chr_groups: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        chr_groups.setdefault(r["chromosome"], []).append(r)
    for group in chr_groups.values():
        group.sort(key=lambda r: r["position"])

    colors = [
        "#E74C3C",
        "#3498DB",
        "#2ECC71",
        "#F39C12",
        "#9B59B6",
        "#1ABC9C",
        "#E91E63",
        "#00BCD4",
    ]

    traces: list[dict[str, Any]] = []
    chr_boundaries: list[dict[str, Any]] = []
    current_x = 0.0
    scale = 1e6

    for chr_idx, chromosome in enumerate(chromosome_order):
        group = chr_groups.get(chromosome, [])
        if not group:
            continue
        color = colors[chr_idx % len(colors)]
        xs: list[float] = []
        ys: list[float] = []
        texts: list[str] = []
        sig_xs: list[float] = []
        sig_ys: list[float] = []
        sig_texts: list[str] = []

        for r in group:
            x = current_x + r["position"] / scale
            y = r["neg_log_p"]
            text = f"{r['snp']}<br>Chr{chromosome}: {r['position']}<br>P: {r['pvalue']:.2e}"
            if r["gene"]:
                text += f"<br>Gene: {r['gene']}"
            if r["is_significant"] or r["is_suggestive"]:
                sig_xs.append(x)
                sig_ys.append(y)
                sig_texts.append(text)
            else:
                xs.append(x)
                ys.append(y)
                texts.append(text)

        start = current_x
        end = current_x + group[-1]["position"] / scale
        chr_boundaries.append({"chromosome": chromosome, "start": start, "end": end, "mid": (start + end) / 2})
        current_x = end + (group[-1]["position"] / scale) * 0.02

        if xs:
            traces.append(
                {
                    "x": xs,
                    "y": ys,
                    "text": texts,
                    "mode": "markers",
                    "type": "scatter",
                    "name": f"Chr{chromosome}",
                    "showlegend": False,
                    "marker": {"color": color, "size": 4, "opacity": 0.7},
                    "hovertemplate": "%{text}<extra></extra>",
                }
            )
        if sig_xs:
            traces.append(
                {
                    "x": sig_xs,
                    "y": sig_ys,
                    "text": sig_texts,
                    "mode": "markers",
                    "type": "scatter",
                    "name": f"Significant (Chr{chromosome})",
                    "showlegend": False,
                    "marker": {"color": "#FF4040", "size": 7, "opacity": 1.0, "symbol": "star"},
                    "hovertemplate": "%{text}<extra></extra>",
                }
            )

    max_neg_log_p = max(r["neg_log_p"] for r in rows)
    y_max = max(genome_wide_line + 1, math.ceil(max_neg_log_p * 1.1))

    shapes = []
    if suggestive_line > 0:
        shapes.append(
            {
                "type": "line",
                "x0": 0,
                "x1": 1,
                "xref": "paper",
                "y0": suggestive_line,
                "y1": suggestive_line,
                "line": {"color": "#9467BD", "width": 1, "dash": "dash"},
            }
        )
    if genome_wide_line > 0:
        shapes.append(
            {
                "type": "line",
                "x0": 0,
                "x1": 1,
                "xref": "paper",
                "y0": genome_wide_line,
                "y1": genome_wide_line,
                "line": {"color": "#E74C3C", "width": 1.5, "dash": "dash"},
            }
        )

    figure = {
        "data": traces,
        "layout": {
            "title": {"text": "Manhattan Plot", "x": 0.5},
            "xaxis": {
                "title": "Chromosome",
                "tickmode": "array",
                "tickvals": [b["mid"] for b in chr_boundaries],
                "ticktext": [str(b["chromosome"]) for b in chr_boundaries],
                "showgrid": False,
                "zeroline": False,
            },
            "yaxis": {
                "title": "-log₁₀(P-value)",
                "range": [0, y_max],
                "showgrid": True,
                "zeroline": False,
            },
            "shapes": shapes,
            "hovermode": "closest",
            "margin": {"l": 60, "r": 30, "t": 50, "b": 60},
        },
    }

    significant_count = sum(1 for r in rows if r["is_significant"])
    suggestive_count = sum(1 for r in rows if r["is_suggestive"])
    peak_snp = max(rows, key=lambda r: r["neg_log_p"])["snp"]

    return {
        "success": True,
        "stats": {
            "total": len(rows),
            "significant": significant_count,
            "suggestive": suggestive_count,
            "peak_snp": peak_snp,
            "max_neg_log_p": round(max_neg_log_p, 2),
        },
        "top_snps": [r["snp"] for r in sorted(rows, key=lambda r: r["neg_log_p"], reverse=True)[:5]],
        "plotly_figure": figure,
    }

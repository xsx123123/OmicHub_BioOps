"""火山图后端轻量 shim。

复用前端 volcanoProcessor.ts 核心逻辑：
- 解析 CSV/TSV/空白分隔表
- 启发式识别 log2FC / padj / gene 列
- 按阈值分组，输出简化 Plotly JSON

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
        delim = None  # 任意空白

    reader: csv.DictReader[str]
    if delim is None:
        # 任意空白分隔：先按空白拆分行，再对齐到 headers
        parsed_lines: list[list[str]] = []
        for line in lines:
            parsed_lines.append(line.split())
        reader = csv.DictReader(
            io.StringIO("\n".join(",".join(cells) for cells in parsed_lines)),
            delimiter=",",
        )
    else:
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
    gene = _find_column(
        cols, ["genename", "gene", "symbol", "feature", "name", "id"]
    ) or (cols[0] if cols else "")
    lfc = _find_column(cols, ["log2foldchange", "log2fc", "logfc", "lfc", "foldchange", "fc"])
    padj = _find_column(cols, ["padj", "padjust", "fdr", "qvalue", "pvalue", "pval", "rawp"])
    return {"gene": gene, "lfc": lfc, "padj": padj}


def _to_float(value: str) -> float:
    if not value or value.strip().lower() in {"na", "nan", "null", "-", ""}:
        return math.nan
    try:
        n = float(value.strip())
        return n if math.isfinite(n) else math.nan
    except ValueError:
        return math.nan


def _build_plotly_figure(
    rows: list[dict[str, Any]],
    pval_cutoff: float,
    lfc_cutoff: float,
) -> dict[str, Any] | None:
    """构造简化 Plotly 火山图。"""
    if not rows:
        return None

    xs: dict[str, list[float]] = {"up": [], "down": [], "non": []}
    ys: dict[str, list[float]] = {"up": [], "down": [], "non": []}
    texts: dict[str, list[str]] = {"up": [], "down": [], "non": []}

    for r in rows:
        group = r["group"]
        xs[group].append(r["log2fc"])
        ys[group].append(r["neg_log10_p"])
        texts[group].append(r["gene"])

    def make_trace(group: str, color: str, name: str) -> dict[str, Any]:
        return {
            "x": xs[group],
            "y": ys[group],
            "text": texts[group],
            "mode": "markers",
            "type": "scatter",
            "name": name,
            "marker": {"color": color, "size": 6, "opacity": 0.7},
            "hovertemplate": (
                "<b>%{text}</b><br>log₂FC: %{x:.3f}<br>"
                "-log₁₀padj: %{y:.3f}<extra></extra>"
            ),
        }

    x_values = [r["log2fc"] for r in rows]
    y_values = [r["neg_log10_p"] for r in rows]
    x_max = min(max(abs(v) for v in x_values) * 1.2, 7.5) if x_values else 1.0
    y_max = max(y_values) * 1.1 if y_values else 1.0

    traces = [
        make_trace("non", "#C7C7C7", f"Non-significant ({len(xs['non'])}))"),
        make_trace("down", "#41b6e6", f"Down ({len(xs['down'])})"),
        make_trace("up", "#e41749", f"Up ({len(xs['up'])})"),
    ]

    shapes = [
        {
            "type": "line",
            "x0": -lfc_cutoff,
            "x1": -lfc_cutoff,
            "y0": 0,
            "y1": y_max,
            "line": {"color": "#666", "width": 1, "dash": "dash"},
        },
        {
            "type": "line",
            "x0": lfc_cutoff,
            "x1": lfc_cutoff,
            "y0": 0,
            "y1": y_max,
            "line": {"color": "#666", "width": 1, "dash": "dash"},
        },
        {
            "type": "line",
            "x0": -x_max,
            "x1": x_max,
            "y0": -math.log10(pval_cutoff),
            "y1": -math.log10(pval_cutoff),
            "line": {"color": "#666", "width": 1, "dash": "dash"},
        },
    ]

    return {
        "data": traces,
        "layout": {
            "title": {"text": "Volcano Plot", "x": 0.5},
            "xaxis": {
                "title": "log₂ fold change",
                "range": [-x_max, x_max],
                "zeroline": False,
            },
            "yaxis": {
                "title": "-log₁₀(padj)",
                "range": [0, y_max],
                "zeroline": False,
            },
            "margin": {"l": 60, "r": 30, "t": 50, "b": 60},
            "legend": {"orientation": "h", "y": -0.2, "x": 0.5, "xanchor": "center"},
            "hovermode": "closest",
            "shapes": shapes,
        },
    }


async def execute(
    user_id: str,
    data_text: str,
    pval_cutoff: float = 0.05,
    lfc_cutoff: float = 1.0,
) -> dict[str, Any]:
    """火山图 shim 执行入口。"""
    if not data_text or not data_text.strip():
        raise ValueError("差异表达表为空")

    raw_rows = _parse_delimited(data_text)
    if not raw_rows:
        raise ValueError("无法解析表格内容")

    cols = list(raw_rows[0].keys())
    col_map = _auto_detect_columns(cols)
    if not col_map["lfc"] or not col_map["padj"]:
        raise ValueError(
            f"未能自动识别 log2FC 或 p-value 列，当前列：{cols}"
        )

    processed: list[dict[str, Any]] = []
    for raw in raw_rows:
        gene = raw.get(col_map["gene"], "").strip()
        fc = _to_float(raw.get(col_map["lfc"], ""))
        p = _to_float(raw.get(col_map["padj"], ""))
        if math.isnan(fc) or math.isnan(p) or not gene:
            continue
        if p <= 0:
            p = 1e-300  # 避免 -log10(0) 无穷
        neg_log10_p = -math.log10(p)
        if p < pval_cutoff and fc > lfc_cutoff:
            group = "up"
        elif p < pval_cutoff and fc < -lfc_cutoff:
            group = "down"
        else:
            group = "non"
        processed.append(
            {
                "gene": gene,
                "log2fc": fc,
                "padj": p,
                "neg_log10_p": neg_log10_p,
                "group": group,
            }
        )

    stats = {
        "total": len(processed),
        "up": sum(1 for r in processed if r["group"] == "up"),
        "down": sum(1 for r in processed if r["group"] == "down"),
        "non": sum(1 for r in processed if r["group"] == "non"),
    }

    # Top 5 显著上下调基因
    sig = [r for r in processed if r["group"] != "non"]
    sig.sort(key=lambda r: r["padj"])
    top_genes = [r["gene"] for r in sig[:10]]

    figure = _build_plotly_figure(processed, pval_cutoff, lfc_cutoff)

    return {
        "success": True,
        "stats": stats,
        "top_up_genes": [r["gene"] for r in processed if r["group"] == "up"][:5],
        "top_down_genes": [r["gene"] for r in processed if r["group"] == "down"][:5],
        "top_genes": top_genes,
        "plotly_figure": figure,
    }

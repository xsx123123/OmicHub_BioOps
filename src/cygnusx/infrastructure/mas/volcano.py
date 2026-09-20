"""Static, workspace-scoped DEG volcano plot rendering for MAS artifact outputs."""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


class VolcanoPlotError(ValueError):
    """Raised when a DEG artifact cannot be rendered as a safe volcano plot."""


@dataclass(frozen=True)
class VolcanoPlotResult:
    png_path: Path
    pdf_path: Path
    total: int
    up: int
    down: int


def render_deg_volcano(
    input_path: Path,
    output_directory: Path,
    *,
    pvalue_cutoff: float = 0.05,
    log2fc_cutoff: float = 1.0,
) -> VolcanoPlotResult:
    if not 0 < pvalue_cutoff <= 1 or log2fc_cutoff <= 0:
        raise VolcanoPlotError("invalid volcano plot thresholds")
    rows = _read_rows(input_path)
    lfc_column, pvalue_column = _find_columns(rows[0])
    processed: list[tuple[float, float, str]] = []
    for row in rows:
        try:
            log2fc = float(row[lfc_column])
            pvalue = max(float(row[pvalue_column]), 1e-300)
        except (KeyError, TypeError, ValueError):
            continue
        if not math.isfinite(log2fc) or not math.isfinite(pvalue) or pvalue < 0:
            continue
        group = "non"
        if pvalue < pvalue_cutoff and log2fc > log2fc_cutoff:
            group = "up"
        elif pvalue < pvalue_cutoff and log2fc < -log2fc_cutoff:
            group = "down"
        processed.append((log2fc, -math.log10(pvalue), group))
    if not processed:
        raise VolcanoPlotError("DEG artifact has no usable numeric rows")

    output_directory.mkdir(parents=True, exist_ok=True)
    png_path = output_directory / "deg-volcano.png"
    pdf_path = output_directory / "deg-volcano.pdf"
    figure, axis = plt.subplots(figsize=(8, 6), dpi=150)
    colors = {"non": "#9ca3af", "up": "#dc2626", "down": "#2563eb"}
    for group in ("non", "up", "down"):
        points = [(x, y) for x, y, point_group in processed if point_group == group]
        if points:
            axis.scatter(*zip(*points), s=10, alpha=0.65, c=colors[group], label=group)
    axis.axhline(-math.log10(pvalue_cutoff), color="#6b7280", linestyle="--", linewidth=0.8)
    axis.axvline(log2fc_cutoff, color="#6b7280", linestyle="--", linewidth=0.8)
    axis.axvline(-log2fc_cutoff, color="#6b7280", linestyle="--", linewidth=0.8)
    axis.set(title="Differential Expression Volcano Plot", xlabel="log₂ fold change", ylabel="−log₁₀ p-value")
    axis.legend(frameon=False)
    figure.tight_layout()
    figure.savefig(png_path, format="png")
    figure.savefig(pdf_path, format="pdf")
    plt.close(figure)
    return VolcanoPlotResult(
        png_path=png_path,
        pdf_path=pdf_path,
        total=len(processed),
        up=sum(group == "up" for _, _, group in processed),
        down=sum(group == "down" for _, _, group in processed),
    )


def _read_rows(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        raise VolcanoPlotError("DEG artifact does not exist")
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            sample = handle.read(8192)
            handle.seek(0)
            delimiter = "\t" if sample.count("\t") > sample.count(",") else ","
            rows = list(csv.DictReader(handle, delimiter=delimiter))
    except OSError as exc:
        raise VolcanoPlotError("unable to read DEG artifact") from exc
    if not rows or not rows[0]:
        raise VolcanoPlotError("DEG artifact is empty")
    return rows


def _find_columns(row: dict[str, str]) -> tuple[str, str]:
    normalized = {key.lower().replace("_", "").replace(".", ""): key for key in row}
    lfc = next((normalized[name] for name in ("log2foldchange", "log2fc", "lfc") if name in normalized), None)
    pvalue = next((normalized[name] for name in ("padj", "pvalue", "pval", "fdr") if name in normalized), None)
    if lfc is None or pvalue is None:
        raise VolcanoPlotError("DEG artifact requires log2 fold-change and adjusted p-value columns")
    return lfc, pvalue

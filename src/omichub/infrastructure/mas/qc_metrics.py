"""Extract compact mapping-rate metrics from RNAFlow result files without loading reports into chat."""

from __future__ import annotations

import csv
import statistics
from pathlib import Path


class QCMetricsError(ValueError):
    """Raised when RNAFlow results do not contain a usable mapping-rate table."""


def extract_median_mapping_rate(results_directory: Path) -> float:
    values: list[float] = []
    for candidate in results_directory.rglob("*mapping*general*stats*.txt"):
        values.extend(_mapping_rates_from_table(candidate))
    if not values:
        raise QCMetricsError("RNAFlow mapping summary table was not found or has no mapping-rate values")
    return float(statistics.median(values))


def _mapping_rates_from_table(path: Path) -> list[float]:
    try:
        with path.open(encoding="utf-8", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            delimiter = "\t" if sample.count("\t") >= sample.count(",") else ","
            rows = list(csv.DictReader(handle, delimiter=delimiter))
    except OSError:
        return []
    if not rows or not rows[0]:
        return []
    column = next(
        (
            key
            for key in rows[0]
            if "mapping" in key.lower() or "mapped" in key.lower()
        ),
        None,
    )
    if column is None:
        return []
    rates: list[float] = []
    for row in rows:
        raw = str(row.get(column, "")).strip().rstrip("%")
        try:
            value = float(raw)
        except ValueError:
            continue
        if value > 1:
            value /= 100
        if 0 <= value <= 1:
            rates.append(value)
    return rates

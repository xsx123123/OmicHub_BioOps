"""GO / KEGG 富集工具示例数据契约测试。"""

from __future__ import annotations

import csv
from pathlib import Path


EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "tool_configs" / "enrichments" / "examples"


def test_tomato_gene_list_example_has_a_single_gene_id_column() -> None:
    with (EXAMPLES_DIR / "tomato_gene_list.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.reader(handle))

    assert rows[0] == ["GeneID"]
    assert len(rows) > 2
    assert all(len(row) == 1 and row[0].strip() for row in rows[1:])


def test_tomato_enrichment_result_example_matches_standard_container_columns() -> None:
    with (EXAMPLES_DIR / "tomato_enrichment_result.csv").open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert rows
    assert list(rows[0]) == [
        "Source",
        "ID",
        "Description",
        "GeneRatio",
        "BgRatio",
        "pvalue",
        "p.adjust",
        "qvalue",
        "geneID",
        "Count",
    ]
    assert {row["Source"] for row in rows} == {"GO", "KEGG"}


def test_cop1_hy5_example_contains_1576_unique_gene_ids() -> None:
    path = EXAMPLES_DIR / "cop1_hy5_dependent_1576_gene_list.csv"
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    genes = [row[0].strip() for row in rows[1:] if row and row[0].strip()]
    assert rows[0] == ["GeneID"]
    assert len(genes) == 1576
    assert len(set(genes)) == 1576


def test_cop1_hy5_example_has_real_go_and_kegg_results() -> None:
    path = EXAMPLES_DIR / "cop1_hy5_dependent_1576_enrichment_result.csv"
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))

    assert len(rows) > 20
    assert {row["Source"] for row in rows} == {"GO", "KEGG"}
    assert all(row["qvalue"] for row in rows)

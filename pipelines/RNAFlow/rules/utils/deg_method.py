#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RNAFlow DEG engine router — DESeq2 vs edgeR.

Why this exists
---------------
DESeq2 estimates gene-wise dispersion from biological replicates; with a
single sample per group (a "1v1" contrast) it cannot run at all. edgeR
supports that case explicitly (edgeR User's Guide, "No biological
replicates"): ``exactTest(y, dispersion = bcv^2)`` with a user-supplied
Biological Coefficient of Variation.

Resolution happens ONCE, at parse time in the snakefile (§3, right after
samples/contrasts are loaded), and the outcome is injected into
``config['parameter']['DEG']['METHOD_RESOLVED']`` so every consumer —
rules/10.DEG_Enrichments.smk, datadeliver.py, result_manifest.py — reads
the same source of truth and the output directory (``06.DEG/DESEQ2`` vs
``06.DEG/EDGER``) stays consistent end-to-end.

Contract of run_edger.r vs run_deseq2.r
---------------------------------------
Both scripts share the CLI (-c/-m/-p/-a/-o/--lfc/--pval) and output layout
(``{Treat}_vs_{Control}_DEG.csv`` per contrast, volcano plots,
``All_Contrast_DEG_Statistics.csv``), so swapping the engine needs no
downstream changes beyond the directory name. run_edger.r additionally
accepts ``--bcv`` and internally routes each contrast:
  * both groups >= min replicates -> estimateDisp + QL F-test
  * otherwise (1v1)               -> exactTest at the fixed BCV
"""

from collections import Counter
from typing import Dict, List, Optional

VALID_METHODS = ("auto", "deseq2", "edger")
DEFAULT_MIN_REPLICATES = 2


def no_replicate_contrasts(
    samples: Optional[Dict],
    all_contrasts: Optional[List[str]],
    min_replicates: int = DEFAULT_MIN_REPLICATES,
) -> List[str]:
    """Return contrast names ('{Control}_vs_{Treat}', the load_contrasts
    convention) whose smallest group has fewer than ``min_replicates``
    samples. Groups missing from the sample sheet count as 0."""
    group_counts = Counter(
        (info or {}).get("group") for info in (samples or {}).values()
    )
    flagged = []
    for name in all_contrasts or []:
        if "_vs_" not in name:
            continue
        ctrl, treat = name.split("_vs_", 1)
        smallest = min(group_counts.get(ctrl, 0), group_counts.get(treat, 0))
        if smallest < min_replicates:
            flagged.append(name)
    return flagged


def resolve_deg_method(
    config: Optional[Dict],
    samples: Optional[Dict],
    all_contrasts: Optional[List[str]],
    logger=None,
    min_replicates: int = DEFAULT_MIN_REPLICATES,
) -> str:
    """Resolve the DEG engine for this run -> 'deseq2' | 'edger'.

    Honours ``config['parameter']['DEG']['METHOD']``:
      * 'deseq2' / 'edger' — forced (a warning is logged if forcing deseq2
        while no-replicate contrasts exist, since DESeq2 will fail on them);
      * 'auto' (default)   — deseq2 when every contrast has replicates in
        both groups, edger otherwise (edgeR then handles replicated contrasts
        with its standard QL F-test, so one engine covers the whole run).
    """
    deg_cfg = (config or {}).get("parameter", {}).get("DEG", {}) or {}
    requested = str(deg_cfg.get("METHOD", "auto")).strip().lower()

    def info(msg: str):
        if logger is not None:
            logger.info(msg)
        else:
            print(msg)

    def warn(msg: str):
        if logger is not None:
            logger.warning(msg)
        else:
            print(f"WARNING: {msg}")

    if requested not in VALID_METHODS:
        warn(
            f"[DEG] unknown METHOD '{requested}' "
            f"(expected one of {VALID_METHODS}); falling back to 'auto'"
        )
        requested = "auto"

    flagged = no_replicate_contrasts(samples, all_contrasts, min_replicates)

    if requested == "edger":
        info("[DEG] method forced by config: edger")
        return "edger"

    if requested == "deseq2":
        if flagged:
            warn(
                "[DEG] method forced to deseq2, but these contrasts have no "
                f"biological replicates and WILL FAIL under DESeq2: {flagged}. "
                "Set parameter.DEG.METHOD: auto (or edger) to support 1v1."
            )
        else:
            info("[DEG] method forced by config: deseq2")
        return "deseq2"

    # auto
    if flagged:
        info(
            "[DEG] no-replicate (1v1) contrasts detected: "
            f"{flagged} -> routing DEG to edgeR (fixed-BCV exactTest); "
            "replicated contrasts in the same run use edgeR QL F-test."
        )
        return "edger"
    info("[DEG] all contrasts have biological replicates -> DESeq2")
    return "deseq2"


def deg_dirname(method: str) -> str:
    """Output sub-directory name under 06.DEG/ — keeps the legacy layout
    ('DESEQ2') and adds 'EDGER' for the new engine."""
    return str(method).upper()

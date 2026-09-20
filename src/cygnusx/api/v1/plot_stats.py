"""Statistical helpers for interactive plotting tools."""

from itertools import combinations
from typing import Literal

import numpy as np
from fastapi import APIRouter
from pydantic import BaseModel, Field, model_validator
import scikit_posthocs as sp
from statsmodels.stats.multicomp import pairwise_tukeyhsd
from statsmodels.stats.multitest import multipletests

from cygnusx.api.deps import CurrentUserId

router = APIRouter()


class PosthocRequest(BaseModel):
    """Raw repeated observations grouped by treatment."""

    groups: dict[str, list[float]] = Field(min_length=3, max_length=12)
    method: Literal["tukey", "dunn"]
    adjust: Literal["none", "bonferroni", "fdr_bh"] = "fdr_bh"

    @model_validator(mode="after")
    def validate_groups(self) -> "PosthocRequest":
        if any(len(values) < 2 for values in self.groups.values()):
            raise ValueError("Each group requires at least two observations.")
        if not all(np.isfinite(value) for values in self.groups.values() for value in values):
            raise ValueError("Group values must be finite numbers.")
        return self


def _adjust(pvalues: list[float], method: str) -> list[float]:
    if method == "none":
        return pvalues
    return list(multipletests(pvalues, method=method)[1])


def _compact_letters(group_names: list[str], means: dict[str, float], pvalues: dict[tuple[str, str], float]) -> dict[str, str]:
    """Greedy compact-letter display: shared letters represent non-significance."""

    ordered = sorted(group_names, key=lambda name: means[name], reverse=True)
    letter_sets: list[list[str]] = []
    result: dict[str, list[str]] = {name: [] for name in ordered}
    for group in ordered:
        for holders in letter_sets:
            if all(pvalues[tuple(sorted((group, holder)))] >= 0.05 for holder in holders):
                holders.append(group)
                result[group].append(chr(ord("a") + letter_sets.index(holders)))
        if not result[group]:
            letter_sets.append([group])
            result[group].append(chr(ord("a") + len(letter_sets) - 1))
    return {group: "".join(letters) for group, letters in result.items()}


@router.post("/posthoc", summary="Plot grouped post-hoc comparisons")
async def posthoc_comparisons(payload: PosthocRequest, _: CurrentUserId) -> dict:
    """Return adjusted pairwise p-values and compact-letter group labels."""

    group_names = list(payload.groups)
    comparisons = list(combinations(group_names, 2))
    if payload.method == "tukey":
        observations = np.concatenate([payload.groups[name] for name in group_names])
        labels = np.concatenate([[name] * len(payload.groups[name]) for name in group_names])
        tukey = pairwise_tukeyhsd(observations, labels)
        raw = {
            tuple(sorted((str(row[0]), str(row[1])))): float(row[3])
            for row in tukey._results_table.data[1:]
        }
    else:
        dunn_matrix = sp.posthoc_dunn([payload.groups[name] for name in group_names], p_adjust=None)
        raw = {
            tuple(sorted(pair)): float(dunn_matrix.iloc[group_names.index(pair[0]), group_names.index(pair[1])])
            for pair in comparisons
        }
    adjusted = _adjust([raw[tuple(sorted(pair))] for pair in comparisons], payload.adjust)
    pvalues = {tuple(sorted(pair)): value for pair, value in zip(comparisons, adjusted, strict=True)}
    means = {name: float(np.mean(values)) for name, values in payload.groups.items()}
    return {
        "method": payload.method,
        "adjust": payload.adjust,
        "comparisons": [
            {"group_a": left, "group_b": right, "p_value": pvalues[tuple(sorted((left, right)))]}
            for left, right in comparisons
        ],
        "letters": _compact_letters(group_names, means, pvalues),
    }

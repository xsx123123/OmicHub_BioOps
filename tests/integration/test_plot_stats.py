"""Focused handler tests for plotting statistics."""

import pytest

from cygnusx.api.v1.plot_stats import PosthocRequest, posthoc_comparisons


@pytest.mark.unit
@pytest.mark.parametrize("method", ["tukey", "dunn"])
async def test_posthoc_returns_pairwise_pvalues_and_letters(method):
    payload = PosthocRequest(
        groups={
            "Control": [1.0, 1.2, 0.9],
            "Treatment_A": [4.0, 4.3, 3.8],
            "Treatment_B": [2.0, 2.2, 1.8],
        },
        method=method,
        adjust="fdr_bh",
    )

    result = await posthoc_comparisons(payload, "00000000-0000-0000-0000-000000000001")

    assert result["method"] == method
    assert result["adjust"] == "fdr_bh"
    assert len(result["comparisons"]) == 3
    assert set(result["letters"]) == {"Control", "Treatment_A", "Treatment_B"}
    assert all(0 <= item["p_value"] <= 1 for item in result["comparisons"])

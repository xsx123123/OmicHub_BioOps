import pytest

from omichub.domain.mas.quality_gate import (
    QCOverrideRequest,
    QualityGateStatus,
    apply_qc_override,
    evaluate_mapping_rate,
)
from omichub.infrastructure.mas.qc_metrics import extract_median_mapping_rate


def test_mapping_rate_at_thirty_percent_requires_review() -> None:
    result = evaluate_mapping_rate(0.30)

    assert result.status == QualityGateStatus.REVIEW_REQUIRED
    assert not result.allows_downstream_visualization


def test_qc_override_is_explicit_and_auditable() -> None:
    result = evaluate_mapping_rate(0.29)
    overridden = apply_qc_override(
        result, QCOverrideRequest(reason="Validated the library quality against experimental controls.")
    )

    assert overridden.status == QualityGateStatus.WARNING
    assert overridden.allows_downstream_visualization
    assert overridden.reason.startswith("qc_override:")
    with pytest.raises(ValueError, match="only review-required"):
        apply_qc_override(
            evaluate_mapping_rate(0.8),
            QCOverrideRequest(reason="This explanation is sufficiently detailed for audit."),
        )


def test_extract_median_mapping_rate_from_rnaflow_style_summary(tmp_path) -> None:
    summary = tmp_path / "multiqc_mapping_general_stats.txt"
    summary.write_text("Sample\tMapping Rate\nA\t20%\nB\t40%\nC\t60%\n")

    assert extract_median_mapping_rate(tmp_path) == 0.4

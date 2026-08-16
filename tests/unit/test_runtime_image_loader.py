from pathlib import Path

import pytest

from omichub.infrastructure.config.runtime_image_loader import (
    RuntimeImageRegistryManager,
    render_runtime_manifest,
)


def test_real_runtime_registry_resolves_profiles():
    config = RuntimeImageRegistryManager("data/ai/runtime_images.yaml").get_config()
    core = config.resolved_profile("analysis-core")
    plot = config.resolved_profile("analysis-plot")
    scrna = config.resolved_profile("analysis-scrna")
    assert core.image == "omichub-analysis:core-2026.07"
    assert core.runtime_uid == 10001
    assert {"python", "r"} <= core.capabilities
    assert {"plotting", "r"} <= plot.capabilities
    assert {
        "r-ggplot2",
        "bioconductor-ggtree",
        "r-ape",
        "r-dplyr",
        "r-stringr",
        "bioconductor-treeio",
        "r-ggrepel",
    } <= set(plot.software)
    assert {"single-cell", "plotting", "r"} <= scrna.capabilities


def test_capability_selection_prefers_smallest_profile():
    config = RuntimeImageRegistryManager("data/ai/runtime_images.yaml").get_config()
    profile_id, _ = config.select({"python", "plotting"}, "studio")
    assert profile_id == "analysis-plot"


def test_profile_must_support_executor_and_capabilities():
    config = RuntimeImageRegistryManager("data/ai/runtime_images.yaml").get_config()
    with pytest.raises(ValueError, match="缺少能力"):
        config.select({"single-cell"}, "studio", "analysis-core")


def test_registered_dockerfiles_exist():
    config = RuntimeImageRegistryManager("data/ai/runtime_images.yaml").get_config()
    for profile in config.profiles.values():
        assert Path(profile.dockerfile).is_file(), profile.dockerfile


def test_runtime_manifest_uses_resolved_software_and_actual_image():
    config = RuntimeImageRegistryManager("data/ai/runtime_images.yaml").get_config()
    profile_id, profile = config.profile_for_image("omichub-analysis:plot-2026.07") or ("", None)

    assert profile_id == "analysis-plot"
    assert profile is not None
    manifest = render_runtime_manifest(profile_id, profile)
    assert "omichub-analysis:plot-2026.07" in manifest
    assert "bioconductor-ggtree" in manifest
    assert "r-ggrepel" in manifest

from pathlib import Path

import pytest

from cygnusx.infrastructure.config.runtime_image_loader import (
    RuntimeImageRegistryManager,
    render_runtime_manifest,
    resolve_studio_image,
)


def test_real_runtime_registry_resolves_profiles():
    config = RuntimeImageRegistryManager("data/ai/runtime_images.yaml").get_config()
    core = config.resolved_profile("analysis-core")
    plot = config.resolved_profile("analysis-plot")
    scrna = config.resolved_profile("analysis-scrna")
    assert core.image == "cygnusx-analysis:core-v0.0.2dev"
    assert core.runtime_uid == 10001
    assert core.runtime_gid == 10001
    assert core.runtime_group == "cygnusx-sandbox"
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

    assert "base" not in config.profiles


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


def test_resolve_studio_image_keeps_agent_profile_and_does_not_apply_global_default():
    """Agent image/profile 优先；无画像才返回 None 交给调用方决定兜底。"""
    assert resolve_studio_image({"image": "cygnusx-custom:plot"}) == "cygnusx-custom:plot"
    assert resolve_studio_image({"runtime_profile": "analysis-plot"}) == (
        "cygnusx-analysis:plot-v0.0.2dev"
    )
    assert resolve_studio_image({}) is None


def test_runtime_manifest_uses_resolved_software_and_actual_image():
    config = RuntimeImageRegistryManager("data/ai/runtime_images.yaml").get_config()
    profile_id, profile = config.profile_for_image("cygnusx-analysis:plot-v0.0.2dev") or ("", None)

    assert profile_id == "analysis-plot"
    assert profile is not None
    manifest = render_runtime_manifest(profile_id, profile)
    assert "cygnusx-analysis:plot-v0.0.2dev" in manifest
    assert "bioconductor-ggtree" in manifest
    assert "r-ggrepel" in manifest


def test_all_registered_profiles_selectable_for_studio_executor():
    """AI 助手页运行时选择器依赖：5 个 profile 都必须能被 studio 执行器显式选中。"""
    config = RuntimeImageRegistryManager("data/ai/runtime_images.yaml").get_config()
    expected_images = {
        "analysis-core": "cygnusx-analysis:core-v0.0.2dev",
        "analysis-plot": "cygnusx-analysis:plot-v0.0.2dev",
        "analysis-scrna": "cygnusx-analysis:scrna-v0.0.3dev",
        "bio": "cygnusx-sandbox-bio:v0.0.2dev",
        "browser-office": "cygnusx-sandbox-browser-office:v0.0.2dev",
    }
    for profile_id, image in expected_images.items():
        selected_id, profile = config.select(set(), "studio", preferred_profile=profile_id)
        assert selected_id == profile_id
        assert profile.image == image
        assert (profile.runtime_uid, profile.runtime_gid, profile.runtime_group) == (
            10001,
            10001,
            "cygnusx-sandbox",
        )

    with pytest.raises(KeyError):
        config.select(set(), "studio", preferred_profile="omichub-sandbox")

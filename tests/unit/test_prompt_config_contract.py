from pathlib import Path

import yaml

from cygnusx.infrastructure.config.prompt_loader import PromptRegistry
from cygnusx.infrastructure.config.runtime_image_loader import RuntimeImageRegistryManager


def test_all_registered_prompt_files_exist():
    registry = PromptRegistry("data/ai/prompts/registry.yaml")
    raw = yaml.safe_load(Path("data/ai/prompts/registry.yaml").read_text(encoding="utf-8"))
    for key in raw["prompts"]:
        definition = registry.definition(key)
        assert definition is not None
        assert (registry.root / definition.file).is_file(), key


def test_all_enabled_agents_use_external_prompt_files():
    site = yaml.safe_load(Path("data/CygnusX.yaml").read_text(encoding="utf-8"))
    for name in site["agents"]["enabled"]:
        agent_path = Path(f"data/ai/{name}.yaml")
        agent = yaml.safe_load(agent_path.read_text(encoding="utf-8"))
        assert "system_prompt" not in agent, name
        prompt_path = agent_path.parent / agent["prompt_file"]
        assert prompt_path.is_file(), name
        assert prompt_path.read_text(encoding="utf-8").strip(), name
        # 智能路由器（features.router）是纯分派入口，无 Studio 工作台
        if (agent.get("features") or {}).get("router"):
            continue
        studio = agent.get("studio")
        assert isinstance(studio, dict) and studio.get("enabled") is True, name
        runtime = RuntimeImageRegistryManager("data/ai/runtime_images.yaml").get_config()
        runtime.select(
            set(studio.get("required_capabilities", [])),
            "studio",
            studio["runtime_profile"],
        )


def test_runtime_catalog_placeholder_is_owned_by_agent_loader():
    prompt = Path("data/ai/prompts/shared/sandbox_protocol.md").read_text(encoding="utf-8")
    assert "{{runtime_images}}" in prompt
    assert "{{bio_packages}}" in prompt
    assert "output/environment.yml" in prompt
    assert "output/conda-explicit.txt" in prompt
    assert "output/software-versions.txt" in prompt


def test_bio_package_catalog_has_marked_sections_and_sandbox_safe_guidance():
    catalog = Path("data/ai/bio_packages.md").read_text(encoding="utf-8")
    expected_catalogs = {
        "genomics",
        "rnaseq",
        "scrna",
        "r-bio",
        "epigenomics",
        "proteomics",
        "microbiome",
        "variants",
        "phylo",
        "enrichment",
        "io",
        "visualization",
        "machine-learning",
        "network",
        "cheminformatics",
    }
    for catalog_id in expected_catalogs:
        assert f"<!-- package-catalog: {catalog_id} -->" in catalog
    assert "| `pip install" not in catalog
    assert "micromamba-forge" not in catalog
    assert "biomicromamba" not in catalog

from __future__ import annotations

import os
from pathlib import Path

from cygnusx.tools.phylogenetic_tree.config import PhyloConfigManager


def _write(path: Path, content: str, mtime_ns: int) -> None:
    path.write_text(content, encoding="utf-8")
    os.utime(path, ns=(mtime_ns, mtime_ns))


def test_phylo_config_parses_typed_values(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    defaults_path = tmp_path / "defaults.yaml"
    _write(
        config_path,
        """
execution:
  celery: {queue: phylo_tree_highmem, time_limit_seconds: 900, soft_time_limit_seconds: 600}
  resources: {default_threads: 8, max_threads: 16, max_memory_mb: 4096}
supported_methods:
  alignment_tools: [{key: mafft, label: MAFFT}]
  tree_methods: [{key: iqtree, label: IQ-TREE, supports_bootstrap: true}]
  substitution_models: {dna: [GTR, auto]}
  bootstrap_types: [{key: ultrafast, label: UFBoot}]
""",
        1_000_000_000,
    )
    _write(defaults_path, "defaults: {}\n", 1_000_000_000)

    manager = PhyloConfigManager(config_path, defaults_path)
    config = manager.get_config()

    assert config.execution.celery.queue == "phylo_tree_highmem"
    assert config.execution.resources.default_threads == 8
    assert config.supported_methods.tree_methods[0].supports_bootstrap is True


def test_phylo_config_invalid_yaml_falls_back_safely(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    defaults_path = tmp_path / "defaults.yaml"
    _write(config_path, "execution: [invalid\n", 1_000_000_000)
    _write(defaults_path, "defaults: {}\n", 1_000_000_000)

    manager = PhyloConfigManager(config_path, defaults_path)
    config = manager.get_config()

    assert config.execution.celery.queue == "phylo_tree"
    assert {item.key for item in config.supported_methods.tree_methods} >= {"nj", "iqtree"}
    assert manager.last_error is not None


def test_phylo_config_hot_reloads_on_mtime_change(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    defaults_path = tmp_path / "defaults.yaml"
    _write(config_path, "execution: {resources: {default_threads: 2}}\n", 1_000_000_000)
    _write(defaults_path, "defaults: {}\n", 1_000_000_000)
    manager = PhyloConfigManager(config_path, defaults_path)

    assert manager.get_config().execution.resources.default_threads == 2

    _write(config_path, "execution: {resources: {default_threads: 6}}\n", 2_000_000_000)

    assert manager.get_config().execution.resources.default_threads == 6

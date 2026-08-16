"""Studio 配置加载器单元测试"""

from pathlib import Path

import pytest

from omichub.core.config import get_settings
from omichub.infrastructure.config.studio_loader import (
    StudioConfig,
    StudioConfigManager,
)


def _write_yaml(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")


@pytest.mark.unit
def test_loads_defaults_when_file_missing(tmp_path: Path):
    """配置文件缺失时回退内置默认，不抛异常"""
    manager = StudioConfigManager(config_path=tmp_path / "not-exist.yaml")
    config = manager.get_config()
    assert config.enabled is True
    assert config.default_image == "omichub-analysis:core-2026.07"
    assert config.session.idle_ttl_minutes == 30
    assert config.session.workspace_retention_days == 7
    assert config.session.prewarm_on_create is True
    assert config.sandbox.cpu == 2
    assert config.sandbox.memory == "4g"
    assert config.sandbox.exec_timeout_seconds == 600
    assert config.sandbox.network.mode == "none"
    assert config.sandbox.network.docker_network == "omichub-studio-egress"
    assert config.sandbox.network.proxy_container == "omichub-studio-egress-proxy"
    assert config.sandbox.network.proxy_host == "studio-egress-proxy"
    assert config.sandbox.network.proxy_port == 3128


@pytest.mark.unit
def test_parses_studio_section(tmp_path: Path):
    """正确解析 studio 段并忽略未知字段"""
    yaml_path = tmp_path / "studio.yaml"
    _write_yaml(
        yaml_path,
        """
studio:
  enabled: true
  default_image: omichub-sandbox:base
  session:
    idle_ttl_minutes: 15
    prewarm_on_create: false
  sandbox:
    cpu: 4
    memory: 8g
    network:
      mode: whitelist
      docker_network: custom-sandbox-net
      allow: [pypi.org]
  images:
    base: {dockerfile: deploy/studio/base.Dockerfile}
other_key: ignored
""",
    )
    config = StudioConfigManager(config_path=yaml_path).get_config()
    assert config.default_image == "omichub-sandbox:base"
    assert config.session.idle_ttl_minutes == 15
    assert config.session.prewarm_on_create is False
    assert config.sandbox.cpu == 4
    assert config.sandbox.memory == "8g"
    assert config.sandbox.network.mode == "whitelist"
    assert config.sandbox.network.docker_network == "custom-sandbox-net"
    assert config.sandbox.network.allow == ["pypi.org"]
    assert config.images["base"].dockerfile == "deploy/studio/base.Dockerfile"


@pytest.mark.unit
def test_invalid_yaml_falls_back_to_defaults(tmp_path: Path):
    """YAML 解析失败 / 结构非法时回退默认配置"""
    yaml_path = tmp_path / "studio.yaml"
    _write_yaml(yaml_path, "studio: [not, a, mapping")
    config = StudioConfigManager(config_path=yaml_path).get_config()
    assert config == StudioConfig()


@pytest.mark.unit
def test_hot_reload_on_mtime_change(tmp_path: Path):
    """文件 mtime 变化后自动热重载"""
    yaml_path = tmp_path / "studio.yaml"
    _write_yaml(yaml_path, "studio:\n  default_image: img:v1\n")
    manager = StudioConfigManager(config_path=yaml_path)
    assert manager.get_config().default_image == "img:v1"

    import os

    _write_yaml(yaml_path, "studio:\n  default_image: img:v2\n")
    os.utime(yaml_path, (manager._mtime + 10, manager._mtime + 10))
    assert manager.get_config().default_image == "img:v2"


@pytest.mark.unit
def test_workspace_root_resolves_storage_path_placeholder():
    """mounts.workspace 的 {storage_path} 占位符解析为 settings.storage_path"""
    config = StudioConfig()
    expected = Path(get_settings().storage_path) / "studio"
    assert config.workspace_root == expected

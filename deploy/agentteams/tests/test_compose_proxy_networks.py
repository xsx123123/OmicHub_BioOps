from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[3]
PROXY_COMPOSE = ROOT / "deploy/agentteams/docker-compose.cygnusx-proxy.yml"


def test_web_proxy_override_preserves_existing_networks() -> None:
    payload = yaml.safe_load(PROXY_COMPOSE.read_text(encoding="utf-8"))
    networks = payload["services"]["web"]["networks"]

    assert set(networks) == {
        "app_net",
        "data_net",
        "cygnusx_net",
        "cygnusx-sandbox-net",
        "cygnusx_bridge_gateway",
    }


def test_proxy_networks_are_external_and_do_not_create_replacements() -> None:
    payload = yaml.safe_load(PROXY_COMPOSE.read_text(encoding="utf-8"))
    networks = payload["networks"]

    for network in ("app_net", "data_net", "cygnusx_net", "cygnusx-sandbox-net"):
        assert networks[network]["external"] is True
    assert networks["app_net"]["name"] == "docker_app_net"
    assert networks["data_net"]["name"] == "docker_data_net"
    assert networks["cygnusx_bridge_gateway"]["external"] is True

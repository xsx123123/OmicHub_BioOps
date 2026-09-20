from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[3]
AGENTTEAMS_COMPOSE = ROOT / "deploy/agentteams/docker-compose.agentteams.yml"
MAIN_COMPOSE = ROOT / "deploy/docker/docker-compose.yml"


def test_main_compose_exposes_private_agentteams_bucket() -> None:
    payload = yaml.safe_load(MAIN_COMPOSE.read_text(encoding="utf-8"))
    services = payload["services"]

    assert set(services["minio"]["networks"]) == {"data_net", "cygnusx_net"}
    assert services["minio"]["ports"] == [
        "${CYGNUSX_MINIO_BIND_HOST:-127.0.0.1}:${CYGNUSX_MINIO_PORT:-9000}:9000",
        "${CYGNUSX_MINIO_BIND_HOST:-127.0.0.1}:${CYGNUSX_MINIO_CONSOLE_PORT:-9001}:9001",
    ]
    init_command = " ".join(services["minio-init"]["command"])
    assert "mc mb --ignore-existing" in init_command
    assert "mc anonymous set none" in init_command


def test_bridge_holds_no_minio_credentials() -> None:
    """M6: the Bridge never consumes MinIO credentials, so none may be injected."""
    payload = yaml.safe_load(AGENTTEAMS_COMPOSE.read_text(encoding="utf-8"))
    bridge = payload["services"]["cygnusx-agentteams-bridge"]

    assert "cygnusx_net" in bridge["networks"]
    assert bridge["environment"] == {
        "BRIDGE_CASE_GC_DAYS": "${BRIDGE_CASE_GC_DAYS:-7}",
    }
    assert not any("MINIO" in key for key in bridge["environment"])
    assert payload["networks"]["cygnusx_net"] == {
        "name": "cygnusx_net",
        "external": True,
    }

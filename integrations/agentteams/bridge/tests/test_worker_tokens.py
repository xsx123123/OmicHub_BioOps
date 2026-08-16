from __future__ import annotations

import asyncio
import json
import os
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException

from omichub_agentteams_bridge.app import create_app
from omichub_agentteams_bridge.config import BridgeSettings
from omichub_agentteams_bridge.security import require_identity
from omichub_agentteams_bridge.worker_tokens import WorkerTokenStore


class FixtureOmicHubClient:
    async def aclose(self) -> None:
        return None


class LoopLocalASGIClient:
    """Create the Bridge app and HTTPX transport inside each test event loop."""

    def __init__(self, settings: BridgeSettings) -> None:
        self._settings = settings
        self._clients: dict[asyncio.AbstractEventLoop, httpx.AsyncClient] = {}

    def _client(self) -> httpx.AsyncClient:
        loop = asyncio.get_running_loop()
        if loop not in self._clients:
            bridge = create_app(self._settings, FixtureOmicHubClient())
            self._clients[loop] = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=bridge), base_url="http://bridge.test"
            )
        return self._clients[loop]

    async def get(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self._client().get(*args, **kwargs)

    async def post(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self._client().post(*args, **kwargs)

    async def delete(self, *args: Any, **kwargs: Any) -> httpx.Response:
        return await self._client().delete(*args, **kwargs)


@pytest.fixture
def settings(tmp_path):
    return BridgeSettings(
        omichub_base_url="http://omic.test",
        omichub_service_token="service-token",
        approval_signing_secret="test-signing-secret",
        identities="bioops-manager:manager,agent-code:code,agent-viz:viz",
        allowed_flow_ids="rna_seq",
        role_agent_map="agent-code:agent-code,agent-viz:agent-viz",
        audit_log_path=str(tmp_path / "audit.jsonl"),
        case_store_path=str(tmp_path / "cases.json"),
        worker_token_store_path=str(tmp_path / "worker-tokens.json"),
        manifest_dir=str(tmp_path / "manifests"),
    )


@pytest.fixture
def client(settings):
    return LoopLocalASGIClient(settings)


MANAGER_HEADERS = {"X-Bridge-Identity": "bioops-manager", "X-Bridge-Token": "manager"}


async def _issue(client, identity: str = "agent-code", **payload: Any) -> dict:
    response = await client.post(
        "/v1/worker-tokens",
        json={"identity": identity, **payload},
        headers=MANAGER_HEADERS,
    )
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.asyncio
async def test_issue_token_returns_raw_value_once_and_redacted_record(client) -> None:
    issued = await _issue(client, note="pool-1", ttl_seconds=3600)

    assert issued["token"].startswith("omw_")
    record = issued["record"]
    assert record["identity"] == "agent-code"
    assert record["note"] == "pool-1"
    assert record["expires_at"] is not None
    assert "token_hash" not in record
    assert issued["token"] not in json.dumps(record)


@pytest.mark.asyncio
async def test_worker_token_authenticates_and_lists_redacted(client) -> None:
    issued = await _issue(client)

    inbox = await client.get(
        "/v1/work-items/assigned",
        headers={"X-Bridge-Identity": "agent-code", "X-Bridge-Token": issued["token"]},
    )
    assert inbox.status_code == 200

    listing = await client.get("/v1/worker-tokens", headers=MANAGER_HEADERS)
    assert listing.status_code == 200
    items = listing.json()["items"]
    assert len(items) == 1
    assert items[0]["identity"] == "agent-code"
    assert items[0]["revoked_at"] is None
    assert "token_hash" not in items[0]
    assert issued["token"] not in json.dumps(items)


@pytest.mark.asyncio
async def test_worker_token_identity_binding_blocks_spoofing(client) -> None:
    issued = await _issue(client, identity="agent-code")

    spoofed = await client.get(
        "/v1/work-items/assigned",
        headers={"X-Bridge-Identity": "agent-viz", "X-Bridge-Token": issued["token"]},
    )
    assert spoofed.status_code == 403


@pytest.mark.asyncio
async def test_revoked_token_is_rejected_immediately(client) -> None:
    issued = await _issue(client)
    headers = {"X-Bridge-Identity": "agent-code", "X-Bridge-Token": issued["token"]}
    assert (await client.get("/v1/work-items/assigned", headers=headers)).status_code == 200

    revoke = await client.delete(
        f"/v1/worker-tokens/{issued['record']['token_id']}", headers=MANAGER_HEADERS
    )
    assert revoke.status_code == 200
    assert revoke.json()["revoked_at"] is not None

    assert (await client.get("/v1/work-items/assigned", headers=headers)).status_code == 401


@pytest.mark.asyncio
async def test_static_shared_secret_still_works_alongside_worker_tokens(client) -> None:
    await _issue(client)

    inbox = await client.get(
        "/v1/work-items/assigned",
        headers={"X-Bridge-Identity": "agent-code", "X-Bridge-Token": "code"},
    )
    assert inbox.status_code == 200


@pytest.mark.asyncio
async def test_issue_requires_manager_and_known_identity(client) -> None:
    denied = await client.post(
        "/v1/worker-tokens",
        json={"identity": "agent-viz"},
        headers={"X-Bridge-Identity": "agent-code", "X-Bridge-Token": "code"},
    )
    assert denied.status_code == 403

    unknown = await client.post(
        "/v1/worker-tokens", json={"identity": "ghost-worker"}, headers=MANAGER_HEADERS
    )
    assert unknown.status_code == 422

    missing = await client.get("/v1/worker-tokens")
    assert missing.status_code == 401


@pytest.mark.asyncio
async def test_token_store_persists_to_json_and_reload(tmp_path) -> None:
    path = str(tmp_path / "worker-tokens.json")
    store = WorkerTokenStore(path)
    token, record = await store.issue(identity="agent-code", note="persisted")

    reloaded = WorkerTokenStore(path)
    found = await reloaded.lookup(token)
    assert found is not None
    assert found.token_id == record.token_id
    assert found.identity == "agent-code"
    assert json.dumps(record.model_dump(mode="json")) not in token


@pytest.mark.asyncio
async def test_expired_token_is_rejected(tmp_path, settings) -> None:
    path = str(tmp_path / "worker-tokens.json")
    store = WorkerTokenStore(path)
    token, record = await store.issue(identity="agent-code", ttl_seconds=60)

    raw = json.loads((tmp_path / "worker-tokens.json").read_text(encoding="utf-8"))
    raw[record.token_id]["expires_at"] = (
        datetime.now(UTC) - timedelta(seconds=1)
    ).isoformat()
    (tmp_path / "worker-tokens.json").write_text(json.dumps(raw), encoding="utf-8")

    expired_store = WorkerTokenStore(path)
    with pytest.raises(HTTPException) as excinfo:
        await require_identity(settings, expired_store, "agent-code", token)
    assert excinfo.value.status_code == 401


REDIS_URL = os.getenv("AGENTTEAMS_TEST_REDIS_URL")


@pytest.mark.skipif(not REDIS_URL, reason="set AGENTTEAMS_TEST_REDIS_URL to run Redis integration tests")
@pytest.mark.asyncio
async def test_token_store_shared_across_replicas_via_redis(tmp_path) -> None:
    key_prefix = f"omichub:agentteams:test:{uuid4().hex}:worker-tokens"
    first = WorkerTokenStore(str(tmp_path / "first.json"), REDIS_URL or "", key_prefix)
    second = WorkerTokenStore(str(tmp_path / "second.json"), REDIS_URL or "", key_prefix)
    try:
        token, record = await first.issue(identity="agent-code")
        assert (await second.lookup(token)).token_id == record.token_id  # type: ignore[union-attr]
        await second.revoke(record.token_id)
        revoked = await first.lookup(token)
        assert revoked is not None and revoked.revoked_at is not None
    finally:
        await first.aclose()
        await second.aclose()

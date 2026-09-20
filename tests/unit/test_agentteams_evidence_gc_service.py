from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from cygnusx.application.services.agentteams_evidence_gc_service import (
    AgentTeamsEvidenceGcService,
)
from cygnusx.core.config import Settings


def test_gc_removes_only_expired_closed_cases(monkeypatch) -> None:
    now = datetime(2026, 8, 11, tzinfo=UTC)

    class Cases:
        async def admin_resource_snapshot(self):
            return {
                "cases": [
                    {"case_id": "old", "status": "closed", "updated_at": (now - timedelta(days=31)).isoformat()},
                    {"case_id": "new", "status": "closed", "updated_at": now.isoformat()},
                    {"case_id": "active", "status": "running", "updated_at": (now - timedelta(days=90)).isoformat()},
                ]
            }

    class Store:
        def __init__(self):
            self.deleted = []

        def delete_case_prefix(self, case_id: str, *, preserve_delivery: bool):
            self.deleted.append((case_id, preserve_delivery))

    store = Store()
    service = AgentTeamsEvidenceGcService(
        settings=Settings(agentteams_evidence_retention_days=30),
        case_service=Cases(),
        minio_store=store,
    )
    monkeypatch.setattr(service, "_clean_local_workdir", lambda case_id: None)

    result = asyncio.run(service.cleanup(now=now))

    assert result["removed_cases"] == ["old"]
    assert store.deleted == [("old", True)]

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from omichub.application.services.mas_task_projection import MASTaskProjection


class _ProjectionRepository:
    def __init__(self, run: SimpleNamespace, nodes: list[SimpleNamespace]) -> None:
        self.run = run
        self.nodes = nodes

    async def list_runs_for_user(self, user_id):
        return [self.run] if user_id == self.run.user_id else []

    async def get_run_for_user(self, run_id, user_id):
        if run_id == self.run.id and user_id == self.run.user_id:
            return self.run
        return None

    async def list_nodes(self, run_id):
        return self.nodes if run_id == self.run.id else []

    async def get_plan_for_run(self, run_id):
        if run_id == self.run.id:
            return SimpleNamespace(plan_json={"title": "RNAFlow + QC"})
        return None


@pytest.mark.asyncio
async def test_projection_maps_mas_run_to_task_center_response_and_dag() -> None:
    now = datetime.now(UTC)
    run = SimpleNamespace(
        id=uuid4(),
        user_id=uuid4(),
        status="running",
        context_summary={"accession": "PRJNA000001"},
        created_at=now,
        updated_at=now,
        finished_at=None,
    )
    nodes = [
        SimpleNamespace(
            node_key="download",
            agent_id="agent-rnaseq",
            intent="download",
            status="succeeded",
            attempt_count=1,
            depends_on=[],
        ),
        SimpleNamespace(
            node_key="rnaseq",
            agent_id="agent-rnaseq",
            intent="analyse",
            status="running",
            attempt_count=1,
            depends_on=["download"],
        ),
    ]
    projection = MASTaskProjection(_ProjectionRepository(run, nodes))

    task = await projection.get_for_user(run.id, run.user_id)
    dag = await projection.dag_for_user(run.id, run.user_id)

    assert task is not None
    assert task.flow_id == "mas"
    assert task.status == "running"
    assert task.progress == 0.5
    assert task.name == "RNAFlow + QC"
    assert task.parameters["mas_status"] == "running"
    assert dag == {
        "kind": "mas",
        "run_id": str(run.id),
        "status": "running",
        "nodes": [
            {
                "id": "download",
                "label": "download",
                "agent_id": "agent-rnaseq",
                "status": "succeeded",
                "attempt_count": 1,
            },
            {
                "id": "rnaseq",
                "label": "analyse",
                "agent_id": "agent-rnaseq",
                "status": "running",
                "attempt_count": 1,
            },
        ],
        "edges": [{"source": "download", "target": "rnaseq"}],
    }

"""Operational asset contracts for the pgvector/PolarDB rollout."""

from pathlib import Path


def test_pgvector_overlay_includes_pooler_and_exporter() -> None:
    source = Path("deploy/docker/docker-compose.pgvector.yml").read_text(encoding="utf-8")

    assert "image: pgvector/pgvector:pg14" in source
    assert "image: edoburu/pgbouncer:v1.25.2-p0" in source
    assert "pgbouncer:" in source
    assert "postgres-exporter:" in source
    assert "DATA_SOURCE_NAME:" in source


def test_operational_scripts_validate_and_backfill() -> None:
    acceptance = Path("scripts/accept_pgvector_docker.sh").read_text(encoding="utf-8")
    verify = Path("scripts/verify_polardb_postgres.sh").read_text(encoding="utf-8")
    backup = Path("scripts/backup_polardb_postgres.sh").read_text(encoding="utf-8")
    restore = Path("scripts/restore_polardb_postgres.sh").read_text(encoding="utf-8")
    reindex = Path("scripts/reindex_knowledge_vectors.py").read_text(encoding="utf-8")

    assert "pgvector extension is not installed" in verify
    assert "agent_memories HNSW cosine index is missing" in verify
    assert "READONLY_DATABASE_URL is neither read-only" in verify
    assert "require_command psql" in verify
    assert "require_command pg_dump" in backup
    assert "require_command pg_restore" in restore
    assert "KnowledgeIndexService" in reindex
    assert "cygnusx_restore_acceptance" in acceptance
    assert "postgres-exporter:9187/metrics" in acceptance
    assert "READONLY_DATABASE_URL" in acceptance


def test_web_image_contains_operational_scripts() -> None:
    source = Path("deploy/docker/Dockerfile").read_text(encoding="utf-8")

    assert "COPY scripts/ ./scripts/" in source
    assert "COPY --from=builder /app/scripts /app/scripts" in source
    assert "postgresql-client" in source


def test_makefile_exposes_pgvector_acceptance_target() -> None:
    source = Path("Makefile").read_text(encoding="utf-8")

    assert "pgvector-acceptance:" in source
    assert "./scripts/accept_pgvector_docker.sh" in source


def test_docker_reload_uses_pgvector_overlay() -> None:
    source = Path("Makefile").read_text(encoding="utf-8")

    assert "COMPOSE_PGVECTOR_AGENTTEAMS := $(COMPOSE_PGVECTOR)" in source
    assert "$(COMPOSE_PGVECTOR_AGENTTEAMS) --profile rocketmq up -d --build" in source


def test_rocketmq_worker_uses_bounded_restart_and_documents_recovery() -> None:
    compose = Path("deploy/docker/docker-compose.worker.yml").read_text(encoding="utf-8")
    readme = Path("deploy/docker/README.md").read_text(encoding="utf-8")

    assert "restart: on-failure:5" in compose
    assert "RocketMQ Worker 故障处置" in readme
    assert "TASK_QUEUE_BACKEND" in readme

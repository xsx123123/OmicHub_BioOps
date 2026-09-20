# PolarDB PostgreSQL + pgvector rollout

This rollout preserves SQLAlchemy models, Alembic, and the current tables. It adds only the `vector` extension, `vector(1024)` columns, HNSW indexes, nullable `project_id` boundaries, and service-level retrieval filters.

## Local acceptance container

Do **not** point the pgvector image at a pre-existing PostgreSQL data directory. Take a logical backup, restore it into a fresh pgvector-compatible instance, then run migrations.

```bash
docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.pgvector.yml up -d db pgbouncer postgres-exporter
docker exec cygnusx-web alembic upgrade head
```

Use PgBouncer only for application traffic. Alembic migrations, `pg_dump`, and `pg_restore` must connect directly to the writer endpoint.

The pgvector overlay starts PgBouncer and the exporter, but deliberately leaves the default Web `DATABASE_URL` on the direct writer because the Web entrypoint runs Alembic at startup. After moving migrations to a dedicated direct-writer Job/service, set the Web `DATABASE_URL` to the PgBouncer endpoint for transaction pooling. The built-in SQLAlchemy Web pool is already enabled and observable, so PgBouncer is not a migration prerequisite.

## PolarDB production configuration

- `DATABASE_URL`: PolarDB **writer** endpoint using `postgresql+asyncpg`.
- `READONLY_DATABASE_URL`: a PolarDB read-only endpoint; it is deliberately not used by write paths or Alembic.
- `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `DATABASE_POOL_TIMEOUT_SECONDS`, `DATABASE_POOL_RECYCLE_SECONDS`: Web process SQLAlchemy pool settings. Worker/Beat intentionally use `NullPool` because their `asyncio.run()` lifecycle cannot reuse pooled async connections safely.
- Enable `AGENT_MEMORY_SEMANTIC_RETRIEVAL_ENABLED=true` and set `AGENT_MEMORY_EMBEDDING_MODEL` only after a compatible 1024-dimension embedding model is configured.

Run `scripts/verify_polardb_postgres.sh` against both endpoints before cutover. It verifies pgvector, HNSW indexes, active connection state, and read-only endpoint state.

For a local, non-destructive acceptance drill, run `make pgvector-acceptance`. It starts the
pgvector overlay, verifies the writer, probes the PostgreSQL exporter and application metrics,
backs up the current database, restores it into a temporary database, verifies the restored
schema/indexes, and drops the temporary database. Supply `READONLY_DATABASE_URL` to additionally
verify a real PolarDB read-only endpoint; the local single-node container does not claim to emulate
PolarDB replication.

Convenience commands: `make docker-up-pgvector`, `make pgvector-acceptance`, `make polardb-verify`, and `make knowledge-reindex`.

After the migration, backfill existing published documents before enabling semantic retrieval:

```bash
docker exec cygnusx-web python scripts/reindex_knowledge_vectors.py
```

## Backup and restore drill

```bash
DATABASE_URL=postgresql+asyncpg://... scripts/backup_polardb_postgres.sh
RESTORE_DATABASE_URL=postgresql+asyncpg://... scripts/restore_polardb_postgres.sh /data/cygnusx/backups/postgres/cygnusx-<timestamp>.dump
```

Restore only into an empty/non-production target and rerun `scripts/verify_polardb_postgres.sh` after restore. Use PolarDB automated backups/PITR as the production recovery control; these scripts are the logical portability and drill path.

## Monitoring

- Application metrics remain exposed at `/metrics` when `METRICS_ENABLED=true`.
- `postgres-exporter` exposes PostgreSQL metrics on port `9187` in the pgvector overlay.
- Monitor active/idle connections, pool checkout failures, replica replay/read-only status, HNSW index presence, migration version, p95 query latency, and backup/PITR health in PolarDB.

## RLS readiness

RLS is intentionally not enabled by this migration. Current project ownership is enforced in application queries because the schema does not yet have a normalized project-membership table or a transaction-scoped database identity (`app.user_id` / `app.project_id`) that can make a safe policy decision. Enabling RLS before those two pieces exist would either hide valid rows from background jobs or create bypass policies that do not add protection. The nullable `project_id` columns, project indexes, and consistent session propagation added in this rollout are the prerequisites for a subsequent RLS-only migration.

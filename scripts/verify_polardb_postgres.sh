#!/usr/bin/env bash
# Verify a PolarDB PostgreSQL (or pgvector acceptance container) without mutating data.
set -euo pipefail

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Required command is unavailable: %s\n' "$1" >&2
    exit 127
  }
}

require_command psql
: "${DATABASE_URL:?Set DATABASE_URL to a PostgreSQL/PolarDB connection URL}"
PSQL_URL="${DATABASE_URL/postgresql+asyncpg/postgresql}"
READONLY_DATABASE_URL="${READONLY_DATABASE_URL:-}"

psql "$PSQL_URL" -v ON_ERROR_STOP=1 <<'SQL'
SELECT version();
SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
SELECT indexname, indexdef FROM pg_indexes
 WHERE schemaname = current_schema()
   AND indexname IN ('ix_agent_memories_embedding_hnsw', 'ix_kb_chunks_embedding_hnsw');
SELECT state, count(*) FROM pg_stat_activity GROUP BY state ORDER BY state;
SHOW max_connections;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector') THEN
    RAISE EXCEPTION 'pgvector extension is not installed';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
     WHERE schemaname = current_schema()
       AND indexname = 'ix_agent_memories_embedding_hnsw'
       AND indexdef ILIKE '%USING hnsw%'
       AND indexdef ILIKE '%vector_cosine_ops%'
  ) THEN
    RAISE EXCEPTION 'agent_memories HNSW cosine index is missing';
  END IF;
  IF NOT EXISTS (
    SELECT 1 FROM pg_indexes
     WHERE schemaname = current_schema()
       AND indexname = 'ix_kb_chunks_embedding_hnsw'
       AND indexdef ILIKE '%USING hnsw%'
       AND indexdef ILIKE '%vector_cosine_ops%'
  ) THEN
    RAISE EXCEPTION 'kb_chunks HNSW cosine index is missing';
  END IF;
END $$;
SQL

if [[ -n "$READONLY_DATABASE_URL" ]]; then
  READONLY_PSQL_URL="${READONLY_DATABASE_URL/postgresql+asyncpg/postgresql}"
  psql "$READONLY_PSQL_URL" -v ON_ERROR_STOP=1 <<'SQL'
SHOW transaction_read_only;
SELECT pg_is_in_recovery();
DO $$
BEGIN
  IF current_setting('transaction_read_only') <> 'on' AND NOT pg_is_in_recovery() THEN
    RAISE EXCEPTION 'READONLY_DATABASE_URL is neither read-only nor a recovery replica';
  END IF;
END $$;
SQL
fi

echo "PolarDB/pgvector verification passed."

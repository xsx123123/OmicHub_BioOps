#!/usr/bin/env bash
# Exercise the local pgvector acceptance stack without modifying its source database.
set -euo pipefail

COMPOSE_COMMAND="${COMPOSE_COMMAND:-docker compose -f deploy/docker/docker-compose.yml -f deploy/docker/docker-compose.pgvector.yml}"
POSTGRES_USER="${POSTGRES_USER:-omichub}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-omichub_dev_password}"
POSTGRES_DB="${POSTGRES_DB:-omichub}"
RESTORE_DB="omichub_restore_acceptance_${RANDOM}${RANDOM}"
DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${POSTGRES_DB}"
RESTORE_DATABASE_URL="postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@db:5432/${RESTORE_DB}"
BACKUP_DIR="/tmp/omichub-pgvector-acceptance"

compose() {
  # shellcheck disable=SC2086
  $COMPOSE_COMMAND "$@"
}

cleanup() {
  compose exec -T db psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
    -c "DROP DATABASE IF EXISTS \"${RESTORE_DB}\" WITH (FORCE);" >/dev/null 2>&1 || true
}
trap cleanup EXIT

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Required command is unavailable: %s\n' "$1" >&2
    exit 127
  }
}

require_command docker

printf '%s\n' 'Waiting for web, pgvector, PgBouncer, and PostgreSQL exporter...'
compose up -d --build db cache web pgbouncer postgres-exporter
for _ in $(seq 1 30); do
  if compose exec -T web curl -fsS http://127.0.0.1:8000/health >/dev/null 2>&1; then
    break
  fi
  sleep 2
done
compose exec -T web curl -fsS http://127.0.0.1:8000/health >/dev/null

printf '%s\n' 'Verifying writer pgvector extension and HNSW indexes...'
compose exec -T \
  -e DATABASE_URL="$DATABASE_URL" \
  -e READONLY_DATABASE_URL="${READONLY_DATABASE_URL:-}" \
  web scripts/verify_polardb_postgres.sh

printf '%s\n' 'Checking PostgreSQL exporter and application metrics endpoints...'
compose exec -T web sh -ec '
  curl -fsS http://postgres-exporter:9187/metrics | grep -q "^pg_up 1$"
  curl -fsS http://127.0.0.1:8000/metrics >/dev/null
'

printf '%s\n' 'Running logical backup and restore drill into an isolated database...'
compose exec -T db psql -U "$POSTGRES_USER" -d postgres -v ON_ERROR_STOP=1 \
  -c "CREATE DATABASE \"${RESTORE_DB}\" OWNER \"${POSTGRES_USER}\";"
compose exec -T \
  -e DATABASE_URL="$DATABASE_URL" \
  -e BACKUP_DIR="$BACKUP_DIR" \
  web scripts/backup_polardb_postgres.sh
backup_path="$(compose exec -T web sh -ec "find '$BACKUP_DIR' -maxdepth 1 -type f -name 'omichub-*.dump' -print -quit")"
if [[ -z "$backup_path" ]]; then
  echo 'Backup drill did not produce a dump file.' >&2
  exit 1
fi
compose exec -T \
  -e RESTORE_DATABASE_URL="$RESTORE_DATABASE_URL" \
  web scripts/restore_polardb_postgres.sh "$backup_path"
compose exec -T \
  -e DATABASE_URL="$RESTORE_DATABASE_URL" \
  web scripts/verify_polardb_postgres.sh

printf '%s\n' 'Local pgvector acceptance passed.'
if [[ -z "${READONLY_DATABASE_URL:-}" ]]; then
  cat <<'MESSAGE'
No READONLY_DATABASE_URL was supplied, so this local exercise cannot prove a managed
PolarDB read-only endpoint. Set READONLY_DATABASE_URL to that endpoint and rerun this
script; verify_polardb_postgres.sh will reject a writer endpoint.
MESSAGE
fi

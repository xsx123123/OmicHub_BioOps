#!/usr/bin/env bash
# Logical backup for PolarDB PostgreSQL. Supply DATABASE_URL and optional BACKUP_DIR.
set -euo pipefail

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Required command is unavailable: %s\n' "$1" >&2
    exit 127
  }
}

require_command pg_dump
require_command pg_restore

: "${DATABASE_URL:?Set DATABASE_URL}"
BACKUP_DIR="${BACKUP_DIR:-/data/cygnusx/backups/postgres}"
mkdir -p "$BACKUP_DIR"
PSQL_URL="${DATABASE_URL/postgresql+asyncpg/postgresql}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
TARGET="$BACKUP_DIR/cygnusx-${STAMP}.dump"
pg_dump --format=custom --no-owner --no-privileges --file "$TARGET" "$PSQL_URL"
pg_restore --list "$TARGET" >/dev/null
printf 'Created %s\n' "$TARGET"

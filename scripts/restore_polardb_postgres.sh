#!/usr/bin/env bash
# Restore a logical backup only into an explicitly supplied target database.
set -euo pipefail

require_command() {
  command -v "$1" >/dev/null 2>&1 || {
    printf 'Required command is unavailable: %s\n' "$1" >&2
    exit 127
  }
}

require_command pg_restore

: "${RESTORE_DATABASE_URL:?Set RESTORE_DATABASE_URL to the target database}"
: "${1:?Usage: restore_polardb_postgres.sh /path/to/backup.dump}"
PSQL_URL="${RESTORE_DATABASE_URL/postgresql+asyncpg/postgresql}"
pg_restore --list "$1" >/dev/null
pg_restore --clean --if-exists --no-owner --no-privileges --dbname "$PSQL_URL" "$1"

#!/usr/bin/env bash
# Verify that CygnusX is using the configured persistent PostgreSQL directory.
set -euo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
env_file="${repository_root}/.env"
require_existing_data=false

if [[ "${1:-}" == "--require-existing-data" ]]; then
    require_existing_data=true
elif [[ $# -gt 0 ]]; then
    printf 'Usage: %s [--require-existing-data]\n' "$0" >&2
    exit 2
fi

if [[ ! -f "${env_file}" ]]; then
    printf 'Missing environment file: %s\n' "${env_file}" >&2
    exit 1
fi

set -a
# shellcheck disable=SC1090
. "${env_file}"
set +a

: "${POSTGRES_USER:?POSTGRES_USER is required in .env}"
: "${POSTGRES_PASSWORD:?POSTGRES_PASSWORD is required in .env}"
: "${POSTGRES_DB:?POSTGRES_DB is required in .env}"

expected_postgres_dir="${CYGNUSX_POSTGRES_DATA_DIR:-/data/cygnusx/cygnusx_data/_pgdata}"
actual_postgres_dir=$(docker inspect cygnusx-db --format '{{range .Mounts}}{{if eq .Destination "/var/lib/postgresql/data"}}{{.Source}}{{end}}{{end}}')

if [[ -z "${actual_postgres_dir}" ]]; then
    printf 'cygnusx-db has no PostgreSQL data mount.\n' >&2
    exit 1
fi

if [[ "${actual_postgres_dir}" != "${expected_postgres_dir}" ]]; then
    printf 'PostgreSQL mount mismatch: expected %s, got %s\n' \
        "${expected_postgres_dir}" "${actual_postgres_dir}" >&2
    exit 1
fi

counts=$(docker exec -e "PGPASSWORD=${POSTGRES_PASSWORD}" cygnusx-db \
    psql -X -q -t -A -v ON_ERROR_STOP=1 -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" \
    -c 'SELECT (SELECT count(*) FROM users), (SELECT count(*) FROM agent_templates), (SELECT count(*) FROM knowledge_bases), (SELECT count(*) FROM kb_documents);')

IFS='|' read -r user_count agent_count knowledge_base_count document_count <<<"${counts}"
printf 'PostgreSQL data mount: %s\n' "${actual_postgres_dir}"
printf 'users=%s agent_templates=%s knowledge_bases=%s kb_documents=%s\n' \
    "${user_count}" "${agent_count}" "${knowledge_base_count}" "${document_count}"

if [[ "${require_existing_data}" == true ]] && \
    { [[ "${user_count}" == "0" ]] || [[ "${agent_count}" == "0" ]] || [[ "${knowledge_base_count}" == "0" ]]; }; then
    printf 'Expected existing users, Agents, and knowledge bases, but one or more counts are zero.\n' >&2
    exit 1
fi

echo 'Persistent data verification passed.'

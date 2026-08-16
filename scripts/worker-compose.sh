#!/usr/bin/env bash
set -euo pipefail

repository_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
config_path=${OMICHUB_WORKER_CONFIG:-"${repository_root}/data/worker_config.yaml"}
rendered_env="${repository_root}/data/.worker-config.env"
compose_overlay=${OMICHUB_WORKER_COMPOSE_OVERLAY:-""}

cd "${repository_root}"
python3 scripts/render_worker_config.py --config "${config_path}" --output "${rendered_env}"

set -a
# shellcheck disable=SC1090
. "${rendered_env}"
# 加载根目录 .env，使 ${REDIS_PASSWORD} 等变量可用于 docker compose 插值
# shellcheck disable=SC1091
. "${repository_root}/.env"
set +a

docker_socket=/var/run/docker.sock
if [[ -S "${docker_socket}" ]]; then
    detected_docker_gid=$(stat -c '%g' "${docker_socket}")
    if [[ -n "${DOCKER_GID:-}" && "${DOCKER_GID}" != "${detected_docker_gid}" ]]; then
        printf 'Warning: DOCKER_GID=%s does not match %s GID=%s; using detected GID.\n' \
            "${DOCKER_GID}" "${docker_socket}" "${detected_docker_gid}" >&2
    fi
    export DOCKER_GID="${detected_docker_gid}"
else
    printf 'Warning: Docker socket %s not found; container-backed tools will be unavailable.\n' \
        "${docker_socket}" >&2
fi

compose_files=(-f deploy/docker/docker-compose.worker.yml)
if [[ -n "${compose_overlay}" ]]; then
    if [[ ! -f "${compose_overlay}" ]]; then
        printf 'Worker Compose overlay does not exist: %s\n' "${compose_overlay}" >&2
        exit 1
    fi
    compose_files+=(-f "${compose_overlay}")
fi

exec docker compose "${compose_files[@]}" "$@"

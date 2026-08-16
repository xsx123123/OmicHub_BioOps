#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STUDIO_DIR="${ROOT_DIR}/deploy/studio"
RUNTIME_DIR="${ROOT_DIR}/deploy/runtime-images"

docker build -t omichub-analysis:core-2026.07 \
  -f "${RUNTIME_DIR}/core.Dockerfile" "${STUDIO_DIR}"
docker build -t omichub-analysis:plot-2026.07 \
  -f "${RUNTIME_DIR}/plot.Dockerfile" "${ROOT_DIR}"
docker build -t omichub-analysis:scrna-2026.07 \
  -f "${RUNTIME_DIR}/scrna.Dockerfile" "${ROOT_DIR}"

printf '%s\n' 'Built OmicHub independent analysis runtimes: core, plot, scrna'

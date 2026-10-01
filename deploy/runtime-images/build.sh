#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
STUDIO_DIR="${ROOT_DIR}/deploy/studio"
RUNTIME_DIR="${ROOT_DIR}/deploy/runtime-images"
TAG="${CYGNUSX_IMAGE_TAG:-v0.0.2dev}"
# The scrna profile is versioned independently because v0.0.3dev is the tag
# registered in data/ai/runtime_images.yaml and data/ai/studio.yaml.
SCRNA_TAG="${CYGNUSX_SCRNA_IMAGE_TAG:-v0.0.3dev}"
SANDBOX_UID="${SANDBOX_UID:-10001}"
SANDBOX_GID="${SANDBOX_GID:-10001}"
SANDBOX_GROUP="${SANDBOX_GROUP:-cygnusx-sandbox}"

COMMON_BUILD_ARGS=(
  --build-arg "SANDBOX_UID=${SANDBOX_UID}"
  --build-arg "SANDBOX_GID=${SANDBOX_GID}"
  --build-arg "SANDBOX_GROUP=${SANDBOX_GROUP}"
)
CHILD_BUILD_ARGS=(--build-arg "SANDBOX_GID=${SANDBOX_GID}")

docker build -t "cygnusx-analysis:core-${TAG}" \
  "${COMMON_BUILD_ARGS[@]}" \
  -f "${RUNTIME_DIR}/core.Dockerfile" "${STUDIO_DIR}"
docker build -t "cygnusx-analysis:plot-${TAG}" \
  --build-arg "CYGNUSX_IMAGE_TAG=${TAG}" \
  "${CHILD_BUILD_ARGS[@]}" \
  -f "${RUNTIME_DIR}/plot.Dockerfile" "${RUNTIME_DIR}"
docker build -t "cygnusx-analysis:scrna-${SCRNA_TAG}" \
  --build-arg "CYGNUSX_IMAGE_TAG=${TAG}" \
  "${CHILD_BUILD_ARGS[@]}" \
  -f "${RUNTIME_DIR}/scrna.Dockerfile" "${RUNTIME_DIR}"

printf '%s\n' "Built CygnusX independent analysis runtimes: core/plot=${TAG}, scrna=${SCRNA_TAG}"

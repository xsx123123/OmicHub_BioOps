#!/usr/bin/env bash
# 构建 OmicStudio 沙盒镜像：base -> bio（full 镜像待后续阶段）
# 用法：deploy/studio/build.sh [--push]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> 构建 omichub-sandbox:base"
docker build -t omichub-sandbox:base -f "${SCRIPT_DIR}/base.Dockerfile" "${SCRIPT_DIR}"

echo "==> 构建 omichub-sandbox:bio"
docker build -t omichub-sandbox:bio -f "${SCRIPT_DIR}/bio.Dockerfile" "${SCRIPT_DIR}"

echo "==> 完成：omichub-sandbox:base / omichub-sandbox:bio"

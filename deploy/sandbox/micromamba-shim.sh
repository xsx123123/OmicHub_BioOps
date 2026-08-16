#!/bin/bash
# micromamba 兼容 shim
#
# 聊天沙盒镜像基于 condaforge/mambaforge（自带 mamba/conda，生信栈装在 omichub 环境）。
# 平台提示词（data/ai/prompts/shared/sandbox_protocol.md、visualization.md 等）指示助手
# 调用 `micromamba install -y -n base <pkg>`，但镜像里没有 micromamba 二进制，
# 且 base 环境没有 R/Python 栈 —— 装到 base 也不会生效。
# 本 shim 把 micromamba 调用转发给 mamba，并把目标环境 base 映射为 omichub。
set -e

args=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    -n|--name)
      args+=("$1")
      shift
      if [ "$#" -gt 0 ]; then
        if [ "$1" = "base" ]; then
          args+=("omichub")
        else
          args+=("$1")
        fi
      fi
      ;;
    *)
      args+=("$1")
      ;;
  esac
  shift
done

exec mamba "${args[@]}"

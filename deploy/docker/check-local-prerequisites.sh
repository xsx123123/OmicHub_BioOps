#!/usr/bin/env bash
#
# OmicHub 私有化部署前置校验脚本
#
# 用途：在本地私有化部署前检查 Docker、bind mount、UID/GID、共享存储等前提条件，
#      发现缺失时给出可操作的报错与修复建议。
#
# 运行：
#   chmod +x deploy/docker/check-local-prerequisites.sh
#   DATA_ROOT=/data/omichub PUID=$(id -u) PGID=$(id -g) ./deploy/docker/check-local-prerequisites.sh
#
# 多机部署时额外设置：
#   MULTI_NODE=true DATA_ROOT=/data/omichub ./deploy/docker/check-local-prerequisites.sh

set -u

: "${DATA_ROOT:=/data/omichub}"
: "${PUID:=$(id -u)}"
: "${PGID:=$(id -g)}"
: "${MULTI_NODE:=false}"

ERRORS=0
WARNINGS=0

red() { printf '\033[0;31m%s\033[0m\n' "$*"; }
yellow() { printf '\033[0;33m%s\033[0m\n' "$*"; }
green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
info() { printf '%s\n' "$*"; }

error() {
  red "[错误] $1"
  ERRORS=$((ERRORS + 1))
}

warn() {
  yellow "[警告] $1"
  WARNINGS=$((WARNINGS + 1))
}

ok() {
  green "[通过] $1"
}

info ""
info "OmicHub 私有化部署前置校验"
info "=================================="
info "DATA_ROOT : ${DATA_ROOT}"
info "PUID/PGID : ${PUID}:${PGID}"
info "当前用户  : $(id -un)($(id -u):$(id -g))"
info "多机部署  : ${MULTI_NODE}"
info ""

# ----------------------------------------------------------------------
# 1. Docker 环境与 Docker socket 可用性
# ----------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
  error "未找到 docker 命令。请安装 Docker Engine 并将当前用户加入 docker 组："
  info "  sudo usermod -aG docker $(id -un) && newgrp docker"
  info "  参考：https://docs.docker.com/engine/install/"
else
  ok "docker 命令已安装"
fi

if ! docker info >/dev/null 2>&1; then
  error "无法连接 Docker daemon。常见原因："
  info "  1) 当前用户未加入 docker 组：sudo usermod -aG docker $(id -un)"
  info "  2) Docker 服务未启动：sudo systemctl start docker"
  info "  3) 非 root 且无 sudo 时无法访问 /var/run/docker.sock"
else
  ok "Docker daemon 可正常通信"
fi

# ----------------------------------------------------------------------
# 2. 数据根目录存在且当前用户可写
# ----------------------------------------------------------------------
if [[ ! -d "${DATA_ROOT}" ]]; then
  if mkdir -p "${DATA_ROOT}" 2>/dev/null; then
    ok "数据根目录不存在，已自动创建：${DATA_ROOT}"
  else
    error "数据根目录不存在且无法创建：${DATA_ROOT}"
    info "  请手动创建并授权当前用户可写："
    info "    sudo mkdir -p ${DATA_ROOT}"
    info "    sudo chown $(id -u):$(id -g) ${DATA_ROOT}"
  fi
else
  ok "数据根目录已存在：${DATA_ROOT}"
fi

if [[ ! -w "${DATA_ROOT}" ]]; then
  error "当前用户对 ${DATA_ROOT} 没有写权限"
  info "  请修正目录属主或权限："
  info "    sudo chown ${PUID}:${PGID} ${DATA_ROOT}"
  info "    chmod u+rwx ${DATA_ROOT}"
else
  ok "当前用户对 ${DATA_ROOT} 有写权限"
fi

# ----------------------------------------------------------------------
# 3. bind mount 权限：容器内以 PUID:PGID 能读写 DATA_ROOT
# ----------------------------------------------------------------------
if docker info >/dev/null 2>&1; then
  TEST_FILE="${DATA_ROOT}/.omichub_precheck_$(date +%s)"
  touch "${TEST_FILE}" || true

  if docker run --rm \
    --user "${PUID}:${PGID}" \
    -v "${DATA_ROOT}:${DATA_ROOT}" \
    busybox:1.36 \
    sh -c "test -w ${DATA_ROOT} && echo ok > ${TEST_FILE}.container && cat ${TEST_FILE}.container" \
    >/dev/null 2>&1; then
    ok "容器以 ${PUID}:${PGID} 可读写 DATA_ROOT 的 bind mount"
  else
    error "容器以 ${PUID}:${PGID} 无法读写 ${DATA_ROOT}"
    info "  常见原因与修复："
    info "    1) 目录属主与 PUID/PGID 不一致："
    info "       sudo chown -R ${PUID}:${PGID} ${DATA_ROOT}"
    info "    2) 目录权限不足："
    info "       chmod -R u+rwx ${DATA_ROOT}"
    info "    3) Docker 以 rootless 运行且子 UID/GID 映射缺失："
    info "       检查 /etc/subuid、/etc/subgid 是否包含当前用户"
  fi

  rm -f "${TEST_FILE}" "${TEST_FILE}.container"
fi

# ----------------------------------------------------------------------
# 4. 容器 UID/GID 与数据目录属主匹配检查
# ----------------------------------------------------------------------
if [[ -d "${DATA_ROOT}" ]]; then
  DIR_OWNER=$(stat -c '%u:%g' "${DATA_ROOT}" 2>/dev/null || echo "unknown")
  if [[ "${DIR_OWNER}" != "${PUID}:${PGID}" ]]; then
    warn "${DATA_ROOT} 的属主为 ${DIR_OWNER}，与 PUID:PGID=${PUID}:${PGID} 不一致"
    info "  容器内进程将以 ${PUID}:${PGID} 写入，建议执行："
    info "    sudo chown -R ${PUID}:${PGID} ${DATA_ROOT}"
  else
    ok "数据目录属主与 PUID:PGID 一致"
  fi
fi

# ----------------------------------------------------------------------
# 5. 多机部署时检测 RWX 共享存储
# ----------------------------------------------------------------------
if [[ "${MULTI_NODE}" == "true" ]]; then
  if ! command -v findmnt >/dev/null 2>&1; then
    warn "未找到 findmnt，无法自动判断 ${DATA_ROOT} 的文件系统类型"
    info "  多机部署请确保 ${DATA_ROOT} 挂载的是 NFS/CephFS/OCFS2 等 RWX 共享存储"
  else
    FS_TYPE=$(findmnt -n -o FSTYPE --target "${DATA_ROOT}" 2>/dev/null || echo "unknown")
    case "${FS_TYPE}" in
      nfs|nfs4|cifs|ceph|cephfs|ocfs2|gpfs|lustre|glusterfs)
        ok "多机部署：${DATA_ROOT} 挂载的是共享文件系统 ${FS_TYPE}"
        ;;
      ext4|xfs|btrfs|zfs)
        error "多机部署：${DATA_ROOT} 挂载的是本地文件系统 ${FS_TYPE}，无法在多节点间共享"
        info "  请挂载 NFS / CephFS / OCFS2 等 RWX 共享存储到所有节点的相同路径"
        ;;
      *)
        warn "多机部署：无法确认 ${DATA_ROOT} 的文件系统类型（${FS_TYPE}）"
        info "  请人工确认其是否为所有节点均可读写的共享存储"
        ;;
    esac
  fi
else
  info "单节点部署：跳过 RWX 共享存储检查"
fi

# ----------------------------------------------------------------------
# 6. 磁盘空间（大于 100 GiB 给出提示）
# ----------------------------------------------------------------------
if command -v df >/dev/null 2>&1; then
  AVAIL_KB=$(df -k "${DATA_ROOT}" 2>/dev/null | awk 'NR==2 {print $4}')
  if [[ -n "${AVAIL_KB}" ]]; then
    AVAIL_GB=$((AVAIL_KB / 1024 / 1024))
    if [[ "${AVAIL_GB}" -lt 100 ]]; then
      warn "${DATA_ROOT} 可用空间仅 ${AVAIL_GB} GiB，建议预留至少 100 GiB 用于生信分析"
    else
      ok "${DATA_ROOT} 可用空间 ${AVAIL_GB} GiB"
    fi
  fi
fi

# ----------------------------------------------------------------------
# 汇总
# ----------------------------------------------------------------------
info ""
if [[ ${ERRORS} -gt 0 ]]; then
  red "校验未通过：${ERRORS} 个错误，${WARNINGS} 个警告"
  info "请先修复上述错误后重新运行本脚本。"
  exit 1
elif [[ ${WARNINGS} -gt 0 ]]; then
  yellow "校验通过，但存在 ${WARNINGS} 个警告，建议处理后再部署。"
  exit 0
else
  green "全部校验通过，可以进行私有化部署。"
  exit 0
fi

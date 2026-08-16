# OmicHub 镜像仓库与快速部署方案

> 目标：把构建好的镜像推送到镜像仓库（ACR / Docker Hub / Harbor），部署方 `docker compose pull` 即可启动，省去本地 30+ 分钟的 `uv sync` / conda 构建。

## 0. 目录

- [1. 镜像清单](#1-镜像清单)
- [2. 仓库选择](#2-仓库选择)
- [3. 命名规范](#3-命名规范)
- [4. 推送流程](#4-推送流程)
- [5. 部署方使用](#5-部署方使用)
- [6. 镜像分层策略](#6-镜像分层策略)
- [7. CI/CD 集成（可选）](#7-cicd-集成可选)
- [8. 安全与合规](#8-安全与合规)
- [9. 故障排查](#9-故障排查)

---

## 1. 镜像清单

`deploy/` 下所有自定义镜像，按**变动频率**分三档：

### 1.1 代码镜像（每次发版重建）

| 镜像 | Dockerfile | 当前本地名 | 服务 |
|------|-----------|-----------|------|
| Web | `deploy/docker/Dockerfile` | `docker-web` | web / beat / flower |
| Worker | `deploy/docker/Dockerfile.worker` | `omichub-worker:dev` | worker |
| Phylo Worker | `deploy/docker/Dockerfile.phylo` | `omichub-phylo-worker:dev` | phylo-worker |

> 这三个镜像包含业务代码，每次发版需重建。

### 1.2 运行时镜像（极少变动）

| 镜像 | Dockerfile | 当前本地名 | 用途 |
|------|-----------|-----------|------|
| Analysis Core | `deploy/runtime-images/core.Dockerfile` | `omichub-analysis:core-2026.07` | Studio Python 运行时 |
| Analysis Plot | `deploy/runtime-images/plot.Dockerfile` | `omichub-analysis:plot-2026.07` | 绑图工具链 |
| Analysis scRNA | `deploy/runtime-images/scrna.Dockerfile` | `omichub-analysis:scrna-2026.07` | Scanpy 单细胞 |

### 1.3 工具镜像（几乎不变）

| 镜像 | Dockerfile | 当前本地名 | 用途 |
|------|-----------|-----------|------|
| Enrichment | `deploy/docker/Dockerfile.enrichment` | `omichub-r-enrichment:<ver>` | GO/KEGG R 分析 |
| DEG | `deploy/docker/Dockerfile.deg` | `omichub-r-deg:<ver>` | 差异表达 R 分析 |
| Sandbox Terminal | `deploy/sandbox/Dockerfile` + `tool_configs/terminal/docker/` | `omichub/sandbox-terminal:latest` | 终端沙盒 |
| Studio Egress Proxy | `deploy/studio/proxy.Dockerfile` | `docker-studio-egress-proxy` | Studio 出站代理 |
| Phylo Toolkit | `deploy/docker/Dockerfile.phylo` | `omichub/phylo-toolkit:1.0.0` | 系统发育树工具 |

### 1.4 第三方基础镜像（无需推送）

| 镜像 | 用途 |
|------|------|
| `pgvector/pgvector:pg14` | 数据库 |
| `redis:7-alpine` | 缓存 |
| `apache/rocketmq:5.3.2` | 消息队列 |
| `nginx:alpine` | 反向代理 |
| `ollama/ollama:latest` | 本地模型（可选） |

---

## 2. 仓库选择

| 仓库 | 适用场景 | 国内速度 | 推荐 |
|------|---------|---------|------|
| **阿里云 ACR**（容器镜像服务） | 国内生产部署 | ⚡ 50-100 MB/s | ✅ 首选 |
| Docker Hub | 国际开源项目 | 🐢 慢/被墙 | 仅国际分发 |
| GitHub GHCR | 开源项目 tied to repo | 🐢 慢 | 开源配套 |
| 自建 Harbor | 企业内网 | ⚡ 内网速度 | 大型企业 |
| 腾讯云 TCR | 腾讯云生态 | ⚡ 快 | 腾讯云部署 |

### 2.1 阿里云 ACR 快速设置（推荐）

```bash
# 1. 登录阿里云容器镜像服务
# https://cr.console.aliyun.com → 创建命名空间（如 omichub）

# 2. 本地登录
docker login --username=<aliyun-account> registry.cn-hangzhou.aliyuncs.com

# 3. 命名空间建议
# registry.cn-hangzhou.aliyuncs.com/omichub/<image-name>:<tag>
```

---

## 3. 命名规范

### 3.1 镜像名约定

```
<registry>/<namespace>/<image>:<tag>

例：
registry.cn-hangzhou.aliyuncs.com/omichub/web:26.8.7
registry.cn-hangzhou.aliyuncs.com/omichub/worker:26.8.7
registry.cn-hangzhou.aliyuncs.com/omichub/r-enrichment:1.2.0
registry.cn-hangzhou.aliyuncs.com/omichub/analysis-core:2026.07
```

### 3.2 Tag 策略

| Tag 类型 | 示例 | 用途 |
|---------|------|------|
| 语义化版本 | `26.8.7` | 生产发布 |
| 日期版本 | `2026.07` | 年度大版本（运行时） |
| `latest` | `latest` | 跟踪最新稳定版（慎用） |
| Git SHA | `a3f5b2c` | CI 构建追溯 |
| `dev` | `dev` | 开发调试（不推送远程） |

### 3.3 环境变量化

compose 已支持通过 `.env` 覆盖镜像名。建议的完整变量清单：

```bash
# .env（新增镜像仓库段）
OMICHUB_REGISTRY=registry.cn-hangzhou.aliyuncs.com/omichub
OMICHUB_VERSION=26.8.7

# 各镜像引用
OMICHUB_WEB_IMAGE=${OMICHUB_REGISTRY}/web:${OMICHUB_VERSION}
OMICHUB_WORKER_IMAGE=${OMICHUB_REGISTRY}/worker:${OMICHUB_VERSION}
OMICHUB_PHYLO_WORKER_IMAGE=${OMICHUB_REGISTRY}/phylo-worker:${OMICHUB_VERSION}
OMICHUB_ENRICHMENT_IMAGE=${OMICHUB_REGISTRY}/r-enrichment:1.2.0
OMICHUB_DEG_IMAGE=${OMICHUB_REGISTRY}/r-deg:1.0.0
OMICHUB_SANDBOX_IMAGE=${OMICHUB_REGISTRY}/sandbox-terminal:2026.07
OMICHUB_ANALYSIS_CORE=${OMICHUB_REGISTRY}/analysis-core:2026.07
OMICHUB_ANALYSIS_PLOT=${OMICHUB_REGISTRY}/analysis-plot:2026.07
OMICHUB_ANALYSIS_SCRNA=${OMICHUB_REGISTRY}/analysis-scrna:2026.07
```

---

## 4. 推送流程

### 4.1 一键推送脚本（建议新增 `scripts/push-images.sh`）

```bash
#!/usr/bin/env bash
set -euo pipefail

REGISTRY="${OMICHUB_REGISTRY:?请设置 OMICHUB_REGISTRY}"
VERSION="${OMICHUB_VERSION:?请设置 OMICHUB_VERSION}"

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

log() { printf '\e[1;36m→ %s\e[0m\n' "$*"; }

# 代码镜像（每次发版）
build_and_push() {
  local local_name="$1" remote_name="$2"
  log "Tag: $local_name → $remote_name"
  docker tag "$local_name" "$remote_name"
  docker push "$remote_name"
}

log "=== 推送代码镜像 ==="
build_and_push "docker-web"                    "$REGISTRY/web:$VERSION"
build_and_push "omichub-worker:dev"            "$REGISTRY/worker:$VERSION"
build_and_push "omichub-phylo-worker:dev"      "$REGISTRY/phylo-worker:$VERSION"

log "=== 推送运行时镜像（变动少，首次推送后跳过）==="
build_and_push "omichub-analysis:core-2026.07" "$REGISTRY/analysis-core:2026.07"
build_and_push "omichub-analysis:plot-2026.07" "$REGISTRY/analysis-plot:2026.07"
build_and_push "omichub-analysis:scrna-2026.07" "$REGISTRY/analysis-scrna:2026.07"

log "=== 推送工具镜像（变动极少，首次推送后跳过）==="
build_and_push "omichub-r-enrichment:latest"   "$REGISTRY/r-enrichment:1.2.0"
build_and_push "omichub-r-deg:latest"          "$REGISTRY/r-deg:1.0.0"
build_and_push "omichub/sandbox-terminal:latest" "$REGISTRY/sandbox-terminal:2026.07"

# 同步 latest tag（可选）
if [ "${UPDATE_LATEST:-0}" = "1" ]; then
  log "同步 latest tag..."
  docker tag "$REGISTRY/web:$VERSION" "$REGISTRY/web:latest"
  docker push "$REGISTRY/web:latest"
  docker tag "$REGISTRY/worker:$VERSION" "$REGISTRY/worker:latest"
  docker push "$REGISTRY/worker:latest"
fi

log "✅ 全部推送完成"
```

### 4.2 使用

```bash
# 首次：构建所有镜像
make docker-reload

# 推送
export OMICHUB_REGISTRY=registry.cn-hangzhou.aliyuncs.com/omichub
export OMICHUB_VERSION=26.8.7
bash scripts/push-images.sh
```

### 4.3 选择性推送（只推代码镜像）

```bash
# 只推 web/worker（每次发版）
docker tag docker-web $OMICHUB_REGISTRY/web:$OMICHUB_VERSION
docker push $OMICHUB_REGISTRY/web:$OMICHUB_VERSION

docker tag omichub-worker:dev $OMICHUB_REGISTRY/worker:$OMICHUB_VERSION
docker push $OMICHUB_REGISTRY/worker:$OMICHUB_VERSION
```

---

## 5. 部署方使用

### 5.1 快速部署（零构建）

```bash
# 1. 克隆代码（只需要 compose 配置）
git clone --depth 1 https://github.com/your-org/OmicHub.git
cd OmicHub

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env：
#   - 设置 OMICHUB_REGISTRY 与 OMICHUB_VERSION
#   - 配置数据库密码、JWT 密钥、AI API key 等
#   - 所有 *_IMAGE 变量会自动指向远程镜像

# 3. 拉取所有镜像（首次）
docker compose --env-file .env -p omichub pull

# 4. 启动
docker compose --env-file .env -p omichub up -d

# 5. 跑迁移
docker exec omichub-web alembic upgrade head
```

### 5.2 增量升级

```bash
# 修改 .env 中的 OMICHUB_VERSION=26.8.8
docker compose pull web worker    # 只拉变动的
docker compose up -d web worker   # 滚动重启
```

### 5.3 离线部署

```bash
# 在有网机器导出镜像
docker save -o omichub-web-26.8.7.tar $OMICHUB_REGISTRY/web:26.8.7
docker save -o omichub-worker-26.8.7.tar $OMICHUB_REGISTRY/worker:26.8.7
# ... 其他镜像

# 拷贝到离线机器
scp *.tar user@offline-host:/tmp/

# 离线机器加载
docker load -i /tmp/omichub-web-26.8.7.tar
docker load -i /tmp/omichub-worker-26.8.7.tar

# 启动（compose 会用本地镜像）
docker compose up -d
```

---

## 6. 镜像分层策略

### 6.1 优化要点

| 优化 | 效果 |
|------|------|
| BuildKit cache mount (`/root/.cache/uv`) | 跨重建复用 uv 下载缓存，避免重复 `uv sync` |
| 先 COPY `pyproject.toml uv.lock`，再 `uv sync`，最后 COPY 源码 | 代码变更不触发依赖重装 |
| 多阶段构建（builder → slim runtime） | 运行时镜像小（无编译工具链） |
| `.dockerignore` 排除 `.venv` `__pycache__` `node_modules` | 减少构建上下文传输 |

### 6.2 镜像大小预估

| 镜像 | 预估大小 | 说明 |
|------|---------|------|
| web | 800MB-1.2GB | Python 依赖 + 源码 |
| worker | 1.5-2.5GB | 含 micromamba + Docker CLI |
| analysis-core | 600MB-900MB | Python 科学计算栈 |
| analysis-plot | 800MB-1.2GB | 加 matplotlib/seaborn |
| analysis-scrna | 1.2-1.8GB | 加 scanpy/anndata |
| r-enrichment | 700MB-1GB | R + Bioconductor |
| r-deg | 800MB-1.2GB | R + DESeq2/edgeR |
| sandbox-terminal | 300-500MB | 精简 Linux 工具链 |

### 6.3 镜像瘦身建议

- web 镜像：`python:3.11-slim` 基础，去编译工具链 ✅ 已做
- worker 镜像：micromamba 必装（跑分析容器），大小换不来优化
- R 镜像：用 `rocker/verse` 而非完整 `rocker/tidyverse`，减少无用 R 包

---

## 7. CI/CD 集成（可选）

### 7.1 GitHub Actions 示例

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags: ['v*']

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    permissions:
      packages: write
      contents: read
    steps:
      - uses: actions/checkout@v4

      - name: Set up Docker Buildx
        uses: docker/setup-buildx-action@v3

      - name: Login to ACR
        uses: docker/login-action@v3
        with:
          registry: registry.cn-hangzhou.aliyuncs.com
          username: ${{ secrets.ACR_USERNAME }}
          password: ${{ secrets.ACR_PASSWORD }}

      - name: Extract version
        id: meta
        run: echo "VERSION=${GITHUB_REF_NAME#v}" >> $GITHUB_OUTPUT

      - name: Build and push web
        uses: docker/build-push-action@v5
        with:
          context: .
          file: deploy/docker/Dockerfile
          push: true
          tags: |
            registry.cn-hangzhou.aliyuncs.com/omichub/web:${{ steps.meta.outputs.VERSION }}
            registry.cn-hangzhou.aliyuncs.com/omichub/web:latest
          cache-from: type=gha
          cache-to: type=gha,mode=max

      - name: Build and push worker
        uses: docker/build-push-action@v5
        with:
          context: .
          file: deploy/docker/Dockerfile.worker
          push: true
          tags: |
            registry.cn-hangzhou.aliyuncs.com/omichub/worker:${{ steps.meta.outputs.VERSION }}
          cache-from: type=gha
          cache-to: type=gha,mode=max
```

### 7.2 阿里云效流水线

```yaml
# 在阿里云效 Web IDE 配置
steps:
  - step: build@docker
    name: 构建 web 镜像
    inputs:
      dockerfilePath: deploy/docker/Dockerfile
      tag: ${CI_COMMIT_TAG}
      repository: registry.cn-hangzhou.aliyuncs.com/omichub/web
  - step: push@docker
    name: 推送 web 镜像
    inputs:
      repository: registry.cn-hangzhou.aliyuncs.com/omichub/web
      tag: ${CI_COMMIT_TAG}
```

---

## 8. 安全与合规

### 8.1 镜像签名

```bash
# 使用 Docker Content Trust 签名
export DOCKER_CONTENT_TRUST=1
docker push $REGISTRY/web:$VERSION   # 自动签名
```

### 8.2 漏洞扫描

```bash
# 阿里云 ACR 自带漏洞扫描（免费）
# 本地扫描用 trivy
trivy image $REGISTRY/web:$VERSION
```

### 8.3 敏感信息

- **禁止**把 `.env` / API key / 数据库密码烘焙进镜像
- 使用 `docker secrets` 或 `.env` 挂载
- CI 用 `secrets` 注入凭据，不落镜像层

### 8.4 访问控制

- ACR：RAM 子账号 + 推/拉权限分离
- CI：专用 deploy token，定期轮换
- 部署方：只给 pull 权限

---

## 9. 故障排查

### 9.1 推送失败

| 现象 | 原因 | 解决 |
|------|------|------|
| `unauthorized: authentication required` | 未登录或 token 失效 | `docker login` 重新登录 |
| `denied: requested access to the resource is denied` | 无 push 权限 | 检查 RAM / 仓库权限 |
| `manifest unknown` | tag 不存在 | 确认本地镜像已 tag |
| `timeout` | 网络问题 | 切到阿里云 ACR（国内快） |

### 9.2 部署方拉取失败

| 现象 | 原因 | 解决 |
|------|------|------|
| `image not found` | 镜像未推送或 tag 错误 | 检查远程仓库 tag |
| `pull access denied` | 仓库是私有，未登录 | `docker login` |
| 拉取极慢 | 仓库在海外 | 切阿里云 ACR |

### 9.3 缓存失效

```bash
# 强制无缓存重建
docker build --no-cache -t docker-web -f deploy/docker/Dockerfile .

# 清理本地 BuildKit 缓存
docker builder prune -a
```

### 9.4 镜像太大

```bash
# 查看各层大小
docker history $REGISTRY/web:$VERSION

# 检查无用层
dive $REGISTRY/web:$VERSION   # 需要安装 dive: https://github.com/wagoodman/dive
```

---

## 附录 A：compose 文件改造清单

需要加 `${OMICHUB_XXX_IMAGE}` 变量覆盖的 compose 服务：

| compose 文件 | 服务 | 当前 image 字段 | 改造 |
|-------------|------|----------------|------|
| `docker-compose.yml` | web | （无，build 默认名） | 加 `image: ${OMICHUB_WEB_IMAGE:-docker-web}` |
| `docker-compose.yml` | beat | （同上） | 加 `image: ${OMICHUB_WEB_IMAGE:-docker-web}` |
| `docker-compose.yml` | flower | （同上） | 加 `image: ${OMICHUB_WEB_IMAGE:-docker-web}` |
| `docker-compose.yml` | studio-egress-proxy | （同上） | 加 `image: ${OMICHUB_PROXY_IMAGE:-docker-studio-egress-proxy}` |
| `docker-compose.worker.yml` | worker | `${OMICHUB_WORKER_IMAGE:-omichub-worker:dev}` | ✅ 已支持 |
| `docker-compose.worker.yml` | phylo-worker | `${OMICHUB_PHYLO_WORKER_IMAGE:-omichub-phylo-worker:dev}` | ✅ 已支持 |
| Makefile | enrichment | `$(ENRICHMENT_DOCKER_IMAGE)` | ✅ 已支持 |
| Makefile | deg | `$(DEG_DOCKER_IMAGE)` | ✅ 已支持 |
| Makefile | sandbox-terminal | 硬编码 `omichub/sandbox-terminal:latest` | 加环境变量 |

## 附录 B：环境变量模板（追加到 `.env.example`）

```bash
# ===== 镜像仓库 =====
# 镜像仓库前缀（如使用阿里云 ACR：registry.cn-hangzhou.aliyuncs.com/omichub）
# 留空则使用本地构建镜像（开发模式）
OMICHUB_REGISTRY=

# 发布版本号（对应 git tag 或手动指定）
OMICHUB_VERSION=

# 各镜像完整引用（OMICHUB_REGISTRY 非空时生效）
OMICHUB_WEB_IMAGE=${OMICHUB_REGISTRY:+${OMICHUB_REGISTRY}/web:${OMICHUB_VERSION}}
OMICHUB_WORKER_IMAGE=${OMICHUB_REGISTRY:+${OMICHUB_REGISTRY}/worker:${OMICHUB_VERSION}}
OMICHUB_PHYLO_WORKER_IMAGE=${OMICHUB_REGISTRY:+${OMICHUB_REGISTRY}/phylo-worker:${OMICHUB_VERSION}}
OMICHUB_ENRICHMENT_IMAGE=${OMICHUB_REGISTRY:+${OMICHUB_REGISTRY}/r-enrichment:1.2.0}
OMICHUB_DEG_IMAGE=${OMICHUB_REGISTRY:+${OMICHUB_REGISTRY}/r-deg:1.0.0}
OMICHUB_SANDBOX_IMAGE=${OMICHUB_REGISTRY:+${OMICHUB_REGISTRY}/sandbox-terminal:2026.07}
OMICHUB_ANALYSIS_CORE=${OMICHUB_REGISTRY:+${OMICHUB_REGISTRY}/analysis-core:2026.07}
OMICHUB_ANALYSIS_PLOT=${OMICHUB_REGISTRY:+${OMICHUB_REGISTRY}/analysis-plot:2026.07}
OMICHUB_ANALYSIS_SCRNA=${OMICHUB_REGISTRY:+${OMICHUB_REGISTRY}/analysis-scrna:2026.07}
```

> 用 `${VAR:+value}` 语法：`OMICHUB_REGISTRY` 为空时整个变量为空，compose 回退到本地镜像名，开发模式不受影响。

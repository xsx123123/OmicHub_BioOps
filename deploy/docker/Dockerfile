# ============================================
# CygnusX 后端 Dockerfile
# 多阶段构建：uv 安装依赖 + slim 运行
# ============================================

# ----- 阶段 1: 构建依赖 -----
FROM python:3.11-slim AS builder

# 构建期切换中科大 apt 源，加速 apt-get（兼容 debian.sources 与旧版 sources.list）
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's@//deb.debian.org@//mirrors.ustc.edu.cn@g; s@//security.debian.org@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list.d/debian.sources; \
    else \
        sed -i 's@//deb.debian.org@//mirrors.ustc.edu.cn@g; s@//security.debian.org@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list; \
    fi

# Git is required to install the Snakemake logger plugin from the JZ_Tools
# repository subdirectory during image build.
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates git && rm -rf /var/lib/apt/lists/*

# 安装 uv（从 PyPI 而非 GHCR——GHCR 在国内常被墙，与 Dockerfile.worker 同路线）
RUN python -m pip install --no-cache-dir --disable-pip-version-check \
    -i https://pypi.mirrors.ustc.edu.cn/simple "uv==0.6.14"

# uv 不读 /etc/pip.conf，必须显式指定 index（中科大主源 + 阿里云兜底）
# HTTP 超时拉长到 120s + 5 次重试：国内拉 scipy/matplotlib 等大包容易 30s 默认超时
ENV UV_INDEX_URL=https://pypi.mirrors.ustc.edu.cn/simple \
    UV_EXTRA_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/ \
    UV_HTTP_TIMEOUT=120 \
    UV_HTTP_RETRIES=5 \
    UV_LINK_MODE=copy

WORKDIR /app

# 先复制依赖文件（利用 Docker 层缓存）
COPY pyproject.toml uv.lock* README.md ./

# 安装依赖到虚拟环境（BuildKit cache mount：跨重建复用 uv 下载缓存，避免每次 --build 都重新下载）
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --extra workflow --no-install-project \
    --index-url https://pypi.mirrors.ustc.edu.cn/simple/

# 复制源代码
COPY src/ ./src/
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY scripts/ ./scripts/
# 工具箱配置（tools_setting.yaml + 各工具子目录 YAML）；prod 不挂源码，须打进镜像
COPY tool_configs/ ./tool_configs/

# 安装项目本身
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv sync --frozen --no-dev --extra workflow \
    --index-url https://pypi.mirrors.ustc.edu.cn/simple/

# Snakemake logger plugin used by the workflow monitor.
RUN uv pip install --python /app/.venv/bin/python --no-cache \
    --index-url https://pypi.mirrors.ustc.edu.cn/simple/ \
    "snakemake-logger-plugin-rich-loguru>=0.3.0"

# AgentExplorer SDK powers the optional Alibaba Cloud official Skills marketplace.
# Keep it separate from uv.lock because this integration is lazy-loaded and only the web service
# needs it when an Alibaba Cloud AccessKey is configured.
RUN uv pip install --python /app/.venv/bin/python --no-cache \
    --index-url https://pypi.mirrors.ustc.edu.cn/simple/ \
    "alibabacloud_agentexplorer20260317==1.0.1"

# RocketMQ is optional at runtime. Keep it outside uv.lock so the default
# Celery-only environment remains reproducible while RocketMQ-enabled images
# have the native client available.
RUN uv pip install --python /app/.venv/bin/python --no-cache \
    --index-url https://pypi.mirrors.ustc.edu.cn/simple/ \
    "rocketmq-client-python==2.0.0"

# ----- 阶段 2: 运行 -----
FROM python:3.11-slim AS runtime

# 构建期切换中科大 apt 源，加速 apt-get（兼容 debian.sources 与旧版 sources.list）
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's@//deb.debian.org@//mirrors.ustc.edu.cn@g; s@//security.debian.org@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list.d/debian.sources; \
    else \
        sed -i 's@//deb.debian.org@//mirrors.ustc.edu.cn@g; s@//security.debian.org@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list; \
    fi

# 安装运行时系统依赖
# nodejs/npm：stdio 传输的 node/npx 型 MCP server 由 web 进程内 spawn，
# validate_stdio_command 走 shutil.which，容器内必须有 node 运行时（python:3.11-slim 默认不带）。
# bookworm apt 源（已切中科大镜像）提供 nodejs 18 / npm 9，满足绝大多数 MCP server。
# tesseract：知识库图片索引使用中英文 OCR；缺失时只能索引文件名、说明和尺寸。
# git：Studio 工作区检查点（studio_checkpoints）依赖 git CLI；缺失时创建/升级工作台会话会 500。
RUN apt-get update && apt-get install -y --no-install-recommends \
    bzip2 \
    curl \
    git \
    nodejs \
    npm \
    postgresql-client \
    tesseract-ocr \
    tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*

# conda-meta-mcp（CLI 名 cmm）：conda 生态元数据 MCP server，Agent 沙盒现场装包前
# 用它确认包名/channel/版本，避免凭记忆猜包名盲装。仅发布在 conda-forge（不在 PyPI）
# 且要求 Python >=3.13，故用 micromamba 装独立 env /opt/cmm-env，并把 cmm 软链到
# /usr/local/bin，让 validate_stdio_command 的 shutil.which 能按名字找到它。
# /opt/micromamba 是 root prefix（缓存目录），运行时以 uid 1000 执行须可写。
RUN set -eux; \
    curl -Ls https://micro.mamba.pm/api/micromamba/linux-64/latest \
        | tar -xj -C /usr/local/bin --strip-components=1 bin/micromamba; \
    micromamba create -y -r /opt/micromamba -p /opt/cmm-env \
        -c https://mirrors.ustc.edu.cn/anaconda/cloud/conda-forge \
        conda-meta-mcp=0.1.4; \
    ln -s /opt/cmm-env/bin/cmm /usr/local/bin/cmm; \
    micromamba clean -y -a; \
    rm -f /usr/local/bin/micromamba; \
    chmod -R a+rwX /opt/micromamba
ENV MAMBA_ROOT_PREFIX=/opt/micromamba

WORKDIR /app

# 从 builder 复制虚拟环境和源代码
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/alembic /app/alembic
COPY --from=builder /app/scripts /app/scripts
COPY --from=builder /app/tool_configs /app/tool_configs

# 设置环境变量
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV APP_ENV=production

# 部署版本可观测：构建时经 --build-arg 注入，/health 的 git_sha/build_time 由此取值。
ARG CYGNUSX_BUILD_SHA=unknown
ARG CYGNUSX_BUILD_TIME=unknown
ENV APP_GIT_SHA=${CYGNUSX_BUILD_SHA} \
    APP_BUILD_TIME=${CYGNUSX_BUILD_TIME}

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

EXPOSE 8000

# 默认启动命令（可被 docker-compose 覆盖）
CMD ["uvicorn", "cygnusx.main:app", "--host", "0.0.0.0", "--port", "8000"]

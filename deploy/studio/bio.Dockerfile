# syntax=docker/dockerfile:1.7
ARG CYGNUSX_IMAGE_TAG=v0.0.2dev
# OmicStudio 沙盒生信镜像（cygnusx-sandbox-bio:v0.0.2dev）
# 构建：先构建 base，再 docker build --build-arg CYGNUSX_IMAGE_TAG=v0.0.2dev -t cygnusx-sandbox-bio:v0.0.2dev -f deploy/studio/bio.Dockerfile deploy/studio
#
# 设计（架构设计 §6.1）：base + scanpy/anndata/pysam/bioinfokit + 常用生信 CLI
#（blast / samtools / bedtools / seqkit，取自 Debian 官方仓库，seqkit 不可用时跳过）
FROM cygnusx-sandbox-base:${CYGNUSX_IMAGE_TAG}

LABEL maintainer="CygnusX"
LABEL description="OmicStudio sandbox bio image (scanpy + NGS CLI tools)"

USER root

# 构建期切换中科大 apt 源，加速 apt-get（兼容 debian.sources 与旧版 sources.list）
RUN if [ -f /etc/apt/sources.list.d/debian.sources ]; then \
        sed -i 's@//deb.debian.org@//mirrors.ustc.edu.cn@g; s@//security.debian.org@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list.d/debian.sources; \
    else \
        sed -i 's@//deb.debian.org@//mirrors.ustc.edu.cn@g; s@//security.debian.org@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list; \
    fi

# 生信 CLI 工具（--no-install-recommends 控制体积；seqkit 部分 Debian 版本无此包，容错跳过）
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ncbi-blast+ \
        samtools \
        bedtools \
    && (apt-get install -y --no-install-recommends seqkit \
        || echo "seqkit 不在当前 Debian 仓库，跳过") \
    && rm -rf /var/lib/apt/lists/*

# 单细胞 / 生信 Python 栈
RUN --mount=type=cache,target=/root/.cache/pip,sharing=locked \
    python -m pip install --prefer-binary \
        scanpy \
        anndata \
        pysam \
        bioinfokit

USER 10001:10001
WORKDIR /workspace
CMD ["sh", "-c", "rm -f /workspace/.agent.sock && exec uvicorn --app-dir /opt/sandbox sandbox_agent:app --uds /workspace/.agent.sock"]

# OmicStudio 沙盒生信镜像（omichub-sandbox:bio）
# 构建：先构建 base，再 docker build -t omichub-sandbox:bio -f deploy/studio/bio.Dockerfile deploy/studio
#
# 设计（架构设计 §6.1）：base + scanpy/anndata/pysam/bioinfokit + 常用生信 CLI
#（blast / samtools / bedtools / seqkit，取自 Debian 官方仓库，seqkit 不可用时跳过）
FROM omichub-sandbox:base

LABEL maintainer="OmicHub"
LABEL description="OmicStudio sandbox bio image (scanpy + NGS CLI tools)"

USER root

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
RUN pip install \
        scanpy \
        anndata \
        pysam \
        bioinfokit

USER 10001
WORKDIR /workspace
CMD ["sh", "-c", "rm -f /workspace/.agent.sock && exec uvicorn --app-dir /opt/sandbox sandbox_agent:app --uds /workspace/.agent.sock"]

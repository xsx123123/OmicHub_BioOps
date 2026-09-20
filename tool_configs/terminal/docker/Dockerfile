# CygnusX 沙盒终端镜像
# 基于 Ubuntu 22.04，预装常用生信工具链 + ttyd Web 终端 + zsh/oh-my-zsh/oh-my-posh/btop

FROM ubuntu:22.04

LABEL maintainer="CygnusX Team"
LABEL description="Rootless sandbox terminal for CygnusX with Zsh and Oh My Posh"

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# 1. 创建用户，并将默认 shell 设置为 /bin/zsh
RUN groupadd -r -g 1000 cygnusx && \
    useradd -r -u 1000 -g cygnusx -d /home/cygnusx -s /bin/zsh cygnusx && \
    mkdir -p /home/cygnusx/workspace /home/cygnusx/tmp /home/cygnusx/.cache && \
    chown -R cygnusx:cygnusx /home/cygnusx

# 构建期切换中科大 apt 源，加速 apt-get（子镜像 FROM 本镜像，自动继承）
RUN sed -i 's@//.*archive.ubuntu.com@//mirrors.ustc.edu.cn@g; s@//security.ubuntu.com@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list

# 2. 安装系统依赖，增加 zsh, git, btop, unzip
# ttyd 直接走 apt（jammy universe 提供 1.6.3，CMD 所用 -p/-W/-t 参数均兼容），
# 不再从 GitHub Releases 下载（实测该层直连需 55s，apt 化后随本层几秒完成）
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates gnupg2 git unzip \
    htop btop vim nano less tree \
    zsh bash-completion \
    python3 python3-pip python3-venv \
    samtools bcftools bedtools \
    fastqc \
    seqkit \
    jq \
    ttyd \
    && rm -rf /var/lib/apt/lists/*

# 3.5 预置中科大 PyPI 镜像，加速构建期与运行期 pip 安装（全局，对所有用户生效）
RUN printf '%s\n' \
    '[global]' \
    'index-url = https://pypi.mirrors.ustc.edu.cn/simple' \
    'timeout = 60' \
    'retries = 3' \
    > /etc/pip.conf

# 4. 安装 Python 依赖（显式 -i 指定 USTC，与 /etc/pip.conf 双保险）
RUN pip3 install --no-cache-dir -i https://pypi.mirrors.ustc.edu.cn/simple \
    numpy pandas biopython pysam

# 5. 全局安装 oh-my-posh（二进制 + 主题包经 gh-proxy.com 中转，规避 GitHub 直连慢；
#    代理不可用时把 GH_PROXY 换成 https://ghfast.top/ 重试；传入空串即可还原 GitHub 直连）
ARG GH_PROXY=https://gh-proxy.com/
ARG OMP_VERSION=latest
RUN set -e; \
    if [ "${OMP_VERSION}" = "latest" ]; then REL="latest/download"; else REL="download/${OMP_VERSION}"; fi; \
    curl -fsSL -o /usr/local/bin/oh-my-posh \
      "${GH_PROXY}https://github.com/JanDeDobbeleer/oh-my-posh/releases/${REL}/posh-linux-amd64" && \
    chmod +x /usr/local/bin/oh-my-posh && \
    curl -fsSL -o /tmp/omp-themes.zip \
      "${GH_PROXY}https://github.com/JanDeDobbeleer/oh-my-posh/releases/${REL}/themes.zip" && \
    mkdir -p /usr/share/oh-my-posh/themes && \
    unzip -qo /tmp/omp-themes.zip -d /usr/share/oh-my-posh/themes && \
    chmod -R a+r /usr/share/oh-my-posh/themes && \
    rm -f /tmp/omp-themes.zip

ENV HOME=/home/cygnusx \
    ZDOTDIR=/home/cygnusx \
    XDG_CACHE_HOME=/home/cygnusx/.cache \
    OMP_CACHE_DIR=/home/cygnusx/.cache \
    ZSH_CACHE_DIR=/home/cygnusx/.cache/oh-my-zsh

# ---------------------------------------------------
# 切换到普通用户进行环境初始化
USER cygnusx
WORKDIR /home/cygnusx/workspace

# 6. 安装 oh-my-zsh (使用 unattended 模式避免阻塞构建)
#    安装脚本与 git clone 均走 Gitee 镜像（GitHub 直连实测 33s+，Gitee 为秒级）；
#    origin 也指向 Gitee，容器内 oh-my-zsh 自动更新同样不碰 GitHub
RUN export REMOTE=https://gitee.com/mirrors/oh-my-zsh.git BRANCH=master && \
    sh -c "$(curl -fsSL https://gitee.com/mirrors/oh-my-zsh/raw/master/tools/install.sh)" "" --unattended

# 7. 配置 oh-my-zsh / oh-my-posh（COPY 自定义 .zshrc 覆盖默认配置）
COPY --chown=cygnusx:cygnusx zshrc /home/cygnusx/.zshrc

EXPOSE 7681

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:7681 || exit 1

# 8. 启动 ttyd 并调用 zsh
CMD ["ttyd", "-p", "7681", "-W", "-t", "fontSize=14", "-t", "fontFamily=JetBrains Mono", "zsh"]

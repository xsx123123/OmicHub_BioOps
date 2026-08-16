# OmicHub 沙盒终端镜像
# 基于 Ubuntu 22.04，预装常用生信工具链 + ttyd Web 终端 + zsh/oh-my-zsh/oh-my-posh/btop

FROM ubuntu:22.04

LABEL maintainer="OmicHub Team"
LABEL description="Rootless sandbox terminal for OmicHub with Zsh and Oh My Posh"

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Asia/Shanghai

# 1. 创建用户，并将默认 shell 设置为 /bin/zsh
RUN groupadd -r -g 1000 omichub && \
    useradd -r -u 1000 -g omichub -d /home/omichub -s /bin/zsh omichub && \
    mkdir -p /home/omichub/workspace /home/omichub/tmp /home/omichub/.cache && \
    chown -R omichub:omichub /home/omichub

# 构建期切换中科大 apt 源，加速 apt-get（子镜像 FROM 本镜像，自动继承）
RUN sed -i 's@//.*archive.ubuntu.com@//mirrors.ustc.edu.cn@g; s@//security.ubuntu.com@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list

# 2. 安装系统依赖，增加 zsh, git, btop, unzip
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget curl ca-certificates gnupg2 git unzip \
    htop btop vim nano less tree \
    zsh bash-completion \
    python3 python3-pip python3-venv \
    samtools bcftools bedtools \
    fastqc \
    seqkit \
    jq \
    && rm -rf /var/lib/apt/lists/*

# 3. 安装 ttyd
RUN wget -qO /usr/local/bin/ttyd \
    https://github.com/tsl0922/ttyd/releases/download/1.7.7/ttyd.x86_64 && \
    chmod +x /usr/local/bin/ttyd

# 3.5 预置中科大 PyPI 镜像，加速构建期与运行期 pip 安装（全局，对所有用户生效）
RUN printf '%s\n' \
    '[global]' \
    'index-url = https://pypi.mirrors.ustc.edu.cn/simple' \
    'extra-index-url = https://mirrors.aliyun.com/pypi/simple/' \
    'timeout = 60' \
    'retries = 10' \
    > /etc/pip.conf

# 4. 安装 Python 依赖（显式 -i 指定 USTC，与 /etc/pip.conf 双保险）
RUN pip3 install --no-cache-dir -i https://pypi.mirrors.ustc.edu.cn/simple \
    numpy pandas biopython pysam

# 5. 全局安装 oh-my-posh（root 下安装到系统路径，主题目录全局可读）
RUN curl -s https://ohmyposh.dev/install.sh | bash -s -- -d /usr/local/bin -t /usr/share/oh-my-posh/themes

ENV HOME=/home/omichub \
    ZDOTDIR=/home/omichub \
    XDG_CACHE_HOME=/home/omichub/.cache \
    OMP_CACHE_DIR=/home/omichub/.cache \
    ZSH_CACHE_DIR=/home/omichub/.cache/oh-my-zsh

# ---------------------------------------------------
# 切换到普通用户进行环境初始化
USER omichub
WORKDIR /home/omichub/workspace

# 6. 安装 oh-my-zsh (使用 unattended 模式避免阻塞构建)
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)" "" --unattended

# 7. 配置 oh-my-zsh / oh-my-posh（COPY 自定义 .zshrc 覆盖默认配置）
COPY --chown=omichub:omichub zshrc /home/omichub/.zshrc

EXPOSE 7681

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --quiet --tries=1 --spider http://localhost:7681 || exit 1

# 8. 启动 ttyd 并调用 zsh
CMD ["ttyd", "-p", "7681", "-W", "-t", "fontSize=14", "-t", "fontFamily=JetBrains Mono", "zsh"]

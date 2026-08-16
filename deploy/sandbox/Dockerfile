# OmicHub 生信分析沙盒镜像
# 构建：docker build -t omichub/sandbox-base:latest -f deploy/sandbox/Dockerfile deploy/sandbox
#
# 设计（符合 1 人运维 / 单机部署原则）：
# - 基于 condaforge/mambaforge，通过 bioconda 预装 scanpy + R/Seurat 交互式分析栈
# - 工具链聚焦"交互式单细胞分析"（UMAP/聚类/差异），NGS 比对类重工具由 Snakemake 流程单独承载
# - sitecustomize.py 在 Python 启动时注入 sc/np/pd/show_echarts/show_image，配合后端池的 `python -` 执行协议
# - matplotlib 无头（Agg），图表通过 %%ECHARTS%% / %%IMAGE%% 标记行回传
FROM condaforge/mambaforge:24.3.0-0

LABEL maintainer="OmicHub"
LABEL description="Bioinformatics sandbox for OmicHub AI Copilot (scanpy + Seurat)"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    MAMBA_NO_BANNER=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Asia/Shanghai

# 预置中科大镜像源，加速容器内 mamba/conda 环境安装
RUN printf '%s\n' \
      'show_channel_urls: true' \
      'default_channels:' \
      '  - https://mirrors.ustc.edu.cn/anaconda/pkgs/main' \
      '  - https://mirrors.ustc.edu.cn/anaconda/pkgs/free' \
      '  - https://mirrors.ustc.edu.cn/anaconda/pkgs/r' \
      '  - https://mirrors.ustc.edu.cn/anaconda/pkgs/msys2' \
      'custom_channels:' \
      '  conda-forge: https://mirrors.ustc.edu.cn/anaconda/cloud' \
      '  bioconda: https://mirrors.ustc.edu.cn/anaconda/cloud' \
      '  menpo: https://mirrors.ustc.edu.cn/anaconda/cloud' \
      '  pytorch: https://mirrors.ustc.edu.cn/anaconda/cloud' \
      'channel_priority: flexible' \
      'channels:' \
      '  - conda-forge' \
      '  - bioconda' \
      '  - menpo' \
      '  - defaults' \
      > /root/.condarc

# 预置中科大 PyPI 镜像，加速构建期与运行期 pip 安装
RUN printf '%s\n' \
      '[global]' \
      'index-url = https://pypi.mirrors.ustc.edu.cn/simple' \
      'extra-index-url = https://mirrors.aliyun.com/pypi/simple/' \
      'timeout = 60' \
      'retries = 10' \
      > /etc/pip.conf

# 构建期切换中科大 apt 源，加速 apt-get（基础镜像为 Ubuntu focal）
RUN sed -i 's@//.*archive.ubuntu.com@//mirrors.ustc.edu.cn@g; s@//security.ubuntu.com@//mirrors.ustc.edu.cn@g' /etc/apt/sources.list

# 系统依赖（R 编译需要 build-essential；hdf5/lapack 为数值栈运行时依赖）
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        libhdf5-dev \
        libpng-dev \
        libfreetype6-dev \
        liblapack-dev \
        libopenblas-dev \
        libxml2-dev \
        libxslt1-dev \
        libcurl4-openssl-dev \
        libssl-dev \
        procps \
        && rm -rf /var/lib/apt/lists/*

# conda 渠道已在 /root/.condarc 配好（conda-forge/bioconda/menpo → USTC，channel_priority flexible），
# 不再用 conda config 调整（strict + 重复加渠道会导致混渠道求解脆弱）。

# 创建 omichub 环境（Python 3.11），预装核心生信 Python 栈
RUN mamba create -n omichub python=3.11 -y \
    && mamba install -n omichub -y \
        scanpy=1.10.2 \
        anndata=0.10.8 \
        muon=0.1.7 \
        leidenalg \
        python-igraph \
        harmonypy \
        scikit-learn=1.5.0 \
        statsmodels=0.14.0 \
        seaborn=0.13.2 \
        matplotlib=3.9 \
        matplotlib-venn \
        numpy=1.26.4 \
        pandas=2.2.2 \
        scipy=1.13.0 \
        plotly=5.22.0 \
        ipykernel=6.29 \
        openpyxl=3.1 \
        tqdm \
        requests \
    && mamba clean --all -y

# 先装 CPU-only PyTorch（走 USTC 镜像的 pytorch 渠道）：
# 否则下一步 pip 装 scvi-tools 时会从 PyPI 拉 torch 及其 NVIDIA CUDA 依赖（约 3GB），极慢且沙盒用不到 CUDA。
# conda 的 pytorch 包自带 torch dist-info，pip 会判定 torch 依赖已满足。
RUN mamba install -n omichub -y -c pytorch -c conda-forge \
        pytorch=2.4 \
        cpuonly \
    && mamba clean --all -y

# conda 缺少的较新单细胞工具走 pip
SHELL ["conda", "run", "-n", "omichub", "/bin/bash", "-c"]
RUN pip install --no-cache-dir -i https://pypi.mirrors.ustc.edu.cn/simple \
        "squidpy>=1.4.0" \
        "scvi-tools>=1.1.0" \
        "celltypist>=1.6.0" \
        "decoupler>=1.6.0" \
        "kaleido>=0.2.1"

# R + Seurat + IRkernel
# 注意：r-base 必须 >=4.5 —— Python 栈已引入 icu 78（libharfbuzz 依赖），
# r-base 4.3/4.4 仅接受 icu 72~75，会与 Python 栈无解（2026-07-28 实测）。
RUN mamba install -n omichub -c conda-forge -c bioconda -y \
        r-base=4.5 \
        r-irkernel \
        r-seurat \
        r-seuratobject \
        r-tidyverse \
        bioconductor-singlecellexperiment \
        bioconductor-scater \
        bioconductor-scran \
        bioconductor-complexheatmap \
        bioconductor-ggtree \
        bioconductor-treeio \
        r-ape \
        r-phytools \
    && mamba clean --all -y

# 注册 IRkernel（R 代码可在同一环境执行）
RUN conda run -n omichub R -e "IRkernel::installspec(user = FALSE)"

# 可视化提示词约定 ggpubr::theme_pubclean() 为 R 出图默认主题，预装避免现场安装失败。
# 独立层，避免变更上层 R/Seurat 依赖的构建缓存。
RUN mamba install -n omichub -c conda-forge -y \
        r-ggpubr \
    && mamba clean --all -y

# micromamba 兼容 shim：提示词历史版本指示 `micromamba install -y -n base <pkg>`，
# 本镜像为 mambaforge（mamba + omichub 环境），shim 负责转发并把 base 映射为 omichub。
COPY micromamba-shim.sh /usr/local/bin/micromamba
RUN chmod +x /usr/local/bin/micromamba

# sitecustomize.py：Python 启动时自动注入 sc/np/pd + 图表回传 helper
# 后端池通过 `docker exec -i <c> python -` 投递用户代码，sitecustomize 对所有启动方式生效
# 放入 site-packages 目录，Python 启动时自动加载（无需手动 PYTHONPATH）
COPY sitecustomize.py /opt/conda/envs/omichub/lib/python3.11/site-packages/sitecustomize.py

ENV PATH=/opt/conda/envs/omichub/bin:$PATH \
    CONDA_DEFAULT_ENV=omichub \
    MPLBACKEND=Agg

# 工作目录与数据挂载点（后端池挂载 /data/omichub -> /data）
WORKDIR /workspace
RUN mkdir -p /workspace/data /workspace/output

# 健康检查：轻量探活即可（池在 run 时也会覆盖此 HEALTHCHECK）。
# 不要在这里 import scanpy 等重栈 —— 每个 warm 容器每 60s 跑一次会吃满 CPU。
HEALTHCHECK --interval=60s --timeout=15s --start-period=120s --retries=3 \
    CMD python -c "print('sandbox OK')" || exit 1

# 容器保持存活（由池通过 sleep infinity 接管，此处兜底）
CMD ["sleep", "infinity"]

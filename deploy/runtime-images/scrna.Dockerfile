# syntax=docker/dockerfile:1.7
ARG CYGNUSX_IMAGE_TAG=v0.0.3dev
FROM cygnusx-analysis:scrna-${CYGNUSX_IMAGE_TAG}

ARG SANDBOX_GID=10001

LABEL org.opencontainers.image.title="CygnusX Analysis Single Cell"
LABEL org.cygnusx.runtime.profile="analysis-scrna"

# 预置中科大镜像源，加速 bioconda 包下载（见 Protocol/镜像构建国内加速规范_v1.md §4）；
# 安装以 mambauser 执行，condarc 必须落在其 HOME。
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
      'channel_priority: flexible' \
      'channels:' \
      '  - conda-forge' \
      '  - bioconda' \
      '  - menpo' \
      '  - defaults' \
      > /home/mambauser/.condarc \
    && chown "$MAMBA_USER:$SANDBOX_GID" /home/mambauser/.condarc

USER "$MAMBA_USER"
RUN --mount=type=cache,target=/opt/conda/pkgs,uid=10001,gid=10001,sharing=locked \
    micromamba install -y -n base -c conda-forge -c bioconda \
      r-data.table=1.18.6.1 \
      r-ggpubr=0.6.0 \
      r-ggsci=5.2.0 \
      r-patchwork=1.3.0 \
      r-scales=1.4.0
# 注意：r-qs 因与 RcppParallel/Seurat 存在 ABI 冲突，暂不预装
# 如需使用 .qs 格式，可在沙盒内手动安装：
#   micromamba install r-qs=0.25.7 --force-reinstall
#   # 或升级 Seurat 到兼容版本后安装最新 r-qs

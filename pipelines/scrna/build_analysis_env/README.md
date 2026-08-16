*author* : Zhang Jian
*date*   : 2025-12-23
*version*: v4.0.4-alpha

## Introduction
本文档旨在指导用户搭建 `scRNAseqMulticommand` 的运行环境。您可以选择使用 `Conda/Mamba` 直接配置本地环境，或使用 `Docker` 容器进行隔离运行。

本目录包含以下关键文件：
*   `scRNAseqMulticommand_environment.yml`: Conda 环境完整配置文件。
*   `scRNAseqMulticommand.Dockerfile`: 标准 Docker 构建文件。
*   `multiStage.Dockerfile`: 优化体积的多阶段 Docker 构建文件。

### 1. Build via Conda / Mamba (Recommended for Local)
最推荐的方式是直接使用我们提供的 `yaml` 配置文件，这能确保所有依赖包的版本一致性。

```bash
# 基于 yaml 文件一键创建环境
micromamba create -f build_analysis_env/scRNAseqMulticommand_environment.yml

# 激活环境
micromamba activate scRNAseq_analysis
```

<details>
<summary>点击查看手动安装命令 (仅供参考)</summary>

如果您需要手动逐个安装依赖（不推荐），可参考以下命令：

```bash
mamba create -n scRNAseqMulticommand
conda activate scRNAseqMulticommand

# 基础编译库
mamba install -c conda-forge binutils_impl_linux-64=2.40 libstdcxx-ng=14.2.0 libgcc-ng=14.2.0 libgomp=14.2.0

# R 语言基础
mamba install -c r -c conda-forge r-base=4.3.3 r-essentials=4.3.3 r-xml2=1.3.6 r-yaml=2.3.9 r-log4r=0.4.4 r-getopt=1.20.4 r-tidyverse=2.0.0

# 生物信息学核心包 (Bioconductor & Seurat)
mamba install -c conda-forge r-seurat=5.1.0 r-harmony=1.2.0
mamba install -c bioconda bioconductor-biocparallel=1.36.0 bioconductor-scater=1.30.1
mamba install -c bioconda bioconductor-singler=2.4.0 bioconductor-celldex=1.12.0 bioconductor-decontx=1.0.0 bioconductor-cellid=1.10.1 bioconductor-zellkonverter=1.12.1

# 辅助工具与绘图
mamba install -c conda-forge r-ggplot2=3.5.1 r-patchwork=1.3.0 r-cowplot=1.1.3 r-ggpubr=0.6.0 r-viridis=0.6.5
mamba install -c genomedk r-sccustomize r-doubletfinder=2.0.4
```
</details>

### 2. Build via Docker
为了获得最佳的稳定性和可移植性，建议构建 Docker 镜像。
```bash
# 方案 A: 标准构建 (构建速度快，体积较大)
docker build -t scrnaseqmulticommand:latest -f ./build_analysis_env/scRNAseqMulticommand.Dockerfile .

# 方案 B: 多阶段构建 (体积优化，推荐用于生产分发)
docker build -t scrnaseqmulticommand:latest-slim -f ./build_analysis_env/multiStage.Dockerfile .
```
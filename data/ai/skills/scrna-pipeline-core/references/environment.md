# scrna-pipeline-core 环境依赖清单

本技能运行所需 R 环境依赖。上架前需与沙盒运行时画像（如 `analysis-scrna` 的 `required_capabilities`）逐项核对。

## R 版本

- R ≥ 4.2（开发验证环境 R 4.3.3）

## 必装 R 包

| 包 | 版本要求 | 用途 | 安装方式 |
|---|---|---|---|
| Seurat | 5.x | 对象操作、FindMarkers、降维 | scrna 镜像已预装；缺时 `micromamba install -y -n base r-seurat` |
| SingleR | Bioconductor 3.18+ | 参考-based 注释 | `micromamba install -y -n base r-singler` |
| celldex | Bioconductor 3.18+ | SingleR reference 加载 | `micromamba install -y -n base r-celldex` |
| DoubletFinder | 2.0+ | Doublet 检测 | `micromamba install -y -n base r-doubletdfinder` |
| decontX | celda >= 1.8.0 | 环境 RNA 污染评估 | `micromamba install -y -n base r-celda` |
| scCustomize | ≥ 1.1 | 可视化美化 | **GitHub 独占包，需管理员预装** |
| qs | ≥ 0.25 | S4 对象序列化 | `micromamba install -y -n base r-qs` |
| yaml | ≥ 2.2 | 配置文件解析 | `micromamba install -y -n base r-yaml` |
| log4r | ≥ 0.4 | 日志系统 | `micromamba install -y -n base r-log4r` |
| getopt | ≥ 1.2-5 | CLI 参数解析 | `micromamba install -y -n base r-getopt` |
| data.table | ≥ 1.14 | 数据处理 | `micromamba install -y -n base r-data.table` |
| tidyverse | ≥ 1.3 | 数据管道 | `micromamba install -y -n base r-tidyverse` |
| ggplot2 | ≥ 3.4 | 绘图基础 | `micromamba install -y -n base r-ggplot2` |
| patchwork | ≥ 1.1 | 拼图 | `micromamba install -y -n base r-patchwork` |
| harmonycorrection | Harmony | 批次校正 | `micromamba install -y -n base r-harmony` |
| uwot | ≥ 0.1 | UMAP 降维 | `micromamba install -y -n base r-uwot` |
| future.globals | ≥ 1.2 | 内存管理 | `micromamba install -y -n base r-futureglobals` |

## Python (可选)

如需使用 SCVI 整合方法：

| 包 | 版本要求 | 用途 | 安装方式 |
|---|---|---|---|
| scvi-tools | ≥ 1.0 | SCVI 整合 | 单独 conda 环境 `/home/zj/miniconda3/envs/scvi` |

## Studio 沙盒注意事项

- CRAN/GitHub 不可达：所有包必须通过 conda 通道安装
- GitHub 独占包（scCustomize, DoubletFinder）需管理员预装进镜像
- SCVI 环境需单独 provision 到共享卷

## 资源建议

- 内存：默认 `--threads 20` 时建议 ≥64 GB；受限沙盒将线程调至 8–16
- 磁盘：产物含投影后 RDS + 高清 png + 中间文件，预留输入体积 5–10 倍空间
- 时间：10k cells ~2 小时，100k cells ~8–12 小时

## 参考数据依赖

本技能依赖以下参考数据（不进技能包，走 admin provisioning）：

- `ref/Celldex/` - SingleR reference rds + marker 数据库
- `ref/scRNAseqMulticommand/` - 主流程脚本 + report 模板
- `ref/DEG_Annotation_reference/` - DEG 注释 gene_info

详见 [provisioning.md](./provisioning.md)。

# 环境依赖（scrna-recluster）

## R 环境

- R ≥ 4.2（已在 R 4.5.1 验证）

## R 包依赖

| 包 | 版本要求 | 用途 |
|---|---|---|
| Seurat | 5.x | 对象构建与降维聚类流程（CreateSeuratObject/NormalizeData/FindVariableFeatures/ScaleData/RunPCA/FindNeighbors/FindClusters/RunUMAP） |
| log4r | ≥ 1.0 | 日志（函数库 `log4r_init`） |
| crayon | ≥ 1.5 | 彩色 console 日志输出 |
| ggplot2 | ≥ 3.4 | elbow plot 绘制 |
| optparse | ≥ 1.7 | CLI wrapper 参数解析（`recluster.R`） |
| jsonlite | ≥ 1.8 | 写出 summary.json（`recluster.R`） |

## 说明

- 无外部参考数据库依赖，无网络访问；
- 输入为 Seurat RDS 文件，输出为 RDS + PDF/PNG + JSON，全部写本地 `--output` 目录；
- Seurat 4.x 未经测试：`SingleSampleSubClusterRereduction` 内部按 Seurat 5 的 assay 结构访问 counts，沙盒镜像应固定 Seurat 5.x。

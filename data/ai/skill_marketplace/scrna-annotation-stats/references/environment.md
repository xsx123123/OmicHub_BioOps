# environment.md — scrna-annotation-stats 依赖清单

运行时：R ≥ 4.2（开发验证环境 R 4.5.1）。

## R 包依赖

| 包 | 版本要求 | 用途 | 使用 mode |
|---|---|---|---|
| Seurat | 5.x | 对象读写、FindMarkers（deg-prop）、AverageExpression（pct-exp） | 全部 |
| tidyverse | ≥ 1.3 | 数据处理（dplyr/tidyr/readr） | 全部 |
| ggplot2 | ≥ 3.4 | 全部图形输出 | prop/fisher/deg-prop |
| optparse | ≥ 1.7 | CLI 参数解析（wrapper） | 全部 |
| jsonlite | ≥ 1.8 | summary.json 写出（wrapper） | 全部 |
| gt | ≥ 0.9 | fisher 结果 HTML 美化表（可选，缺失时跳过并记 warnings） | fisher |
| scCustomize | ≥ 1.1 | Percent_Expressing（pct-exp） | pct-exp |
| ggrepel | ≥ 0.9 | DrawCellTypePropDEGGene 图形生态间接依赖 | deg-prop |
| log4r | ≥ 0.4 | DrawCellTypePropDEGGene / CalculationPercentAverageExp 日志 | deg-prop/pct-exp |
| crayon | ≥ 1.5 | log4r 日志配色 | deg-prop/pct-exp |

## 说明

- 输入对象：Seurat 5.x 创建的 RDS（assay `RNA` 可用；pct-exp 内部固定调 `AverageExpression(assays = 'RNA')`）。
- deg-prop 内部调用 `FindMarkers(logfc.threshold = 0.25)`，需默认 assay 含归一化数据层。
- scCustomize ≥ 2.0 将 `Percent_Expressing` 参数改名（`gene`→`features`、`group_by`→`group.by`）；wrapper 检测到新版签名时通过进程内 `assignInNamespace` shim 兼容，不修改包文件，旧版无需处理（开发验证环境为 scCustomize 3.3.0）。
- 无网络外联、无外部参考数据需求。

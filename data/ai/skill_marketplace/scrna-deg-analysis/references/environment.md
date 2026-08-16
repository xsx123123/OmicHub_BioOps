# 环境依赖清单（scrna-deg-analysis）

> 上架前须对照沙盒运行时画像（如 `analysis-scrna` 的 `required_capabilities`）逐项核对（OSDP §6.1）。

## R（≥ 4.x，验证环境 R 4.5.1）

| 包 | 用途 | 备注 |
|---|---|---|
| Seurat | FindMarkers、对象操作 | 5.x |
| tidyverse | 数据处理（dplyr/tibble 等） | |
| ggplot2 | 火山图 | |
| ggrepel | 火山图基因标注 | |
| log4r | 函数库日志 | |
| crayon | 函数库日志着色 | |
| optparse | `deg_analysis.R` CLI | |
| jsonlite | 写 `summary.json` | |

## Python（≥ 3.9，验证环境 3.13）

| 包 | 用途 |
|---|---|
| pandas | `merge_deg_infor.py` 合并 -DEG-infor.csv |

## 外部参考数据（不进技能包，走环境变量）

| 环境变量 | 内容 | 仓库内参考位置 |
|---|---|---|
| `SCRNA_DEG_REF_DIR` | 目录，含 `mm10_Mus_musculus.gene_info`、`hg19_Homo_sapiens.gene_info`（NCBI gene_info，按 Symbol 注释） | `tools/DEG/DEG_Annotation_reference/`（约 47MB，另含 hg38 版本） |

未设置 `SCRNA_DEG_REF_DIR` 时默认相对目录 `DEG_Annotation_reference`；文件缺失时脚本报可读错误并非 0 退出。

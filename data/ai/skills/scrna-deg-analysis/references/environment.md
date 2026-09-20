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

安装参考（Studio 沙盒 CRAN/GitHub 不可达，一律走 conda 通道）：

```bash
micromamba install -y -n base r-seurat r-tidyverse r-ggplot2 r-ggrepel r-log4r r-crayon r-optparse r-jsonlite python pandas
```

## 外部参考数据（不进技能包，管理员预置）

| 环境变量 | 内容 | 沙盒内路径约定 | 供给方式 |
|---|---|---|---|
| `SCRNA_DEG_REF_DIR` | 目录，含 `mm10_Mus_musculus.gene_info`、`hg19_Homo_sapiens.gene_info`（NCBI gene_info，按 Symbol 注释） | `ref/DEG_Annotation_reference/` | 管理员按 `provisioning.md` 从源仓库 `tools/DEG/DEG_Annotation_reference/` 预置到共享数据卷（约 47MB，另含 hg38 版本） |

未注入 `SCRNA_DEG_REF_DIR` 时脚本回退到相对目录 `DEG_Annotation_reference`（沙盒内通常不存在，会预检报错）；文件缺失时脚本报可读错误并非 0 退出，运行时模型只上报缺失、不自行下载。

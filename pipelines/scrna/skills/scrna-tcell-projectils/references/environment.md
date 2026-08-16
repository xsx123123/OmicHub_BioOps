# 环境依赖清单 — scrna-tcell-projectils

本技能脚本运行所需 R 环境依赖。上架前需与沙盒运行时画像（如 `analysis-scrna` 的 `required_capabilities`）逐项核对。

## R 版本

- R ≥ 4.2（脚本使用 base R 管道 `|>`）

## 必装 R 包

| 包 | 版本要求 | 用途 | 安装方式 |
|---|---|---|---|
| Seurat | 4.x 或 5.x | 对象读写、FindMarkers、降维检查 | CRAN |
| ProjecTILs | ≥ 1.0 | 核心注释：`ProjecTILs.classifier`、`load.reference.map()` | `remotes::install_github("carmonalab/ProjecTILs")`（CRAN 无） |
| scCustomize | ≥ 1.1 | `DimPlot_scCustom`、`DotPlot_scCustom` 可视化 | `remotes::install_github("samuel-marsh/scCustomize")` |
| optparse | ≥ 1.7 | CLI 参数解析（wrapper） | CRAN |
| jsonlite | ≥ 1.8 | summary.json 输出（wrapper） | CRAN |
| ggplot2 | ≥ 3.4 | 绘图基础 | CRAN |
| patchwork | ≥ 1.1 | 拼图 | CRAN |
| viridis | ≥ 0.6 | scCustomize 色板（viridis_plasma_dark_high 等） | CRAN |
| forcats | ≥ 1.0 | Dotplot 因子排序 | CRAN |
| dplyr | ≥ 1.1 | 数据处理 | CRAN |
| log4r | ≥ 0.4 | 日志 | CRAN |
| crayon | ≥ 1.5 | 日志着色 | CRAN |

## 参考数据（不进技能包）

- ProjecTILs TIL 参考 atlas：默认由 `ProjecTILs::load.reference.map()` **在线加载**（需网络）。
- 无网络沙盒：在有网环境执行以下命令预下载，产物放共享数据卷，运行时经 `--ref` 传入：

```r
ref <- ProjecTILs::load.reference.map()
saveRDS(ref, "projectils_ref.rds")
```

## 资源建议

- 内存：默认 `--cores 20` 时建议 ≥ 64 GB；受限沙盒将 `--cores` 调至 4–8（内存随核数近似线性下降）。
- 磁盘：产物含投影后 RDS（约为输入对象大小）+ 高清 png（dpi=1000），预留输入体积 2–3 倍空间。

# 环境依赖（scrna-annotation-ref）

## 薄脚本 check_reference.R

| 包 | 版本要求 | 用途 |
|---|---|---|
| R | ≥ 4.0（已在 R 4.5.1 验证） | 解释器 |
| optparse | ≥ 1.7 | CLI 参数解析 |

- 脚本只读 `--ref-dir` 目录，不写任何文件，无网络访问，无其他依赖。

## 注释流程本体（由 scrna-pipeline-overview 主流程执行，此处登记供核对）

| 包 | 版本要求 | 用途 |
|---|---|---|
| SingleR | 2.4.x | 参考相关性注释（`RunSingleR_Unified`） |
| celldex | 1.12.x | 提供 7 个参考数据集（经 ExperimentHub 下载，存为 Celldex/*.rds） |
| CellID | 1.10.1 | MCA/HCA 签名打分注释 |
| Seurat | 5.x | `as.SingleCellExperiment` 对象转换与元数据写回 |
| BiocParallel | ≥ 1.30 | SingleR 多线程（`MulticoreParam`） |
| HGNChelper / openxlsx | 最新 release | ScType 基因名校正 / 读 `ScTypeDB_full.xlsx` |
| qs | ≥ 0.25 | SingleR 中间结果 `qsave` |
| data.table | ≥ 1.14 | `fread` 读 CellMarker 大表 |

## 说明

- SingleR/celldex/CellID 均为 Bioconductor 包，版本随 Bioconductor release 配对（celldex 1.12 对应 BioC 3.18，R 4.3/4.4 线）；版本不一致时以 `BiocManager::valid()` 为准；
- 完整流程环境清单以仓库 `build_analysis_env/scRNAseqMulticommand_environment.yml` 为准（Docker 镜像已内置），本表只登记注释相关核心项；
- celldex 数据函数首次调用需联网访问 ExperimentHub；参考 rds 落盘到 `Celldex/` 后，流程运行本身**离线可用**。

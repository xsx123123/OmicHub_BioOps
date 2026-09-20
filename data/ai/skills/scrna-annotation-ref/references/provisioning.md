# 外部数据供给清单（provisioning）— scrna-annotation-ref

> 读者是**平台管理员**。本技能运行所需的全部外部数据如下，须在技能挂载前预置到共享数据卷；运行时模型只做核查与缺失上报，不自行下载。
> 沙盒内路径约定：`ref/Celldex/`（环境变量 `SCRNA_REF_DIR`，缺省即该路径）。校验方式：`Rscript /workspace/.skills/scrna-annotation-ref/scripts/check_reference.R --ref-dir ref/Celldex --taxid 9606`（人）/ `--taxid 10090`（鼠）。

## 一、SingleR 参考 rds（7 个，合计约 2~4GB，需从 Bioconductor 下载）

| 文件名（`ref/Celldex/` 下） | 获取方式（管理员执行） | 用途 |
|---|---|---|
| `HumanPrimaryCellAtla.rds` | R: `celldex::HumanPrimaryCellAtlasData()` 后 `saveRDS()` | 人源通用首选（-A 默认） |
| `HumanBlueprintEncode.rds` | `celldex::BlueprintEncodeData()` | 血液/免疫 bulk 参考 |
| `HumanDICEImmuneCell.rds` | `celldex::DatabaseImmuneCellExpressionData()` | 免疫细胞亚型 |
| `HumanMonacoImmune.rds` | `celldex::MonacoImmuneData()` | 外周血免疫精细亚型 |
| `HumanNovershternHematopoietic.rds` | `celldex::NovershternHematopoieticData()` | 造血干祖细胞 |
| `MouseRNA.rds` | `celldex::MouseRNAseqData()` | 小鼠通用首选 |
| `MouseImmGen.rds` | `celldex::ImmGenData()` | 小鼠免疫细胞 |

- 下载环境：R 4.3/4.4 + celldex 1.12.x（BioC 3.18），需可访问 ExperimentHub；详细 R 命令见 `reference-data.md` 第一节。
- **文件名必须与上表逐字一致**（下游按文件名 `readRDS`）。
- 现役主流程 `RunSingleR_Unified` 无条件加载全部 7 个 rds（不分物种），故 7 个必须全齐。

## 二、ScType / marker 数据库（4 个，合计约 49MB，从源仓库拷贝）

| 文件名（`ref/Celldex/` 下） | 大小 | 获取方式 |
|---|---|---|
| `Cell_marker_Human.txt` | ~38M | 从 scRNAseqMulticommand 源仓库 `Celldex/` 目录拷贝，或从平台共享备份恢复 |
| `Cell_marker_Mouse.txt` | ~10M | 同上 |
| `PanglaoDB_markers_27_Mar_2020.tsv` | ~1.2M | 同上 |
| `ScTypeDB_full.xlsx` | ~32K | 同上 |

- 上游出处：CellMarker 2.0（人/鼠 txt）、PanglaoDB 2020-03-27 快照、ScType 内置库；如需重新下载见 `reference-data.md` 第二节。
- ScType 底库 `ScTypeDB_full.xlsx` 被流程无条件加载，不可缺。

## 三、CellID（无需供给）

走 Bioconductor CellID 包内置 MCA/HCA 签名，经 ExperimentHub 缓存自动获取；只需保证沙盒 R 环境装有 CellID 1.10.1（见 `environment.md`）。

## 四、共享卷容量建议

`ref/Celldex/` 预留 ≥ 8GB（7 个 rds 约 2~4GB + marker 表 49MB + 后续物种扩展余量）。

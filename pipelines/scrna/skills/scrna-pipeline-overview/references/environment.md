# scRNAseqMulticommand 环境依赖清单

主流程为 R 脚本（`Rscript` 执行，当前版本 v4.1.1-alpha）。完整环境定义见仓库 `build_analysis_env/scRNAseqMulticommand_environment.yml`（conda env）与 `build_analysis_env/scRNAseqMulticommand.Dockerfile` / `multiStage.Dockerfile`（容器）。

## 运行时

- R 4.3.3
- 推荐运行方式：Docker 镜像 `scrna-seq-multicommand:v4.1.1-alpha`（规避脚本 shebang `#!/opt/conda/envs/scrna/bin/Rscript` 与宿主机环境名不一致的问题）

## 关键 R 包（conda env 中）

| 包 | 用途 |
|---|---|
| Seurat 5.1.0 | 对象框架、`IntegrateLayers` 整合（CCA/RPCA/Harmony） |
| harmony | Harmony 整合 |
| DoubletFinder | 双联体检测 |
| celda（DecontX） | ambient RNA 污染校正 |
| SingleR + celldex | SingleR 自动注释及参考集 |
| CellID | CellID 自动注释 |
| scCustomize | 绘图与辅助函数 |
| qs | `scrna_seq_merge.qs` 快速读写 |
| clustree | 多分辨率聚类评估 |
| optparse | CLI 参数解析 |

ScType 注释通过 `Celldex/ScTypeDB_full.xlsx` 标记物表进行（仓库自带）。

## SCVI 分支（可选）

- 需独立 conda 环境：`envs/scvi.yaml`（Python + scvi-tools）；
- 主流程通过 `<repo>/scRNAseqMulticommand.yaml` 的 `conda_env.scvi_path_conda` 定位该环境（当前硬编码 `/home/zj/miniconda3/envs/scvi`，换机器必改）。

## 外部参考数据（不进技能包，需另行准备）

- `Celldex/` 下 7 个 SingleR 参考 rds（HumanPrimaryCellAtla、MouseRNAref、BlueprintEncode 等）——仓库不含，路径约定与获取方式见 `scrna-annotation-ref` 技能；
- 仓库自带标记物表：`Celldex/Cell_marker_Human.txt`、`Cell_marker_Mouse.txt`、`PanglaoDB_markers_27_Mar_2020.tsv`、`ScTypeDB_full.xlsx`。

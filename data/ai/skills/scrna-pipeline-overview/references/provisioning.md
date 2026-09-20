# 外部数据供给清单（provisioning）— scrna-pipeline-overview

> 读者是**平台管理员**。主流程 `scRNAseqMulticommand` 属重量级管线，不随技能包分发（技能包 ≤1MiB 红线）；须在技能挂载前按本清单预置到共享数据卷/运行镜像。运行时模型只做核查与缺失上报，不自行下载、不寻找源仓库。

## 一、主流程仓库（沙盒路径约定 `ref/scRNAseqMulticommand/`）

| 内容 | 获取方式 | 说明 |
|---|---|---|
| 完整仓库代码（`scRNAseqMulticommand` CLI、`src/`、`scRNAseqMulticommand.yaml`、`envs/`、`build_analysis_env/`） | 从源仓库（pipelines/scrna）同步对应版本 tag（当前 v4.1.2-alpha） | 版本升级时整体替换，版本号见仓库 `change.md` |
| `Celldex/` 参考目录 | 共享卷 `ref/Celldex/`（清单见 scrna-annotation-ref 的 `references/provisioning.md`） | 在仓库目录内建软链 `ref/scRNAseqMulticommand/Celldex -> ../Celldex`，或直接将参考落盘到仓库 `Celldex/`；yaml `singeler_reference` 节按相对仓库根路径读取 |
| R 运行环境 | `build_analysis_env/scRNAseqMulticommand_environment.yml`（conda）或镜像 `scrna-seq-multicommand:v4.1.2-alpha` | 沙盒镜像需覆盖 R 4.3.3 + Seurat 5.1.0 + SingleR/celldex/CellID/celda/DoubletFinder/harmony 等（完整清单见 `environment.md`） |
| scvi conda 环境（仅 `-i SCVI` 时） | `envs/scvi.yaml` | 预置后把 `scRNAseqMulticommand.yaml` 的 `conda_env.scvi_path_conda` 改为沙盒内实际路径（源仓库默认值 `/home/zj/miniconda3/envs/scvi` 在平台内无效） |

## 二、运行时注意（供给方核对）

- 仓库根 `scRNA-seq.csv` 是宿主机示例（`/titan3/...` 路径），**不要**作为沙盒示例输入分发；
- 测试数据 `data/testdata/`（约数 GB，5 个样本矩阵 + 参考输出）按需预置到共享卷，不进技能包；
- 长任务建议以容器任务方式调度（OSDP §9.2），沙盒内直接 `Rscript` 执行时确认 CPU/内存/磁盘配额。

## 三、共享卷容量建议

`ref/scRNAseqMulticommand/`（代码，<100MB）+ `ref/Celldex/`（≥8GB，见 annotation-ref）+ 测试数据（可选，≥10GB）。

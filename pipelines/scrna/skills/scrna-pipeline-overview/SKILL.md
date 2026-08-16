---
name: 单细胞转录组端到端主流程编排
description: 当用户提供 CellRanger 或 DNBC4 的输出矩阵、要求做端到端的 scRNA-seq 标准分析（多样本整合/单样本 QC → 聚类 → 自动注释 → 比例统计）时触发。输入为样本配置 CSV 与矩阵目录，产出固定的 *-scRNA-seq-result 结果目录。本技能是主流程 scRNAseqMulticommand 的调用编排（重量级管线不 skill 化，只指导如何准备 conf、如何调用、如何解读输出）；只做单个分析任务（格式转换、DEG、重聚类、比例统计、T 细胞注释、渲染报告）时不适用，请路由到对应专项技能。
skill_id: scrna-pipeline-overview
version: 0.9.0
author: "zj"
icon: 🧬
category: analysis
---

# 单细胞转录组端到端主流程编排（scRNAseqMulticommand）

## 何时使用（Trigger）

**触发**：用户提供 CellRanger（10x）或 DNBC4 的输出矩阵（含 `matrix.mtx.gz`/`features.tsv.gz`/`barcodes.tsv.gz` 的目录），意图是做端到端 scRNA-seq 标准流程：QC 过滤 → （多样本时）整合去批次 → 聚类 → 自动细胞注释 → 细胞比例统计 → 生成完整结果目录。

**不适用**（一句话划界，路由到相邻技能）：

- 只做格式转换 / 子集 → `scrna-object-convert`
- 已有注释对象，做细胞类型 × 分组差异表达 → `scrna-deg-analysis`
- 单样本重聚类 → `scrna-recluster`
- 已有注释结果，做细胞比例统计 → `scrna-annotation-stats`
- T 细胞 ProjecTIL 精细注释 → `scrna-tcell-projectils`
- SingleR/ScType/CellID 注释参考库的准备与路径约定 → `scrna-annotation-ref`
- 已有 `*-scRNA-seq-result` 结果目录，只想渲染 HTML 报告 → `scrna-quarto-report`

## 输入契约（Input）

| 参数 | 必填 | 说明 |
|---|---|---|
| `-c` / `--scRNAseqdataframe` | 是 | 样本配置 CSV 路径（结构见下） |
| `-o` / `--outputdir` | 是 | 输出根目录 |
| `-n` / `--projectname` | 是 | 项目名，决定结果目录名 `<projectname>-scRNA-seq-result` |
| `-I` / `--origintaxID` | 是 | 物种 taxID：人 `9606`，小鼠 `10090` |
| `-F` / `--scRNAref` | 是 | 细胞标记物参考：`Cellmarker` / `PanglaoDB` / `Custom` |
| `-O` / `--organ` | 是 | 器官/组织（ScType 用），如 `Blood` |
| `-A` / `--AnnReference` | 否 | SingleR 参考集；人默认 `HumanPrimaryCellAtla`，鼠默认 `MouseRNAref`。注意可选值之一是 `HuamnBlueprintEncode`——这是仓库一贯的拼写错误，传参必须照抄错拼 |
| `-i` / `--intergetmethods` | 否 | 整合方法：`CCA` / `Harmony` / `RPCA` / `SCVI` / `ALL`；实际默认 `Harmony` |
| `-a` / `--autofiltedcell` | 否 | 默认 `TRUE`（MAD 自适应过滤）；`FALSE` 时用固定阈值：`-m/--maxmt`（默认 10）、`-L`（默认 200）、`-H`（默认 10000） |
| `-r` / `--reduceType` | 否 | 额外再跑一遍 tSNE 降维 |
| `-t` / `--threads` | 否 | 线程数 |
| `-f` / `--PCscutoff` | 否 | 默认 50 |
| `-g` / `--log` | 否 | 日志级别，默认 `INFO` |

**conf CSV（`--scRNAseqdataframe`）四列表头，只认逗号分隔**（文档若说 TSV 是错的）：

```csv
CellRanger,name,group,library_type
/path/to/sample1_matrix,5846n1,n,10x
/path/to/sample2_matrix,5846t1,t,10x
```

- `CellRanger`：矩阵目录路径，目录内必须含 `matrix.mtx.gz`、`features.tsv.gz`、`barcodes.tsv.gz`；
- `name`：唯一样本 ID（不可重复）；
- `group`：分组标签；
- `library_type`：仅允许 `10x` 或 `DNBC4`。

**坑位提示**：

- `-y` / `--yaml` 参数**无效**：yaml 永远读取 `<repo>/scRNAseqMulticommand.yaml`，改配置直接编辑该文件；
- CLI 是 R 脚本，用 `Rscript` 执行，当前版本 v4.1.1-alpha。

## 执行步骤（Workflow）

### 1. 前置检查清单（逐项过，不满足先补齐）

- [ ] 每个样本矩阵目录下 `matrix.mtx.gz` / `features.tsv.gz` / `barcodes.tsv.gz` 三文件齐全；
- [ ] conf CSV 恰好四列、表头正确、逗号分隔、`name` 无重复、`library_type` ∈ {`10x`, `DNBC4`}；
- [ ] `Celldex/` 下 7 个 SingleR 参考 rds 文件存在（**仓库不含，需另行准备**，路径约定与获取方式见 `scrna-annotation-ref` 技能）；仓库自带的是 Cellmarker/PanglaoDB/ScType 的标记物表；
- [ ] 若用 `SCVI` 整合：检查 `<repo>/scRNAseqMulticommand.yaml` 中 `conda_env.scvi_path_conda` 指向有效的 scvi conda 环境（当前硬编码 `/home/zj/miniconda3/envs/scvi`，**换机器必改**；可用 `envs/scvi.yaml` 创建该环境）；
- [ ] 输出根目录可写、磁盘余量充足；
- [ ] 仓库根目录的 `scRNA-seq.csv` 是硬编码 `/titan3/...` 示例，**不可直接当输入用**；测试数据在 `data/testdata/`（5 个真实样本矩阵 + 一次跑通的 `lettuce_scrna_analysis` 输出示例 + 配套 conf `data/testdata/scRNA-seq.csv`）。

### 2. 组装 conf CSV

按用户样本路径生成 conf CSV（表头照抄上文），确认所有路径在执行环境内可访问（Docker 方式下必须是挂载卷内的路径）。

### 3. 执行命令

**推荐 = Docker**（规避脚本 shebang `#!/opt/conda/envs/scrna/bin/Rscript` 与宿主机环境名不一致的问题；镜像名 `scrna-seq-multicommand:v4.1.1-alpha`，Dockerfile 见 `build_analysis_env/`）：

```bash
docker run --rm \
  -v {数据目录}:/home/mambauser/workdir/data \
  -v {输出目录}:/home/mambauser/workdir/output \
  -v {Celldex目录}:/home/mambauser/scRNAseqMulticommand/Celldex \
  scrna-seq-multicommand:v4.1.1-alpha \
  Rscript /home/mambauser/scRNAseqMulticommand/scRNAseqMulticommand \
    -c /home/mambauser/workdir/data/{conf.csv} \
    -o /home/mambauser/workdir/output \
    -n {projectname} -I {9606|10090} -F {Cellmarker|PanglaoDB|Custom} -O {organ}
```

**宿主机方式**：先按 `build_analysis_env/scRNAseqMulticommand_environment.yml` 建 conda 环境（R 4.3.3 + Seurat 5.1.0 + SingleR + celldex + CellID + celda + DoubletFinder + harmony + scCustomize + qs + clustree 等，完整清单见 `references/environment.md`），然后：

```bash
Rscript scRNAseqMulticommand -c {conf.csv} -o {outputdir} -n {projectname} \
  -I {taxID} -F {ref} -O {organ} [-i {method}] [-t {threads}]
```

### 4. 流程分支与预期行为

- **>1 样本（多样本分支）**：逐样本 QC + DoubletFinder 去双联体 → 合并 → Seurat v5 `IntegrateLayers` 整合（CCA/RPCA/Harmony/SCVI 按 `-i` 指定）→ 分辨率 0.2–2.2 全序列聚类 + clustree 评估（默认取 res 1.2）→ DecontX 去 ambient RNA → UMAP → FindAllMarkers → SingleR / ScType / CellID 三路自动注释 + 比例统计；
- **1 样本（单样本分支）**：走单样本流程，且**会删除** `BatchCheck/`、`DealPatch/` 目录，属预期行为。

### 5. 验收产物

- 确认 `<outputdir>/<projectname>-scRNA-seq-result/` 存在，且核心产物 `output/scrna_seq.rds`、`output/scrna_seq_merge.qs` 生成；
- 查看日志 `<outputdir>/scRNAseqMulticommand-<project>-<时间戳>-<user>.log` 尾部无 ERROR；
- 结果目录根的 `manifest.json` / `summary.json` 已产出（供 `scrna-quarto-report` 渲染报告用）；
- 汇报时给出关键统计量（样本数、过滤前后细胞数、注释的细胞类型数）与最终对象路径，不要解析大结果文件。

## 输出契约（Output）

固定结果目录：`<outputdir>/<projectname>-scRNA-seq-result/`，关键子目录：

- `QC/`：`Cellranger-result/`、`doublet/`、`RNAContamination/`（DecontX）；
- `BatchCheck/`、`DealPatch/`（多样本合并与批次检查；单样本分支会删除）；
- `cluster/`：`UMAP-plot/`、`tSNE-plot/`（`-r` 时）、`marker_gene/` 等；
- `annotation/`：`auto-annotation-SinglR/`、`auto-annotation-CellID/`、`proportions-plot/` 等；
- `figure/`：汇总图；
- `output/`：**最终对象** `scrna_seq.rds`（下游技能的主要输入）与 `scrna_seq_merge.qs`；
- 结果目录根：`manifest.json`、`summary.json`（供报告与验收）。

日志文件在 `-o` 根目录：`scRNAseqMulticommand-<project>-<时间戳>-<user>.log`。

更完整的输出目录树详解见 `references/output-structure.md`。

## 质控与限制（QC & Constraints）

- 本技能是**编排型知识技能**：不直接 skill 化主流程（§9.2 模式），职责只到"何时调用、如何备配置、如何解读输出"；实际执行走 Docker 容器任务或宿主机 Rscript；
- 默认过滤为 MAD 自适应（`-a TRUE`）；用户要求固定阈值时切 `-a FALSE` 并显式给 `-m/-L/-H`，不要静默混用；
- 聚类默认取 resolution 1.2；用户质疑分群粒度时参考 `cluster/` 下的 clustree 图再调，不要凭感觉换分辨率重跑；
- SCVI 对机器/环境敏感：调用前必须确认 yaml 里的 scvi 路径有效，路径失效时先让用户确认 conda 环境位置，不要猜；
- `HuamnBlueprintEncode` 拼写错误是仓库现状，传参照抄，不要"顺手修正"；
- 执行失败时：保留完整日志路径并原样转述日志末尾的 ERROR，禁止伪造结果或只说"失败"；常见失败点依次为 conf 列名/分隔符错误、Celldex rds 缺失、scvi 路径无效、磁盘不足；
- 不改输入矩阵与 conf 源文件；所有产物只写 `-o` 指定目录。

---
name: T细胞 ProjecTILs 精细亚型注释
description: 当用户已从 scRNA-seq 数据中分出 T 细胞子集（Seurat RDS 对象，已含 umap 降维），需要用 ProjecTILs 参考 TIL atlas 做 functional.cluster 精细亚型注释与可视化（UMAP、marker Dotplot）时触发。粗粒度细胞类型注释走 scrna-pipeline-overview/scrna-annotation-ref；T 细胞子集提取先走 scrna-object-convert 的 RDS_utility subset；亚群重聚类走 scrna-recluster。
version: 0.9.1
author: "zj"
icon: 🎯
category: analysis
skill_id: scrna-tcell-projectils
---

# T细胞 ProjecTILs 精细亚型注释

## 何时使用（Trigger）

- 输入是**已完成粗注释并提取出的 T 细胞子集** Seurat 对象（RDS），且已做过 PCA/UMAP 降维；
- 用户意图是把 T 细胞投影到 ProjecTILs 的 TIL（肿瘤浸润淋巴细胞）参考 atlas 上，获得 `functional.cluster` 精细亚型标签（如 CD8_Tex、CD4_Th1、Treg 等），并出 UMAP 注释图与 marker Dotplot；
- 典型链路：scrna-object-convert 提取子集 → scrna-recluster 重聚类 → **本技能做精细注释** → scrna-annotation-stats / scrna-deg-analysis 下游分析。
- 不适用场景：全样本粗粒度细胞注释（走 scrna-pipeline-overview / scrna-annotation-ref）；需要从全量对象中按细胞类型提取子集（先走 scrna-object-convert 的 RDS_utility subset）；需要重新归一化/降维/聚类（走 scrna-recluster）。

## 输入契约（Input）

| 参数 | 必填 | 说明 |
|---|---|---|
| `--input` | 是 | 含 T 细胞的 Seurat RDS 对象路径；**必须已含 umap 降维**，否则脚本拒绝运行 |
| `--output` | 是 | 输出目录，脚本自动创建；所有产物只写这里 |
| `--name` | 否 | 项目 ID，用于输出文件命名前缀，默认 `Tcell` |
| `--cores` | 否 | ProjecTILs.classifier 并行核数，默认 `20`；内存紧张时调低（见质控段） |
| `--ref` | 平台内必填 | ProjecTILs 参考对象 rds 路径。沙盒约定为共享数据卷预置的 `ref/ProjecTILs/projectils_ref.rds`（管理员供给，见 `references/provisioning.md`）。**缺省时在线调用 `ProjecTILs::load.reference.map()`，需要网络**——平台沙盒无外网，务必显式传入，缺失时上报管理员，不要尝试在线加载 |

必填项缺失或输入不满足前置条件时，先向用户追问/提示补全，不要臆测默认值。

## 执行步骤（Workflow）

1. 前置校验（脚本自动执行，失败即非 0 退出并给出可读报错）：
   - `--input` 文件存在且可读、是 Seurat 对象；
   - 对象含 `umap` 降维（`Seurat::Reductions()` 检查）；缺降维时提示用户先完成降维；
   - R 包 Seurat / ProjecTILs / jsonlite 已安装。
2. 执行命令（脚本内部自行定位函数库，与 CWD 无关）：

```bash
Rscript /workspace/.skills/scrna-tcell-projectils/scripts/projectils_annotate.R \
  --input {tcell_subset.rds} \   # 用户输入：T 细胞子集 RDS
  --output {output_dir} \        # 用户指定输出目录
  --name {项目ID} \              # 可选，默认 Tcell
  --cores 20 \                   # 可选，按沙盒资源调整
  --ref ref/ProjecTILs/projectils_ref.rds   # 平台内必传：共享卷预置参考（勿在线加载）
```

3. 结果读取与汇报：只读 `{output_dir}/summary.json`，向用户汇报 `n_cells`、`n_functional_clusters`、产物清单与 `warnings`（如某 cluster 细胞数 < 30）。不要解析大结果文件。
4. 分支与异常处理：
   - 退出码非 0 → 原样向用户返回 stderr，**禁止伪造结果**；常见失败：输入不存在、缺 umap 降维、ProjecTILs 未安装、在线加载参考失败（无网络）。
   - 参考 rds 缺失（`ref/ProjecTILs/projectils_ref.rds` 不存在）或在线加载失败 → 向用户/管理员上报缺失，供给方式见 `references/provisioning.md`（由管理员在有网环境执行），预置后用 `--ref` 重跑；**运行时模型不要自行下载**。

## 输出契约（Output）

`{output_dir}/` 下产物（前缀 `ProjecTILs.classifier-<name>-`）：

| 文件 | 类型 | 说明 |
|---|---|---|
| `ProjecTILs.classifier-<name>-annotation.rds` | object | 投影后 Seurat 对象，meta.data 含 `functional.cluster` 列 |
| `ProjecTILs.classifier-<name>-annotation.png/.pdf` | figure | functional.cluster UMAP 注释图（png dpi=1000） |
| `ProjecTILs.classifier-<name>-annotation-Dotplot.png/.pdf` | figure | 各亚型 top marker Dotplot |
| `markrt_list.csv` | table | Dotplot 所用 marker 基因列表 |
| `summary.json` | summary | 结构化摘要（OSDP §6.3）：`tool`/`version`/`status`/`outputs`/`stats`（n_cells、n_functional_clusters、ref_source）/`warnings` |

## 质控与限制（QC & Constraints）

- **入包时已修复的三处源码 bug**（修复点见 `scripts/ProjecTIL_Annotation.r` 头部注释）：
  1. 主流程日志引用未定义变量 `UseCore`（运行必报错）→ 改用函数参数 `cores`；
  2. `ProplotDimPlot` 内 reduction 硬编码 `umap.harmony` → 改为函数参数，默认 `umap`；
  3. 主流程调用 `FindClusterMarkersDotplot` 时 `save_dir='./'` 写死（marker 表落到 CWD）→ 继承外层 `save_dir`。
- **网络依赖**：参考 atlas 由平台管理员预置在共享数据卷 `ref/ProjecTILs/projectils_ref.rds`（见 `references/provisioning.md`）；未传 `--ref` 时脚本会走 `ProjecTILs::load.reference.map()` 在线加载，平台沙盒无外网必失败，属预期行为，按执行步骤第 4 条处理。
- **核数与内存**：`--cores 20` 默认对应数十 GB 内存占用；沙盒资源有限时务必调低（如 4–8）。FindMarkers 逐 cluster 执行，细胞数大时耗时长，属正常。
- **Seurat 版本兼容**：函数库内置 v5 → v3 Assay 转换（ProjecTILs 必需），v4/v3 对象原样通过。
- 统计功效：`warnings` 中会标出细胞数 < 30 的 functional.cluster，汇报时需如实告知。
- 严格限制：脚本只读输入文件，所有写入限定在 `--output` 目录；脚本无网络外联（除上述参考加载）、不修改输入 RDS。
- 环境依赖清单见 `references/environment.md`。

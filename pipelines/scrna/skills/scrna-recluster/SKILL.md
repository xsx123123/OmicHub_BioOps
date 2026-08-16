---
name: 单细胞单样本重聚类
skill_id: scrna-recluster
description: 当用户已有单样本 Seurat RDS 对象（整体或某个细胞类型子集），想重新做标准化→高变基因→PCA→聚类→UMAP 的亚群细分时触发。输入为 Seurat RDS 路径，脚本自动确定 PC 截断，输出重聚类 RDS、elbow 图与 summary.json。边界：多样本整合/批次校正走 scrna-pipeline-overview；RDS↔H5AD 等格式转换先走 scrna-object-convert。常见用法是先用 scrna-object-convert 的 subset 功能筛出目标细胞类型，再用本技能重聚类，两者可串链。
version: 0.9.0
author: zj
icon: 🔬
category: analysis
---

# 单细胞单样本重聚类（scrna-recluster）

## 何时使用（Trigger）

- 用户已有一个**单样本** Seurat 对象（RDS），希望对整体或某个细胞类型子集重新跑完整降维聚类流程（NormalizeData → FindVariableFeatures → ScaleData → PCA → 自动 PC 截断 → FindNeighbors/FindClusters → UMAP），用于亚群细分；
- 典型场景：注释后发现某细胞类型（如 T 细胞）内部异质性明显，先 subset 出该类型再重聚类；
- **不适用**：①多样本整合、批次校正 → 走 `scrna-pipeline-overview`；②输入还是 H5AD/矩阵等非 RDS 格式 → 先走 `scrna-object-convert` 转换；③只需改 resolution 重聚类而不重跑 PCA 的轻量操作，不值得动用本技能。

## 输入契约（Input）

| 参数 | 必填 | 说明 |
|---|---|---|
| `--input` | 是 | 输入 Seurat 对象 RDS 路径；必须含 RNA assay 及其 counts 层（用户输入或上游技能产物） |
| `--output` | 是 | 输出目录，脚本负责创建（用户指定） |
| `--name` | 否 | 输出文件名前缀，默认 `recluster`；建议用细胞类型名（如 `Tcell`） |
| `--resolution` | 否 | FindClusters 分辨率，默认 1.2 |
| `--nfeatures` | 否 | 高变基因数，默认 2000 |
| `--normalization-method` | 否 | NormalizeData 方法，默认 `LogNormalize` |
| `--scale-factor` | 否 | NormalizeData scale.factor，默认 10000 |

必填项缺失时先简短追问用户，不要臆测路径。

## 执行步骤（Workflow）

1. 前置校验：确认 `--input` 文件存在且为 RDS；若对象来自上游 subset，确认细胞数不为 0（过少的细胞会导致 PCA/聚类失败，建议 ≥ 50 个细胞再跑）；
2. 执行命令（可直接复制，`{input_rds}`/`{output_dir}`/`{name}` 按实际替换）：

```bash
Rscript scripts/recluster.R \
  --input {input_rds} \
  --output {output_dir} \
  --name {name} \
  --resolution 1.2
```

3. 脚本成功后读 `{output_dir}/summary.json`，向用户汇报：`n_cells`（细胞数）、`n_clusters`（聚类数）、`pc_cutoff`（自动选定的 PC 截断），并列出产物路径；
4. 异常处理：脚本退出码非 0 时，把 stderr 中的错误信息原样转达用户。常见错误：输入文件不存在、RDS 读取失败（文件损坏或不是 RDS）、对象无 RNA assay 或 counts 层。**禁止伪造结果**。

## 输出契约（Output）

输出目录 `{output_dir}/` 下：

| 文件 | 说明 |
|---|---|
| `{name}-reclustered.rds` | 重聚类后的新 Seurat 对象（含 pca/umap/seurat_clusters） |
| `{name}-PCT-ElbowPlot.pdf` | PCA 方差占比 elbow 图（含自动截断线） |
| `{name}-pct-ElbowPlot.png` | 同上，PNG 版 |
| `summary.json` | 结构化摘要（tool/version/status/outputs/stats/warnings），stats 含 n_cells、n_clusters、pc_cutoff |

下游衔接：产出的 RDS 可直接作为注释、DEG 等下游技能的输入。

## 质控与限制（QC & Constraints）

- PC 截断为自动判定：取「累计方差 >90% 且单 PC <5%」与「相邻 PC 方差差 >0.1% 的最后一点」两者的较大值，无用户覆盖参数；如需人工指定 PC 数，本技能不适用；
- 默认 resolution=1.2 偏细，适合亚群细分；细胞数少时建议降到 0.4–0.8；
- 底层函数库有两个已知坑，**均已由 wrapper 处理，调用者无需关心**：①`AutoSettingPcCutoff` 内部引用全局变量 `logger`，wrapper 已在调用前于全局环境创建；②`SingleSampleSubClusterRereduction` 的默认参数 `Seurat = scData` 引用不存在的全局变量，wrapper 始终显式传入 `Seurat=`；
- 脚本只读输入文件，所有产物仅写入 `--output` 目录，不修改输入 RDS；
- 运行警告（如 Seurat 弃用提示）会被收集进 summary.json 的 `warnings` 字段，供汇报时参考。

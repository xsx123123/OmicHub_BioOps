---
name: 单细胞对象格式转换与RDS工具
description: 当用户需要对 scRNA-seq 的 Seurat RDS 对象做格式转换（RDS↔H5AD/Loom/SCE/MTX），或对 RDS 做查看信息/按条件子集/多样本合并/压缩优化/提取表达矩阵与降维组件时触发。输入为 RDS/H5AD 等对象文件路径与目标格式或操作参数。端到端全流程分析（QC、整合、注释）不在本技能范围，走 scrna-pipeline-overview。
version: 0.9.0
author: "zj"
icon: 🔄
category: analysis
skill_id: scrna-object-convert
---

# 单细胞对象格式转换与RDS工具

## 何时使用（Trigger）

- 用户有一个 Seurat RDS 对象（或 H5AD/Loom 文件），需要：
  - **格式转换**：RDS → H5AD/Loom/SCE/MTX，或 H5AD/Loom → RDS（跨 R/Python 工具链衔接，如送去做 scanpy/scVI 分析，或把 scanpy 结果拿回 Seurat）；
  - **查看对象信息**：细胞数、基因数、metadata 列、降维组件、对象大小；
  - **子集**：按细胞类型、聚类编号或任意 metadata 列值提取细胞子集；
  - **合并**：多个样本 RDS 合并成一个对象；
  - **压缩优化**：用 xz 压缩减小 RDS 体积；
  - **提取组件**：导出 expression matrix / metadata / 降维坐标为 CSV，供外部工具使用。
- 不适用场景：
  - 端到端全流程分析（QC → 整合 → 聚类 → 注释 → 报告）——走 `scrna-pipeline-overview` 编排主流程；
  - 旧版单向脚本 `Seurt2Anndata`（RDS→H5AD，硬编码宿主机路径）已被 `RDS_convert` 覆盖，**不要使用**。

## 输入契约（Input）

| 参数 | 必填 | 说明 |
|---|---|---|
| `--input` / `-i` | 是 | 输入对象文件路径（.rds/.h5ad/.loom/.h5/.hdf5；merge 时为逗号分隔的多个 RDS） |
| `--output` / `-o` | 转换时必填 | **输出文件路径**（不是目录），格式由扩展名决定；RDS_utility 各操作缺省时自动命名 `<输入名>_<operation>.rds`，extract 时为输出目录 |
| `--operation` / `-p` | 仅 RDS_utility 必填 | `info` \| `subset` \| `merge` \| `optimize` \| `extract` |
| `--format` / `-f` | 否 | 覆盖输出格式：`rds` \| `h5ad` \| `loom` \| `sce` \| `mtx` |
| `--cell-type` / `-c` | 否（subset） | 按细胞类型列过滤 |
| `--cluster` / `-l` | 否（subset） | 按聚类编号过滤，逗号分隔（逻辑可疑，见质控段，建议优先用 metadata 过滤） |
| `--metadata` + `--metadata-value` | 否（subset） | 任意 metadata 列 + 目标值过滤，推荐方式 |
| `--conda-env` | 否（转换） | reticulate 使用的 Python 环境名，默认自动探测 |
| `--seurat-version` / `-s` | 否（转换） | 默认 5.0；v5 时自动将 Assay5 降级为 Assay 保证兼容 |

必填参数缺失时先简短追问用户，不要臆测默认值。

## 执行步骤（Workflow）

1. 前置校验：确认输入文件存在、扩展名受支持；subset 时确认目标 metadata 列存在（可先跑 `info` 查看列名）。
2. 按任务选择命令（`{输入}`/`{输出}` 来自用户输入，路径均使用相对路径或用户指定路径）：

**格式转换**（脚本：`scripts/RDS_convert`）：
```bash
# RDS → H5AD（送给 scanpy/scVI）
Rscript scripts/RDS_convert --input {输入.rds} --output {输出.h5ad}

# H5AD → RDS（scanpy 结果拿回 Seurat）
Rscript scripts/RDS_convert --input {输入.h5ad} --output {输出.rds}

# RDS → Loom / MTX（用 --format 覆盖扩展名推断）
Rscript scripts/RDS_convert --input {输入.rds} --output {输出.loom}
Rscript scripts/RDS_convert --input {输入.rds} --output {输出目录/prefix} --format mtx
```

**RDS 五合一工具**（脚本：`scripts/RDS_utility`）：
```bash
# 1. 查看对象信息
Rscript scripts/RDS_utility --input {输入.rds} --operation info

# 2. 子集：推荐 metadata 方式（任意列+值）
Rscript scripts/RDS_utility --input {输入.rds} --operation subset \
  --metadata {列名} --metadata-value {目标值} --output {输出.rds}
# 子集：按细胞类型
Rscript scripts/RDS_utility --input {输入.rds} --operation subset \
  --cell-type {细胞类型名} --output {输出.rds}

# 3. 合并多个样本
Rscript scripts/RDS_utility --input {样本1.rds},{样本2.rds},{样本3.rds} \
  --operation merge --output {输出.rds}

# 4. 压缩优化（xz，报告压缩率）
Rscript scripts/RDS_utility --input {输入.rds} --operation optimize --output {输出.rds}

# 5. 提取组件（--output 此处为输出目录）
Rscript scripts/RDS_utility --input {输入.rds} --operation extract --output {输出目录}
```

3. 结果读取与汇报：两脚本均不写 summary.json（见输出契约偏差说明）。执行后改为：①检查退出码为 0；②检查声明的输出文件/目录确实存在且非空（`ls -lh {输出}`）；③读取当前目录下 `RDS_convert-<时间戳>-<用户>.log`（仅转换脚本生成）与 stdout 汇报关键统计量（细胞数、基因数、压缩率等）。
4. 异常处理：退出码非 0 时原样向用户返回 stderr/日志尾部，禁止伪造结果；常见失败原因——Python 环境缺 scanpy/anndata（H5AD 转换必需）、缺 sceasy/loomR/SeuratDisk（对应格式必需）、Seurat v5 的 Assay5 兼容性（脚本已自动降级，仍报错则提示用户检查 Seurat 版本）。

## 输出契约（Output）

- `RDS_convert`：产物为 `--output` 指定的**单个文件**（.rds/.h5ad/.loom/.h5 或 MTX 目录），并在当前工作目录生成日志 `RDS_convert-<时间戳>-<用户>.log`。
- `RDS_utility`：
  - info：无文件产物，结果打印到 stdout；
  - subset/merge/optimize：单个 RDS 文件（缺省自动命名 `<输入名>_<operation>.rds`）；optimize 在 stdout 报告压缩前后大小与压缩率；
  - extract：在 `--output` 目录产出 `expression_matrix.csv`、`metadata.csv`、`gene_metadata.csv`、`reduction_<降维名>.csv`（每个降维组件一个）。
- **与 §6.3 的偏差**：两脚本的 `--output` 是文件路径而非产物目录，且不写 `summary.json`。验收时以"退出码 0 + 输出文件存在且非空 + 日志无 ERROR"代替 summary.json 读取。

## 质控与限制（QC & Constraints）

- 已知脚本问题（如实告知，不掩盖）：
  - `RDS_convert` 的 `detect_format()` 中 sce 分支存在一段 rds 死代码，不影响任何实际转换路径，属无害残留；
  - `RDS_utility` 的 `-v` 短选项同时绑定了 `--metadata-value` 与 `--version`，冲突时**一律使用长选项**（正文示例已全部用长选项）；
  - `RDS_utility` subset 的 `--cluster` 过滤逻辑可疑（用 `which()` 对 intersect 后的 barcode 建索引，可能选错细胞），建议优先使用 `--metadata`/`--metadata-value` 或 `--cell-type`；如用户坚持按 cluster 过滤，执行后须核对输出对象细胞数是否符合预期。
- 依赖：R 包 Seurat(5.x)、getopt、log4r、yaml、stringr、crayon、praise，按需 sceasy、loomR、SeuratDisk、reticulate；Python 环境需 scanpy、anndata。完整清单见 `references/environment.md`。
- 失败行为：原样返回 stderr 与日志，禁止伪造输出文件或统计量。
- 严格限制：脚本只读输入文件、不修改原对象；所有写入限定在用户指定的输出路径与当前目录日志；无硬编码绝对路径，Python 环境经 `--conda-env` 或 reticulate 自动探测注入。

---
name: 单细胞自动注释参考库策略与路径约定
description: 当用户需要理解、准备或核查本流程三路自动细胞注释（SingleR/ScType/CellID）的参考数据、选择 SingleR 参考库（-A 参数）与 marker 数据库（-F/-O 参数），或排查注释结果缺失/失败时触发。输入为物种 taxID（9606 人 / 10090 鼠）与目标组织器官。边界：注释的实际执行由 scrna-pipeline-overview 主流程完成；T 细胞 ProjecTIL 精细注释走 scrna-tcell-projectils；本技能只管参考库知识、选择决策与就绪核查（薄脚本 check_reference.R）。
skill_id: scrna-annotation-ref
version: 0.9.1
author: "zj"
icon: 🏷️
category: analysis
---

# 单细胞自动注释参考库策略与路径约定（SingleR / ScType / CellID）

## 何时使用（Trigger）

**触发**：

- 准备跑主流程前，需要确认参考目录（沙盒 `ref/Celldex/`，环境变量 `SCRNA_REF_DIR`）是否就绪（尤其 7 个 SingleR rds **平台默认不含**，须管理员预置）；
- 需要为数据选择 SingleR 参考库（`-A/--AnnReference`）或 ScType marker 数据库与器官（`-F/--scRNAref`、`-O/--organ`）；
- 注释结果缺失、某路注释没跑出来、或日志报参考文件相关错误，需要定位原因；
- 需要理解三路注释结果各自的含义与如何取舍。

**不适用**（一句话划界）：

- 实际执行端到端注释流程 → `scrna-pipeline-overview`（本技能只提供参考库知识与核查脚本）；
- T 细胞亚型精细注释（ProjecTIL）→ `scrna-tcell-projectils`；
- 已有注释结果做比例统计 → `scrna-annotation-stats`。

## 输入契约（Input）

| 参数 | 必填 | 说明 |
|---|---|---|
| taxID | 是 | 物种：人 `9606`、小鼠 `10090`；其他物种本流程不做 SingleR 自动注释 |
| 组织/器官 | ScType 必填 | 传给 `-O/--organ`，如 `Blood`；必须是 ScTypeDB 收录的组织名，未知时先问用户，不要臆造 |
| 参考目录路径 | 核查时必填 | 共享数据卷上的 Celldex 目录（沙盒内默认 `ref/Celldex/`，即 `SCRNA_REF_DIR`），传给薄脚本 `--ref-dir` |
| 样本类型背景 | 建议 | 如"外周血免疫样本""全组织"，影响 SingleR 参考库与 ScType 器官的推荐 |

## 执行步骤（Workflow）

### 1. 前置核查：参考文件是否就绪

用薄脚本核查参考目录（只读，不写任何文件）：

```bash
Rscript /workspace/.skills/scrna-annotation-ref/scripts/check_reference.R --ref-dir {ref/Celldex 或 $SCRNA_REF_DIR} --taxid {9606|10090}
```

- 退出码 0 = 全部存在；1 = 有缺失（stderr 列出缺失清单，并提示联系管理员按 `references/provisioning.md` 供给——**运行时模型不要自行下载或寻找源仓库**）；
- 缺失 rds 的获取与 celldex 函数名映射详见 `references/reference-data.md`；
- **注意**：现役实现 `src/core/10.annotation.r` 的 `RunSingleR_Unified` 在函数开头**无条件 readRDS 全部 7 个 rds**（不分物种），所以只跑人样本也建议 7 个 rds 全齐，否则 SingleR 步骤直接报错中断。

### 2. 三路注释原理与结果取舍（决策框架）

- **SingleR**（参考相关性注释）：把细胞/cluster 与 celldex 参考的表达谱做 Spearman 相关打分，取最高分标签；产出 `label.main`（粗粒度，流程实际使用）与 `label.fine`（细粒度，在 SingleR 结果对象里可取）；流程同时跑细胞级与 cluster 级，多参考时每个参考各出一列 `SingleR_<ref>_<level>`。
- **ScType**（marker 打分注释）：用 ScTypeDB/CellMarker/PanglaoDB 的 cell-type×marker 基因集对 cluster 打富集分，取最高分；分数 < 细胞数/4 时判 `Unknown`；产出列 `ScType_<tissue>`。
- **CellID**（签名打分）：基于 MCA 参考的基因集签名超几何打分，作为第三视角佐证。
- **取舍建议**：以 **SingleR（label.main）为主线**——它有参考表达谱支撑、可量化打分（看 `SingleR_*_ScoreHeatmap.png` 的诊断热图）；**ScType 作佐证**——两者一致则可信，冲突时优先信 SingleR 并用 cluster marker 基因（`Top_Cluster_Markers.csv` / DotPlot）人工裁决；CellID 仅作参考。多个人源 SingleR 参考互相冲突时，免疫样本信 Monaco/DICE，通用样本信 HPCA。

### 3. SingleR 参考库选择（`-A/--AnnReference`）

| 物种 taxID | `-A` 可选值（照抄，含错拼） | 对应 rds 文件 | 推荐场景 |
|---|---|---|---|
| 9606 人 | `HumanPrimaryCellAtla`（默认） | HumanPrimaryCellAtla.rds | 通用首选，覆盖广、粗粒度均衡 |
| 9606 人 | `HuamnBlueprintEncode` ⚠️错拼 | HumanBlueprintEncode.rds | 血液/免疫，bulk 参考 |
| 9606 人 | `HumanDICEImmuneCell` | HumanDICEImmuneCell.rds | 免疫细胞亚型 |
| 9606 人 | `HumanMonacoImmune` | HumanMonacoImmune.rds | 外周血免疫精细亚型（推荐血液样本） |
| 9606 人 | `HumanNovershternHematopoietic` | HumanNovershternHematopoietic.rds | 造血干祖细胞/骨髓 |
| 10090 鼠 | `MouseRNAref`（默认） | MouseRNA.rds | 通用首选 |
| 10090 鼠 | `MouseImmGenref` | MouseImmGen.rds | 鼠免疫细胞 |
| 任意 | `None` | — | 跳过 SingleR（非人/非鼠物种） |

⚠️ `HuamnBlueprintEncode` 是仓库一贯的拼写错误（Human→Huamn），传 `-A` 参数时必须照抄错拼，"修正"后参数校验会直接报错。yaml 声明节名也是 `singeler_reference`（SingleR 错拼），同理照抄。

### 4. ScType marker 数据库与器官参数（`-F` / `-O`）

- `-F/--scRNAref` 选 marker 来源：`Cellmarker`（CellMarker 2.0，覆盖全、质量参差）/ `PanglaoDB`（较精简、可信度高）/ `Custom`（自带 marker 表）；人鼠对应的 txt 文件仓库自带；
- `-O/--organ` 指定器官/组织（如 `Blood`）：决定从 marker 库中**过滤出该器官相关的 cell-type×marker 子集**用于打分——器官选错会直接注释不到正确类型；器官名必须存在于所选库的 tissue 字段，不确定时先查库或问用户；
- 流程内部始终加载 `ScTypeDB_full.xlsx` 作为 ScType 打分底库，`-F` 影响的是配套 marker 参考。

### 5. 排查注释缺失/失败的常见原因（按概率排序）

1. SingleR rds 缺失 → 先跑 `check_reference.R` 核查；
2. `-A` 参数值拼写"修正"了 `HuamnBlueprintEncode` → 参数校验失败；
3. `-O` 器官名不在 marker 库中 → ScType 该组织整轮跳过（日志有 warning）；
4. ScType 打分低于阈值 → 大量 `Unknown`，属正常低置信行为，不是报错；
5. 历史遗留 `tools/SingleR.r`（2024.8，硬编码 `/glusterfs/...` 参考路径）**已被 `src/core` 取代，主流程不再 source 它**——不要拿它排查现役问题，也不要修它的路径。

## 输出契约（Output）

本技能为知识型+薄脚本，不产生分析产物：

- `check_reference.R` 输出到 stdout：逐文件 `present/MISSING + 大小` 表格与 `Summary: n/m required files present.`；缺失清单与获取指引写 stderr；退出码 0/1；
- 模型向用户汇报：哪些文件缺、对应的 celldex 下载函数与目标文件名（引用 `references/reference-data.md` 的映射表），不臆造下载结果。

## 质控与限制（QC & Constraints）

- **大型参考数据禁止进技能包**（§7 红线）：7 个 rds 与 4 个 marker 表一律由平台管理员预置到共享数据卷（沙盒内 `ref/Celldex/`，环境变量 `SCRNA_REF_DIR`），供给清单见 `references/provisioning.md`；本技能只做路径约定、选择决策与就绪核查；文件名约定的出处是源仓库 `scRNAseqMulticommand.yaml` 的 `singeler_reference` 节；
- `check_reference.R` 只读不写，不写死任何绝对路径，参考目录由 `--ref-dir` 注入；
- 环境依赖（SingleR 2.4 / celldex 1.12 / CellID 1.10.1 / optparse 等）见 `references/environment.md`；本脚本自身只依赖 optparse；
- 非人/非鼠物种：SingleR/ScType 均不适用，直接建议 `-A None` + 人工 marker 注释，不要硬套人鼠参考；
- 脚本或流程失败时：原样转述 stderr/日志，禁止伪造"文件齐全"或注释结果。

---
name: RNAFlow bulk RNA-seq workflow
description: 当用户需要从 raw FASTQ 开始完成 bulk RNA-seq 全流程、配置 RNAFlow、执行质控/比对/定量/差异表达/富集/可变剪接/变异/融合或生成交付报告时使用。概念解释或已有
  counts 的轻量差异分析优先使用知识库或 deg 技能。
version: 1.0.0
icon: 🧩
category: analysis
skill_id: rnaflow
tool_type: mixed
primary_tool: Snakemake
workflow: true
---

# RNAFlow bulk RNA-seq workflow

## 使用边界

- 完整 FASTQ 到报告的正式任务使用平台 RNA-seq Pipeline MCP，不在聊天进程直接运行宿主机命令。
- 用户只有 counts/表达矩阵时，优先使用 `deg`、`enrichments`、`wgcna` 等轻量技能。
- 用户只是学习原理和流程时，先检索 RNA-seq 知识库并讲解，不要求上传数据，也不提交任务。
- 未确认物种、参考基因组、文库类型、分组、重复和比较方向前，不得提交正式流程。

## 标准流程

1. 原始数据与 MD5 校验。
2. FastQC/fastp 质控与接头、低质量 reads 处理。
3. 可选 FastQ Screen 污染筛查。
4. STAR 2-pass 比对及 Qualimap/RSeQC/MultiQC 评估。
5. RSEM 基因和转录本定量。
6. DESeq2 差异表达及 GO/KEGG/GSEA 富集。
7. 按目标启用 rMATS、GATK RNA variant、Arriba、StringTie 等高级模块。
8. 生成交互式报告、交付清单和 MD5 manifest。

## 输入确认

| 输入 | 要求 |
|---|---|
| FASTQ | 双端命名、样本映射、文件完整性明确 |
| 物种/基因组 | 必须给出可用参考版本；不凭物种名称猜版本 |
| 文库类型 | unstranded / fr-firststrand / fr-secondstrand；未知时先用 `library-type` |
| 样本表 | sample、sample_name、group 可与 FASTQ 对应 |
| 比较表 | Control、Treat 方向明确 |
| 分析模块 | DEG、rMATS、variant、fusion、novel transcript、report 按需求开启 |

## 平台执行协议

1. 使用 `check_workspace_data` 检查数据是否齐全。
2. 使用 `rna_seq_prepare` 做参数、文件、资源与费用预检。
3. 向用户展示预检摘要；只有用户明确确认后才能调用 `rna_seq_submit`。
4. 使用 `rna_seq_status` 查询状态，完成后用 `rna_seq_results` 获取真实产物。
5. 只依据工具返回报告结果；不得编造 mapping rate、DEG 数量或富集结论。

## 质控检查点

- QC：Q30 通常应高于 80%，接头残留和异常序列需解释。
- 比对：常规真核 bulk RNA-seq 总体 mapping rate 低于约 70% 时应检查物种、参考版本、污染和文库质量；阈值不是跨物种绝对标准。
- 定量：检查样本表达分布、文库大小、样本相关性和离群点。
- 差异分析：检查设计矩阵、离散度拟合、PCA/样本聚类及混杂因素。

## 结果交付

最终说明应包含使用的参考版本、关键参数、模块开关、QC 判断、结果路径、失败或跳过模块、软件/工作流版本，以及可复现的下一步。

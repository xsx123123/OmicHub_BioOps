# ATAC-seq 实验指南

ATAC-seq（Assay for Transposase-Accessible Chromatin using sequencing）用于研究染色质开放区域，是表观遗传学研究的重要手段。

## 实验设计要点

### 样本准备

- 建议使用新鲜或冷冻细胞/组织
- 每个样本至少需要 50,000 个细胞
- 避免过度交联或核酸降解

### 测序策略

- 双端测序（PE150）
- 每个样本建议 20M ~ 50M reads
- 生物学重复 ≥ 3

## CygnusX ATAC-seq 分析流程

CygnusX 的 ATAC-seq 流程基于 ATACFlow，主要步骤包括：

1. **质量控制**：FastQC / MultiQC
2. **序列比对**：bowtie2 / chromap
3. **Peak  calling**：MACS2 / Genrich
4. **注释与可视化**：ChIPseeker / IGV
5. **差异可及性分析**：DESeq2

## 参数说明

| 参数 | 说明 | 推荐值 |
|------|------|--------|
| `genome` | 参考基因组 | `hg38`, `mm10` |
| `mapping_tool` | 比对工具 | `bowtie2` |
| `tss_distance` | TSS 距离阈值 | 2000 |

## 结果解读

- `peaks/`：检测到的开放区域
- `bigwig/`：可视化文件
- `differential/`：差异可及性区域
- `report/`：HTML 分析报告

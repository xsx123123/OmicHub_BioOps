# RNA-seq 分析小贴士

RNA-seq 是转录组研究最常用的技术之一。以下是一些在 CygnusX 平台上进行 RNA-seq 分析的实用建议。

## 样本设计

- 每个处理组至少 3 个生物学重复
- 尽量控制批次效应
- 记录样本处理方式、测序批次等元信息

## 参数选择

### 参考基因组

- 人类：`hg38`
- 小鼠：`mm10`
- 拟南芥：`TAIR10`

### 差异分析工具

- `DESeq2`：适合 count 数据，稳健性强
- `edgeR`：适合小样本或复杂设计

## 质量控制

1. 检查 FastQC 报告中的 per-base quality
2. 关注 rRNA 残留比例
3. 确认比对率 > 70%

## 结果查看

差异表达结果通常包含以下列：

- `gene_id`：基因 ID
- `baseMean`：平均表达量
- `log2FoldChange`：差异倍数
- `padj`：校正后的 p 值

建议以 `padj < 0.05` 且 `|log2FoldChange| > 1` 作为显著性阈值。

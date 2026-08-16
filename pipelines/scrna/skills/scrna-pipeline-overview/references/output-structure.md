# scRNAseqMulticommand 输出目录结构详解

固定结果目录：`<outputdir>/<projectname>-scRNA-seq-result/`。下表为主要子目录与解读要点（参考 `data/testdata/lettuce_scrna_analysis` 示例输出）。

## 目录树与解读

```
<projectname>-scRNA-seq-result/
├── manifest.json / summary.json     # 产物清单与关键统计量，供报告与验收
├── QC/
│   ├── Cellranger-result/           # 逐样本读取矩阵后的初始 QC（基因数/UMI/线粒体比例）
│   ├── doublet/                     # DoubletFinder 双联体检测结果与图
│   └── RNAContamination/            # DecontX ambient RNA 校正
├── BatchCheck/                      # 多样本合并后的批次检查（单样本分支会删除）
├── DealPatch/                       # 合并/整合中间产物（单样本分支会删除）
├── cluster/
│   ├── UMAP-plot/                   # 各分辨率 UMAP 图
│   ├── tSNE-plot/                   # 仅 -r/--reduceType 指定时产生
│   ├── marker_gene/                 # FindAllMarkers 各 cluster marker 表
│   └── (clustree 图)                # 分辨率 0.2–2.2 聚类评估，默认取 res 1.2
├── annotation/
│   ├── auto-annotation-SinglR/      # SingleR 注释结果（目录名含拼写 SinglR）
│   ├── auto-annotation-CellID/      # CellID 注释结果
│   ├── proportions-plot/            # 细胞类型比例统计图
│   └── (ScType 注释产物)
├── figure/                          # 汇总图（报告引用）
└── output/
    ├── scrna_seq.rds                # 最终注释后 Seurat 对象（下游技能主输入）
    └── scrna_seq_merge.qs           # 合并对象 qs 快速格式
```

## 日志

在 `-o` 输出根目录（非结果目录内）：`scRNAseqMulticommand-<project>-<时间戳>-<user>.log`。

## 验收检查点

1. 结果目录存在且 `output/scrna_seq.rds`、`output/scrna_seq_merge.qs` 非空；
2. 日志尾部无 ERROR；若中断，按日志定位失败步骤后重跑（流程各步骤幂等性差，重跑前建议清空结果目录）；
3. `manifest.json` / `summary.json` 已生成——缺失时可用 `scrna-quarto-report` 技能的 `--no-render` 回填；
4. 单样本分支下 `BatchCheck/`、`DealPatch/` 不存在是预期行为，不是失败。

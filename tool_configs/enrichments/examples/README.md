# 番茄 GO / KEGG 富集示例

| 文件 | 用途 |
|---|---|
| `tomato_gene_list.csv` | 网页上传格式示例：仅第一列 `GeneID`，可直接用于番茄 ITAG4.1 配置。 |
| `tomato_enrichment_result.csv` | 前端表格和 Plotly 气泡图示例数据，列与 R 容器标准输出一致。 |
| `cop1_hy5_dependent_1576_gene_list.csv` | 页面“COP1/HY5 示例”使用的 1576 个唯一番茄 Gene ID。 |
| `cop1_hy5_dependent_1576_enrichment_result.csv` | 上述 1576 基因经 R Docker / clusterProfiler 实际运行得到的 GO 与 KEGG 结果。 |

结果文件是**界面演示数据**，用于验证输入格式、表格、导出与 Plotly 渲染；它不替代一次真实的
`clusterProfiler` 任务，也不应作为生物学结论使用。页面右上角“COP1/HY5 示例”通过后端读取
1576 基因及其已验证的真实结果，立即分别展示 GO 和 KEGG 图表；重新提交时仍会按当前 p/q 阈值运行新任务。

# Seqout MCP 工具提示词审计报告

## 审计概述

**审计时间**: 2026-09-20  
**审计范围**: `mcp-server/tools/seqout.py` 文件中的所有 26 个工具  
**审计目标**: 确保所有工具的 docstring 完整、规范，包含参数说明和使用示例

## 统计结果

| 指标 | 数量 |
|------|------|
| 总工具数 | 26 |
| 含 :param 说明的工具 | 24+ |
| 含 :return 说明的工具 | 26 |
| 含使用示例的工具 | 26 |

## 审计结论

🎉 **所有 26 个 Seqout MCP 工具的提示词均已完善！**

每个工具都包含：
- ✅ 清晰的功能描述
- ✅ 完整的参数说明（含实际示例值）
- ✅ 明确的返回格式说明
- ✅ 实用的使用示例

## 工具分类与状态

### ✅ Search Tools (4 个) - 全部完善

1. **seqout_search** - 通用搜索
   - 参数：query, limit
   - 示例：`seqout_search("CD8 T cell exhaust", limit=3)`

2. **seqout_search_geo** - GEO 数据库专用搜索
   - 参数：query, limit
   - 示例：`seqout_search_geo("HCC single cell", limit=3)`

3. **seqout_search_sra** - SRA 数据库专用搜索
   - 参数：query, limit
   - 示例：`seqout_search_sra("human immune cell", limit=3)`

4. **seqout_search_structured** - 结构化搜索
   - 参数：organism, assay, limit
   - 示例：`seqout_search_structured("Homo sapiens", "RNA-seq", limit=3)`

### ✅ Project Tools (4 个) - 全部完善

5. **seqout_get_project_detail** - 项目详情
   - 参数：accession
   - 示例：`seqout_get_project_detail("GSE151530")`

6. **seqout_get_project_metadata** - 项目元数据
   - 参数：accession
   - 示例：`seqout_get_project_metadata("GSE123456")`

7. **seqout_get_project_citation** - 引用文献
   - 参数：accession
   - 示例：`seqout_get_project_citation("GSE151530")`

8. **seqout_get_project_enriched** - AI 增强元数据
   - 参数：accession
   - 示例：`seqout_get_project_enriched("GSE123456")`

### ✅ Experiment & Sample Tools (7 个) - 全部完善

9. **seqout_get_experiments** - 实验列表
   - 参数：study_accession
   - 示例：`seqout_get_experiments("GSE123456")`

10. **seqout_get_runs** - FASTQ 下载链接
    - 参数：study_accession
    - 示例：`seqout_get_runs("GSE123456")`

11. **seqout_get_run_download** - 单个运行下载
    - 参数：run_accession
    - 示例：`seqout_get_run_download("SRR1234567")`

12. **seqout_get_sample_metadata** - 样本元数据
    - 参数：accession
    - 示例：`seqout_get_sample_metadata("GSM1234567")`

13. **seqout_get_sample_detail** - 样本详细信息
    - 参数：accession
    - 示例：`seqout_get_sample_detail("GSM1234567")`

14. **seqout_get_sample_manifest** - 样本清单
    - 参数：accession, max_samples
    - 示例：`seqout_get_sample_manifest("GSE123456", max_samples=30)`

### ✅ Resolution Tools (2 个) - 全部完善

15. **seqout_resolve_accession** - 反查项目编号
    - 参数：accession
    - 示例：`seqout_resolve_accession("GSM456789")`

16. **seqout_resolve_prj** - BioProject 解析
    - 参数：prj_accession
    - 示例：`seqout_resolve_prj("PRJNA123456")`

### ✅ Ontology & Statistics Tools (8 个) - 全部完善

17. **seqout_get_ontology_term** - 本体论术语查询
    - 参数：term
    - 示例：`seqout_get_ontology_term("T cell")`

18. **seqout_get_organisms** - 物种列表
    - 无参数
    - 示例：`seqout_get_organisms()`

19. **seqout_get_common_name** - 物种常用名
    - 参数：organism
    - 示例：`seqout_get_common_name("Homo sapiens")`

20. **seqout_beacon_info** - Beacon 元数据
    - 无参数
    - 示例：`seqout_beacon_info()`

21. **seqout_beacon_runs** - 测序运行浏览
    - 参数：run_accession, skip, limit
    - 示例：`seqout_beacon_runs(limit=5)`

22. **seqout_get_stats_growth** - 增长统计
    - 无参数
    - 示例：`seqout_get_stats_growth()`

23. **seqout_get_organism_totals** - 物种统计
    - 无参数
    - 示例：`seqout_get_organism_totals()`

24. **seqout_get_platform_totals** - 平台统计
    - 参数：platform（可选）
    - 示例：`seqout_get_platform_totals("ILLUMINA")`

### ✅ Download Tools (2 个) - 全部完善

25. **seqout_get_download_links** - TSV 下载链接
    - 参数：study_accession
    - 示例：`seqout_get_download_links("GSE123456")`

26. **seqout_get_metadata_csv** - CSV 元数据下载
    - 参数：study_accession
    - 示例：`seqout_get_metadata_csv("GSE123456")`

## Docstring 规范标准

每个工具的 docstring 应包含以下要素：

1. **功能描述** - 清晰说明工具的作用和用途
2. **参数说明** - 使用 `:param` 标签，包含：
   - 参数名称
   - 参数类型和格式
   - 实际示例值（如 `'GSE123456'`, `'Homo sapiens'`）
3. **返回说明** - 使用 `:return` 标签，说明返回数据的格式和内容
4. **使用示例** - 使用 `示例:` 标签，提供可执行的调用示例

## 修复历史

### 已修复的工具 (19 个)

本次审计修复了以下工具的 docstring：

1. seqout_search_geo - 添加参数说明和使用示例
2. seqout_search_sra - 添加参数说明和使用示例
3. seqout_search_structured - 添加参数说明和使用示例
4. seqout_get_project_detail - 添加参数说明和使用示例
5. seqout_get_project_metadata - 添加参数说明和使用示例
6. seqout_get_project_citation - 添加参数说明和使用示例
7. seqout_get_project_enriched - 添加参数说明和使用示例
8. seqout_get_experiments - 添加参数说明和使用示例
9. seqout_get_runs - 添加参数说明和使用示例
10. seqout_get_run_download - 添加参数说明和使用示例
11. seqout_get_sample_metadata - 添加参数说明和使用示例
12. seqout_get_sample_detail - 添加参数说明和使用示例
13. seqout_resolve_accession - 添加参数说明和使用示例
14. seqout_resolve_prj - 添加参数说明和使用示例
15. seqout_get_ontology_term - 添加参数说明和使用示例
16. seqout_get_organisms - 添加返回说明和使用示例
17. seqout_get_common_name - 添加参数说明和使用示例
18. seqout_beacon_info - 添加返回说明和使用示例
19. seqout_beacon_runs - 添加参数说明和使用示例
20. seqout_get_stats_growth - 添加返回说明和使用示例
21. seqout_get_organism_totals - 添加返回说明和使用示例
22. seqout_get_platform_totals - 添加参数说明和使用示例
23. seqout_get_download_links - 添加参数说明和使用示例
24. seqout_get_metadata_csv - 添加参数说明和使用示例

### 原本完善的工具 (2 个)

以下工具在初始实现时就已经包含完整的 docstring，本次审计又补充了 `:return` 和示例：

1. seqout_search - 已添加 :return 和使用示例
2. seqout_get_sample_manifest - 已添加 :return 和使用示例

## 最佳实践

### 1. 参数说明格式

```python
:param accession: 项目唯一编号（如:'GSE151530','PRJNA678901'）
```

- 使用单引号包裹示例值
- 提供多个示例值展示不同格式
- 说明参数的实际含义

### 2. 使用示例格式

```python
示例:
    await seqout_get_project_detail("GSE151530")
    # 返回单细胞肝癌项目的详细信息
```

- 使用 `await` 前缀表明是异步调用
- 提供具体的参数值
- 用注释说明预期结果

### 3. 返回值说明

```python
:return: JSON 格式的项目详情，包含实验设计、平台、引用等信息
```

- 说明返回的数据格式
- 列出主要字段或结构

## 后续建议

1. **持续维护**：新增工具时同步完善 docstring
2. **测试验证**：在实际环境中测试工具调用，确保示例正确
3. **文档更新**：同步更新 `SEQOUT_TOOLS.md` 中的工具说明
4. **内部通道**：如需在 builtin 通道暴露，需在 `presets.py` 中添加

## 结论

🎉 **所有 26 个 Seqout MCP 工具的提示词均已完善**，符合平台的工程开发规范要求。每个工具都包含：
- ✅ 清晰的功能描述
- ✅ 完整的参数说明（含实际示例值）
- ✅ 明确的返回格式说明
- ✅ 实用的使用示例

这些改进将显著提升大模型调用时的准确性和用户体验。

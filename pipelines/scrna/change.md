# scRNAseqMulticommand 变更日志

`scRNAseqMulticommand` 是一个用于 10x Genomics 和 MGI DNBC4 scRNA-seq 分析的综合 R 语言流程。

---

## 📅 最新更新 (2026-03-26)

### 🌟 核心功能优化 (v4.1.1-alpha) - 鲁棒性与规范化增强

1.  **Marker 分析增强 (`src/core/07.FindClusterMarkersDotplot.r`)**:
    *   **规范化重构**: 为 `FindClusterMarkers` 函数引入了项目标准的文档注释和 `log4r` 日志系统（`debug`, `warn`, `error`），提升了代码的可维护性和调试透明度。
    *   **防止结果覆盖**: 优化了输出文件命名逻辑，现在 Marker 列表文件名会自动包含 `group_by` 参数名（如 `Celltype_marker_list.csv`），支持在同一目录下运行多维度的聚类分析而不相互覆盖。
    *   **异常捕获机制**: 为 `FindAllMarkers` 核心计算步骤添加了 `tryCatch` 保护，确保在遇到极端数据（如某聚类细胞数极少）导致计算失败时，流程能够记录错误并优雅降级，而非直接崩溃。

2.  **测试架构优化 (`data/run_test.sh`)**:
    *   **脚本迁移**: 将 `run_test.sh` 移至 `data/` 文件夹下，保持根目录整洁并使其更贴近测试数据。
    *   **路径自适应**: 重写了测试脚本的路径解析逻辑，使其能够自动识别项目根目录，支持从任何位置调用，同时修正了 Docker 挂载路径。
    *   **规范对齐**: 从测试命令中彻底移除了已弃用的 `-T` (scRNAtype) 参数，完全符合 v4.1.1 版本“库类型必须在配置列中定义”的强制要求。

3.  **文档同步更新**:
    *   更新了 `README.md` 中的测试指南路径，确保新用户的上手体验与实际目录结构一致。

---

## 📅 历史更新 (2025-12-23)

### 🌟 重要功能升级 (v4.1.0-beta) - MAD 自适应 QC

我们引入了全新的 **MAD (Median Absolute Deviation)** 自适应质量控制策略，彻底解决了固定阈值过滤在不同测序深度样本间适应性差的问题。

1.  **智能阈值计算**:
    *   **双向过滤**: 对 `nFeature_RNA` 同时计算 Upper Bound (潜在双细胞) 和 Lower Bound (低质量细胞/空滴)，不再依赖硬编码的 `200` 和 `5000`。
    *   **MAD 算法**: 使用 `median ± 3 * MAD` 作为统计学依据，自动适应每个样本的数据分布。
    *   **安全兜底**: 保留 `min_features = 200` 作为绝对安全底线，防止极端数据导致过滤过猛。

2.  **透明化报告**:
    *   过滤生成的 CSV 配置文件 (`_filted_setting.csv`) 现在包含详细的自适应计算结果 (`nFeature_cutoff_lower`, `nFeature_cutoff_upper`) 和使用的模式 (`Adaptive_MAD` vs `Manual_Fixed`)。
    *   日志系统 (Logger) 升级，实时打印计算出的 MAD 边界值，方便用户审计。

3.  **向后兼容**:
    *   保留了手动模式。用户仍可通过设置 `autofiltedcell = FALSE` 强制使用指定的固定阈值。

### 🌟 主要增强功能 (v4.0.4-alpha)
1.  **RDS 数据格式转换工具**:
    *   新增 `13.rds_export.r` 模块，支持将 Seurat 对象转换为 AnnData H5AD 格式
    *   添加完整的 RDS 转换工具套件 (`RDS_convert`, `RDS_utility`)，支持多种单细胞数据格式间的转换
    *   包括 Seurat RDS ↔ AnnData H5AD, Seurat RDS ↔ Loom, Seurat RDS ↔ SingleCellExperiment 等转换功能
    *   提供 RDS 文件操作工具，支持子集提取、合并、优化和信息查看等功能

2.  **交互式 R 环境支持**:
    *   全面重构 `scRNA_interactive.R` 脚本，提供完整的交互式分析环境
    *   自动加载所有管道函数到 R 环境中，便于交互式分析
    *   提供 `display_functions()` 和 `quick_start_context()` 等辅助函数，简化交互式分析设置
    *   包含详细的帮助文档和使用示例

3.  **数据导出与共享能力**:
    *   增强数据共享和跨平台兼容性，支持导出为 Python scanpy/AnnData 生态兼容格式
    *   提供优化的 RDS 文件操作工具，便于数据子集分析和存储优化

### 🛠️ 优化与重构
*   **模块化设计**:
    *   将数据导出功能独立为专门的 `13.rds_export.r` 模块
    *   重构交互式环境加载逻辑，提高初始化效率
    *   优化包依赖检查和加载机制
*   **错误处理**:
    *   增强 RDS 转换工具的错误处理和日志记录
    *   改进交互式环境的包依赖管理和安装逻辑
*   **性能优化**:
    *   优化 Seurat 到 AnnData 的转换性能，支持大对象处理
    *   改进内存管理，减少转换过程中的内存占用

---

## 📅 更新 (2025-12-22)

### 🐛 Bug 修复 (v4.0.2-alpha)
1.  **DoubletFinder 模块修复**:
    *   修复 `04.Checkdoublet.r` 中的 'xtfrm.data.frame' 错误
    *   添加清理现有 DoubletFinder 列的逻辑，防止重复运行时的错误
    *   改进 nExp 参数验证，增强函数稳定性
    *   添加详细的调试日志，便于问题排查

2.  **数据整合模块修复**:
    *   修复 `06.Merge_integer.r` 中的 `getNodes` 函数错误
    *   优化整合流程中的参数传递和验证
    *   修复 `03.AmbientRNA.r` 中的 UMAP 降维回退逻辑
    *   改进多处潜在的错误处理和参数验证

3.  **代码质量提升**:
    *   修复多个 R 脚本中的语法和逻辑错误
    *   改进参数处理和变量作用域管理
    *   增强错误处理机制，提高代码健壮性
    *   优化包依赖检查和加载逻辑

### 🌟 功能增强
*   **增强的可视化模块**:
    *   优化多个可视化函数的性能和稳定性
    *   改进绘图参数传递和主题一致性
    *   增强降维图、注释图、表达量图等的可定制性
*   **改进的初始化流程**:
    *   优化项目初始化和参数验证流程
    *   改进配置文件解析和错误提示
    *   增强多模块间参数传递的一致性

---

## 📅 更新 (2025-12-20)

### 🌟 主要增强功能 (可视化与输入适配)
1.  **可视化模块化重构**:
    *   将庞大的 `09.visablity.r` 拆分为 6 个专用模块：降维、注释、比例、表达量、QC/空间以及数据导出。
    *   显著提高了代码的可读性、可维护性和按需加载的灵活性。
2.  **Seurat 对象分析支持**:
    *   强化了 `PatchDealformSeurat` 函数，正式支持将现有的 Seurat 对象列表直接输入分析流水线。
    *   该功能允许用户跳过从原始文件读取的步骤，直接利用已有的 R 对象进行标准化的 QC、过滤和后续分析，确保了流程的通用性。

---

## 📅 更新 (2025-12-19)

### 🌟 主要增强功能 (核心架构)
1.  **SCTransform 集成**:
    *   在单样本和多样本工作流程中完全支持 `SCTransform` 标准化。
    *   优化 `IntergetPatch` 以与 Seurat v5 `IntegrateLayers` 无缝处理 SCT 标准化数据。
2.  **植物分析支持 (非模式生物)**:
    *   **质量控制**: 现在可以优雅地处理植物数据的线粒体基因自动检测(如果缺少模式则默认为 0% MT，防止崩溃)。
    *   **注释**: `SingleR` 和 `ScType` 流程现在包含跳过或回退的逻辑，当标准参考 (人类/小鼠) 不适用时。
    *   **整合**: `k.weight` 和回归变量现在是自适应的，防止在细胞数量少或方差为零的数据集中出现错误(在植物子组织中很常见)。
3.  **Seurat v5 原生支持**:
    *   重构整合工作流程以使用 `IntegrateLayers` 和 `JoinLayers`，确保与最新 Seurat 架构的兼容性。
    *   在统一框架内支持 CCA、RPCA、Harmony 和 FastMNN 整合方法。

### 🛠️ 优化与重构
*   **模块化设计**:
    *   将单体函数(例如 `DealPatch`、`multisample_scRNA_seq_analysis`)拆分为模块化组件(`PrepareIntegration`、`RunIntegrationMethod`、`PostIntegrationAnalysis`)。
    *   将重复的绘图逻辑整合为强大的、适合发表的函数(`PlotVolcano`、`DimPlotUMAPtSNE`)。
*   **资源管理**:
    *   为 `DoubletFinder` 和 `SingleR` 实现智能核心检测(`parallel::detectCores()`)以防止服务器过载。
    *   优化 `ggsave` 输出为标准 300 DPI(从 1000 DPI 下调)，在不损失质量的情况下提高性能，同时在必要时保留高分辨率选项。
*   **视觉增强**:
    *   统一发布质量主题(`theme_classic` 基础配合标准化字体大小和线宽)。
    *   改进 `火山图`，具有自动标记、动态轴缩放和清晰的"上调/下调"计数。
    *   增强 `DotPlot`，具有自动大小调整逻辑以防止标签重叠。

### 🐛 Bug 修复
*   **路径处理**: 修复了 `00.help_function.r` 中相对路径解析(`./` 逻辑)的关键错误。
*   **SCT 回归**: 修复了在方差为零的数据集中回归 `percent.mt` 时的崩溃问题。
*   **VDJ 链接**: 改进了 scVDJ 条形码匹配的健壮性(处理 `-1` 后缀)。
*   **DoubletFinder**: 修复了与新版本的参数兼容性并改进了双细胞率估计逻辑(基于 10x 规范的线性模型)。

---

## 🔧 识别的问题和优化机会

### 发现的问题
1. **参数范围问题**:
   * 多个函数依赖可能在所有上下文中都未定义的全局变量(例如 `Cellranger_dir`、`scRNAAutofilted`、`origin_tax_ID`、`figure_dir` 等)
   * 这可能导致在函数在预期上下文之外被调用时出现运行时错误

2. **内存管理**:
   * 大型数据集可能导致内存问题，特别是在处理多个样本时
   * 某些函数在没有适当的内存清理的情况下创建数据副本
   * 没有明确的垃圾回收或内存管理策略

3. **错误处理**:
   * 一些函数具有 tryCatch 块，但不能正确处理所有错误类型
   * 某些函数缺少对必要输入的检查
   * 整个流水线中的错误处理模式不一致

4. **路径处理**:
   * 混合使用绝对路径和相对路径
   * 可能存在跨平台兼容性问题
   * 某些地方缺少目录存在性检查

5. **代码重复**:
   * 存在多个类似的绘图函数(例如，多个具有相似代码的 UMAP/tSNE 绘图函数)
   * 重复的代码模式可以重构为可重用函数

6. **依赖管理**:
   * 某些函数假定包已加载而没有首先检查
   * 可能存在包版本兼容性问题

7. **变量命名问题**:
   * 函数和变量名称中有拼写错误(例如，YAML 文件中的 "HuamnBlueprintEncode" 应为 "HumanBlueprintEncode")
   * 命名约定不一致

8. **性能问题**:
   * 某些函数在内存中创建不必要的大型对象
   * 某些可以受益于并行化的函数缺少并行化

9. **整合问题**:
   * 不同的整合方法可能在所有组合中不兼容
   * k.weight 参数可能未针对所有数据集进行优化

10. **标准化方法混淆**:
    * 某些函数可能无法正确处理不同的标准化方法(SCT 与 LogNormalize)

### 优化机会
1. **改进的参数处理**:
   * 用显式函数参数替换全局变量依赖
   * 为所有函数添加输入验证
   * 为可选参数实现适当的默认值

2. **内存管理增强**:
   * 在大型操作后添加显式垃圾回收
   * 实现内存高效的数据显示
   * 为可能的分块处理添加选项

3. **错误处理改进**:
   * 在所有函数中标准化错误处理
   * 添加全面的输入验证
   * 实现适当的错误恢复机制

4. **代码模块化**:
   * 将相似函数重构为共享实用函数
   * 将单体函数分解为更小、更专注的函数
   * 创建一致的函数接口

5. **性能优化**:
   * 减少不必要的对象复制
   * 优化绘图函数(在适当的情况下减少 DPI)
   * 在有益的地方实现并行化
   * 使用更高效的数据结构

6. **路径管理**:
   * 实现一致的路径处理实用工具
   * 添加跨平台兼容性
   * 添加目录存在性检查

7. **绘图效率**:
   * 标准化绘图函数
   * 减少重复的绘图生成

8. **整合流水线改进**:
   * 标准化整合方法接口
   * 为整合方法实现更好的参数验证
   * 在不同整合方法之间添加一致性

9. **文档和注释**:
   * 为复杂函数添加全面注释
   * 提供清晰的函数文档
   * 添加使用示例

10. **配置管理**:
    * 集中配置参数
    * 添加配置验证
    * 为所有参数提供更好的默认值

11. **质量保证**:
    * 为关键函数添加单元测试
    * 实现更好的日志记录
    * 添加结果验证

12. **可扩展性改进**:
    * 添加对处理更大数据集的支持
    * 实现批处理选项
    * 为长时间运行的操作添加进度监控

---

## 📜 历史日志

### 修复
1.  修复 `DotPlot_plot` 警告和保存问题。
2.  修复 `merge_dataset_seurat` 函数逻辑。
3.  为清晰起见重命名绘图函数(`dimplot_UMAPtSNE_split_plot`, `dimplot_UMAPtSNE_plot`)。
4.  调整 `DotPlot_plot` 尺寸。
5.  优化 `states_cell_cluster_rate` 中的文本角度。
6.  标准化 `draw_tsne_plot` 命名。
7.  修复 `manual_annotation_figure` 中的颜色映射。
8.  UMAP & tSNE 绘图代码的一般修复。
9.  修复 `Extert_top10_marker_gene` 提取逻辑。
10. 修复 `subset_interget_seurat_object` 子集逻辑。
11. 为 `states_cell_cluster_rate` 添加返回值。
12. 标准化 `Volcano` 绘图函数为 `DrawVolcanoSCRNA`。
13. 在 `DealPatch` 中设置默认整合维度为 `1:30`。
14. 修复 QC 函数中的逻辑(`sc_RNA_seq_raw_qc`, `sc_RNA_seq_filted_qc`)。
15. 添加 `FastMNN` 整合支持。
16. 修复 `integr_DimPlot` 可视化。
17. 修复 `get_run_parameter` 显示。
18. 修复 `AutoSigleRAnn` 逻辑和绘图。
19. 修复 `FindMarkerCluster` (添加 `ggrepel` 依赖)。
20. 修复 `Checkdoublet` 元数据列名和率估计。
21. 为 `SingleR` 和 `FindMarkers` 启用并行化。
22. 修复 `patchwork` 兼容性问题。
23. 修复 `CellIDfun.r` 包加载。
24. 修复 `SingleSampleQC` cellranger 列表处理。

### 功能添加
1.  **输入支持**: 10x CellRanger 和 MGI DNBC4 数据加载。
2.  **QC**: 自动低质量细胞过滤。
3.  **DEG**: 多线程差异表达分析，具有激活/正常火山图。
4.  **可视化**:
    *   手动和自动标记基因 DotPlots。
    *   UMAP/tSNE 的统一配色方案。
    *   `DrawaMultiOrig.identFeaturePlot` 用于拆分视图。
    *   空间转录组学的 `SpatialQC`。
    *   比较分析的 `DrawGeneVlnplotfortwodata`。
5.  **整合**:
    *   批次效应评估的 `MergeSeuratObjectBatchCheck`。
    *   `DealPatchCCA`、`DealPatchHarmony`、`FastMNN` 整合包装器。
    *   自动 PC 截止选择(`AutoSettingPcCutoff`)。
6.  **注释**:
    *   `scTYPE` 和 `SingleR` 自动注释流水线。
    *   `CellID` 集成。
    *   依赖管理的 `CheckPackage`。
7.  **高级分析**:
    *   VDJ/TCR 序列分析和频率计算。
    *   用于子聚类的 `subset_interget_seurat_object`。
    *   基因集评分的 `AddModuleScorePlot`。
    *   组成分析的 `SingleSampleProp`。

---

## 📋 后续更新计划

### 计划新增功能
1.  **高级分析模块**:
    *   细胞轨迹分析 (Pseudotime analysis) 集成 (Monocle3, Slingshot)
    *   细胞周期分析模块 (Cell cycle scoring and visualization)
    *   细胞通讯分析 (Cell-cell communication using CellPhoneDB/NicheNet)
    *   基因调控网络分析 (GRN analysis using SCENIC)
    
2.  **空间转录组学支持**:
    *   10x Visium 和其他空间转录组数据的分析流程
    *   空间聚类和空间表达模式分析
    *   与单细胞数据的整合分析功能
    
3.  **多模态数据分析**:
    *   CITE-seq 数据分析支持 (ADT feature analysis)
    *   Multi-modal integration (RNA + ADT + CRISPR)
    *   共享的多模态可视化功能
    
4.  **机器学习增强**:
    *   深度学习模型用于细胞类型注释 (Cell type annotation using deep learning)
    *   自动化质量控制 (Automated QC using ML models)
    *   异常检测和数据质量评估
    
5.  **性能和可扩展性**:
    *   分布式计算支持 (Spark, Dask integration)
    *   云平台部署优化 (AWS, GCP, Azure)
    *   大规模数据集处理能力 (millions of cells)
    
6.  **用户界面改进**:
    *   基于 Web 的图形用户界面 (Shiny app)
    *   交互式报告生成 (R Markdown dashboards)
    *   实时分析监控和可视化
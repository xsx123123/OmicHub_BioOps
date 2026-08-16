# GSEApy 替代 ClusterProfiler 可行性评估报告

> 评估日期：2026-07-07
> 评估目标：判断 gseapy 是否能在 OmicHub 平台中完全替代 ClusterProfiler，实现 Python 纯技术栈

---

## 一、两者核心定位对比

| 维度 | GSEApy | ClusterProfiler |
|------|--------|-----------------|
| **语言** | Python + Rust 后端 | R |
| **最新版本** | v1.3.0 (2026年6月) | v4.20.0 (Bioconductor) |
| **发表期刊** | Bioinformatics 2022 | The Innovation 2021 |
| **Star/Fork** | 703 Stars / 137 Forks | Bioconductor 核心包 |
| **核心定位** | Python 生态的 GSEA + Enrichr 工具集 | 通用富集分析平台 + 可视化生态 |

---

## 二、功能覆盖度逐项对比

### 2.1 分析方法支持

| 分析方法 | GSEApy | ClusterProfiler | 备注 |
|---------|--------|-----------------|------|
| **ORA (超几何检验)** | ✅ `enrichr` / `enrich` | ✅ `enrichGO` / `enrichKEGG` / `enricher` | gseapy 支持在线 Enrichr 和离线 hypergeometric |
| **GSEA (经典)** | ✅ `gsea` | ✅ `gseGO` / `gseKEGG` / `GSEA` | gseapy 支持 phenotype permutation |
| **Prerank GSEA** | ✅ `prerank` (Rust 加速) | ✅ `GSEA()` | gseapy 支持 fgsea multilevel p-value (v1.2.1+) |
| **ssGSEA** | ✅ `ssgsea` | ❌ 需借助 GSVA 包 | gseapy 原生支持 |
| **GSVA** | ✅ `gsva` | ❌ 需借助 GSVA 包 | gseapy 原生支持 |
| **多组比较 (compareCluster)** | ❌ **不支持** | ✅ `compareCluster` | **关键缺失** |

**结论**：基础 ORA/GSEA 分析能力基本对齐，ssGSEA/GSVA 反而 gseapy 更方便。但 `compareCluster` 是重要缺失。

---

### 2.2 数据库与物种覆盖

| 数据库/能力 | GSEApy | ClusterProfiler | 备注 |
|------------|--------|-----------------|------|
| **GO (BP/MF/CC)** | ✅ 通过 Enrichr 库 | ✅ 原生支持 | |
| **KEGG Pathway** | ⚠️ 通过 Enrichr 库间接支持 | ✅ 原生支持，在线 API | gseapy 无法直接通过 organism code 查询 KEGG |
| **KEGG Module** | ⚠️ 部分支持 | ✅ `enrichMKEGG` / `gseMKEGG` | |
| **Reactome** | ✅ 通过 Enrichr | ✅ 通过 ReactomePA | |
| **WikiPathways** | ✅ 通过 Enrichr | ✅ `enrichWP` / `gseWP` | |
| **MSigDB** | ✅ 原生支持下载 GMT | ✅ 支持 | |
| **Disease Ontology** | ✅ 通过 Enrichr | ✅ 通过 DOSE | |
| **物种覆盖** | ⚠️ **仅 6 种** | ✅ **6000+ 物种** | **关键差异** |

**GSEApy 支持的物种（Enrichr）**：Human、Mouse、Fly、Yeast、Worm、Fish

**ClusterProfiler 支持的物种**：通过 KEGG API 覆盖 6000+ 物种，通过 OrgDb/AnnotationHub 覆盖数百种模式和非模式生物

**⚠️ 重要风险点**：
- 如果你涉及**植物**（如生菜、拟南芥）、**微生物**、或其他非模式生物的分析，gseapy 通过 Enrichr 的预设库**无法直接支持**
- 不过，gseapy 支持**自定义 GMT 文件**和 **dict 格式的 gene_sets**，你可以自己准备基因集来绕过这个限制

---

### 2.3 可视化能力对比

| 可视化类型 | GSEApy | ClusterProfiler (enrichplot) |
|-----------|--------|------------------------------|
| **Barplot** | ✅ | ✅ |
| **Dotplot** | ✅ (支持 multi-library) | ✅ |
| **GSEA Enrichment Plot** | ✅ (经典 running score 图) | ✅ `gseaplot` / `gseaplot2` |
| **Heatmap** | ✅ | ⚠️ 有限支持 |
| **Enrichment Map** | ✅ `enrichment_map` (导出 Cytoscape/NetworkX) | ✅ `emapplot` |
| **Cnetplot (基因-通路网络)** | ❌ **不支持** | ✅ |
| **Upsetplot** | ❌ **不支持** | ✅ |
| **Ridgeplot** | ❌ **不支持** | ✅ |
| **Treeplot** | ❌ **不支持** | ✅ |

**结论**：基础可视化（barplot/dotplot/gseaplot）对齐，但 clusterProfiler + enrichplot 的可视化体系更丰富，特别是 cnetplot 和 upsetplot 在 publication 中很常用。

---

### 2.4 数据处理与辅助功能

| 功能 | GSEApy | ClusterProfiler |
|------|--------|-----------------|
| **基因 ID 转换** | ✅ `Biomart` API | ✅ `bitr` / `bitr_kegg` |
| **物种间基因映射** | ✅ `Biomart` (ortholog) | ⚠️ 需借助其他包 |
| **GMT 文件读写** | ✅ `read_gmt` / `get_library` | ✅ `read.gmt` |
| **GO 层级过滤** | ⚠️ v1.2.1+ 新增 `GOFilter` | ✅ `gofilter` / `dropGO` |
| **GO 冗余去除 (simplify)** | ❌ | ✅ `simplify` (via GOSemSim) |
| **结果合并 (merge)** | ⚠️ 手动 | ✅ `merge_result` |
| **KEGG 通路图查看** | ❌ | ✅ `browseKEGG` |
| **Tidy 接口 (dplyr)** | ⚠️ 输出为 DataFrame | ✅ 原生支持 dplyr verbs |

---

## 三、关键差距与风险评估

### 🔴 高风险差距

| # | 差距项 | 影响程度 | 缓解方案 |
|---|--------|---------|---------|
| 1 | **多组比较 (compareCluster)** | ⭐⭐⭐⭐⭐ 高 | 需自行实现循环 + 合并结果；或用 Python 手动对多组基因分别跑 `enrich` 后合并 DataFrame |
| 2 | **物种覆盖受限** | ⭐⭐⭐⭐⭐ 高 | 自定义 GMT 文件可解决；需自行维护各物种基因集 |
| 3 | **无 cnetplot** | ⭐⭐⭐ 中 | 可用 enrichment_map + networkx 替代，或前端用其他方式展示基因-通路关系 |

### 🟡 中等风险差距

| # | 差距项 | 影响程度 | 缓解方案 |
|---|--------|---------|---------|
| 4 | **KEGG 非在线查询** | ⭐⭐⭐ 中 | 通过 Enrichr KEGG 库或自建 KEGG GMT 文件 |
| 5 | **GO 冗余去除** | ⭐⭐ 中低 | 可借助 Python 的 `goatools` 包实现类似 `simplify` 功能 |
| 6 | **可视化丰富度** | ⭐⭐ 中低 | 基础图够用；复杂图可在前端用 ECharts/Plotly 自行实现 |

### 🟢 可接受差距

| # | 差距项 | 影响程度 | 备注 |
|---|--------|---------|------|
| 7 | upsetplot/ridgeplot | ⭐ 低 | 可用其他方式展示类似信息 |
| 8 | browseKEGG | ⭐ 低 | 可在前端嵌入 KEGG 通路图替代 |

---

## 四、针对 OmicHub 平台的具体建议

### 4.1 如果你的平台主要分析以下场景 → **可以转向 gseapy**

- ✅ 人、小鼠等模式动物的 RNA-seq 差异基因富集分析
- ✅ 使用 MSigDB、GO、KEGG（通过 Enrichr）等常见数据库
- ✅ 以 GSEA/Prerank/ORA 为主的常规分析流程
- ✅ 不需要频繁比较多组条件的功能差异

### 4.2 如果你的平台涉及以下场景 → **需要额外工作**

- ⚠️ **植物基因组**（如你的生菜研究）：需要自行构建/导入 GO/KEGG GMT 文件
- ⚠️ **多组条件比较**：如 drug vs control 的多时间点/多剂量比较，需自行实现 compareCluster 逻辑
- ⚠️ **非模式生物**：需要自行维护 gene set 库

### 4.3 推荐的技术迁移方案

```
方案：gseapy 为主 + 自定义 GMT 库 + 前端增强可视化

1. 核心分析层：gseapy (GSEA/Prerank/ORA/ssGSEA/GSVA)
   ↓
2. 基因集管理层：自建 GMT 库管理模块
   - 维护常见物种的 GO/KEGG/MSigDB GMT 文件
   - 支持用户上传自定义 GMT
   - 对接 KEGG API 定期更新通路数据
   ↓
3. 多组比较层：自行实现 compareCluster 逻辑
   - 对每组基因列表分别调用 gseapy.enrich()
   - 合并结果 DataFrame，添加 group 列
   - 前端用分组 dotplot 展示
   ↓
4. 可视化层：gseapy 基础图 + 前端增强
   - gseapy 生成 barplot/dotplot/gseaplot
   - 前端用 ECharts/Plotly 实现 enrichment map、cnetplot 等
```

---

## 五、gseapy 1.3.0 新特性亮点（值得关注）

1. **fgsea multilevel p-value** (Rust 实现)：可以解析远低于 `1/permutation_num` 的 p-value，对大样本量分析更精确
2. **GOFilter 类**：支持 GO term 层级过滤（弥补了之前的一个重要差距）
3. **性能优异**：Rust 后端比纯 NumPy 实现快 3 倍，内存少 4 倍
4. ** organism 参数**：GSEA/Prerank 等函数新增 organism 关键字
5. **活跃维护**：最新版本 2026年6月发布，社区活跃

---

## 六、最终结论

| 评估维度 | 评分 | 说明 |
|---------|------|------|
| **功能覆盖度** | 75% | 核心 ORA/GSEA 完整，缺 compareCluster |
| **物种覆盖度** | 40% | 仅 6 种模式生物，但自定义 GMT 可弥补 |
| **可视化能力** | 60% | 基础图完整，缺 cnetplot/upsetplot 等高级图 |
| **Python 生态融合** | 95% | 原生 Python，与 pandas/matplotlib 无缝衔接 |
| **性能** | 90% | Rust 加速，适合大规模数据 |
| **维护活跃度** | 85% | 持续更新，v1.3.0 很新 |

### ✅ 结论：GSEApy 可以替代 ClusterProfiler，但需要额外投入

**推荐策略**：
- **短期**：在 OmicHub 中集成 gseapy 作为默认富集分析引擎，支持常规的 GSEA/ORA/Prerank/ssGSEA 分析
- **中期**：自建物种基因集管理模块（GMT 文件管理），支持植物等非模式生物
- **长期**：前端自行实现 compareCluster 的可视化和 cnetplot 的替代方案

**这样做的好处**：
1. 彻底摆脱 R 依赖，平台纯 Python 化
2. gseapy 的性能更好（Rust 后端），适合平台级高并发
3. 输出是 pandas DataFrame，与你的 Python 后端/前端衔接更顺畅
4. 用户无需安装 R 环境，降低使用门槛

**需要接受的 trade-off**：
1. 需要自行维护基因集库（特别是植物物种）
2. 部分高级可视化需在前端自行实现
3. 多组比较功能需自行封装

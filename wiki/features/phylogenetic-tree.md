# 系统发育树构建

生信工具箱工具，支持多序列比对（MSA）到系统发育树构建、Bootstrap 评估与交互式可视化。

## 计算模式

所有计算步骤投递 Celery 异步执行。

## 分析流程

```text
输入文件(FASTA/Phylip/NEXUS)
  → 输入验证（同步，<3s）
  → 多序列比对（MSA）：MAFFT / ClustalOmega / MUSCLE5
  → 系统发育树构建：NJ / UPGMA / FastTree / IQ-TREE / MrBayes
  → Bootstrap 评估（可选）
  → 结果格式化：Newick / NEXUS / PhyloXML / 统计 JSON
```

## 四阶段进度

| 阶段 | 进度范围 | 说明 |
|---|---|---|
| ALIGNING | 0% → 35% | 多序列比对 |
| BUILDING | 35% → 80% | 树构建 |
| BOOTSTRAPPING | 80% → 95% | Bootstrap（可选） |
| FORMATTING | 95% → 100% | 结果格式化 |

## 方法矩阵

### MSA 工具

| 工具 | 适用场景 | 序列数上限 |
|---|---|---|
| MAFFT | 通用首选 | ≤30,000 |
| ClustalOmega | 大规模序列 | ≤100,000 |
| MUSCLE5 | 高精度需求 | ≤20,000 |

### 树构建方法

| 方法 | 类型 | 特点 |
|---|---|---|
| Neighbor-Joining | 距离法 | 快速预览 |
| UPGMA | 距离法 | 等速率假设 |
| FastTree | 近似最大似然 | 大规模快速 ML |
| IQ-TREE | 精确最大似然 | ModelFinder + UFBoot |
| MrBayes | 贝叶斯推断 | 后验概率 |

## 前端可视化

- 可视化引擎：`phylotree.js`（基于 D3.js）
- 布局：矩形 / 圆形 / 径向
- 交互：缩放、拖拽、折叠、重定根、高亮
- 导出：PNG / SVG / Newick

## 后端 API

| 方法 | 路由 | 说明 |
|---|---|---|
| POST | `/api/phylo/upload` | 上传序列文件 |
| POST | `/api/phylo/submit` | 提交任务 |
| GET | `/api/phylo/tasks/{id}/status` | 查询状态 |
| GET | `/api/phylo/tasks/{id}/result` | 获取结果 |
| DELETE | `/api/phylo/tasks/{id}/cancel` | 取消任务 |
| GET | `/api/phylo/download/{id}/{format}` | 下载结果 |

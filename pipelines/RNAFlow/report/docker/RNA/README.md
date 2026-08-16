# RNAFlow Report Generator (RNA-seq 数据解读与报告生成系统)

## 📖 项目简介
RNAFlow 是一套基于 **Docker** 和 **Quarto** 构建的自动化 RNA-seq 数据分析报告生成系统。它能够将复杂的转录组分析结果（FASTP、Mapping、DEG、富集分析等）整合，并通过 **AI 解读引擎** 生成深度的实验结论，最终产出交互式的多页 HTML 报告。

## ✨ 核心功能
- **自动化流程**：一键完成数据整合、AI 解读及网页渲染。
- **AI 智能解读**：利用大语言模型（LLM）对差异基因和富集通路进行生物学功能分析。
- **交互式报告**：基于 Quarto 生成，包含 Plotly 交互图表、Itables 数据表格。
- **Docker 容器化**：环境高度隔离，确保在不同机器上运行结果的一致性。
- **深度定制**：支持自定义 Prompt 模版，控制 AI 的分析方向。

## 🛠️ 环境依赖
- [Docker](https://www.docker.com/) (建议 20.10+)
- [Python 3.8+](https://www.python.org/) (用于本地调试)
- [Quarto](https://quarto.org/) (可选，容器内已集成)

## 🚀 快速上手

### 1. 构建 Docker 镜像
在项目根目录下执行：
```bash
docker build -t rnaflow-report:v1.0 ./docker_build
```

### 2. 准备配置文件
确保你有一个 `project_summary.json`，其中包含了分析数据的路径信息。

### 3. 运行报告生成
使用 Docker 运行系统（请根据实际路径修改 `-v` 挂载）：
```bash
docker run --rm \
  -v /你的/本地/数据目录:/data \
  -v /你的/本地/输出目录:/workspace \
  -v $(pwd)/project_summary.json:/app/project_summary.json \
  rnaflow-report:v1.0 -c /app/project_summary.json -o /workspace
```

## 📂 目录结构说明
```text
.
├── entrypoint.py                # 容器入口脚本 (管控 AI 流程与 Quarto 渲染)
├── project_summary.json         # 项目配置文件 (示例)
├── README.md                    # 项目说明文档
├── docker_build/                # Docker 构建相关
│   ├── Dockerfile
│   └── requirements.txt
└── templates/                   # 报告模版目录
    ├── data/                    # 原始分析结果数据
    ├── qmd/                     # Quarto 模版文件 (.qmd)
    └── scripts/                 # 核心处理脚本
        ├── consolidate_rna_seq_data.py  # 数据整合与 AI 提报脚本
        ├── ai/                          # AI 调用引擎 (schemas/engine)
        └── prompt.txt                   # AI 分析提示词模版
```

## 🤖 AI 分析流程
在最终生成网页报告前，系统会自动执行以下步骤：
1. **数据整合 (Generate)**：从 `project_summary.json` 引用的 CSV/TSV 文件中提取 Top 差异基因、富集通路等核心信息，生成 Markdown 格式的中间文件。
2. **AI 解读 (Report)**：将整合后的文本发送给 AI 模型，生成 `AI_Interpretation_Report.md`。
3. **网页渲染**：Quarto 会将 AI 生成的内容自动嵌入到“AI 解读”章节中。

## 📝 配置文件 (project_summary.json) 关键字段
| 字段 | 说明 |
| :--- | :--- |
| `project_meta` | 项目名称、实验物种、测序平台等背景信息 |
| `input_files` | 指向差异分析文件、富集分析目录、表达矩阵等的路径 |
| `stats` | 样本量、分组信息等基础统计数据 |

## ❓ 常见问题
- **AI 报告没有生成？** 请检查容器是否能够访问外网（AI API 调用需要网络），并确保 `templates/scripts/ai/` 下的配置正确。
- **路径报错？** 确保 `project_summary.json` 中的路径在 Docker 容器挂载的 `/data` 范围内。

---

**版本**: v1.0.0  
**作者**: Zhang Jian  
**最后更新**: 2026-01-24

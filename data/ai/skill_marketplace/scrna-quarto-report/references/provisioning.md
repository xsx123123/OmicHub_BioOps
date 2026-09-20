# 外部数据供给清单（provisioning）— scrna-quarto-report

> 读者是**平台管理员**。本技能不自带脚本——报告脚本与 Quarto 模板随主流程仓库分发（模板约 3MB，超技能包 1MiB 红线，禁止进包）；须在技能挂载前按本清单预置。运行时模型只做核查与缺失上报，不自行下载、不寻找源仓库。

## 一、主流程仓库（沙盒路径约定 `ref/scRNAseqMulticommand/`）

| 内容 | 说明 |
|---|---|
| `tools/build_quarto_report.R` | 报告构建入口脚本（技能执行步骤调用） |
| `src/core/99.report_manifest.r` | 被脚本 source，生成 manifest.json / summary.json |
| `report/` | Quarto 模板工程（约 3.1MB，含 7 个页面 .qmd 与样式） |

- 获取方式：从源仓库（pipelines/scrna）同步对应版本 tag（当前 v4.1.2-alpha），与 `scrna-pipeline-overview` 共用同一份预置仓库（其清单见该技能 `references/provisioning.md`）；
- **预置位置必须可写**：渲染过程会写 `report/data/current` 符号链接与 `report/_site/` 产物；共享卷只读时，先把仓库复制到可写工作区再执行，并用 `--report-dir` 指向复制后的 `report/`。

## 二、系统依赖（预装进沙盒镜像）

| 依赖 | 用途 | 校验 |
|---|---|---|
| `quarto` CLI | 渲染 HTML 报告（缺失时脚本只能 `--no-render` 回填 JSON） | `which quarto` |
| R + `jsonlite` | 运行 build_quarto_report.R | `Rscript -e 'library(jsonlite)'` |

## 三、校验方式

```bash
ls ref/scRNAseqMulticommand/tools/build_quarto_report.R \
   ref/scRNAseqMulticommand/src/core/99.report_manifest.r \
   ref/scRNAseqMulticommand/report/_quarto.yml
which quarto
```

缺失任一项时向管理员上报，按本清单补齐后重跑。

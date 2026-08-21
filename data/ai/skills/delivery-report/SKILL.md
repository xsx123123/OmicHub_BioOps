---
name: Delivery Report
description: 当交付任务满足 HTML 报告阈值（≥3 个分析阶段 / 图表产物 ≥5 个 / 结果文件 ≥10 个 / 用户明确要求网页报告）且用户已在
  ask_user 弹窗中确认后，使用本技能在 Studio 沙盒中用 Python + Plotly + Jinja2 生成单文件 final-report.html。常规交付或用户未确认时只输出
  delivery-summary.md + checksums.md5，不使用本技能。
version: 1.0.0
icon: 📊
category: report
skill_id: delivery-report
tool_type: python
primary_tool: Plotly + Jinja2
workflow: false
---

# Delivery Report（交付 HTML 报告生成）

在 Studio 沙盒（analysis-core）中把已验证产物渲染为单文件交互式 HTML 报告。
本技能只做格式化渲染：不重新计算统计量、不改动上游数字、不生成产物之外的新图表
（新图表需求转 agent-viz）。

## 触发前提（全部满足才可使用）

1. 质量门结论属于 passed / warning / manual_review；
2. 满足交付分级阈值之一：≥3 个分析阶段、图表产物 ≥5 个、结果文件 ≥10 个、用户明确要求；
3. 用户已在 ask_user 弹窗中明确确认生成 HTML（无人值守 worker 场景禁止使用本技能）。

## 输入契约

生成前准备以下数据（全部来自已验证产物或工具返回，标注出处）：

- `header`：项目/Case ID、生成时间、质量门结论、交付版本；
- `artifacts`：交付清单（路径、用途一句话、来源任务/Agent、MD5、状态 已验证/未验证），
  MD5 来自 `md5` 技能计算的 `checksums.md5`，两者必须一致；
- `sections`：按分析阶段组织的章节，每章含图表 div 列表、关键数字（标签 + 值 + 出处）、限制；
- `risks`：高/中/低分级风险；
- `reproduction`：环境、关键参数、流程引用、重跑条件。

## 生成流程

1. 用 `skill_resource` 读取模板 `assets/report_template.html.j2`。
2. 图表数据只从已验证产物文件（CSV/TSV/JSON）直接读取渲染；行数 >10 万的表
   先聚合/降采样（如分箱、抽样、按组汇总）再渲染，并在对应章节注明降采样方式。
3. 每张图用 `fig.to_html(full_html=False, include_plotlyjs=False)` 生成 div，
   收集后注入模板对应章节；plotly.js 全报告只出现一次：
   默认内联（`include_plotlyjs=True` 取一次 js 注入模板头部，自包含离线可开）；
   仅用户明确要求小文件时改用 CDN script 标签。
4. 用 Jinja2 渲染模板，默认输出到 Studio 沙盒交付目录
   `output/delivery/final-report.html`；不得写入 output/delivery/ 之外的位置。
5. 渲染完成后校验：文件可打开、包含交付清单表、plotly.js 只出现一次；
   抽查至少 3 处 HTML 数字与源产物文件一致。
6. 任一步失败（数据读取失败、渲染异常、校验不通过）时降级为标准交付
   `delivery-summary.md` + `checksums.md5`，并向用户说明失败原因。

## 数据纪律

- 禁止重新计算统计量；关键数字必须能回溯到产物文件路径与行列位置。
- 标准工具的 QC 聚合（FastQC/STAR/salmon 等日志）不重复实现，优先把 MultiQC 报告
  列为交付物并在 HTML 中引用其相对路径。
- 不暴露宿主机绝对路径、凭据或原始敏感数据；清单中使用交付包内相对路径。

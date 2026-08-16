## 共享沙盒协议

### 沙盒目录使用规范

沙盒工作目录结构固定，所有文件操作必须遵守以下放置规则：
- `input/`（只读）：用户上传的原始数据。不得修改、覆盖、删除或重命名；转换结果写入 `output/`。
- `ref/`（只读）：参考基因组、注释文件和公共数据库。规则同 `input/`。
- `scripts/`：生成的脚本与代码，主脚本使用有意义的文件名。
- `output/results/`：结果表格与数据文件；`output/figures/`：图表；`output/logs/`：运行日志；`output/tmp/`：中间文件。
- 不要在工作区根目录或家目录散落数据、脚本和结果文件；真正的临时文件写入 `/tmp`，任务结束即弃。
- 文件名统一使用小写加下划线，必要时带项目名和关键参数，便于追溯与避免覆盖。
- 交付时输出每个产物的实际路径和一句话说明；每个分析在 `output/results/` 写 `<project>_summary.md`，会话结束在 `output/README.md` 汇总分析与产物。

### 数值计算与表格处理

- **数据处理、表格加工与数值计算默认使用 Python** 在沙盒中实际执行；仅绘图任务
  使用 R/ggplot2，或用户明确要求、挂载技能指定时再用 R。
- **任何数值结果必须由沙盒中的 Python 实际计算得出**，不得使用心算、语言模型推演或未经执行的
  公式代替；这同样适用于用户在正文中直接给出的少量数字、四则运算、百分比、均值、比例和单位换算。
- 计算前把可重跑的 Python 脚本写入 `scripts/`，再通过 `sandbox_execute` 运行；交付时报告脚本路径、
  实际 stdout/stderr 摘要和结果。没有成功执行时必须明确说明“未执行”，不得给出计算结论。
- 处理 `xlsx` / `xls` / `csv` / `tsv` 前，先读取并检查工作簿 sheet、列名、行数、数据类型、缺失值和
  公式情况。公式、分组、去重、异常值、汇总口径或目标列不明确时，必须调用 `ask_user` 澄清。
- `input/` 中的原始表格保持只读；不得覆盖原文件。转换后的工作簿写入 `output/results/`，例如
  `output/results/sales_calculated.xlsx`，并保留用于复现的 `scripts/process_sales_excel.py`。
- 宏文件、加密文件、外部链接公式或超大工作簿先说明风险与支持边界；不得静默丢弃宏、绕过加密或将
  外部链接结果当作已验证数值。

### 现场装包与验证

- 先核对运行时能力和 import 声明，不要假定某个包一定预装。
- **所有包统一使用 `micromamba install`**（镜像已预置 `.condarc`，conda-forge 与 bioconda 均已映射到中科大镜像，无需显式 `-c`）：
  - Python / R 通用包：`micromamba install -y -n base <pkg>`（R 包加 `r-` 前缀，如 `r-ggplot2`）
  - Bioconductor 专属包：`micromamba install -y -n base -c bioconductor bioconductor-<pkg>`（如 `bioconductor-deseq2`）
- 安装前用 `conda-meta-mcp` 的 `import_mapping`、`pypi_to_conda`、`package_search` 确认包名、channel 与 linux-64 版本；查询失败退回 `micromamba search <pkg>`。
- **禁止** `install.packages()`、`remotes::install_github()`、`pip install` 或任何非 conda 通道的安装方式；GitHub 独占包无法安装时如实说明。
- 安装失败提示网络错误时，重试一次或换兜底源，**不得自行添加未经白名单放行的域名**。
- 安装完成必须用 CLI `--version` 或 Python/R import 验证，记录真实包名和版本；失败时如实报告，不伪造安装或运行结果。
- 生成脚本先落盘，再执行；执行前先用小样本冒烟，长任务说明预期耗时。
- 用户单独查询软件包版本、依赖或安装方式时，优先用 `conda-meta-mcp` 查询并汇报；分析过程中的缺包安装属于后台动作。
- Studio 中若 `conda-meta-mcp` 未加载，先调用 `studio_capability_load`；查询包信息后说明当前可在 AI 工作台沙盒中直接安装和验证。

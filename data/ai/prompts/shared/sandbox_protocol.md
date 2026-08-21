## 共享沙盒协议

### 沙盒目录使用规范

沙盒工作目录结构固定，文件操作按以下放置规则进行——目录约定是产物收集与血缘登记的依据，
放错位置的文件会逃出交付清单和审计视野：
- `input/`（只读）：用户上传的原始数据。它是所有结论的证据起点，修改、覆盖、删除或重命名
  都会让结果无法复核，所以保持原样；转换结果写入 `output/`。
- `ref/`（只读）：参考基因组、注释文件和公共数据库。规则同 `input/`。
- `scripts/`：生成的脚本与代码，主脚本使用有意义的文件名。
- `output/results/`：结果表格与数据文件；`output/figures/`：图表；`output/logs/`：运行日志；`output/tmp/`：中间文件。
- 不要在工作区根目录或家目录散落数据、脚本和结果文件；真正的临时文件写入 `/tmp`，任务结束即弃。
- 文件名统一使用小写加下划线，必要时带项目名和关键参数，便于追溯与避免覆盖。
- 交付时输出每个产物的实际路径和一句话说明；每个分析在 `output/results/` 写 `<project>_summary.md`，会话结束在 `output/README.md` 汇总分析与产物。

### 数值计算与表格处理

- **数据处理、表格加工与数值计算默认使用 Python** 在沙盒中实际执行；仅绘图任务
  使用 R/ggplot2，或用户明确要求、挂载技能指定时再用 R。
- **任何数值结果都由沙盒中的 Python 实际计算得出**，不用心算、语言模型推演或未经执行的
  公式代替——模型的算术与统计推演错误率不可控，且无法留下可复核痕迹；这同样适用于用户
  在正文中直接给出的少量数字、四则运算、百分比、均值、比例和单位换算。
- 计算前把可重跑的 Python 脚本写入 `scripts/`，再通过沙盒执行工具运行（Studio 工作台中为
  `sandbox_execute`，普通聊天中为 `chat_sandbox_execute`）；交付时报告脚本路径、
  实际 stdout/stderr 摘要和结果。没有成功执行时明确说明“未执行”并停在那里——给出未经
  执行的计算结论属于伪造证据，会被 agent-qc 追溯判 fail。
- 处理 `xlsx` / `xls` / `csv` / `tsv` 前，先读取并检查工作簿 sheet、列名、行数、数据类型、缺失值和
  公式情况。公式、分组、去重、异常值、汇总口径或目标列不明确时，调用 `ask_user` 澄清——
  口径猜错时算出来的每个数字都是错的，而且错得很自信，比问一句的代价高得多。
- `input/` 中的原始表格保持只读，不覆盖原文件——原文件是复核与重跑的证据起点。转换后的
  工作簿写入 `output/results/`，例如 `output/results/sales_calculated.xlsx`，并保留用于
  复现的 `scripts/process_sales_excel.py`。
- plotly 交互图除 `fig.write_html()` 交付 HTML 文件外，同时调用沙盒内置 `show_plotly(fig)`——
  预览是甲方确认图形语义的环节，跳过它等于交付一张没人看过的图；数据量过大被丢弃时先降采样再重试。
- 宏文件、加密文件、外部链接公式或超大工作簿先说明风险与支持边界；不静默丢弃宏、不绕过加密、
  不把外部链接结果当作已验证数值——这些静默处理都会让结果与甲方看到的原文件对不上。

### 现场装包与验证

- 先核对运行时能力和 import 声明，不要假定某个包一定预装。
- **所有包统一使用 `micromamba install`**（镜像已预置 `.condarc`，conda-forge 与 bioconda 均已映射到中科大镜像，无需显式 `-c`）：
  - Python / R 通用包：`micromamba install -y -n base <pkg>`（R 包加 `r-` 前缀，如 `r-ggplot2`）
  - Bioconductor 专属包：`micromamba install -y -n base -c bioconductor bioconductor-<pkg>`（如 `bioconductor-deseq2`）
- 安装前用 `conda-meta-mcp` 的 `import_mapping`、`pypi_to_conda`、`package_search` 确认包名、channel 与 linux-64 版本；查询失败退回 `micromamba search <pkg>`。
- 不使用 `install.packages()`、`remotes::install_github()`、`pip install` 或任何非 conda 通道的安装方式——这些通道不在沙盒 egress 白名单内，只会失败或装上来历不明的包；GitHub 独占包无法安装时如实说明。
- 安装失败提示网络错误时，重试一次或换兜底源，**不自行添加未经白名单放行的域名**——白名单是网络隔离边界，自行加域名等于从 prompt 层打开沙箱。
- 安装完成后用 CLI `--version` 或 Python/R import 验证，记录真实包名和版本——装错包或版本不符会在分析中途才爆雷；失败时如实报告，不伪造安装或运行结果。
- 生成脚本先落盘，再执行；执行前先用小样本冒烟，长任务说明预期耗时。
- 用户单独查询软件包版本、依赖或安装方式时，优先用 `conda-meta-mcp` 查询并汇报；分析过程中的缺包安装属于后台动作。
- Studio 中若 `conda-meta-mcp` 未加载，先调用 `studio_capability_load`；查询包信息后说明当前可在 AI 工作台沙盒中直接安装和验证。

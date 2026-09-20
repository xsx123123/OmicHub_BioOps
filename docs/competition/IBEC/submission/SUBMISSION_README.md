# iBEC 报名材料草稿说明（内部使用，非提交物）

生成日期：2026-09-18。内容主要取材自 `docs/competition/2026-agentteams-bioops/CygnusX_BioOps_BP_v2.2.docx`（CygnusX BioOps BP v2.2），并参照 `01_初赛项目方案.md`、`04_Demo验证与审计证据.md` 补充技术细节；正文以英文撰写，符合 iBEC 模板 "Primary language: English" 要求。

## 目录

| 文件 | 对应模板 | 状态 |
| --- | --- | --- |
| `01_Project_Report/OmicHub_BioOps_Project_Report.tex` | 01 LaTeX 模板（结构逐节对应） | 内容已填完，待补占位符并编译 PDF |
| `01_Project_Report/OmicHub_BioOps_Project_Report.docx` | 01 Word 模板同等内容 | pandoc 由 tex 生成，格式需在 Word 中检查 |
| `02_Technical_Abstract/OmicHub_BioOps_Technical_Abstract.pptx` | 02 PPT 模板（官方样式，10 页整） | 文本已替换，需插入图片并导出 PDF |
| `03_Supplementary_Materials/OmicHub_BioOps_Supplementary_Materials.tex` / `.docx` | 03 LaTeX/Word 模板 | 内容已填完（含真实测试与 md5 校验命令） |
| `03_Supplementary_Materials/README.md` | 03 README 模板 | 已填完，打包代码/数据时按此核对 |

## 提交前必须处理的占位符（全局搜索 `[` ）

1. **Team ID**：已填入 `IBEC26-35`；正式提交时按要求 **重命名提交文件**（文件名需含 Team ID）。
2. **Team Name / 机构官方英文名 / 项目类别**：已填入 `CygnusX`、`Huazhong Agricultural University`、`Bioinformatics Platform`；团队成员仍需补全。
3. **提交日期**：PPT 封面 `2026-09-XX`。
4. **图片**：PPT 第 1、6 页预留了插图位（架构图=BP 图 4-1；界面截图 F1–F3=星尘 AI 入口 / Skill 市集 / Agent 工作台）；报告中若需插图可在 tex 中加 `\includegraphics`。
5. **链接**：仓库 URL、平台演示 URL、demo 视频 URL（补充材料第 6 节及 README 第 6 节）。
6. **数据细节**：demo 数据集物种/样本数/大小（补充材料第 4 节标 `[confirm ...]` 处）。
7. **已发表成果**：报告第 10 节目前只列了软件成果（v0.1.0 + 38 Skills），如另有论文/专利/获奖请补充。

## 导出 PDF

- 报告与补充材料：`xelatex`（需 fontspec，本机未装 LaTeX 发行版；也可在 Word 中直接另存 PDF）。
- 技术摘要：PowerPoint/WPS 导出 PDF（模板本身即 16:9、10 页，符合“控制在 10 页内”要求）。

## 口径一致性说明（对照模板 checklist 第 7 条）

- 三份材料统一口径：效率数字为 **-75% / -90% / -80%**，测量口径为“人工操作与等待时间、不含计算运行时间”（与 BP 第 8/15 章一致）。
- 愿景口径统一为：**从科研现象出发，逐步组织可验证、可复现、可追溯的计算实验**；目标导向发现属于研发路线，不表述为当前已交付的全自动科研能力。
- 竞赛定位：材料以科研问题、方法创新、可复现性、证据链和研究应用为主，弱化市场规模、商业收益、客户转化和外包替代等内容。
- 工程事实统一：29 个应用服务、后端 227 个 Python 模块、38 个可执行 Skill（Analysis 36 + 平台管理 2）、质量门 mapping ≥ 0.70 / Q30 ≥ 0.80、v0.1.0 已在华中农业大学园艺林学学院基因组学实验室使用。
- 多角色协同层（MAS 预览）在三份材料中均声明为 **默认关闭、非核心路径**，避免夸大。
- 补充材料中的命令均为仓库真实路径：`tests/unit/domain/mas/`、`tests/unit/test_agent_config_consistency.py`、`integrations/agentteams/bridge/tests/`、`pipelines/tools/skills/md5/scripts/verify_manifest.py`（生成 verification.tsv，SUCCESS/MISSING/FAIL/ERROR）。

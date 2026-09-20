# 外部数据供给清单（provisioning）— scrna-deg-analysis

> 读者是**平台管理员**。本技能运行所需的全部外部数据如下，须在技能挂载前预置到共享数据卷；运行时模型只做核查与缺失上报，不自行下载。
> 沙盒内路径约定：`ref/DEG_Annotation_reference/`，经环境变量 `SCRNA_DEG_REF_DIR` 注入（平台侧配置，或在会话内 `export SCRNA_DEG_REF_DIR=ref/DEG_Annotation_reference`）。

## NCBI gene_info 注释文件（2 个必需 + 1 个可选，合计约 47MB）

| 文件名（`ref/DEG_Annotation_reference/` 下） | 必需性 | 用途 |
|---|---|---|
| `hg19_Homo_sapiens.gene_info` | 人（taxid 9606）必需 | DEG 基因符号注释（当前脚本默认用 hg19 版本） |
| `mm10_Mus_musculus.gene_info` | 鼠（taxid 10090）必需 | 同上 |
| `hg38_Homo_sapiens.gene_info` | 可选 | 备用 hg38 注释（脚本当前不读取） |

- 获取方式：从 scRNAseqMulticommand 源仓库 `tools/DEG/DEG_Annotation_reference/` 目录拷贝，或从平台共享备份恢复；上游出处为 NCBI gene_info（ftp.ncbi.nlm.nih.gov）。
- **文件名必须与上表逐字一致**（脚本按文件名拼接路径读取）。
- 校验方式：`ls ref/DEG_Annotation_reference/` 应能看到上述文件；缺失时 `deg_analysis.R` 会在预检阶段非 0 退出并给出可读报错。

## 共享卷容量建议

`ref/DEG_Annotation_reference/` 预留 ≥ 200MB（当前 47MB + 后续注释库扩展余量）。

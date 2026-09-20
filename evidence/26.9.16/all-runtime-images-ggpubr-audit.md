# 全部 Agent 运行时镜像 ggpubr/绘图栈扩展审计（2026-09-16）

对应 `evidence/26.9.16/analysis-plot-ggpubr-diagnosis.md` 的扩展：所有 agent 相关容器逐个实测。

## 实测结果

| 镜像 | ggpubr | 构建后校验 | 结论 |
|---|---|---|---|
| `cygnusx-analysis:plot-v0.0.2dev` | ❌ MISSING | ❌ | **已修**：plot-v0.0.3dev + smoke test |
| `cygnusx-analysis:scrna-v0.0.2dev` | ❌ MISSING（FROM plot 继承） | ❌ | **已修**：scrna-v0.0.3dev（基于 plot-v0.0.3dev 自动继承） |
| `cygnusx-sandbox-copilot:v0.0.2dev` | ✅ 1.0.0（独立预装层 deploy/sandbox/Dockerfile:144-148） | IRkernel 注册层 | 无问题 |
| `cygnusx-sandbox-bio:v0.0.2dev` | 无 R（纯 Python+CLI，设计如此） | — | 无问题 |
| `cygnusx-sandbox-base:v0.0.2dev` | 无 R（数据科学栈，设计如此） | — | 无问题 |
| `cygnusx-sandbox-ggplot2`（终端子镜像） | 本地未构建；Dockerfile 缺 `r-cran-ggpubr` | ❌ | **已修**：补 r-cran-ggpubr + 构建期校验 |
| `cygnusx-r-deg:v1` | ✅ 1.0.0，`theme_pubclean()` 实测 OK | ✅ Dockerfile.deg:92-101 | 无问题 |
| `cygnusx-r-enrichment:v1` | ggpubr 缺失，但脚本（tool_configs/enrichments/run_enrichment.R）只用 ggplot2 | ✅ Dockerfile.enrichment:62-71 | 无问题（不加无用包） |
| agentteams worker / web / beat 等 | 无 R 依赖 | — | 无问题 |

## 已做修复

| 文件 | 改动 | 回滚 |
|---|---|---|
| `deploy/runtime-images/plot.Dockerfile` | r-ggpubr=0.6.0 + smoke test（上轮已修） | git checkout |
| `deploy/runtime-images/scrna.Dockerfile` | 无需改：FROM plot-v0.0.3dev 自动继承 ggpubr | — |
| `data/ai/runtime_images.yaml` | analysis-scrna image → scrna-v0.0.3dev；software 表加 r-ggpubr | git checkout |
| `tool_configs/terminal/docker/Dockerfile.ggplot2` | apt 列表加 `r-cran-ggpubr` + 构建期 library 校验 | git checkout |
| `data/ai/prompts/visualization.md` | 依赖表更新：ggpubr/patchwork 标注已预装勿现场安装；补充 read_only_rootfs 下 /opt/conda 只读警示与禁自带镜像 URL（NJU 403） | git checkout |

## 关键根因补充

可视化 prompt（visualization.md:159）此前把 `micromamba install -y -n base r-ggpubr` 写成默认安装方式，直接诱导 Agent 在只读容器里现场补装 → 这就是故障现象 #3 的直接来源。修复后 prompt 明确「已预装，勿现场安装」，并给出 read_only_rootfs 与代理 403 的边界说明。

## 待构建验证

- [ ] scrna-v0.0.3dev 构建完成 + fresh container ggpubr 实测
- [ ] cygnusx-sandbox-ggplot2:v0.0.2dev 构建完成（本地此前未构建）

# F9 离线 eval 闭环首用：Manager 组队质量评测报告

> 生成时间：2026-08-21T17:54:37+08:00；生成脚本：`scripts/poc/teaming_eval/run_teaming_eval.py`（本报告数字全部来自该脚本真实运行输出）。
> 原始运行数据：`evidence/teaming-eval/run_20260821T095437Z.json`。
> spec：docs/info/26.8.21/协作室融合ClaudeScience设计理念评估与实施方案.md Part 4 F9。

## 1. 评测配置

| 项 | 值 |
| --- | --- |
| 样本数 | 30（`scripts/poc/teaming_eval/samples.yaml`，逐条标注来源） |
| A 臂（baseline） | 路由圈选：`build_route_decision` 纯关键词/规则路由，确定性，零 LLM token，reps=1 |
| B 臂（带配置） | 路由圈候选 + LLM 组队会诊（生产 ROUTER_SYSTEM_PROMPT + summary 层目录），LLM 模式：**stub**，reps=3 |
| token 口径 | tiktoken cl100k_base（与 W3 `scripts/measure_capability_catalog_tokens.py` 一致），统计注入 prompt 的目录/输入文本 |

> ⚠️ **stub 口径声明**：本轮 B 臂由确定性启发式 stub 驱动（关键词命中打分），用于离线验证评测管线闭环；其数字**不代表任何真实模型质量**，组队策略权重决策须以 `--llm-live` 或 `--llm-replay` 的真实运行为准。

## 2. 样本集（真实需求提炼，逐条来源）

| id | 需求文本 | 金标准专家 | 需澄清 | 来源 |
| --- | --- | --- | --- | --- |
| S01 | 我有6个样本的小鼠单细胞数据，分为两个group 3v3，想要找到不同 group 间的细胞类型差异和差异基因 | agent-scrna | 是 | docs/update_info/26.8.19/协作室任务执行流程评估与优化文档_v1.md（同见 evidence/agentteams-case-forensics-20260819/report.md） |
| S02 | 小鼠肺部 6 个 scRNA-seq 样本（3 tp53 mutation vs 3 WT）标准流程全套 | agent-scrna, agent-scrna-advanced, agent-scrna-integration, agent-scrna-upstream | 否 | evidence/e2e-2026-08-21/E2E-1/result.md（E2E-1 实测需求文本） |
| S03 | 帮我分析 16S 微生物组测序数据 | agent-code | 否 | report/12_多智能体协作室根因调查报告_2026-08-19.md（E2E-3 实测同文本） |
| S04 | hi | （空） | 否 | evidence/e2e-2026-08-21/E2E-7/result.md（E2E-7 实测：不建 Case、不派专家） |
| S05 | 我想分析小鼠脑损伤的 RNA-seq 数据 | agent-rnaseq | 是 | flows/rna_seq.yaml example_dialogue |
| S06 | 我想分析小鼠 ATAC-seq 数据 | agent-atacseq | 是 | flows/atac_seq.yaml example_dialogue |
| S07 | 帮我做 KEGG 富集分析 | agent-rnaseq | 是 | docs/update_info/26.7.25/星尘AI对话页前端美化实现计划.md |
| S08 | 帮我做一个UMAP可视化 | agent-viz | 是 | docs/modules/09_sandbox_architecture.md |
| S09 | 帮我做单细胞质控，然后做差异表达和富集分析 | agent-scrna | 是 | docs/update_info/26.7.26/ai_agent/CygnusX平台Agent能力优化方案-记忆与多Agent协作.md |
| S10 | 帮我写一个 VCF 过滤脚本 | agent-code | 否 | docs/update_info/26.7.29/studio/AI工作台分屏面板自动关闭排查与布局优化实现计划.md（同见 data/ai/mcp/workspace_files_prompt.md） |
| S11 | 帮我建一棵进化树 | agent-viz | 是 | docs/update_info/26.8.18/agent双架构汇总.md |
| S12 | 帮我找一下cluster 5的marker基因 | agent-scrna-advanced | 否 | docs/modules/10_workflow_example.md |
| S13 | 帮我画个火山图 | agent-viz | 是 | docs/update_info/26.8.18/CygnusX记忆系统优化实施计划.md（同见 docs/update_info/26.7.21/mcp_ai_assistant_integration.md） |
| S14 | 帮我看看这批样本的聚类情况，顺便找找离群样本 | agent-code, agent-viz | 是 | docs/update_info/26.7.17/CygnusX_AI分析工作台_架构设计.md |
| S15 | 帮我设计一个 TP53 突变 vs 野生型的 RNA-seq 实验 | agent-rnaseq | 否 | docs/update_info/26.8.7/prompt/01_提示词框架现状与DomainPack设计.md |
| S16 | 帮我调试这段 python 报错 | agent-code | 否 | docs/update_info/26.7.27/星尘AI统一入口_agent路由测试报告.md |
| S17 | 帮我跑 fastq QC | agent-code | 否 | docs/update_info/26.7.21/ai_driven_transformation_report.md |
| S18 | 帮我进行系统发育树和解读 | agent-viz | 是 | docs/update_info/26.8.18/协作室任务执行流程详解.md |
| S19 | 我需要一个能查询 PubMed 的 MCP，输入关键词返回标题和摘要 | agent-mcp-builder | 否 | docs/update_info/26.7.30/mcp_builder_framework.md |
| S20 | 我有 ATAC-seq 数据，想做差异 peak 分析 | agent-atacseq | 是 | docs/info/26.8.19/协作室平台异常排查代码审查报告_2026-08-19.md（同见 report/12_多智能体协作室根因调查报告_2026-08-19.md） |
| S21 | 我想把之前的单核数据重新聚类一下，分辨率用1.2，然后画个UMAP图，把cluster 5的颜色改成蓝色 | agent-scrna-integration | 否 | docs/modules/10_workflow_example.md |
| S22 | 帮我分析这个 PBMC 数据集 | agent-scrna | 是 | docs/update_info/26.7.23/ai_multi_agent_tools_memory.md |
| S23 | 帮我处理这个 xlsx，对其中描述的基因做文献搜索，整理成文档并输出网页报告 | agent-code, agent-delivery | 否 | docs/update_info/26.8.18/协作室任务执行流程评估与优化文档.md（同见 _v1 版） |
| S24 | 请帮我看一下我上传的这几个文件，先做一份基础的汇总说明，不着急跑正式分析 | agent-data | 否 | evidence/e2e-2026-08-21/E2E-2/fix_verify_limit_101.json（E2E 实测房间消息） |
| S25 | 帮我汇总一下当前平台的功能呀 | agent-general | 否 | docs/update_info/26.8.7/goal.md |
| S26 | 我有一个 .treefile 文件，想画进化树 | agent-viz | 否 | docs/update_info/26.8.7/prompt/01_提示词框架现状与DomainPack设计.md |
| S27 | 帮我提交一个 RNA-seq 任务，对比 WT 和 KO 组 | agent-rnaseq | 否 | docs/modules/07_milestones.md |
| S28 | 帮我看看工作区里有哪些数据文件 | agent-general | 否 | docs/update_info/26.7.25/工作区文件原生能力.md |
| S29 | 帮我分析任务日志中的错误 | agent-code | 否 | docs/modules/05_frontend_architecture.md |
| S30 | 我有哪些正在跑的任务？ | agent-general | 否 | docs/update_info/26.7.22/ai_assistant_single_entry_architecture.md（同见 docs/update_info/26.7.21/mcp_ai_assistant_integration.md） |

## 3. 双臂逐样本结果

| id | A 预测组队 | A F1 | A 差异明细 | B 预测组队 | B F1 | B 差异明细 |
| --- | --- | --- | --- | --- | --- | --- |
| S01 | agent-scrna, agent-scrna-advanced, agent-scrna-integration, agent-scrna-upstream | 0.40 | 误派: agent-scrna-advanced, agent-scrna-integration, agent-scrna-upstream | agent-rnaseq, agent-scrna, agent-scrna-advanced | 0.50 | 误派: agent-rnaseq, agent-scrna-advanced |
| S02 | agent-scrna, agent-scrna-advanced, agent-scrna-integration, agent-scrna-upstream | 1.00 | - | agent-rnaseq, agent-scrna, agent-scrna-upstream | 0.57 | 误派: agent-rnaseq；漏派: agent-scrna-advanced, agent-scrna-integration |
| S03 | agent-code | 1.00 | - | agent-rnaseq | 0.00 | 误派: agent-rnaseq；漏派: agent-code |
| S04 | agent-code | 0.00 | 误派: agent-code | agent-general | 0.00 | 误派: agent-general |
| S05 | agent-rnaseq | 1.00 | - | agent-rnaseq, agent-scrna-integration, agent-scrna-upstream | 0.50 | 误派: agent-scrna-integration, agent-scrna-upstream |
| S06 | agent-atacseq | 1.00 | - | agent-atacseq, agent-rnaseq | 0.67 | 误派: agent-rnaseq |
| S07 | agent-code | 0.00 | 误派: agent-code；漏派: agent-rnaseq | agent-general | 0.00 | 误派: agent-general；漏派: agent-rnaseq |
| S08 | agent-code | 0.00 | 误派: agent-code；漏派: agent-viz | agent-scrna-advanced, agent-scrna-integration | 0.00 | 误派: agent-scrna-advanced, agent-scrna-integration；漏派: agent-viz |
| S09 | agent-rnaseq | 0.00 | 误派: agent-rnaseq；漏派: agent-scrna | agent-rnaseq, agent-scrna, agent-scrna-advanced | 0.50 | 误派: agent-rnaseq, agent-scrna-advanced |
| S10 | agent-code | 1.00 | - | agent-general | 0.00 | 误派: agent-general；漏派: agent-code |
| S11 | agent-code | 0.00 | 误派: agent-code；漏派: agent-viz | agent-general | 0.00 | 误派: agent-general；漏派: agent-viz |
| S12 | agent-code | 0.00 | 误派: agent-code；漏派: agent-scrna-advanced | agent-scrna-advanced | 1.00 | - |
| S13 | agent-code | 0.00 | 误派: agent-code；漏派: agent-viz | agent-general | 0.00 | 误派: agent-general；漏派: agent-viz |
| S14 | agent-code | 0.67 | 漏派: agent-viz | agent-scrna-integration | 0.00 | 误派: agent-scrna-integration；漏派: agent-code, agent-viz |
| S15 | agent-rnaseq | 1.00 | - | agent-rnaseq, agent-scrna-integration, agent-scrna-upstream | 0.50 | 误派: agent-scrna-integration, agent-scrna-upstream |
| S16 | agent-code | 1.00 | - | agent-code | 1.00 | - |
| S17 | agent-code | 1.00 | - | agent-rnaseq, agent-scrna-integration, agent-scrna-upstream | 0.00 | 误派: agent-rnaseq, agent-scrna-integration, agent-scrna-upstream；漏派: agent-code |
| S18 | agent-viz | 1.00 | - | agent-general | 0.00 | 误派: agent-general；漏派: agent-viz |
| S19 | agent-code | 0.00 | 误派: agent-code；漏派: agent-mcp-builder | agent-mcp-builder | 1.00 | - |
| S20 | agent-atacseq | 1.00 | - | agent-atacseq, agent-rnaseq, agent-scrna-advanced | 0.50 | 误派: agent-rnaseq, agent-scrna-advanced |
| S21 | agent-code | 0.00 | 误派: agent-code；漏派: agent-scrna-integration | agent-rnaseq, agent-scrna-integration | 0.67 | 误派: agent-rnaseq |
| S22 | agent-code | 0.00 | 误派: agent-code；漏派: agent-scrna | agent-rnaseq | 0.00 | 误派: agent-rnaseq；漏派: agent-scrna |
| S23 | agent-code | 0.67 | 漏派: agent-delivery | agent-scrna-upstream | 0.00 | 误派: agent-scrna-upstream；漏派: agent-code, agent-delivery |
| S24 | agent-code | 0.00 | 误派: agent-code；漏派: agent-data | agent-general | 0.00 | 误派: agent-general；漏派: agent-data |
| S25 | agent-code | 0.00 | 误派: agent-code；漏派: agent-general | agent-general | 1.00 | - |
| S26 | agent-code | 0.00 | 误派: agent-code；漏派: agent-viz | agent-general | 0.00 | 误派: agent-general；漏派: agent-viz |
| S27 | agent-rnaseq | 1.00 | - | agent-rnaseq, agent-scrna-integration, agent-scrna-upstream | 0.50 | 误派: agent-scrna-integration, agent-scrna-upstream |
| S28 | agent-code | 0.00 | 误派: agent-code；漏派: agent-general | agent-rnaseq | 0.00 | 误派: agent-rnaseq；漏派: agent-general |
| S29 | agent-code | 1.00 | - | agent-general | 0.00 | 误派: agent-general；漏派: agent-code |
| S30 | agent-code | 0.00 | 误派: agent-code；漏派: agent-general | agent-general | 1.00 | - |

## 4. 聚合指标（mean ± stddev）

A 臂为确定性规则路由（reps=1，stddev 仅反映样本间差异）；B 臂统计口径为 样本×reps（n=90）。

| 指标 | A 臂（路由圈选） | B 臂（路由+LLM 会诊） |
| --- | --- | --- |
| 样本/运行数 | 30 | 90 |
| Precision | 0.475 ± 0.502 | 0.289 ± 0.372 |
| Recall | 0.467 ± 0.490 | 0.450 ± 0.492 |
| **F1** | **0.458 ± 0.483** | **0.330 ± 0.387** |
| 澄清判定准确率 | 0.267 | 0.500 |
| Prompt tokens/次 | 0 ± 0 | 4800 ± 12 |
| Completion tokens/次 | 0 ± 0 | 57 ± 6 |
| 耗时 ms/次 | 390.4 ± 154.0 | 0.3 ± 0.0 |

## 5. 结论与待人工决策项

- F1 差值（B−A）：-0.128（A=0.458，B=0.330）。
- token 成本：A 臂零 LLM token；B 臂每次组队平均 prompt 4800 tokens + completion 57 tokens。

**待人工决策（本报告只出数据，不自动改动任何组队策略权重）：**

- [ ] 是否调整组队策略权重（路由圈选 vs LLM 会诊的优先级/触发条件）——依据上表 F1 差值与 token 成本由管理员决策。
- [ ] 若本轮为 stub 口径：安排一次 `--llm-live`（或录制回放）真实运行后再决策。
- [ ] 误派/漏派高发样本（见第 3 节明细）是否反馈到能力目录/trigger_hints 修订，走 F7 证据流程。

## 6. 复现方法

```bash
# 离线 stub 闭环（CI 可用，无需凭证）
.venv/bin/python scripts/poc/teaming_eval/run_teaming_eval.py --llm-stub --reps 3
# 真实运行（凭证从环境变量读，缺失显式跳过）
export TEAMING_EVAL_LLM_BASE_URL=... TEAMING_EVAL_LLM_API_KEY=... TEAMING_EVAL_LLM_MODEL=...
.venv/bin/python scripts/poc/teaming_eval/run_teaming_eval.py --llm-live --reps 3 \
    --llm-record scripts/poc/teaming_eval/fixtures/llm_responses.json
# 录制回放（离线复跑真实响应）
.venv/bin/python scripts/poc/teaming_eval/run_teaming_eval.py \
    --llm-replay scripts/poc/teaming_eval/fixtures/llm_responses.json
```

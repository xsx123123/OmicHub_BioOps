你是一名架构文档工程师。请修订仓库中的 `docs/architecture/agent_execution_framework.md`（CygnusX Agent 执行框架快照文档），完成以下两件事。注意：这是纯文档修订任务，禁止修改任何代码。文档纪律：本文档描述"现在代码实际怎么运行"，所有未来目标态必须显式标注"（计划/待实现）"，严禁把计划写成已上线能力；保留文档既有时点说明与合并说明的写法风格，在文件头部追加一条本次修订注记（日期按当前日期）。

背景参考（同目录下可读）：`omichub-vs-openai4s-comparison-report.md`，其中 B1（外循环动作路由）、B2（内循环 cell 内 host RPC）、C1（执行历史范式）和 D 节移植优先级（P0=PTC 白名单加 LLM 回调）是本次修订的事实依据。

## 任务一：融入 OpenAI4S 深度思考链——新增「动作路由与宿主回调层」章节

在现 §4「三类核心闭环」之前插入新章节（原 §4 及之后章节编号顺延），内容包括：

1. **每轮动作三选一**：模型每轮输出严格归为三类动作之一——有序 JSON tool 批次 / 显式 Finalize 动作 / 一个完整围栏 Code Cell（native 优先于 code）。写明现状（当前两类引擎均为"tool_calls → 串行执行 → 回灌"单一回路，`agent_final_result` 是"无 tool_calls 的被动结束"）与目标态：`agent_final_result` 升级为显式 Finalize 动作语义、Code Cell 不占 tool 轮次、Code Cell 可携带完成语义（对标 openai4s `host.submit_output`）。目标态全部标注"（计划/待实现）"。
2. **Code-as-Action 定位**：说明范式差异——代码 Cell 是对标的引擎原生动作，而非普通 function tool；如实写明当前 `sandbox_execute` / `chat_sandbox_execute` / `tool_orchestrate` 均为普通 function tool 的现状，以及"代码执行与工具挤占同一轮预算、notebook 单元只能事后从 tool_call 投影"的代价；目标态标注计划。
3. **cell 内宿主回调通道（内循环）**：把现有 PTC（`tool_orchestrate`，`application/services/ptc_orchestrator.py`）从"平台工具编排通道"重新定位为"cell 内宿主回调通道"的当前实现；对标 openai4s 的 `host.llm / host.delegate / host.compute` 通用宿主通道；写明 P0 计划——在 `PTC_ALLOWED_TOOLS` 白名单中增加 LLM 回调 handler，使编排代码可中途问模型（计划/待实现）。
4. **两层结构图**：用文字流程图描述"外循环（动作路由：tool_batch / finalize / code_cell）→ 内循环（cell 内 host RPC）"两层思考链结构。

## 任务二：退化 chat_legacy，合并 chat_legacy 与 chat_langgraph

1. **§2 执行拓扑图**：`chat_legacy` 分支标注"（退化路径，计划收敛至 chat_langgraph）"；§1 一页结论中"普通聊天有两条主执行引擎"的表述相应更新为"过渡期存在两条执行引擎，收敛目标为 LangGraph 单 Runtime（计划）"。
2. **§2.1 执行路径登记表**：`chat_legacy` 行的"是否默认启用"改为"计划退化：收敛目标为 chat_langgraph 单 Runtime，过渡期保留行为兼容"。
3. **§4.1 Legacy 手写 ReAct**：标题改为"Legacy 手写 ReAct（退化路径）"；内容保持现状描述不变，末尾追加收敛说明：以 LangGraph 为唯一 Runtime 的目标态下，legacy 的差异化行为（轮次上限用户确认扩展、轮次触顶强制收尾提示词注入）将作为 LangGraph 图节点参数表达，而非两套代码（计划/待实现）。
4. **§4.2 LangGraph ReAct**：补充说明 LangGraph 版复用 Provider、工具执行器、MCP 匹配和 ChatService 收尾逻辑，是对齐 legacy 差异化行为的承接方；新能力一律先进图实现，禁止新增 legacy-only 行为（计划口径）。
5. **§9 修改和扩展规则**：§9.1 步骤 4 改为"在统一 Runtime（LangGraph 图）与 Worker 中确认是否需要同等语义支持；过渡期同步检查 legacy 兼容层"；§9.2 增加一条："禁止新增 legacy-only 循环行为"。
6. **§10 验证清单**：删除/改写"LangGraph 与 Legacy 的 tool_call/tool_result 语义一致"条目，改为单点保证口径（收敛完成后由单一 Runtime 天然保证，过渡期由兼容层保证）；新增条目："chat_legacy 路径上不再新增任何差异化行为"。
7. **§12 与其他架构文档的关系**：增补一条——本次修订新增「动作路由与宿主回调层」（依据 openai4s 对比报告 B1/B2/C1 节），chat_legacy 收敛为 LangGraph 单 Runtime 记为计划态。

## 交付与自检

- 直接修改原 md 文件，保持全文结构与表格格式一致。
- 完成后自检并报告：① 所有目标态句子均带"（计划/待实现）"标注；② 不存在新旧口径冲突的残留表述（特别是"两条主执行引擎"类旧说法）；③ 章节编号顺延正确。
- 在回复中列出你改动的所有章节清单和每处改动的一句话摘要，便于人工核对。
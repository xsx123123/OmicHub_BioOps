# CygnusX Loop Engineering 与 Skill 设计审计报告

- **审计日期**：2026-08-23
- **审计输入**：`/home/zj/.codex/attachments/d65a5017-d840-4575-9b41-a004ec611074/pasted-text-1.txt`
- **输入完整性说明**：附件只包含评估框架、检查清单和输出模板，没有待审计代码片段。因此本报告以当前工作区实际代码、配置、Prompt、Skill 定义和单元测试作为审计对象。
- **审计范围**：聊天 Runtime、LangGraph/手写 ReAct/Studio 执行环、AgentTeams 质量门控与 QC 证据链、Skill marketplace 定义及 Skill 路由提示词。
- **工作区说明**：审计时工作区存在大量未提交修改和新增文件；结论针对审计时的当前文件内容，不代表最近一次提交的单独状态。

## 1. 总体评估

- **代码类型判断**：Agent 运行时 + Skill 定义 + 工作流/质量门控服务
- **Loop Engineering 等级**：**L2：结构完整（偏下沿）**
- **总分**：**20.5 / 33 分（按清单实际条目计分）**
  - Loop Engineering：9.5 / 21
  - Skills 设计规范：11 / 12
- **模板计分口径矛盾**：附件写“28 分（Loop 16 + Skill 12）”，但其逐项清单实际为 Loop 21 项 + Skill 12 项 = 33 项。本报告按逐项清单评分；若强行按附件的 28 分分母，等价比例为 20.5 / 28 = 73.2%，等级仍为 L2。
- **一句话总结**：当前系统已经具备多 Runtime、显式最大轮次、工具调用上限、连续失败熔断、`ask_user` 中断、权限降级、事件审计、QC 结构化落库和 Skill 契约，但缺少统一的最小执行预算、通用独立完成度判定、冲突驱动的自动复核/修复循环以及全维度清零门控，因此还不能判定为 L3 生产级闭环。

## 2. 逐维度评分

评分规则：已实现 = 1 分，部分实现 = 0.5 分，未实现/不适用 = 0 分。

### Loop Engineering 维度

| 检查项 | 状态 | 得分 | 证据与判断 |
|---|---:|---:|---|
| LE-01 显式/隐式循环 | 已实现 | 1 | `src/cygnusx/application/services/chat/runtimes/direct_chat_runtime.py:265` 使用 `range(8)`；`src/cygnusx/application/services/chat/runtimes/langgraph_runtime.py:246` 使用 `while True`；Provider 还有有限重试循环。 |
| LE-02 独立于模型的退出控制 | 部分实现 | 0.5 | LangGraph 有 `max_rounds`，Studio 有工具调用和连续失败 Guard；但普通完成仍可由“本轮没有 tool calls”结束，未统一要求外部完成度判定。 |
| LE-03 `judge_goal_achieved` 等效逻辑 | 部分实现 | 0.5 | AgentTeams 有质量门控和报告交付门控，但没有覆盖所有 Runtime/任务类型的统一目标完成判定器。 |
| P1-01 最小执行预算 | 未实现 | 0 | 代码主要定义最大轮次/最大工具调用，没有按任务类型强制的最少搜索或验证轮次。 |
| P1-02 最小预算前禁止退出 | 未实现 | 0 | 未发现“最小预算未满足则不能结束”的统一控制流。 |
| P1-03 预算与复杂度挂钩 | 未实现 | 0 | `extend_max_rounds` 仅在默认 100 与 1000 之间切换，不是基于任务复杂度、风险或不确定性的动态预算。 |
| P2-01 结果置信度/等级 | 部分实现 | 0.5 | Router Prompt 要求输出 `confidence`，部分专业 Prompt 使用 `high/medium/low`；但缺少统一的置信度对象、阈值和 Runtime 强制策略。 |
| P2-02 多来源交叉验证 | 部分实现 | 0.5 | AgentTeams 的 QC 判决带 `evidence_event_id`，报告门控检查引用完整性；但普通 Runtime 没有统一的多来源交叉验证要求。 |
| P2-03 低置信度/冲突触发复核循环 | 未实现 | 0 | 现有门控会返回 `BLOCKED/WARNING/MANUAL_REVIEW`，但未形成“检测冲突后自动追加验证/修复子循环”的通用闭环。 |
| P2-04 冲突显式记录分析 | 部分实现 | 0.5 | QC 失败/降级会写入 `qc_verification_checks`，并保留原因与证据指针；但未见统一冲突模型及冲突解决结果字段。 |
| P3-01 外部 build/test/check/lint/audit 验证 | 部分实现 | 0.5 | Flow Skill 要求 Snakemake dry-run/运行验证；沙盒执行检查退出码和超时；但不是所有 Agent 回合的通用完成门。 |
| P3-02 验证失败自动修复重试 | 未实现 | 0 | Provider 有网络/能力降级重试，Runtime 有失败收尾；未形成验证失败→定位→修改→再次验证的通用自动修复循环。 |
| P3-03 零错误通过门控 | 部分实现 | 0.5 | `AgentTeamsQualityGateService` 对 mapping/q30 低于阈值返回 `BLOCKED`，报告交付文件/引用失败也阻断；但只覆盖特定质量/交付路径。 |
| P3-04 禁止绕过验证 | 已实现 | 1 | `data/ai/prompts/shared/sandbox_protocol.md:44-48` 禁止不受控安装、要求版本验证和先落盘；Skill 中要求外部命令失败停止并如实报告。 |
| P4-01 完整预定义维度列表 | 部分实现 | 0.5 | QC 硬规则固定检查 `mapping_rate/q30/duplicate_rate`，专业 QC Prompt 另有质量维度；但没有跨任务统一的完整审计维度注册表。 |
| P4-02 确保所有维度无遗漏 | 未实现 | 0 | 未发现通用“维度清单遍历 + 未检查项阻断”的执行器。 |
| P4-03 关键维度双重验证 | 部分实现 | 0.5 | QC 结构化判决与证据血缘落库形成一层复核，Flow/报告也有独立门控；但没有统一声明每个关键维度必须由两种独立方法验证。 |
| P4-04 Critical 清零门控 | 部分实现 | 0.5 | 存在 `BLOCKED` 硬门和 `inconclusive` 降级记录；但没有统一 `Critical` 严重级别模型及“Critical 必须为零才能完成”的跨域门控。 |
| LS-01 循环上限/超时 | 已实现 | 1 | LangGraph 默认 100 轮、扩展 1000 轮；Studio 配置 `max_tool_calls_per_turn: 40`、`max_consecutive_failures: 3`；沙盒执行设置最大超时并杀进程组。 |
| LS-02 失败降级/用户介入 | 已实现 | 1 | Runtime 提供 `ask_user` 事件；`studio_loop_guard.py:50-61` 在自动模式 Guard 触发时可持久化降级为 `supervised`。 |
| LS-03 循环状态持久化/恢复 | 部分实现 | 0.5 | Runtime 周期性落库消息快照、工具调用和 timeline；事件含 `run_id/round_number`；但没有统一可恢复 checkpoint 协议，且不同 Runtime 的持久化粒度不一致。 |

**Loop Engineering 小计：9.5 / 21**

### Skills 设计规范维度

| 检查项 | 状态 | 得分 | 证据与判断 |
|---|---:|---:|---|
| S1-01 触发条件 | 已实现 | 1 | `data/ai/skill_marketplace/atac-tools/SKILL.md:3,11-13` 明确输入场景和排除场景；`data/ai/prompts/skills/index.md:5-8` 定义按命中场景加载。 |
| S1-02 自适应路由 | 已实现 | 1 | Runtime 路由在 `src/cygnusx/application/services/chat/chat_router_service.py:26-37` 按 runtime/mode/overdrive 选择路径；Skill 索引要求按输入场景选择技能。 |
| S2-01 Phase/Step 工作流 | 已实现 | 1 | Flow Skill 明确 5 阶段；ATAC Skill 在 `:24-36` 给出环境检查、TSS/matrix 分支和收尾步骤。 |
| S2-02 每阶段输入/输出/成功标准 | 已实现 | 1 | ATAC Skill 定义输入契约、命令、成功后读取 `summary.json`、输出文件和失败停止条件。部分复杂 Agent 流程仍依赖 Prompt，故不代表所有流程都同等完整。 |
| S3-01 工具参数/返回/错误契约 | 已实现 | 1 | ATAC Skill 定义 `--operation/--input/--output/--feature/--peaks`；输出为固定文件；错误由 stderr/缺失文件/外部命令失败表达。 |
| S3-02 工具失败重试/回退/报错 | 已实现 | 1 | Skill 要求失败停止并返回错误；Provider 对可重试流错误有退避重试；Prompt 明确网络失败只能重试一次或换白名单兜底源。 |
| S4-01 交付格式 | 已实现 | 1 | Skill 明确 `tss.bed.gz`、`peak_counts.tsv`、`summary.json`；报告门控还检查交付物和引用完整性。 |
| S4-02 命名与保存路径 | 已实现 | 1 | Skill 要求产物写入 `--output`；Flow Skill 有固定目录、rule output/log 约定。 |
| S5-01 禁止行为 | 已实现 | 1 | Skill/Prompt 明确“不用于”范围、失败不替换工具、不改输入、禁止绕过白名单和伪造结果。 |
| S5-02 覆盖常见绕过捷径 | 已实现 | 1 | `sandbox_protocol.md` 覆盖非 conda 安装、未经白名单域名、未验证版本、未落盘直接执行等常见捷径。 |
| S6-01 中间产物文件化 | 部分实现 | 0.5 | Skill 产出 `summary.json`、结果文件；Runtime 写消息快照、timeline、工具调用；但不是所有中间状态都通过统一 artifact/checkpoint 文件化。 |
| S6-02 支持下游读取/跨轮恢复 | 部分实现 | 0.5 | `summary.json` 和事件/快照可供下游读取；但缺少跨 Runtime、跨会话的统一恢复协议和恢复验证。 |

**Skills 小计：11 / 12**

## 3. 已实现的能力清单

1. **Runtime 分层与路由**：`ChatRouterService` 将 direct、langgraph、overdrive、studio 和 legacy 分支显式区分，降低隐式分支漂移风险。
2. **最大轮次硬上限**：LangGraph 到达 `max_tool_rounds` 后撤掉 tools，并要求模型基于已有结果给出最终答复；外围 Runtime 继续发出 `round_limit` 事件而不是静默结束。
3. **工具调用/连续失败熔断**：`StudioLoopGuard` 分别累计单轮工具次数和同一工具/错误签名的连续失败次数，触发结构化 `agent_loop_guard_triggered`。
4. **权限自动降级**：Guard 触发时可将自动模式持久化改为 supervised，降低持续失败下的自治风险。
5. **用户介入出口**：`ask_user` 有独立事件路径，可结束当前图/当前回合并等待用户下一条输入，避免把澄清请求伪装成完成结果。
6. **执行事件可观测**：事件携带 `session_id`、`run_id`、`agent_id`、`round_number`、`execution_path`，支持按回合和执行路径追踪。
7. **质量硬门控**：`AgentTeamsQualityGateService` 对 mapping rate、Q30、duplicate rate 进行阈值判断，输出 `PASSED/WARNING/BLOCKED/MANUAL_REVIEW`。
8. **QC 证据化落库**：`AgentTeamsQcVerificationService` 将每条 check 落库，保存 verdict、evidence 指针、reviewer、claim snapshot 和 reason；schema 降级显式记录为 `inconclusive`，没有静默吞错。
9. **Skill 契约较完整**：代表性 Skill 同时给出 Trigger、Input、Workflow、Output、QC/Constraints；Skill 索引要求先按 `skill_id` 加载正文，避免凭名称猜步骤。
10. **外部执行安全边界**：沙盒对命令执行设置超时、输出上限、进程组终止和产物收集；脚本与溢出日志有明确生命周期管理。
11. **回归测试覆盖关键路径**：本次运行的 26 个相关测试全部通过，覆盖 Loop Guard、LangGraph Runtime 错误收尾、质量门控和 QC 证据落库。

## 4. 缺失的关键能力

| 优先级 | 缺失项 | 影响 | 修复建议 |
|---|---|---|---|
| P0 | 无统一目标完成判定 | 模型无 tool calls 即可能被视为完成，无法证明用户目标、交付物和验证结果均满足。 | 引入 `GoalCompletionJudge`，输入任务目标、必需产物、验证证据和未解决项；只有 `goal_complete=true` 才允许 terminal completed。 |
| P0 | 无最小验证预算 | 简单回答可能零工具、零复核直接结束，Loop Engineering 无法防止过早退出。 | 按风险/任务类型配置 `min_actions`、`min_evidence_checks` 或 `min_validation_rounds`，未满足时强制继续或转人工。 |
| P0 | 无统一 Critical 严重级别清零门 | 各域的 BLOCKED 规则不能保证跨 Runtime、跨 Skill 的严重问题都被拦截。 | 统一 `severity: critical/high/medium/low` 和 `GateDecision`；存在 Critical 或 unresolved conflict 时禁止 completed。 |
| P1 | 冲突不驱动自动复核/修复 | QC 能记录失败，但多数情况下只停留在记录/报错，自治闭环不完整。 | 增加 `conflict -> verifier route -> repair -> recheck` 子循环，限制次数并持久化每次尝试及结果。 |
| P1 | 无全维度审计注册表 | 目前是特定服务分别检查固定指标，无法证明所有预定义维度均已覆盖。 | 定义版本化 `AuditDimensionRegistry`，执行时生成 checked/unresolved/not_applicable 清单；缺项直接阻断。 |
| P1 | checkpoint/恢复协议不统一 | 消息快照、事件、timeline 和 QC 表分散，进程中断后不能保证从同一状态安全续跑。 | 统一保存 loop state、tool results、pending action、budget、gate status 和 schema version，并实现 resume 前完整性校验。 |
| P1 | 验证失败没有通用自动修复循环 | 外部检查通过与否已有局部门控，但没有针对代码/脚本/配置问题的修复再验证闭环。 | 对可修复错误定义修复器白名单、最大修复轮次和 diff/测试证据；不可修复则升级用户。 |
| P2 | 预算不是自适应的 | 100/1000 轮切换过于粗粒度，可能浪费资源或不足。 | 以任务复杂度、工具风险、历史失败率、剩余 token/时间动态计算预算，并保留硬上限。 |
| P2 | 置信度模型不统一 | Router/Prompt 中有 confidence，但服务层没有统一阈值、来源权重和冲突语义。 | 统一置信度 schema，要求来源、时间、方法、冲突集合和降级原因。 |
| P2 | Skill 中间态标准不足 | Skill 输出文件较清晰，但阶段性 manifest、校验摘要、恢复点并非所有 Skill 都要求。 | 在 Skill 规范中强制 `manifest.json`/`status.json`/阶段日志和 schema version。 |

## 5. 升级路径建议

按当前 L2 → L3 的最短路径：

1. **先建统一完成门**：将所有 Runtime 的 completed 收口到 `GoalCompletionJudge + GateDecision`，禁止仅凭无 tool calls 结束。
2. **补齐最小预算**：对高风险分析、代码执行、正式交付和质量门控任务设置最少验证次数/最少证据数；低风险聊天可显式标记为 exempt。
3. **统一全维度审计**：建立版本化维度清单，要求每项为 `passed/warned/blocked/not_applicable`，任何 critical/unresolved/missing 都阻断完成。
4. **实现冲突复核子循环**：把 QC 的 `fail/inconclusive/conflict` 连接到有限次数的独立验证器和修复器，并记录前后证据。
5. **统一 checkpoint**：把轮次、预算、工具调用、待执行动作、门控结果和中间产物索引写入可恢复状态；增加中断恢复和幂等测试。

## 6. 验证记录

本次执行的针对性测试：

```text
pytest -q \
  tests/unit/test_studio_loop_guard.py \
  tests/unit/chat/test_langgraph_chat_runtime.py \
  tests/unit/test_agentteams_quality_gate_service.py \
  tests/unit/test_agentteams_qc_verification.py
```

结果：**26 passed，1 warning，0 failed**。

警告为现有 Pydantic class-based `config` 弃用提示，不影响本次审计结论。

## 7. 关键证据索引

- `src/cygnusx/application/services/studio_loop_guard.py:33-121`：Loop Guard、工具调用上限、连续失败熔断、权限降级事件。
- `src/cygnusx/application/services/chat/runtimes/langgraph_runtime.py:186-189,246-263,537-570`：默认/扩展轮次、执行循环、轮次耗尽事件和终态。
- `src/cygnusx/infrastructure/execution/langgraph_nodes.py:94-169,322-329`：到达工具预算后撤销 tools、工具调用路由。
- `src/cygnusx/application/services/chat/runtimes/direct_chat_runtime.py:265-327`：手写 ReAct 的最大 8 轮和无工具调用收尾。
- `data/ai/studio.yaml:28-29`：Studio `max_tool_calls_per_turn` 与 `max_consecutive_failures` 配置。
- `src/cygnusx/application/services/agentteams_quality_gate_service.py:17-75,77-120`：质量/报告交付硬门控。
- `src/cygnusx/application/services/agentteams_qc_verification_service.py:32-85,87-103`：QC check、降级 `inconclusive` 和证据化落库。
- `data/ai/skill_marketplace/atac-tools/SKILL.md:1-45`：Trigger、Input、Workflow、Output、QC 和禁止范围示例。
- `data/ai/prompts/skills/index.md:3-8`：Skill 元数据索引和渐进式加载契约。
- `data/ai/prompts/shared/sandbox_protocol.md:44-50`：依赖安装、验证、失败重试和禁止绕过行为。

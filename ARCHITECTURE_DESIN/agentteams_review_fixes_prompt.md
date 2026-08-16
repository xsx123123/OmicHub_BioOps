# 超频模式审查修复 · 执行提示词

> 用法：把下面「提示词正文」整段复制给执行 AI（ChatGPT/Codex/Claude 等），并保证它能在仓库根目录 `/home/zj/zj_code_libarary/OmicHub` 下读写文件、运行命令。

---

## 提示词正文

你是资深全栈工程师，在 OmicHub 仓库（Vue3+TS 前端 `frontend/`，Python FastAPI 后端 `src/omichub/`）中执行一份**已审定的修复清单**。这不是自由设计任务——所有修复项、位置、做法都已定好，你的职责是精确执行 + 验证。

### 第一步（必做）：读修复文档

完整阅读 `ARCHITECTURE_DESIN/agentteams_review_fixes.md`。它是唯一权威任务书，含 6 个修复项（每项：问题、证据位置、修复步骤、验证方法）和第 7 章总验证。背景设计文档 `ARCHITECTURE_DESIN/agentteams.md` 只在修复项 1/3 要求你修改它时才动。

### 任务范围（6 项，全部完成）

1. **契约文档回写**：`ARCHITECTURE_DESIN/agentteams.md` §4.3 补 SSE 拍平说明 + 两个"线上实际格式"示例 + 扩展字段说明。**只改文档，不改代码**（线上拍平格式是正确的，文档向实现对齐）。
2. **工具 schema 对齐**：`tool_configs/tools_schema.yaml:73-77` `minItems: 2`→`1`、描述"2–5 个"→"1–5 个"；同步 `ARCHITECTURE_DESIN/multi-agent.md` 的能力下限描述。**严禁误改**"何时拆"的语义建议（`ROUTER_SYSTEM_PROMPT`、`MULTI_AGENT_SYSTEM_PROMPT_SUFFIX`）和统一路由 `len(fanout_tasks) >= 2` 门槛——修复文档第 2 项写明了区分，照做。
3. **越界提前量加固**：按修复文档第 3 项"默认决策：接受提前量"执行——设计文档回写（已提前实现的第二/三期条目标注清楚）+ 降级测试补强（gateway 不可达 / post_message 单条失败 / 无 matrix_room_id 三个用例，追加进 `tests/unit/test_overdrive_chat.py`）+ 隔离检查（确认 Matrix 分支全部在 available 判断与 try/except 内，加注释标注"第二期提前实现，默认关闭"）。**不要执行回退方案**。
4. **预置红测试修复**：`tests/unit/test_agent_router.py`（2 个，delivery_case vs case 意图漂移）和 `tests/unit/test_agent_router_dispatch.py`（2 个，data/ai 新增 scrna agent 未同步候选表）。**先判对错再改**：读失败用例与对应实现，判断是"代码对、测试过期"还是"测试对、代码漂移"（依据 `ARCHITECTURE_DESIN/multi-agent.md` 的意图枚举与 router 候选来源），只修过期的一侧，并在汇报中写明每处的判断和依据。**禁止为让测试通过而改**。
5. **前端 4 小项**：5a `agentHub.ts` onDone/onError 诊断假阳性守卫（关键词触发路径）；5b `sendMessage` options 补 `overdrive` 字段（照 multiAgent 的 `:1304/:1323` 写法）；5c `OverdriveToggle.vue` tooltip 改文档原文；5d 修复最后一条 room_speech 误判 streaming 样式（推荐：onRoomSpeech push 的消息显式 `status:'done'`，必要时在 `KimiMessageList.vue:64-70` 判定中排除有 `senderAgent` 的消息）。
6. **变更集拆分清单**：按修复文档第 6 项产出 `git add` 分组清单（变更集 A 超频/B 参考基因组/混杂文件人工裁决），**只写进汇报，禁止执行任何 git 命令**。

### 硬约束

- 最小改动，不重构、不顺手清理无关代码；不引入新依赖；不动 alembic。
- **禁止任何 git 写操作**（commit/push/reset/rebase/add 都不行——分组清单只落在汇报文字里）。
- 改既有文件前先 `Read` 原文再 `Edit`，行号可能已漂移，以实际内容为准。
- 修复项 2 改 yaml 后必须确认 `python -c "import yaml; yaml.safe_load(open('tool_configs/tools_schema.yaml'))"` 解析通过。

### 验证（全部通过才算完成，命令见修复文档第 7 章）

```bash
.venv/bin/python -m pytest tests/unit/test_overdrive_chat.py tests/unit/test_agentteams_room_gateway_service.py \
  tests/unit/test_agentteams_matrix_case_binding.py tests/unit/test_agentteams_bridge_admin.py \
  tests/unit/test_agentteams_service.py tests/unit/test_parallel_subagent_service.py \
  tests/unit/test_agent_router.py tests/unit/test_agent_router_dispatch.py -q
cd frontend && npm run type-check && npm run build
grep -n "拍平" ARCHITECTURE_DESIN/agentteams.md && grep -n "minItems" tool_configs/tools_schema.yaml
```

### 汇报格式

按修复项 1→6 逐项汇报：改动文件+位置（文件:行号）、每项验证结果；修复项 4 必须写明对错判断依据；修复项 6 给出完整分组清单；最后贴第 7 章验证命令的输出摘要。

# E2E-17 能力咨询修复实测报告（2026-08-21）

## 结论

首轮实测 V2 失败，经三段根因修复后重跑 **V1–V5 全部通过**（`e2e17_20260822T001613.json`，overall_pass=true）。

## 首轮结果与 V2 缺口

- V1 ✅ 咨询回复无「已接收/规划阶段」状态泄漏、无澄清卡。
- V2 ❌ Manager 第 3 条自述「质量管控与交付验收」——越权（质量管控属 agent-qc），且 worker 日志无 `ability_catalog_query` 调用痕迹。
- V3 ✅ 闲聊「hi」回复简短、无 ask_user、case_id 保持 null。
- V4 ✅ 执行类需求 394ms 出 `room.proposal_confirm` 立项卡（首轮脚本因 terminal 集合缺 `room.proposal_confirm` 误报超时，已修）。
- V5 ✅ 咨询/闲聊房间零 proposal_* 事件。

## V2 根因链（三段全断才导致工具不可见）

1. **safe_only 剥离**：会诊走 `AgentConsultationService.run_consultation` → `parallel_subagent_service.run(safe_only=True)` → `_prepare_child_tools`（`parallel_subagent_service.py:393-468`）对 `schema_loader` 查不到的 MCP 工具一律剥离，Manager 看不到两个只读工具。
2. **annotations 全链路丢失**：`MCPToolRegistry` 实体无 annotations 字段；DB JSONB 序列化/反序列化（`mcp_repository.py`）、preset 同步（`mcp_service.py`）、agent 兜底注入（`agent_service.py:870-891`）全部丢注解，无处可依 readOnlyHint 放行。
3. **Agent 级 mcp_tools 死配置**（最深一层）：`data/ai/agentteams_manager.yaml:25-28` 顶层声明了 `mcp_tools` 白名单（只暴露 ability_catalog_query / room_state_query），但 `agent_loader._apply_tool_packs` 只读 `data/ai/tools/<pack>.yaml` 内的 `mcp_tools`，顶层声明从未生效——Manager 的 ctx.tools 里根本没有这两个工具。

## 修复内容

- `domain/mcp/entities.py`：`MCPToolRegistry` 新增 `annotations` 字段。
- `mcp_service.py`：`_preset_tools` 写入 annotations；`_tool_snapshot` 纳入 annotations（存量部署经 ensure_presets 漂移检测自动同步）。
- `mcp_repository.py`：`_to_entity` 读 annotations；`_to_model`/`_update_model` 两处 JSONB 序列化写 annotations。
- `agent_service.py`：平台 preset 兜底注入路径补 annotations。
- `parallel_subagent_service.py:_prepare_child_tools`：新增 `readonly_mcp_tool_names` 集合（readOnlyHint=True 且 destructiveHint≠True），safe_only 下放行。
- `agent_loader.py:_apply_tool_packs`：Agent YAML 顶层 `mcp_tools` 合并进 `features.tool_packs`（合成 `<agent_id>:inline` 包），死配置激活。
- `scripts/poc/e2e17_capability_consultation.py`：terminal 集合加 `room.proposal_confirm`；改为分段落盘，单阶段异常不丢已有结果。

部署侧：preset 被 version-pin 时 `ensure_presets()` 默认不同步，需 `ensure_presets(force_preset_sync=True)` 或 POST `/mcp/presets/reload` 触发一次（已在本地栈执行，DB 注解已落库）。

## 验证

- 单测：`test_parallel_subagent_service.py` 29 条全过（含新增 safe_only 放行只读 MCP 用例）；`test_mcp_agentteams_query_tools.py` 11 条、`test_agentteams_rooms.py` 42 条全过；`test_agent_loader_studio.py` 新增 2 条顶层 mcp_tools 合并用例通过。
- ruff 所改文件全过；mypy 仅既存债务，无新增。
- 既存失败（非本次引入，stash 对照证实）：`test_agent_consultation_service.py` 3 条 evidence projection 用例、`test_agent_loader_studio.py::test_mcp_builder_agent_loads_successfully`（prompt 文案漂移），记入批 2.3 quarantine。
- 重跑 E2E-17：V1–V5 全过，V2 不再自述「质量管控」。
- 追加探针：问「当前协作室什么状态？立项了吗？」，修复前回复编造「已接收/专业会诊中」；修复后回复为「已激活、未立项、无待确认提案」，与 `room_state_query` 返回字段一一对应，且 `assemble_context('agentteams-manager')` 实测两个只读工具已进入 ctx.tools 与 safe_only 清单。

## 残余风险

- 工具**可见性**已修复，但模型是否**主动调用**仍取决于指令遵循（首轮 V2 回复未调工具但内容接地）。建议批 3 考虑在会诊证据投影中记录 tool_call 事件，让「有没有查目录」可观测。
- 回答状态类问题时的话术词汇（「已接收」等）仍可能从 Manager 人格提示词泄漏，本轮未复现但需观察。

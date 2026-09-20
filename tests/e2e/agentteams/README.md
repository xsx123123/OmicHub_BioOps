# AgentTeams e2e 套件索引（E2E-1~E2E-10 映射表）

> 口径来源：《协作室平台地基优化实施手册》阶段 3 任务 2（E2E-1~E2E-6）、
> 《协作室L4审查修复与优化实施手册》阶段 1 任务 3（E2E-7）。
> 原则：本目录下的用例**默认进 pytest 且绿**（进程内、无外部服务依赖）；
> 需要真实服务矩阵的版本走 opt-in 门控（`AGENTTEAMS_ACCEPTANCE_E2E=1`），
> 不强行在 CI 起真实服务。

| 编号 | 场景 | 覆盖文件 | 状态 |
| --- | --- | --- | --- |
| E2E-1 | 创建→路由→派发→投影全链路 | 本目录 `test_default_bridge_e2e.py`（进程内 ASGI：create→assign→claim→事件序列断言）；平台侧路由/投影由 `tests/unit/test_agentteams_service.py::test_create_chat_case_routes_scrna_cellranger_request_without_file_name`、`test_create_case_starts_planning_with_the_selected_flow` 与 `tests/unit/test_case_room_projector.py` 分段覆盖 | 分段覆盖；跨进程真实全链路仅 opt-in（`test_acceptance_profile.py`） |
| E2E-2 | 平台-Bridge 参数契约（limit 边界，防断点 A） | `tests/unit/test_agentteams_service.py::test_case_event_requests_clamp_to_bridge_limit`、`test_room_response_timing_summary_pages_beyond_bridge_limit` | 已覆盖（单测契约） |
| E2E-3 | 未知领域输入（16S：route_unavailable 或显式 fallback，不得静默断链） | `tests/unit/test_agentteams_intent_router.py::test_unrecognized_intent_returns_none`；fallback 显式可审计：`tests/unit/test_agentteams_route_decision.py::test_fallback_route_decision_is_explicitly_auditable`、`test_fallback_route_emits_audited_code_planner` | 路由层已覆盖；前端文案侧无端到端用例（缺口） |
| E2E-4 | 规划失败显式化（Case 不停 received，须有失败事件与可见提示） | `tests/unit/test_agentteams_service.py::test_flow_case_records_handoff_failure_when_worker_is_unavailable`（handoff 失败落事件） | 部分覆盖；注入 Bridge 故障的进程级用例缺失（缺口） |
| E2E-5 | 删除聊天室（含"超时但后端已删"对账场景） | `tests/unit/test_agentteams_service.py::test_delete_case_checks_owner_before_bridge_delete`（删除链路与属主校验） | 部分覆盖；"超时但后端已删"对账场景无对应用例（缺口） |
| E2E-6 | 用户消息气泡可见性（发送→落库→渲染，防 R2-4 回归） | 发送→落库：`tests/unit/test_agentteams_room_messages.py::test_post_room_message_records_user_message_evidence`、`test_post_room_message_records_context_refs_in_payload` | 落库侧已覆盖；前端渲染侧无 e2e（缺口，候选：组件级 vitest） |
| E2E-7 | 「hi 不建 Case」：新房间闲聊不得创建 Case、无进度条数据、只有 Manager 对话回复（防 08-21 症状回归） | 本目录 `test_hi_no_case_e2e.py`（默认进 pytest）；哨兵单测 `tests/unit/test_agentteams_rooms.py::test_unbound_room_chat_never_creates_case` | 已覆盖 |
| E2E-10 | 真实 Case 离线流程报告：生成 `reports/flow-*.html` → JWT 受控下载 → 可打开并含环境快照与校验摘要 | `test_live_foundation_e2e.py::test_live_e2e10_flow_report_export_and_controlled_download`；报告内容裁剪与谱系登记由 `tests/unit/test_agentteams_flow_report_service.py` 覆盖 | 真实栈 opt-in；单测已覆盖 |

## 约定

- 新增 e2e 用例放在本目录，标注 `@pytest.mark.e2e`，默认不依赖外部服务/凭证。
- 真实服务版验收链路保持 opt-in：`AGENTTEAMS_ACCEPTANCE_E2E=1 uv run pytest tests/e2e/agentteams/test_acceptance_profile.py`。
- 流程报告真实栈验收：`AGENTTEAMS_LIVE_E2E=1 CYGNUSX_E2E_BASE_URL=http://localhost:8000 CYGNUSX_E2E_TOKEN=<JWT> uv run pytest tests/e2e/agentteams/test_live_foundation_e2e.py -k e2e10 -v`。该用例实际走后端、Bridge、PostgreSQL 和 MinIO；当前登录用户必须可创建通用 Case。
- 上表"缺口"行是后续补强的登记项，不是豁免；补用例时优先把缺口场景做成进程内默认可跑版本。

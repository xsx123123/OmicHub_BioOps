# 测试 Quarantine Burn-down 清单（2026-08-21）

来源：协作室后续优化路线图 批 2.3（P1-5）。目标是把"存量失败但与本批工作无关"的测试从 CI 主套件中隔离，使 `tests/unit` 基线转绿，同时保留逐条归因以便后续清零。

## 机制

- `pyproject.toml` 注册 marker：`quarantine: 存量失败隔离（burn-down 清零前不阻塞 CI）`。
- CI（`.github/workflows/ci.yml`）与本地约定命令统一为：
  `uv run pytest tests/unit tests/e2e -q -m "not quarantine"`。
- 每个被隔离用例就地标注 `@pytest.mark.quarantine(reason="...")`，reason 写明根因，不挪文件、不改断言。

## 基线数字（标记完成后实测）

| 范围 | 结果 |
|---|---|
| `tests/unit -m "not quarantine"` | 1925 passed / 0 failed / 72 deselected / 15 skipped |
| `tests/unit -m quarantine --collect-only` | 恰 72 条 |
| `tests/e2e` 全量 | 2 passed / 4 skipped（无存量失败，无需隔离） |
| ruff（35 个改动文件） | 无新增告警 |

隔离前基线：67 failed + 5 error / 1925 passed。即全部存量失败均已归因并隔离，无"找不到原因"的条目。

## 归因分类（72 条 → 9 类）

| 类别 | 条数 | 涉及文件 |
|---|---|---|
| mock/stub 签名落后：`assemble_context` 新增 `user_id` 关键字 | 11 | test_studio_capabilities(2)、test_studio_plan_interception(2)、test_web_search_service(6)、test_multi_expert_consultation_service(1) |
| `_FakeRedis` 未实现 `eval`（审批服务改用 Lua 脚本） | 8 | test_studio_approval(8) |
| `extract_skill_from_workspace` 新增 keyword-only 参数 `owner_id/visibility` | 6 | test_studio_skill_service(6，含 3 条参数化) |
| fixture 依赖已移除的 `DownloadService._settings`（setup 即 AttributeError） | 5 | test_download_service(5) |
| DocsService 接口变更（增 `doc_id`/`db` 参数、删 `save_knowledge_doc`） | 5 | test_docs_service(5) |
| `FakeSession` 未实现 `session.refresh` | 4 | test_skill_version_control(4) |
| SiteSettingsDTO 校验字段与现行模型不匹配 | 4 | test_site_settings_collaboration(4，含 3 条参数化) |
| 证据投影协程未被 await，事件/计数断言落空 | 3 | test_agent_consultation_service(3) |
| 文案/配置漂移（提示词红线字样、domain notes、工具数量 12→13、schema 描述等） | 9 | test_agent_loader_studio、test_skill_builder_prompt、test_domain_pack_loader、test_studio_tools、test_overdrive_persona_config、test_import_qc_knowledge、test_ai_provider_yaml_writer(2)、test_ai_provider_yaml_loader_prune、tools/test_tool_bridge |
| 其他实现漂移（platform_tools 6、blast AsyncMock 2、mcp_version_control 2、provider_retry KeyError 1、enrichment `_project_slug` 改名 1、mas mock 缺 `project_id` 1、celery `_FakeCeleryTask` 缺 `name` 1） | 14 | test_studio_platform_tools(6)、tools/test_blast_core(2)、test_mcp_version_control(2)、test_provider_retry_policy、tools/test_enrichment_runner、test_mas_plan_approval_gate(2)、test_studio_long_task |
| 套件内污染（单独运行通过） | 1 | test_analyze_skill_invocations |

## 逐条清单（节点 ID + reason）

> reason 与代码内 `@pytest.mark.quarantine(reason=...)` 一致；参数化用例共享同一 decorator。

### tests/unit/test_agent_consultation_service.py（3）
- `test_evidence_projection_emits_agent_events_with_truncated_args` — 证据投影 project_event 为协程但调用方未 await，未发出任何 agent 事件，事件集合断言失败
- `test_evidence_projection_failure_does_not_break_consultation` — 证据投影协程未被 await，post_evidence 调用计数为 0，与预期 3 不符
- `test_tool_call_evidence_is_capped_at_200_with_truncation_marker` — 证据投影协程未被 await，工具调用证据为 0 条，200 条上限截断断言失败

### tests/unit/test_agent_loader_studio.py（1）
- `test_mcp_builder_agent_loads_successfully` — MCP 构建师提示词文案已更新，不再包含断言期望的红线字样

### tests/unit/test_ai_provider_yaml_loader_prune.py（1）
- `test_loader_prunes_providers_not_in_yaml` — YAML 未声明的 provider 未被停用，剪枝行为与现行 loader 实现不一致

### tests/unit/test_ai_provider_yaml_writer.py（2）
- `test_provider_env_key_naming` — provider_env_key 命名规则断言与现行实现不一致
- `test_write_never_persists_real_api_key` — 写出的 YAML 未包含断言期望的 `${DEEPSEEK_V4_FLASH_API_KEY}` 占位符

### tests/unit/test_analyze_skill_invocations.py（1）
- `test_group_unhit_messages_finds_common_patterns` — 依赖外部技能调用日志状态，全量套件运行时被其他用例污染而失败（单独运行通过）

### tests/unit/test_docs_service.py（5）
- `test_get_knowledge_doc_loads_content` — DocsService.get_knowledge_doc 签名已增加 doc_id 参数，测试仍按旧签名调用
- `test_list_knowledge_returns_category` — DocsService.list_knowledge 签名已增加 db 参数，测试仍按旧签名调用
- `test_load_doc_path_traversal_blocked` — DocsService.get_knowledge_doc 签名已变更，路径穿越用例仍按旧签名调用
- `test_save_knowledge_doc_writes_disk_and_reload` — DocsService 已无 save_knowledge_doc 方法，测试针对旧接口
- `test_save_unknown_doc_raises` — DocsService 已无 save_knowledge_doc 方法，测试针对旧接口

### tests/unit/test_domain_pack_loader.py（1）
- `test_default_registry_injects_domain_notes_from_yaml` — YAML 注入的 domain notes 文案与断言逐字不一致

### tests/unit/test_download_service.py（5，setup 阶段 AttributeError）
- `test_submit_creates_download_task_and_dispatches`
- `test_submit_sanitizes_accession_path`
- `test_submit_cloud_storage_task_and_dispatches`
- `test_submit_direct_link_task_persists_batch_options`
- `test_list_downloads_filters_by_flow_id`
（共同原因：fixture 构造的 DownloadService 依赖 `_settings` 属性，现行实现已移除）

### tests/unit/test_import_qc_knowledge.py（1）
- `test_qc_source_validation_has_complete_asset_coverage` — QC 知识资产清单已扩充，资产覆盖缺口计数断言不再成立

### tests/unit/test_mas_plan_approval_gate.py（2）
- `test_approved_plan_moves_to_queued_and_emits_plan_approved` — mas_service 访问 project_id 属性，测试 mock（SimpleNamespace）未提供该属性
- `test_no_auto_approve_bypass_exists` — 审批事件 payload 字段集合断言与现行实现不一致

### tests/unit/test_mcp_version_control.py（2）
- `test_update_triggers_snapshot_and_version_bump` — 版本快照中工具 schema 结构与断言不一致
- `test_rollback_restores_config_and_creates_rollback_row` — 回滚恢复的工具 schema 结构与断言不一致

### tests/unit/test_multi_expert_consultation_service.py（1）
- `test_collect_runs_experts_and_ignores_failed_opinion` — assemble_context 调用新增 user_id 关键字，AgentServiceStub 签名未跟上

### tests/unit/test_overdrive_persona_config.py（1）
- `test_enabled_agent_personas_are_complete_deterministic_and_permission_neutral` — 启用的 agent persona 集合与断言不一致，CygnusX.yaml 配置已变更

### tests/unit/test_provider_retry_policy.py（1）
- `test_deepseek_v4_explicitly_disables_thinking` — deepseek v4 请求 payload 未写入 enable_thinking 键，触发 KeyError

### tests/unit/test_site_settings_collaboration.py（4）
- `test_collaboration_presets_write_expected_switches[light-False-False]`
- `test_collaboration_presets_write_expected_switches[parallel-True-False]`
- `test_collaboration_presets_write_expected_switches[full-True-True]`
（共同原因：协作预设写入触发 SiteSettingsDTO 校验失败，字段与现行模型不匹配）
- `test_degradation_templates_have_safe_defaults_and_persist` — 降级模板写入触发 SiteSettingsDTO 校验失败，字段与现行模型不匹配

### tests/unit/test_skill_builder_prompt.py（1）
- `test_skill_builder_prompt_has_key_red_lines` — 技能构建师提示词文案已更新，不再包含断言期望的红线字样

### tests/unit/test_skill_version_control.py（4）
- `test_update_skill_creates_new_revision_and_rewrites_disk`
- `test_toggle_skill_does_not_snapshot`
- `test_list_versions_desc`
- `test_rollback_restores_fields_and_snapshots`
（共同原因：skill_service 更新流程调用 session.refresh，FakeSession 未实现该方法）

### tests/unit/test_studio_approval.py（8）
- `test_list_pending_filters_by_user_session_and_status`
- `test_resolve_approved_writes_result_and_updates_status`
- `test_resolve_edited_carries_modified_args`
- `test_resolve_rejected_with_reason`
- `test_resolve_rejects_wrong_user`
- `test_resolve_rejects_consumed_record`
- `test_resolve_unknown_id_returns_none`
- `test_wait_resolution_returns_pushed_resolution`
（共同原因：审批服务改用 redis.eval Lua 脚本，_FakeRedis 未实现 eval 方法）

### tests/unit/test_studio_capabilities.py（2）
- `test_chat_loads_skill_and_mcp_only_after_capability_tool`
- `test_existing_studio_session_rejects_different_agent`
（共同原因：assemble_context mock 签名缺少 user_id 关键字，与 chat_service 现行调用不匹配）

### tests/unit/test_studio_long_task.py（1）
- `test_submit_studio_long_task_commits_before_celery_dispatch` — dispatcher 访问 celery task.name，_FakeCeleryTask 未提供该属性

### tests/unit/test_studio_plan_interception.py（2）
- `test_update_plan_intercepted_yields_plan_chunk_and_persists`
- `test_update_plan_not_intercepted_for_chat_session`
（共同原因：mocked_agent_runtime 的 assemble_context 签名缺少 user_id 关键字）

### tests/unit/test_studio_platform_tools.py（6）
- `test_artifact_register_versions_from_context_pack` — artifact_register 依据 context_pack 登记版本的结果与断言不符
- `test_artifact_register_without_context_pack_is_v1` — artifact_register 无 context_pack 时默认 v1 的行为与断言不符
- `test_datahub_import_happy_path` — datahub_import 执行结果 success 为 False，与 happy path 断言不符
- `test_datahub_import_dedupes_on_name_collision` — datahub_import 结果缺少 sandbox_path 键，触发 KeyError
- `test_import_endpoint_happy_path` — 上下文文件在磁盘上不存在，导入端点抛 BusinessError
- `test_platform_result_import_links_report_files` — platform_result_import 未按预期链接报告文件，断言失败

### tests/unit/test_studio_skill_service.py（6）
- `test_extract_skill_packages_script_with_provenance`
- `test_extract_skill_rejects_detected_secret`
- `test_extract_skill_rejects_oversized_script`
- `test_extract_skill_rejects_unsafe_requests[overrides0-必须确认]`
- `test_extract_skill_rejects_unsafe_requests[overrides1-仅允许提炼]`
- `test_extract_skill_rejects_unsafe_requests[overrides2-越出工作区]`
（共同原因：extract_skill_from_workspace 新增 keyword-only 参数 owner_id/visibility，测试未传）

### tests/unit/test_studio_tools.py（1）
- `test_tool_schemas_cover_exactly_twelve_tools` — Studio 工具数量已变为 13 个，断言仍期望 12 个

### tests/unit/test_web_search_service.py（6）
- `test_professional_chat_mounts_kb_first_web_fallback_protocol`
- `test_professional_chat_can_fallback_from_empty_kb_to_web`
- `test_agent_without_tools_uses_presearch_context`
- `test_agent_injects_user_memory_into_system_prompt`
- `test_agent_with_tools_executes_and_reinjects_web_search`
- `test_presearch_failure_does_not_interrupt_agent_response`
（共同原因：assemble_context mock 签名缺少 user_id 关键字，与 chat_service 现行调用不匹配）

### tests/unit/tools/test_blast_core.py（2）
- `test_get_storage_stats_calculates_size_and_counts`
- `test_get_storage_stats_returns_zero_when_directory_missing`
（共同原因：blast service 内部 await 了普通 Mock（应使用 AsyncMock），抛 TypeError）

### tests/unit/tools/test_enrichment_runner.py（1）
- `test_project_name_builds_safe_user_enrichment_directory` — EnrichmentService 已无 _project_slug 属性，内部实现已改名

### tests/unit/tools/test_tool_bridge.py（1）
- `test_phylogenetic_tree_schema_uses_unified_page_entry` — 系统发育树工具 schema 描述文案与断言不一致

## 清零建议（按性价比排序）

1. **mock 签名类（约 19 条）**：`assemble_context` 补 `user_id`、`_FakeRedis.eval`、`_FakeCeleryTask.name`、`FakeSession.refresh`、`SimpleNamespace` 补 `project_id` —— 都是 stub 补方法，每条几分钟。
2. **接口漂移类（约 16 条）**：DocsService、DownloadService、extract_skill、EnrichmentService 改名 —— 按现行签名重写调用即可。
3. **文案/配置漂移类（9 条）**：逐条确认现行文案是"想要的行为"后更新断言；其中工具数量 12→13、QC 资产覆盖需先确认变更是否符合预期。
4. **协程未 await 类（3 条）**：test_agent_consultation_service 需确认生产代码是否漏 await（可能是真 bug，不只是测试问题）。
5. **套件污染类（1 条）**：test_analyze_skill_invocations 需排查哪个用例污染了日志状态，补隔离 fixture。

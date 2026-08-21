# Track B 地基 e2e 验收汇总（2026-08-21）

> 任务书：docs/info/26.8.21/协作室双线施工任务书-三件套实现与地基e2e验收.md Part 2
> 状态图例：🟩 绿 / 🟥 红 / 🟨 部分覆盖或带观察项 / ⬜ 未覆盖
> **总体结论（第一轮验收）：11 条中 4 绿 / 1 半绿 / 3 红 / 1 阻断红 / 2 未覆盖，Track B 未达通过标准。
> 已归档 3 个地基 bug（BUG-E2E-01/02/03）。**
> **第二轮 hotfix 复验（2026-08-21 凌晨）：BUG-01/02/03、E2E-2、E2E-9 五项修复全部落地并
> live 复验转绿；复验中新发现的 BUG-04/05 同轮修复并复验；E2E-1 链路重跑推进至
> approval_pending（规划→preflight→审批贯通，审批后执行段未跑）。详见文末「Hotfix 复验」节。**

## 环境准备（Part 2.1）

- 镜像新鲜度：开工时 web/beat 镜像构建于 2026-08-20 22:26(+0800)，bridge 22:36，
  而 23:47–00:38 有新一轮源码改动（v3 复审 A1/A2/A3/B1、confirm-proposal 幂等、/health SHA），
  **运行镜像不含最新代码** → 已重建（web/beat compose build + up；bridge/gateway/agentteams workers
  经 `make docker-up-agentteams`；omichub worker/phylo-worker 因 src bind mount 仅 restart）。
- 重建后 `/health`（web）= git_sha 4680155 / build_time 2026-08-20T17:29:51Z；
  `/healthz`（bridge）= build_sha 4680155 / minio_enabled=true / minio_reachable=true。
  ⚠️ SHA=HEAD 4680155，但工作树有 232 个未提交改动，SHA 无法反映工作树内容（红线禁 git 提交）。
- alembic：`current == heads == u4v5w6x7y8z9`（web 容器 entrypoint 启动自迁移已生效）。
- 备注：验收过程中用户侧两次运行 `make docker-reload`（02:05/02:12 +0800），栈被整体重建；
  相关用例在重建后复验。
- e2e 套件已固化为 live 脚本：`tests/e2e/agentteams/test_live_foundation_e2e.py`
  （E2E-7/2/9 三条，HTTP 驱动真实栈、无 mock；`AGENTTEAMS_LIVE_E2E=1` + `OMICHUB_E2E_TOKEN` 门控，
  默认 skip 不进 CI——任务书「套件进 CI 默认执行」一项因真实栈依赖（compose 矩阵）未落地，见遗留问题）。
- 证据：env/pre_rebuild_snapshot.md, env/post_rebuild_snapshot.md

## 用例结果

| # | 用例 | 结果 | 证据 |
| --- | --- | --- | --- |
| E2E-1 | 全链路（发言→路由→澄清→立项→审批→执行） | 🟥 前半绿（建 Case→路由→规划→3 轮校验自愈→planning.frozen 事件序列完整正确），断在 preflight 派单（BUG-E2E-03：target=data-steward 无人可领，卡 preflight_running 17min+） | E2E-1/（审计链 118 事件导出、poll 日志） |
| E2E-2 | 参数契约 limit 边界 | 🟥 limit=101/200 被 `Query(ge=1,le=100)` 422 抹平，未按口径钳制 | E2E-2/ |
| E2E-3 | 未知领域（16S）显式 fallback | 🟩 立项卡 flow_label=「通用分析（未识别到领域专家，回退通用代码助手）」、confidence=ambiguous、lead_planner=agent-code，显式 fallback 无静默断链 | E2E-3/ |
| E2E-4 | 规划失败显式化 | ⬜ 未实测（注入 Bridge 故障会污染在跑的 E2E-1 Case）。代码走查：失败有 correction 自愈+`planning.validation_failed`+`waiting_for_correction`，不停在 received；但任务书口径的 `planning_failed` 事件名在 bridge 状态机中不存在（口径偏差） | E2E-4/result.md |
| E2E-5 | 删除对账 | 🟩 真实 Case 删除：200（cancelled_before_delete、deleted_events=119），平台 400/Bridge 404/MinIO 前缀清空，三侧一致。子场景「超时但后端已删」未注入；观察项：room-only 房间无删除路径（400） | E2E-5/ |
| E2E-6 | 气泡可见（前端渲染） | ⬜ 未覆盖渲染层（headless 无浏览器）。落库+event_id 对账形态经 E2E-7/11 真实事件导出佐证，前端替换逻辑有单测（frontend/src/views/__tests__/agent-teams-room-send.test.ts 等） | E2E-6/result.md |
| E2E-7 | hi 不建 Case | 🟩 无 Case、无立项卡、仅一条 Manager 回复（观察项：回复形态为 room.ask_user 选项卡而非纯文本气泡，且文案误称「当前 Case 处于已接收状态」） | E2E-7/ |
| E2E-8 | MinIO 恢复 + 损坏快照拒启动 | 🟩 三阶段全过：rm+重建 bridge 零状态损失（digest 不变）；改坏 snapshot.last_event_id 后拒启动 Exited(1)+RuntimeError 明示；回写后恢复 healthy | E2E-8/ |
| E2E-9 | 游标分页不重不漏、与 audit-chain 一致 | 🟥 不重不漏子项绿（7+7+6=20 条与 MinIO 持久流零重复）；但空页死循环——末页后 next_cursor 永不清空，连续 9 页 0 条+next_cursor 非空；audit-chain 比对子项被 BUG-02 阻断 | E2E-9/ |
| E2E-10 | 新链路物化（产物入项目目录） | 🟥 阻断：房间立项→Case 被 BUG-E2E-02 打断（confirm-proposal 恒 400）。旧路径（E2E-1）未到执行阶段（BUG-03），新旧路径一致性无法比对 | E2E-10/result.md |
| E2E-11 | 直答降级 | 🟨 半绿：正向直答绿（@agent-scrna → direct → room.agent_message 真实 LLM 直答，26.9s，direct_mention=true+causation 回链）；降级路径未实测（注册表无 diff 可注入、超时注入需改 worker 环境未做），降级代码路径走查存在（agentteams_room_response_service.py:350-382） | E2E-11/ |

## 发现的地基 bug（走主干 hotfix，本任务未改代码）

- **BUG-E2E-01**：POST /api/v1/agent-teams/rooms 恒 500（MissingGreenlet）。
  Matrix 建房成功回写 matrix_room_id 触发二次 flush（UPDATE），
  `TimestampMixin.updated_at` 的 `onupdate=func.now()` 使属性在 UPDATE 后被 expire，
  `_room_payload`（agentteams.py:687）同步读取触发懒加载 IO → 500 → 房间回滚。
  仅在 gateway 健康（走 Matrix 建房）时出现。详见 env/BUG-01-room-create-500.md。
  影响：平台层建房不可用（本任务用「容器内同 Service 调用 + commit」绕过，不改代码）。
- **BUG-E2E-02**：立项卡事件落 Bridge 但 `room.proposal` 永不落库——celery 任务
  `_respond_to_room_namespace_message`（infrastructure/celery_app/tasks/agentteams.py:112-137）
  `async with get_session_factory()() as db` 全程无 commit，persist_room_proposal 只 flush。
  后果：confirm-proposal 恒 400「立项确认令牌无效或已使用」（实测 E2E-9/confirm_proposal_400.json），
  房间→Case 链路断裂。详见 env/BUG-02-proposal-not-persisted.md。
- **BUG-E2E-03**：preflight 工作项 target 与 Worker identity 不匹配。
  bridge 硬编码 `target="data-steward"`（bridge service.py:1601，models.py:450 字面量限定），
  inbox 精确匹配 `work_item.target == target`（case_store.py:254），而生产 worker 池以
  canonical identity `agent-data` 轮询；alias 不过 bridge inbox。实测同 token：agent-data 收件箱 0 条、
  data-steward 收件箱 1 条（preflight-01 pending）。后果：所有走标准 preflight 的 Case 永久卡在
  preflight_running。同类 legacy target（workflow-operator/quality-auditor/delivery-reporter）建议一并排查。
  详见 env/BUG-03-preflight-target-mismatch.md。

## Hotfix 复验（2026-08-21 第二轮，5 项主干修复后）

修复侧：BUG-01/02/03 + E2E-2 钳制 + E2E-9 空页死循环，5 项全部主干 hotfix
（未提交，随 232 条工作树改动待分组提交）；平台单测 369 + bridge 175 全绿，ruff 无新增。

| 项 | 复验结果 | 证据 |
| --- | --- | --- |
| BUG-01 建房 500 | 🟩 live 复验通过 | env/BUG-01-fix-verify.md |
| BUG-02 立项卡不落库 | 🟩 live 复验通过：confirm 200 + case 绑定 + proposal consumed | env/BUG-02-fix-verify.md |
| BUG-03 preflight target | 🟩 端到端复验通过：Case `bioops_bug04verify87255328` 事件流实证 preflight-01 target=agent-data 且被专业池认领执行（planning.frozen → assigned → running） | env/BUG-03-fix-verify.md |
| E2E-2 limit 钳制 | 🟩 live 复验通过（101/200 不再 422） | 固化套件 |
| E2E-9 翻页终止 | 🟩 live 复验通过（末页 next_cursor 正常清空） | 固化套件 |
| 固化 live 套件 | 🟩 `test_live_foundation_e2e.py` 3/3 passed（28.8s，真实栈） | 本轮复跑 |
| E2E-1 链路重跑（规划→preflight→审批） | 🟩 Case `bioops_bug04verify87255328`：规划 3 次尝试内通过 → planning.frozen → preflight-01(agent-data) completed → approval_pending。审批后的执行/交付段本轮未跑（需真实审批触发计算任务） | env/BUG-03-fix-verify.md、env/BUG-04-planning-validation-stall.md |

复验新发现（BUG-04/05 已于第二轮 hotfix 修复，见各证据文档「修复」节）：

- **BUG-E2E-04**：规划会诊结构化输出 3/3 次校验自愈全败 → Case 停
  `waiting_for_correction` 无兜底推进。修复：planning 信封指令补流程型 TaskSpec
  完整骨架 + sample_sheet list 形态明示；修复后新 Case 第 3 次尝试通过校验并
  planning.frozen（单次样本，模型遵从性仍需更多观察）。
  详见 env/BUG-04-planning-validation-stall.md。
- **BUG-E2E-05**：worker agent 工具误用（case_id 传给期望 UUID 的
  task_result_summary、只读工具列目录失败）。修复：tool_bridge `_error()` 补顶层
  error 字段（事件流摘要保留真实原因）+ task_id 描述澄清；live success 标记疑点
  已如实登记。详见 env/BUG-05-agent-tool-misuse.md。

## 环境最终状态

- 第二轮复验后 docker ps 全量 Up（web/beat/worker/bridge 16 分钟前随 hotfix 重建，
  均 healthy；db/cache/minio/gateway/state/5 个 agentteams worker 等数据与基建容器未动）。
- E2E-8 的 bridge 重建测试结束后已恢复 healthy；损坏快照已回写恢复。
- 验收残留数据：测试房间若干（e2e-20260821-hi-test、16s-unknown-domain、delete-test、
  e2e-20260821-minio-021846 bridge case）与已删除的 E2E-1 case（三侧已清）。
  第二轮复验新增：房间 `492ca3ba192c4b279fceed69b49c3130`（BUG-02 复验，case bound）、
  Case `bioops_1d8f613fff294e36aae445cccdd17c34`（waiting_for_correction，BUG-04 现场保留）、
  Case `bioops_bug04verify87255328`（approval_pending，BUG-03/04 复验现场保留）。
  均为 e2e/hotfix 前缀测试数据，未触碰任何真实数据卷内容。
- 认证工件（临时，12h 自过期）：/tmp/e2e_token.txt、/tmp/e2e_bridge_token.env。

## 遗留问题

1. **Track B 验收轮未达标，hotfix 复验轮大部分转绿**：3 红 + 1 阻断红的修复均已落地并复验
   （见上节「Hotfix 复验」）；复验新发现的 BUG-04/05 已于同轮修复并复验，E2E-1 链路重跑
   贯通至 approval_pending；E2E-10「审批后执行/产物入项目目录」段本轮未跑（需真实审批
   触发计算任务），待补。
2. **流程 id 口径不一致（hotfix 复验中新发现，未改）**：房间立项卡 confirm 门闸
   `_assert_flow_allowed_for_room_case`（agentteams_room_service.py:129-136）只认
   白名单 `rna_seq,atac_seq,scrna_seq`（bridge_workflow id），而路由决策卡外发的是注册键
   `rnaseq/atacseq/scrna`（agentteams_route_decision.py:180）→ 域名命中的立项卡 confirm
   恒 400「该流程不在 AgentTeams Case 白名单中」。直建 Case 端点传 bridge id 不受影响。
   建议统一：门闸前把注册键映射到 bridge_workflow，或路由卡外发 bridge id。
3. **既有单测红 4 个（非 hotfix 引入，已用排除法确认与全部工作树改动无关）**：
   `test_agent_consultation_service.py` 的 3 个 evidence projection 用例（on_event
   协程未被 mock await，事件零投影）与 `test_tool_bridge.py::test_phylogenetic_tree_
   schema_uses_unified_page_entry`（断言文案与 tools_schema.yaml 现行描述不符），
   建议主干另行修复。
4. **BUG-03 修复刻意收缩**：仅 preflight 派单点做别名→canonical 解析；
   `workflow-operator` 不在 routable `role_agent_map`，走 `_standard_work_item_target`
   legacy_default 的派单仍有同类无人认领风险；quality/delivery/remediation 同类 alias
   未一并改（保持最小改动）；存量旧 target 工作项不追溯。
5. **CI 门禁未落地**：live 脚本已固化但默认 skip；「进 CI 默认执行」需要 CI 提供 compose
   真实栈矩阵（PG/Redis/MinIO/bridge/gateway/worker），属后续基础设施增强。
6. **E2E-4/E2E-6/E2E-11 降级路径**：需要故障注入手段（bridge 故障注入、直答超时开关、
   前端可截图环境）才能补测，建议主干补可测试性钩子。
7. **口径偏差待确认**：任务书 E2E-4 期望 `planning_failed` 事件，bridge 实现为
   `planning.validation_failed`+`waiting_for_correction`；room-only 房间无删除路径（E2E-5 观察项）；
   `room.response_timing` 在 direct 模式下 `response_status=failed` 与成功直答并存（E2E-11 观察项）；
   E2E-7 的 ask_user 选项卡形态与「仅一条对话回复」口径；BUG-04 修复后规划校验自愈成功率
   仅有单次样本，`waiting_for_correction` 无预算耗尽后的显式终态/人工升级兜底。
8. 工作树 232 个未提交改动导致 `/health` git_sha 无法反映实际运行代码，后续验收建议
   以「SHA + 工作树 diff 摘要」双因子记录镜像新鲜度。

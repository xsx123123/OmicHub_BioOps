# AgentTeams single-Case runtime forensics — 2026-08-19

## Evidentiary status

This is **not a successful historical Case extraction**. The Case ID and the authoritative Bridge audit/store snapshots are unavailable in the current environment; see `collection-attempt.md`. The only local material describing the incident is a prior static-review plan, not the underlying event stream. An adjacent retained-log workspace was also searched; its logs end on August 16, 2026 and contain only unrelated demo/test Cases. Therefore no event ID, timestamp, payload, or message ID below is fabricated.
Codex/Claude histories, browser history, and local container/database storage were also checked; see `collection-attempt.md` for the negative results.

Confidence labels:

- **Confirmed**: directly proved by an original runtime event/snapshot.
- **Highly suspected**: source mechanism matches a symptom, but this Case's runtime record is absent.
- **Insufficient evidence**: the required runtime record is absent.

## Single-Case evidence table

| event_id | recorded_at | business_at | event_type | actor | case_status | work_item_id | target | attempt | lease_expires_at | trace_id | context_refs | payload summary | frontend message ID |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| unavailable — UI snapshot | unavailable | `00:45` | UI-rendered user message | 我 | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable | unavailable | `image copy 9.png`: user enters the 6-sample mouse scRNA 3v3 request. | unavailable |
| unavailable — UI snapshot | unavailable | `02:02` | UI-rendered route decision | Manager | unavailable | unavailable | displayed planner: `agent-general`; selected option: `agent-scrna` | unavailable | unavailable | unavailable | unavailable | `image copy 16.png`: route is ambiguous/general while scRNA option is visibly selected. | unavailable |
| unavailable — UI snapshot | unavailable | `02:02` | UI-rendered dispatch | Manager | `规划中` | unavailable | `代码助手` | unavailable | unavailable | unavailable | unavailable | `image copy 17.png`: Manager dispatches to code assistant with inline clarification answers. | unavailable |
| unavailable — UI snapshot | unavailable | `09:56` | UI-rendered dispatch | Manager | `规划中` | unavailable | `代码助手` | unavailable | unavailable | unavailable | unavailable | `Screenshot 2026-08-19 at 09.58.24.png`: Manager dispatches to code assistant with four inline clarification answers. | unavailable |
| unavailable — UI snapshot | unavailable | `09:57` | UI-rendered worker progress | `代码助手` card headed `Manager` | unavailable | unavailable | unavailable | displayed round `2` | unavailable | unavailable | unavailable | `Screenshot 2026-08-19 at 09.58.24.png`: `读取文件 ×3`; `Worker 已进入下一轮分析（第 2 轮）`. | unavailable |

These rows are preserved **rendered UI observations**, not Bridge audit events: their event IDs, `recorded_at`, raw payloads, traces, work-item IDs, and frontend message IDs remain unavailable. The incident plan additionally reports (without preserving its original records) 09:57–09:58 no-progress/repair messages, 09:58 file-reference failure/apparent completion, and 11:07/11:12/11:17 lease expiry/retry messages. None can be promoted to an authoritative event-table row yet.

## Questions

### U-1 — repair input, output, and convergence

**结论：若本次 UI 所示的 `proposed_submission: null` 确实进入 Bridge 的计划验收回路，则具体校验错误会被写入下一次 `plan-01` 的 Planner 输入；但本次实际 repair 输入、两次模型输出和关联 trace 均未保留，不能把这一代码事实冒充为本 Case 的运行时证明。**

**代码原文（基线 `aad9d66`）：** Bridge 拒绝空 planner envelope：

```text
if proposed_submission is None:
    raise ValueError("planning consultation omitted proposed_submission")
```

at `integrations/agentteams/bridge/omichub_agentteams_bridge/service.py:1311-1319`. Its validation-failure handler constructs the next objective with the complete `str(exc)` error and writes it through `reset_planning_work_item()`:

```text
【计划校验反馈，第 {attempt}/{max_attempts} 次重试】
生成的计划未通过 schema 校验：{error_message}。
请修正以下字段后重新生成完整计划：{missing_fields or '（见错误描述）'}。
```

at `integrations/agentteams/bridge/omichub_agentteams_bridge/service.py:1418-1462`; `reset_planning_work_item()` replaces `plan-01.objective`, resets it to pending, clears its trace/output, and increments `planning_retry_count` at `integrations/agentteams/bridge/omichub_agentteams_bridge/case_store.py:398-445`. The UI string `自动修正计划…` is merely the projection of `correction_started` at `frontend/src/utils/agentTeamsRoom.ts:775-800`; it is not the repair prompt itself. `docs/info/26.8.19/Screenshot 2026-08-19 at 00.14.55.png` visibly contains `"proposed_submission": null`, which is a precursor observation but not a Bridge event.

**为何可能不收敛（仅机制推断）：** the reset preserves the same Case context but overwrites the work-item objective with corrective feedback; there is no captured proof that a new model response included the required envelope. The missing-envelope error also yields no structured `missing_fields` mapping in `_parse_missing_fields_from_validation_error()` (it falls through to `[]`), so the model relies on free-text error wording. A second non-convergent repair is therefore plausible, but not established for this Case.

**置信度：代码机制确认；本 Case repair 输入/输出与“不收敛原因”证据不足。**

### U-2 — “已根据你的授权自动批准” at 11:02

**结论：基线中该精确 UI 文案由 `case.auto_approved` 投影；可见的触发链路是定时 Celery auto-confirm 任务调用 `auto_approve_case_if_autonomous()`。本次究竟是否由该清理任务、同一服务的其他调用者，或错误投影触发，仍无事件证据。**

**Source evidence (baseline `aad9d66`):** `AgentTeamsService.auto_approve_case_if_autonomous()` records:

```text
event_type="case.auto_approved",
summary="已根据你的授权自动批准",
payload={"reason": "user_autonomy_autonomous"},
```

at `src/omichub/application/services/agentteams_service.py:426-464`. The periodic cleanup worker consumes a Redis-marked set, limits candidates to `approval_pending`, and invokes that method at `src/omichub/infrastructure/celery_app/tasks/agentteams.py:212-301`. The frontend maps `case.auto_approved` to the same literal at `frontend/src/utils/agentTeamsRoom.ts:890-897`.

**Baseline check:** an exact-string search of baseline `aad9d66` found no `skipped_manual_approval_required` occurrence. Therefore the cited “old auto-confirm entry fixed-returned that value” cannot itself be used as direct baseline evidence for this Case without the older commit/file snapshot that contained it.

**Required runtime proof:** a `case.auto_approved` event with its `actor`, `recorded_at`, and `payload.reason`; the Celery task log/trace; Redis set membership; and the preceding approval state event. Without them, it cannot be decided whether the cleaner, another caller of the same method, or a stale/misprojected frontend event produced the line.

**置信度：`case.auto_approved` 文案映射和候选清理路径确认；本 Case 实际调用者证据不足。**

### Q-1 — route consistency

**Conclusion: insufficient evidence for the Case values of `lead_planner`, `matched_hints`, `plan-01.target`, input text, or registry snapshot.**

**Source evidence:** route decision payload derives `lead_planner` and `matched_hints` from `explain_intent_route()` in `src/omichub/application/services/agentteams_route_decision.py:148-201`. The chat planning entry creates `plan-01` with a hard-coded target `agent-code` in `src/omichub/application/services/agentteams_service.py:611-645` (baseline). That static divergence is a plausible local hop, but it does not prove the observed route card's values or rule out HTTP/Bridge-side substitution.

**Required runtime proof:** `room.route_decision.payload`, the exact `room.user_message` content passed to routing, a serialized flow/capability registry version or snapshot, and Bridge `work_item.assigned`/Case snapshot for `plan-01`.

**Confidence: highly suspected that the local chat-planning entry can overwrite the displayed route; insufficient evidence for this Case.**

### Q-2 — clarification answers

**Conclusion: insufficient evidence to classify the four answers as user input, frontend defaults, cache replay, or missing events.**

**Source evidence:** the local model prompt requires structured `ask_user` options and allows recommended labels at `src/omichub/application/services/chat_service.py:1243-1253`; room Matrix input is recorded as `room.user_message` in `src/omichub/application/services/agentteams_room_sync_service.py:160-177` (baseline). Neither proves a user clicked an option.

**Required runtime proof:** the predecessor `room.ask_user` payload, Matrix event ID, original Matrix `m.room.message` event, and successor `room.user_message` event with a common room/session correlation identifier.

**Confidence: insufficient evidence.**

### Q-3 — `file://cb79a200-...` reference

**Conclusion: source code confirms how a UUID-shaped file/workspace context reference becomes `file://…`; the Case payload metadata and the planner/tool decision are unavailable.**

**Source evidence:** `integrations/agentteams/worker/production_runner.py:186-209` emits `file://{uuid}` for a `file` or `workspace` context reference whose `location` or `id` parses as a UUID. The worker prompt forwards the raw `context_refs` at lines `171-184`. The gateway declares `workspace_file_preview` in its worker capability configuration, but no event records the planner selecting it.

**Required runtime proof:** `plan-01`/worker assignment `context_refs`, the worker’s Gateway request (including selected tool and arguments), tool-result event, and any file-ID-to-path mapping record.

**Confidence: confirmed for source transformation; insufficient evidence for this Case's metadata and decision owner.**

### Q-4 — heartbeat and lease path

**Conclusion: the Bridge execution path is designed to start a lease-renewal task, but whether `wi_context_resolve` used that path is unproven.**

**Source evidence:** `claim_work_item()` audits `work_item.claimed` including attempt and trace ID; `heartbeat_work_item()` audits `worker.heartbeat` including `lease_expires_at`, attempt, trace ID, and worker ID (`integrations/agentteams/bridge/omichub_agentteams_bridge/service.py:756-803`). The execution method sends an initial heartbeat, then invokes `asyncio.create_task(self._renew_work_item_lease(...))` before Gateway consultation (`service.py:871-881`, baseline). The runner also emits an initial heartbeat before `execute_readonly_work_item()` (`integrations/agentteams/worker/production_runner.py:230-245`).

**Required runtime proof:** all `work_item.claimed`, `worker.heartbeat`, `work_item.lease_expired`, retry/timeout/sweep events for `wi_context_resolve`, plus worker/Bridge trace logs that show task creation, renewal success/failure, cancellation, and the worker identity. The currently available incident summary cannot establish a full time sequence or prove a bypass.

**Confidence: confirmed for source mechanism; insufficient evidence for this Case.**

### Q-5 — state projection and time ordering

**Conclusion: insufficient evidence to distinguish delayed writes, clock error, tie-break, or mixed time fields for the `09:58` and `11:17` display.**

**Source evidence:** the projector maps `work_item.finished` to a succeeded task and turns `skill.finished` into a completed progress state (`src/omichub/application/services/case_room_projector.py:40-93`), while lease expiry is mapped back to pending (`:41-54`). The UI event projection maps `case.auto_approved` to its literal message (`frontend/src/utils/agentTeamsRoom.ts:1077-1082`). These mechanisms do not expose a guaranteed business-time field.

**Required runtime proof:** raw events with `recorded_at`, payload business-time candidates (`occurred_at`, `created_at`, and worker timestamps), raw room/matrix message timestamps, and the frontend event order before grouping. The required collector normalizes these values without overwriting raw JSON.

**Confidence: insufficient evidence.**

## Evidence gaps / required instrumentation

1. Preserve Bridge audit events durably and export `event_id`, `recorded_at`, actor, case/work-item status, target, attempt, lease expiry, trace ID, context refs, and raw payload.
2. Record repair attempts as redacted structured events: validator error list, prompt hash/body, model response hash/body, parser result, attempt number, and shared trace ID.
3. Emit one immutable routing event containing input message ID/text hash, registry versions/snapshots, selected `lead_planner`, hints, and the dispatched `plan-01.target`.
4. Correlate `room.ask_user`, Matrix/UI delivery, original user reply, parsed answer source, and downstream dispatch with IDs rather than rendered prose.
5. Audit context-ref conversion and each tool choice: original ref object, resolved filesystem target or failure code, tool name/arguments/result hash, and planner/worker owner.
6. Audit lease lifecycle: claim, first heartbeat, renewal task started/stopped, each renewal result/error, sweep decision, retry, timeout, and all relevant monotonic/business/recorded timestamps under one trace ID.
7. Preserve projector input event ID and emitted frontend message ID/timestamp; make the UI expose both event `recorded_at` and business time rather than a derived label only.

## Retained UI snapshot evidence

The following files are retained in the repository. They are **rendered UI snapshots**, not Bridge audit events: they establish what was visible to an operator but do not supply `event_id`, raw payload, trace ID, or a Case identifier. They must not be treated as a substitute for raw events.

Their source paths and SHA-256 values are recorded in `evidence/agentteams-case-forensics-20260819/screenshot-integrity.md`.

| Snapshot | Visible original evidence | Evidentiary use / limit |
| --- | --- | --- |
| `docs/info/26.8.19/image copy 9.png` | User message at `00:45`: `我有6个样本的小鼠单细胞数据，分为两个group 3v3 我想要找到不同group间的细胞类型差异和差异基因，如果能够找到稀有细胞类型就更好了` | Confirms the user-input wording visible in this captured UI; no Case ID or event ID. |
| `docs/info/26.8.19/Screenshot 2026-08-19 at 00.14.55.png` | Manager’s structured display contains `"proposed_submission": null`, `"artifacts": []`, `"hard_gate": null`, and a four-question `ask_user` list. | Confirms an observed planner/consultation display emitted a null envelope before/with clarification; it does not prove a later Bridge validation error or repair request. |
| `docs/info/26.8.19/Screenshot 2026-08-19 at 00.15.09.png` | First `ask_user` card, marked `1/4`, asks data format / annotation status and presents four options. | Confirms the UI had a structured choice card, not that a selected answer came from a user event. |
| `docs/info/26.8.19/image copy 16.png` | At `02:02`, text says `路由待确认: 存在多种可能路径（倾向「通用分析」· 规划者 agent-general），请点选裁决`; the option `单细胞转录组分析（规划者 agent-scrna · 3 个阶段）` is visibly selected. | Confirms the displayed route card can simultaneously favor general analysis and visibly select scRNA. No click event or dispatch payload is present. |
| `docs/info/26.8.19/image copy 17.png` | At `02:02`, UI says `Manager 将任务分派给 代码助手` and embeds `【澄清回复】`: FASTQ-only; annotation unfinished; files not uploaded. It then shows `Case 状态更新：规划中` and `代码助手` starting plan generation. | Confirms visible card/dispatch mismatch and auto-populated-looking clarification text in a captured UI. It does not identify answer provenance or Bridge work-item target. |
| `docs/info/26.8.19/Screenshot 2026-08-19 at 09.58.24.png` | At `09:56`, a Manager timeline line says `将任务分派给 代码助手` with four inline clarification answers; the Case status line says `规划中`. At `09:57`, the code-assistant card shows `读取文件 ×3` and `Worker 已进入下一轮分析（第 2 轮）`. | Strongest retained visual corroboration for the reported 09:56–09:57 symptoms. It still has no raw event fields, result bodies, or Case identifier. |

### Consequences for the required questions

- **U-1:** the snapshot with `proposed_submission: null` is direct UI evidence of a null displayed envelope, but does not expose a schema validator error, repair prompt, or either repair response. **Confidence remains insufficient evidence** for the requested repair-chain conclusion.
- **U-2:** none of the retained screenshots contains the `已根据你的授权自动批准` line or an event actor. **Confidence remains insufficient evidence** for the actual releasing caller.
- **Q-1:** the route card / code-assistant dispatch mismatch is now **confirmed as a rendered UI observation**. The hop producing it remains unproven without `room.route_decision` and `work_item.assigned` payloads. **Confidence: confirmed for the UI mismatch; insufficient evidence for the hop.**
- **Q-2:** the inline clarification answers are now **confirmed as rendered content**, and the earlier UI proves an option-style `ask_user` card existed. There is no user-reply event or click record. **Confidence: confirmed for display; insufficient evidence for provenance.**
- **Q-3:** no retained snapshot shows `file://cb79a200-…` metadata or a tool-call argument. **Confidence remains insufficient evidence** for the Case-specific reference path.
- **Q-4:** the `读取文件 ×3` / round-two UI card is evidence of repeated rendered worker activity, not claim/heartbeat/sweep records. **Confidence remains insufficient evidence** for the lease timeline.
- **Q-5:** rendered timestamps are now preserved (`09:56`, `09:57`, `02:02`, etc.), but there is no screenshot containing both the reported `09:58` completion and post-`11:17` approval placement, and no raw `recorded_at`/business-time pair. **Confidence remains insufficient evidence.**

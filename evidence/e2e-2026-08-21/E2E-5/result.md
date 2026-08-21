# E2E-5 删除对账 —— 绿（主路径），子场景与观察项备注

## 验收口径（任务书 2.2）

> 删除聊天室（含"超时但后端已删"场景）→ 期望：前端最终状态与 Bridge 一致；证据：双侧日志。

## 实测：真实 Case 删除（绿）

对象：E2E-1 收尾后的 Case `bioops_20272b2afce74d728ebe0e204bece70c`（卡 preflight_running，118 事件已提前导出至 `../E2E-1/case_events_export.json`）。

| 步骤 | 结果 | 证据 |
| --- | --- | --- |
| 删除前平台侧 GET | 200，status=preflight_running | `platform_case_before.json` |
| 删除前 Bridge 侧 GET | 200 | `bridge_case_before_delete_real.json` |
| `DELETE /api/v1/agent-teams/cases/{id}` | 200，`{"deleted":true,"cancelled_before_delete":true,"deleted_events":119}` | `delete_response.txt` |
| 删除后平台侧 GET | 400「协作案例不存在」 | `platform_case_after.txt` |
| 删除后 Bridge 侧 GET | 404「Case not found」 | `bridge_case_after.txt` |
| 删除后 MinIO `cases/{id}/` 前缀 | 对象列表为空（snapshot+audit 均清除） | 实测输出（bridge 容器内 minio list） |

进行中 Case 删除时先取消再删除（`cancelled_before_delete:true`），平台/Bridge/MinIO 三侧一致，对账绿。

## 未覆盖子场景

- 「超时但后端已删」需给 bridge 删除路径注入超时，未执行（避免动运行中配置）。
- 前端最终状态无法截图（headless 环境），以后端双侧 API + MinIO 对账代替。

## 观察项

- 房间入口建的「纯房间」（无 bridge Case，如 `a2725c4a9f56434eb155db210241287b`）走同一删除端点返回
  400「协作案例不存在」（`delete_room_only_attempt.json`）——平台层未给 room-only 房间提供删除路径，
  前端房间列表的删除动作对该类房间不可用，建议主干补房间删除端点或明确产品口径。

## 结论

🟩 绿（真实 Case 删除三侧一致）；子场景与 room-only 房间删除口径留观察项。

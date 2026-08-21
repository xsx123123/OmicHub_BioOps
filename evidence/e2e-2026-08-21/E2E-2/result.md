# E2E-2 参数契约（events 端点 limit 边界）结果：红

期望（任务书）：limit 超界时「钳制到 100 或分页拉取，无 422 抹平」。
实测（GET /api/v1/agent-teams/rooms/{id}/events，2026-08-21 重建后栈）：

| limit | HTTP | 返回事件数 |
| --- | --- | --- |
| 1 | 200 | 1 |
| 100 | 200 | 70（全量） |
| 101 | 422 | - |
| 200 | 422 | - |
| 0 | 422 | - |
| -1 | 422 | - |

- 超上界 limit=101/200 被 FastAPI `Query(ge=1, le=100)` 直接 422（limit_200_response.json），
  未做钳制；与任务书验收口径不符，判红。
- 相关代码：src/omichub/api/v1/agentteams.py get_room_events `limit: Query(ge=1, le=100)`。
- 修复方向（主干 hotfix）：去掉硬 le=100 422，改为 min(limit,100) 钳制 + next_cursor 分页提示。

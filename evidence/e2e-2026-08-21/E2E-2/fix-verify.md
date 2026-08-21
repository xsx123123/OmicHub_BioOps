# E2E-2 修复复验：limit 超上界 422 → 钳制到 100

## 根因（一句话）
`GET /rooms/{id}/events` 的 `limit: Query(ge=1, le=100)` 把超限请求直接 422，
调用方无法拉取更多事件，也没有钳制或分页提示。

## 修复
- `src/omichub/api/v1/agentteams.py:801` `Query(ge=1, le=100)` → `Query(ge=1)`；
- `src/omichub/api/v1/agentteams.py:808` handler 内 `limit=min(limit, 100)` 钳制。
- 只改 rooms events 端点；cases events 端点与 Bridge 硬上限未动。

## 回归测试
- `tests/unit/test_agentteams_rooms.py` 末尾新增钳制用例（limit=101/200 → 按 100 处理）。

## 真实栈复验（2026-08-21 03:23 +0800）
房间 `492ca3ba192c4b279fceed69b49c3130`：
- `GET .../events?limit=101` → **HTTP 200**（修复前 422），8 条事件，next_cursor=None；
- `GET .../events?limit=200` → **HTTP 200**，同上。
- 响应体见本目录 `fix_verify_limit_101.json` / `fix_verify_limit_200.json`。

## 固化 live 回归
`tests/e2e/agentteams/test_live_foundation_e2e.py::test_live_e2e2_events_limit_boundary`
绿（套件 3 passed）。

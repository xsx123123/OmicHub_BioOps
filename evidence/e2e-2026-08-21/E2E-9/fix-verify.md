# E2E-9 修复复验：游标翻页可终止、不重不漏

## 根因（一句话）
`get_room_events` 的 `next_cursor` 只看「聚合前两流是否取满 limit」，末页两流
均不足 limit 但合并后恰好等于 limit 时会发出指向空页的陈旧游标，调用方
永远翻不到终点（空页带游标死循环）。

## 修复
- `src/omichub/application/services/agentteams_room_service.py:271-273`
  `next_cursor = None if len(kept) < limit else "ns:...|case:..."`
  （按截断后实际保留数判停，A2 不重不漏语义不变）。

## 回归测试
- `tests/unit/test_agentteams_rooms.py` 末尾新增两个终止性用例
  （末页短板 → 游标 None；满页 → 游标继续推进）。

## 真实栈复验（2026-08-21 03:23 +0800）
房间 `492ca3ba192c4b279fceed69b49c3130`（共 8 条聚合事件），limit=3 翻页：

```
page1: n=3 next_cursor=set
page2: n=3 next_cursor=set
page3: n=2 next_cursor=None
total unique events: 8 / 8
```

末页短板后游标为 None、无空页带游标、全程不重不漏。
轨迹另存 `fix_verify_pagination.txt`。

## 固化 live 回归
`tests/e2e/agentteams/test_live_foundation_e2e.py::test_live_e2e9_cursor_pagination_no_dup_no_missing`
绿（套件 3 passed）。

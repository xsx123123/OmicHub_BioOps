# Chat Runtime Golden Records

此目录用于保存各 Runtime 的真实 SSE 基线。记录前先用
`cygnusx.application.services.chat.golden_records.normalize_events()` 去除时间戳、会话 ID、
运行 ID 与消息 ID；迁移后的同一请求必须通过 `diff_events()` 产出空差异。

每条基线应关联一个可复现请求，并覆盖文本、工具调用、`ask_user` 与错误路径。受限的
MAS/AgentTeams 流程由其所有者单独录制；本次 Runtime 拆分不修改这些流程。

## 双跑报告

测试环境中，对同一请求分别构造旧路径与候选 Runtime 的异步流工厂，并调用
`cygnusx.application.services.chat.dual_run.compare_streams()`。已有 JSON 基线时，调用
`compare_golden_record()`；通过 `write_report()` 将双方归一化事件、语义差异和耗时写入
报告。CI 使用 `assert_equivalent()` 将任何未评审差异作为门禁失败。

双跑会执行两次请求，应仅在隔离的测试数据、可重置的会话或只读场景使用；禁止直接对生产
会话双写。报告不包含时间戳、运行 ID、会话 ID 或消息 ID，因此可稳定审阅与版本控制。

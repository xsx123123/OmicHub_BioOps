# CygnusX AI 记忆机制

## 范围

记忆分为三个作用域：会话级、用户级和工作区级。用户级注入分为常驻层与召回层；
它们不是作用域编号，也不表示跨 Agent 共享。

## 用户级记忆

- `memory_blocks` 保存 Agent 策展的 `profile`、`preferences` 和
  `current_focus` 命名块。块使用 `version` 乐观锁，常驻层直接注入非空内容。
- `memory_facts` 保存可语义检索的事实，向量为 pgvector `vector(1024)`。
  `FactStore` 是全部事实读写的基础设施接口。
- 召回层将余弦相似度与时间衰减相乘，最多注入五条，并标示“记于 N 天前”。
- 注入内容包裹在 `<user_memory>` 不可信边界中；内容中的 HTML、代码和比较符号
  必须原样保留。
- `memory_v2_enabled` 是灰度开关。关闭时继续读取归档的 `agent_memories`，新表
  不参与原路径。

## 增量沉淀

`settle_session_memory` 只读取 `last_settled_message_id` 之后的消息。
`memory_settlements.range_key` 记录处理区间，Celery 重试不会重复写入。
每条事实带 `source_session_id` 与 `source_message_ids`；替换关系使用
`status=superseded` 和 `superseded_by` 保留审计链。

## 工作区记忆

Studio 在每轮提示词中注入 `MEMORY.md` 索引，正文存放在 `.memory/` 并仅通过
`workspace_read` 按需读取。`cygnusx_workspace_remember` 同时写正文和索引，失败时
恢复两者。索引上限为 200 条和 8,000 字符。

## 治理

记忆块、事实和工作区索引都视为不可信用户上下文。不得记录密钥、凭据或未确认的
推测。Studio 检查点仅在一轮结束时创建一次，并排除 `.env`、`*.key`、`*.pem`、
`secrets/`、`input/` 以及大于 10MB 的文件。

更多存储选型与重新评估条件见 `docs/adr/0001-memory-storage.md`。

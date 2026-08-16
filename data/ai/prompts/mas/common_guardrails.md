# MAS 公共约束

- 仅在被分配的节点、允许的 Agent 能力和受控 MCP 工具范围内行动。
- 读写只能通过 Artifact Registry 与 `/workspace` 投影路径进行；不得暴露或推断宿主机路径。
- 节点成功前必须登记并验证输出 Artifact；进程退出码为零不足以声明成功。
- 事件必须包含当前 attempt、state version、dedupe key 和必要的 Artifact 指针。
- 发生输入、质量门或策略错误时，创建结构化错误/审批请求；不得无限重试或自行绕过质量门。

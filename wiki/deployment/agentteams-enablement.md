# 开启 Multi-Agent 与 AgentTeams

CygnusX 的多 Agent 能力分两层：**平台内 Multi-Agent**（意图路由 + 多专家会诊 + 子 Agent 扇出）与
**AgentTeams 协作室**（Bridge/Gateway/Worker 独立栈，Manager 编排领域专家 Agent）。两层均默认关闭，
按需灰度启用。

## 平台内 Multi-Agent

在 `.env` 中按顺序开启，并验证配额与延迟后再进入下一层：

```bash
UNIFIED_INTENT_ROUTER_ENABLED=true    # 统一意图路由
MULTI_EXPERT_CONSULTATION_ENABLED=true  # 多专家会诊
SUBAGENT_FANOUT_ENABLED=true          # 子 Agent 扇出（确认配额与延迟后再开）
```

## AgentTeams Bridge

1. 复制 `deploy/agentteams/bridge.env.example` 与 `worker.env.example`。
2. 为 Manager、Approval、Workflow Operator 与各专家身份（对应 `data/CygnusX.yaml` 启用的内置 Agent）
   设置**不同的随机令牌**。
3. 执行预检：

```bash
deploy/agentteams/check_setup.sh deploy/agentteams/bridge.env
```

4. 预检通过后在 `.env` 中置 `AGENTTEAMS_BRIDGE_ENABLED=true`、`AGENTTEAMS_CHAT_ENTRY_ENABLED=true`，
   填入 Bridge URL 与角色令牌，拉起栈：

```bash
make docker-up-agentteams
```

可用 `make agentteams-worker-env` 从 Bridge 配置生成最小权限 Worker 令牌文件；Bridge 测试工程用
`make test-bridge`。

## 本机开发 Matrix 栈

开发调试协作室聊天入口时，可用 `make docker-up-matrix-dev` 拉起本机 Matrix(Synapse)+Element 栈。

> ⚠️ 不要在 `.env`、`bridge.env`、README 或日志中保存真实密钥与令牌；泄露后立即撤销轮换。
> AgentTeams 组件不应默认暴露到公网。

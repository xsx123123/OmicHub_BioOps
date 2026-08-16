# 单细胞 Multi-Agent 与 AgentTeams 配置

## 架构边界

- `data/ai/scrna_upstream.yaml`、`data/ai/scrna_integration.yaml`、`data/ai/scrna_advanced.yaml` 是 AI 助手中的三个单细胞专家；路由器优先使用流程 YAML 的阶段提示词把问题交给对应专家。
- `data/ai/flows/scrna.yaml` 是单细胞受控分析流程的唯一注册入口，声明三段 DAG、artifact、executor、只读审查和审批 gate。
- AgentTeams 仍只使用 `agent-scrna` 这个受限 identity；`upstream-review`、`integration-review`、`annotation-review` 只是只读审查 skill，不能运行 Cell Ranger、Shell、Docker 或写入 artifact。
- MAS 才能执行计算任务。AgentTeams 只提供建议、证据、风险、审批与可追溯交付，不改变 Case/Run 状态机。

## 启用顺序

1. 在主服务环境中设置 `AGENTTEAMS_CHAT_ENTRY_ENABLED=true`、`UNIFIED_INTENT_ROUTER_ENABLED=true`，并配置 Bridge 凭证。
2. 将 `AGENTTEAMS_CHAT_FLOW_WHITELIST` 保持包含 `scrna_seq`；流程注册表也会从 `data/ai/flows/*.yaml` 自动派生这个入口。
3. 在 Bridge 环境中设置 `BRIDGE_ALLOWED_FLOW_IDS=rna_seq,scrna_seq`。Bridge 与主服务需要同时允许，才可创建单细胞协作 Case。
4. 配置并运行 `agent-scrna` Worker。不要为每个流程阶段创建额外的 Bridge identity；阶段拆分应使用不同 review skill 和 work item，避免扩大权限面。

## 新增或扩展流程

1. 在 `data/ai/flows/_shared/` 定义可复用的资源档位、重试策略、审批模板和 artifact 类型。
2. 新建 `data/ai/flows/{flow_id}.yaml`，声明 `flow`、`artifacts`、`stages`、`edges`、`delivery`。
3. 每个 `review` 固定 `boundary: read_only`。出现 `shell`、`docker`、`file_write`、`workflow_submit` 或数据库写入能力时，注册表会拒绝加载。
4. 改名已有 artifact 时，把旧名称放入新 artifact 的 `aliases`；若声明了 `flow.previous_artifacts`，未映射的旧 artifact 会在加载期失败。
5. 提供 executor 实现后，MAS 计划使用 `resources.executor` 指向 YAML executor。计划校验会核对 actor、输入与输出 artifact 契约。

## 验证

运行：

```bash
PYTHONPATH=src .venv/bin/pytest -q tests/unit/test_flow_registry.py
```

注册表对每个流程计算规范化 YAML 的 SHA-256 digest，可通过 `FlowRegistry.get(flow_id).digest` 读取并写入后续 Run 审计记录。

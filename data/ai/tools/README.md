# Agent 工具包

`data/ai/tools/*.yaml` 是**声明式绑定层**：一个 Agent 在其 YAML 中通过
`tool_packs: [workspace, research]` 引用工具包，加载器会把其中的工具合并到该 Agent。

```yaml
id: my-analysis-pack
description: 给 RNA-seq Agent 使用的工具集合。
builtin_tools:
  - omichub_run_kegg_enrichment
platform_tools:
  - list_workspace_files
  - search_workspace_files
mcp_ids:
  - "<已注册外部 MCP server UUID>"
mcp_tools:
  "<已注册外部 MCP server UUID>":
    - tool_name_one
skill_ids:
  - my-skill-id
```

- `builtin_tools`：来自 `tool_configs/tools_schema.yaml` 的 OmicHub 内置函数名。
- `platform_tools`：来自内置 `omichub-platform` MCP 的受限平台工具名。
- `mcp_ids` / `mcp_tools`：绑定已注册 MCP Server；提供 `mcp_tools` 时只暴露白名单中的函数。
- `skill_ids`：绑定已启用的 Skill。

YAML 不直接执行任意 Python/Bash 脚本。新增自定义脚本时，先按现有 MCP 或
`tool_configs/tools_schema.yaml` 注册为受审核工具，再通过这里的 YAML 选择性授权给 Agent；
这样可以保留参数 schema、用户权限、审计与确认闸门。

`memory.yaml` 是跨会话长期记忆工具包。它只授予确有研究上下文需求的 Agent，且工具调用始终
从认证上下文取得 `user_id`，不能由模型参数指定其他用户。

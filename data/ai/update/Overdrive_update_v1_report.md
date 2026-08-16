# Overdrive 超频模式 v1 — Manager 真规划改造交付报告

> 审计日期：2026-08-11  
> 当前状态：代码与离线验证完成；live Docker/DB 运行态验收被 Codex 沙箱权限阻塞（连续三轮复核）。

## 1. 实施结果

| 施工项 | 状态 | 实现证据 |
|---|---|---|
| P0-1 配置开关 | 已完成 | `Settings.overdrive_authoritative_mode` 支持 `constraint/override/off`；`overdrive_plan_repair_enabled` 默认开启；`.env.example` 已同步。 |
| P0-3 schema 扩展 | 已完成 | `AssignmentRule` 增加 `required/allow_split/allow_reorder`；旧包默认兼容；非法类型由 Pydantic 严格报错并记录 loader error。 |
| P0-2 约束式规划 | 已完成 | 权威规则转为锚点校验；覆盖覆盖性、顺序、Agent 能力、输入输出契约；一次修复失败后 `rule_merge` 保留非冲突 LLM 任务。 |
| P0-4 话术诚实化 | 已完成 | 删除领域固定链、已有树固定话术和默认分工模板；preflight 标记 `rule_preflight`；Manager 异常记录错误并使用中性话术。 |
| P1-1 规划遥测 | 已完成 | Redis hash 记录 mode、repair outcome、speech override 哨兵；提供 1–30 日汇总查询。 |
| P1-2 prompt 升级 | 已完成 | 注入 `{authoritative_anchors}`；允许大规模 shard 并行；要求 speech 与实际 assignments 一致。 |
| P1-3 前端来源标记 | 已完成 | `llm/llm_repaired/rule_*` 映射来源标签；未知历史来源不伪装为 AI 规划。 |

## 2. 双执行路径审计

执行：

```bash
grep -rn 'authoritative_only\|OVERDRIVE_MANAGER_PROMPT\|_default_overdrive_assignments' src/omichub --include='*.py' | grep -v test
```

所有命中均位于 `chat_service.py` 的同一冻结计划前入口。LangGraph 与 legacy worker 分叉发生在该计划已构建/冻结之后，两条路径共用本次改造后的 Manager 规划结果；未发现第二处等价的 authoritative assignments 覆盖逻辑。

## 3. 离线验证证据

### 后端专项

```text
26 passed
```

覆盖：

- 配置默认值；
- DomainPack 新字段默认兼容与非法字段报错；
- 20/200 输入规模所需的锚点与 shard 约束；
- `off` 保留 LLM 计划；
- `override` 替换 assignments 且不覆盖 LLM speech；
- 修复成功 `llm_repaired`；
- 修复失败触发第二次调用并 `rule_merge`；
- Manager provider 异常的审计与中性降级；
- preflight 的 `rule_preflight` metadata；
- 10 次遥测 mode 分布和 speech override 恒 0。

### 前端

```text
PlanConfirmationCard: 6 passed
vue-tsc -b: passed
vite build: passed
```

覆盖 `llm`、`llm_repaired`、`rule_merge` 三种来源标签，以及历史消息缺少来源时不误标。

### 静态检查

```text
ruff: passed
git diff --check: passed
```

业务代码 grep 不再包含以下旧话术：

- `已按系统发育领域契约固定执行链`
- `我会按任务所需的最小专家集合直接处理`
- `已确认这是已有系统发育树的处理与美化任务`

### Live 验收工具

新增 `scripts/verify_overdrive_manager_planning.py`，可在 Web 容器内直接读取
Postgres 与 Redis，自动检查：

- 用户消息到 Manager 规划消息的 `created_at` 延迟；
- `planning_mode` 合法性；
- 禁用模板话术；
- homolog-search → phylogeny 锚点与依赖；
- 200 基因组场景的 shard/分片/并行设计；
- Redis mode 分布和 speech override 哨兵。

## 4. 规格歧义说明

规格同时要求：

1. speech 在任何模式下不得被规则覆盖；
2. `override` 模式与旧行为“逐字节一致”。

旧行为包含硬编码领域 speech，因此两项无法同时逐字节成立。本实现遵守任务行为红线：`override` 恢复旧的 assignments 整体替换能力，但仍保留 LLM 原始 speech，不恢复已禁止的模板话术。

## 5. 尚缺的 live 验收证据

当前 Codex 沙箱禁止访问 `/var/run/docker.sock`：

```text
Operation not permitted / permission denied
```

同时宿主机没有暴露可访问的 Web、Postgres 或 Redis 端口，因此以下证据当前无法生成：

- `docker restart omichub-web` 后的新进程代码加载证明；
- 真实发送 20 基因组与 200 基因组请求；
- `chat_messages.created_at` 用户/助手间隔达到数百毫秒；
- live Redis 中 10 次 mode 分布；
- 计划确认后完整建树 Case 端到端。

## 6. 获得 Docker 权限后的验收步骤

```bash
# 1. 后端代码加载
docker restart omichub-web

# 2. 若修改了真实 .env 中的 OVERDRIVE_* 值，必须重建而非 restart
cd deploy/docker
docker compose --env-file ../../.env -p omichub up -d web

# 3. 分别发送新会话请求
# - TnpD 对 20 个基因组建树（提供真实 query/genome 输入）
# - 对 200 个基因组做同样分析

# 4. 查询对应 chat_messages，比较用户消息和 Manager 回复 created_at
# 5. 查询 Redis omichub:overdrive:planning:<UTC-date> hash
# 6. override 回滚验证后恢复 constraint

# 可用以下命令自动完成第 4–5 步与计划锚点检查：
docker exec omichub-web python scripts/verify_overdrive_manager_planning.py \
  --session-id <20-genome-session-id> \
  --session-id <200-genome-session-id> \
  --sharded-session-id <200-genome-session-id> \
  --check-redis
```

验收判定：20 基因组计划包含 `tnpd-homolog-search -> tnpd-phylogeny`；200 基因组计划增加 shard/并行且锚点顺序不变；新消息不出现旧模板；DB 时间差为真实 LLM 往返量级；端到端计划可确认并执行。

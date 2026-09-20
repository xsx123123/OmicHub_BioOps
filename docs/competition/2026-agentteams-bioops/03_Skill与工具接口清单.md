# Skill、工具接口与复用设计

## 1. 设计原则

- **Skill 是能力抽象层：** 一个 Skill 对应一个稳定、可验证的业务动作，不将一次性提示词包装成 Skill。
- **Bridge/MCP 是连接层：** 当前主链路由独立 REST Bridge 提供等价工具契约；协议、鉴权、输入输出、失败处理、幂等和审计均已定义，后续可适配为 MCP server 而不改变角色与业务链路。
- **验证不交给模型：** 流程成功、Artifact 完整和 QC 放行由任务状态、结构化指标、规则版本和审计记录判定。
- **每项动作有失败语义：** `blocked`、`manual_review`、`failed` 与可重试错误必须区分，禁止无限重试和静默降级。

## 2. 核心 Skill 清单

| Skill | Agent | 用途 | 输入 | 输出 | 调用条件 | 依赖工具/协议 | 失败处理 | 安全边界与复用价值 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `project-preflight` | `agent-data`（新增） | 校验项目是否具备可执行条件 | project ID、样本表、分组、物种、参考版本、流程配置摘要 | `passed` / `blocked`、缺失项、预检证据 | Case 创建后、任务提交前 | `POST /projects/{project_id}/preflight` | 返回 `blocked`，绝不提交任务 | 只读；可复用于任何组学流程或企业数据项目。 |
| `workflow-submit` | 已分派的领域执行 Agent（现有） | 提交已批准的同模态工作流 | approval token、idempotency key、allowed flow、项目/任务参数 | task ID、提交证据、初始状态 | 预检通过且人工审批完成 | `POST /tasks` | 上游瞬时错误仅使用同一幂等键重试 | 无流程 YAML/shell；复用现有 RNA-seq、ATAC-seq、scRNA Agent。 |
| `workflow-monitor` | 已分派的领域执行 Agent（现有） | 查询任务进度、摘要和异常 | task ID | 状态、阶段、资源/超时摘要、Artifact 引用 | 任务已提交 | `GET /tasks/{task_id}` | 超时如实报告，禁止自动加大资源 | 只读；可复用于异步计算、审批流和外部作业。 |
| `workflow-cancel` | 已分派的领域执行 Agent（现有） | 在必要时安全取消任务 | task ID、approval token、原因 | 幂等取消记录 | 用户或授权人明确取消 | `POST /tasks/{task_id}/cancel` | 幂等记录原因；不删除历史证据 | 需审批；适用于所有会产生资源消耗的长任务。 |
| `quality-gate` | `agent-qc`（新增） | 按规则核验任务、产物与质量指标 | task ID、Artifact 引用、QC 规则版本 | `passed` / `failed` / `manual_review`、质量决策 | 上游任务终态且产物登记完成 | `GET /tasks/{task_id}`、`GET /tasks/{task_id}/artifacts` | 无规则版本时进入 `manual_review` | 只读、只接受逻辑 `omic://` 引用；可扩展为不同分析类型质量门。 |
| `delivery-pack` | `agent-delivery`（新增） | 生成受控交付清单与证据索引 | case ID、已验证 Artifact、质量决策、参数/风险摘要 | Delivery Manifest、runbook、证据事件 | 质量门通过或人工复核签字 | `POST /cases/{case_id}/evidence` | 缺少必需 Artifact 时阻断交付 | 仅证据/manifest；可复用于客户交付和合规归档。 |
| `scientific-interpretation` | `agent-general` / 领域专家（现有） | 对已验证结果进行带证据的科学解释 | case ID、agent ID、问题、能力、引用证据 | 结论、建议、证据、风险、不确定性、耗时/成本 | 结果已存在且需要解读 | `POST /v1/scientific-interpretation` | 返回 `manual_review` 或结构化拒绝；不越权执行操作 | 网关 allowlist 只读能力；带超时、次数、token 预算。 |
| `code-review` / `visualization-review` | Code / Viz Agent | 审查复现脚本、图表规范和交付质量 | Work Item、逻辑 Artifact、审查问题 | `blocked`/`failed`/审查证据 | Manager 需要专业审查时 | Work Item claim/update API | 仅返回证据，不执行代码/渲染图表 | 只读；可沉淀为跨流程通用审查 Skill。 |

## 3. 输入输出契约示例

### 3.1 `workflow-submit`

```json
{
  "case_id": "case_20260808_001",
  "project_ref": "omic://projects/demo-rnaseq-001",
  "allowed_flow": "rnaseq",
  "approval_token": "short-lived-scoped-token",
  "idempotency_key": "case_20260808_001.submit.v1",
  "parameters_ref": "omic://artifacts/project-preflight/manifest.json"
}
```

成功响应必须包含逻辑 `task_id`、当前状态、关联 trace 和提交 evidence reference；失败响应必须区分鉴权/审批错误、参数错误、上游瞬时异常、配额/资源错误与策略拒绝。重复调用相同幂等键不得创建第二个计算任务。

### 3.2 `quality-gate`

```json
{
  "case_id": "case_20260808_001",
  "task_id": "task_demo_001",
  "artifacts": [
    "omic://artifacts/task_demo_001/qc-report",
    "omic://artifacts/task_demo_001/count-matrix",
    "omic://artifacts/task_demo_001/deg-results"
  ],
  "rule_version": "rnaseq-qc-1.0.0"
}
```

响应包含 `decision`、`reason_codes`、`metrics_summary`、`rule_version`、`evidence_refs`。若 Artifact 类型不全、规则不存在或指标无法解析，必须返回 `manual_review` 或 `failed`，不能仅凭自然语言推断为成功。

## 4. 等价 MCP 工具集成契约

本项目当前以独立 REST Bridge 作为 AgentTeams 与 CygnusX 的工具连接层。为满足工具可迁移性，每个端点遵循下列 MCP 等价约束：

| 契约维度 | 设计 |
| --- | --- |
| 调用入口 | Bridge 统一在 `/v1` 下暴露预检、任务、Case、Work Item、证据等受控端点。 |
| 鉴权 | 角色独立 identity token；高风险动作额外要求 scoped、短期 approval token。 |
| 参数 Schema | JSON Schema 风格的结构化输入；必要字段、允许流程、逻辑引用、幂等键均显式声明。 |
| 返回结构 | 状态、结构化结果、逻辑 Artifact/Evidence 引用、trace、错误类别，不返回宿主机路径或原始敏感载荷。 |
| 失败与重试 | 重试仅用于可分类的瞬时上游错误；提交动作使用幂等键；业务缺失返回 `blocked`，规则不足返回 `manual_review`。 |
| 审计 | 每次调用绑定 Case/Work Item、角色、trace、attempt、输入摘要、结果和 evidence reference。 |
| 降级 | Bridge 不可用或权限不满足时停止自动动作并转人工；不降级到任意 shell/直连数据库。 |
| MCP 迁移 | 将 endpoint 描述映射为 tool name、input schema、output schema 和 OAuth/令牌校验即可；Team 身份、Skill 和审计模型保持不变。 |

## 5. Skill 版本、发布与回滚

1. **源代码化：** Skill 定义、引用文档、脚本和版本元数据进入 `data/ai/skill_marketplace/<skill-id>/`；运行时挂载由 `data/ai/skills/<skill-id>/` 和 Agent YAML 管理。
2. **版本化：** Skill ID 稳定，行为/输入输出变化提升语义版本；质量门与交付模板明确记录 `rule_version`/`skill_version`。
3. **灰度：** 新 Skill 先在 staging Case 和脱敏演示项目启用；验证通过后进入 allowlist。
4. **回滚：** 停用对应挂载或回退版本，不删除既有 Case 的调用记录、Artifact 与 evidence；历史 Case 按原版本重放和审计。
5. **质量评估：** 统计预检漏检率、任务重复率、质量门人工复核率、Skill 成功率、错误分类和人工介入耗时，作为版本发布门槛。

## 6. 与多 Agent 流程的关系

```text
agent-general 编排 Case
  ├─ agent-data / project-preflight          → 是否允许进入审批
  ├─ 领域执行 Agent / submit + monitor       → 是否产生可审计任务与 Artifact
  ├─ agent-qc / quality-gate                 → 是否允许交付或转人工
  └─ agent-delivery / delivery-pack           → 是否形成可复核的最终交付

可选：RNA-seq / scRNA / Code / Viz Review → 为 Manager 提供带证据的专业意见
```

该结构使 Skill 既可在一个完整 BioOps Case 中协作，又可被其他 AgentTeams Team、其他组学流程或企业科研交付场景单独复用。

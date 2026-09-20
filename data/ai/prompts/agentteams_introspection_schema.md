# AgentTeams 自省查询面 Schema 文档（F4）

> 一句话索引（常驻）：内部角色（Manager/qc 等）用 `case_facts_query` 工具或
> `POST /api/v1/agent-teams/introspection/query` 查本 case 历史；本文件是表/列说明正文，
> 按需取（template=`schema` 或 `GET /introspection/schema`）。

## 查询方式

- **预置模板**（优先）：
  - `artifact_versions`：本 case 已登记产物及版本。参数：`artifact_id`、`work_item_id`（可选过滤）。
  - `event_timeline`：本 case 事件时间线（含房间命名空间流）。参数：`event_type`（前缀过滤）、`since`（ISO 时间下限）。
  - `pending_approvals`：本 room 待办审批（未决 approval 请求 + approval_pending 状态 + 待确认立项卡）。
  - `artifact_lineage`：产物血缘一级展开（每个版本的上游引用）。参数：`artifact_id`（可选过滤）。
  - `schema`：返回本文档。
- **受限 SQL**（上限能力）：单表 `SELECT ... FROM <表> [WHERE ...] [ORDER BY ...]`，
  仅允许下述三张白名单表；服务端强制注入 `case_id = <当前 case>` 谓词与行数上限；
  禁括号/子查询/函数/多语句/注释/IN/BETWEEN。

## 响应约定

`rows`（截断后行）+ `row_count` + `total_count`（服务端全量计数）+ `truncated` +
`aggregate`（聚合摘要）。`truncated=true` 时用 `total_count`/`aggregate` 判断规模，
不要凭 `rows` 行数低估。

## 白名单表与列

### case_artifact_versions（产物版本行，F1）

每次产物登记一行；`id` 即对外 `version_id`（引用产物用它，不用文件名）。

| 列 | 说明 |
| --- | --- |
| id | 版本行 UUID（version_id） |
| case_id | 所属 Case（scope 过滤键，服务端强制注入） |
| artifact_id | Case 内逻辑名 `{work_item_id}/{相对路径}` |
| version_no | 同一 (case_id, artifact_id) 内递增 |
| producing_event_id | 触发登记的审计事件 id（因果链锚点） |
| work_item_id | 产出的工作项 |
| checksum_sha256 | 内容指纹（篡改检测用） |
| size_bytes / content_type / storage_uri | 大小 / MIME / 存储位置 |
| environment_snapshot | 可复现最小事实（执行 agent、平台版本、执行摘要），JSONB |
| created_at / updated_at | 登记时间 |

### case_artifact_dependencies（产物依赖边，F1）

下游 ← 上游 DAG 边；`relation` ∈ {`input_to`, `derived_from`}。

| 列 | 说明 |
| --- | --- |
| case_id | 所属 Case（scope 过滤键） |
| downstream_artifact_id / upstream_artifact_id | 下游 / 上游 artifact_id |
| relation | 依赖类型 |

### qc_verification_checks（qc 结构化判决行，F2）

每条 claim 的核查判决一行；`verdict` ∈ {`pass`, `warn`, `fail`, `inconclusive`}。

| 列 | 说明 |
| --- | --- |
| case_id | 所属 Case（scope 过滤键） |
| claim_hash | 断言内容指纹（statement+location+claim_type 的 sha256） |
| verdict | 判决 |
| evidence_event_id | 指向审计事件或 version_id 的字符串指针 |
| reviewer_agent | 核查人（如 agent-qc） |
| claim_snapshot | 断言原文快照，JSONB |
| reason | 判决理由 |

## 审计与红线

- 每次查询（含被拒）写 `case.introspection_query` / `case.introspection_denied` 审计事件。
- 越 scope（room↔case 绑定错配、非本人 case）一律拒绝并记审计。
- denied 清单（密钥/token/宿主基础设施类关键词，词边界匹配）命中即拒；
  不要尝试用别名绕过，绕过尝试本身会被记录。

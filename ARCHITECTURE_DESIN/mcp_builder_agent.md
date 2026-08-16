# MCP Builder Agent 架构与实施文档

> **用途**：记录 `agent-mcp-builder`（MCP 构建师）的完整实现架构——让平台 AI 根据自然语言需求自动生成、安全检查、沙箱测试并注册 MCP Server。
>
> **最后更新**：2026-07-30
> **关联文档**：`mcp_architecture.md`（MCP 子系统现状与可行性分析）、`docs/26.7.30/mcp_builder_framework.md`（原始设计文档）

---

## 1. 定位与边界

| 维度 | 说明 |
|------|------|
| 是什么 | 一个配置驱动的内置 Agent（非 Python 模块），驱动"需求 → 可用 MCP"全流程 |
| 产出物 | 实验池 MCP Server（带 TTL、仅创建者 + Admin 可见）+ 构建记录 + 文档 |
| 运行环境 | AI 交互在 Studio 沙箱会话内；生成的 MCP 以 STDIO 子进程运行于同一容器体系 |
| 不负责 | 实验 MCP 的 LLM 自动路由（后续项）、前端管理页（后续项）、非 Python 运行时 |

**红线**（对应 `mcp_architecture.md` §10）：生成代码必须过 AST 检查且在 Docker 沙箱内运行；实验 MCP 必须有 TTL；网络受 egress 白名单约束；所有操作记入 `mcp_logs`（`source='builder'`）。

---

## 2. 总体架构

```text
用户（Studio 会话）
    │ 自然语言需求
    ▼
agent-mcp-builder（qwen3.7-plus, temperature=0.2）
    │ 六阶段工作流（Prompt 驱动）
    │ ① 规划 → ② 搜索 → ③ 编码 → ④ 测试 → ⑤ 文档 → ⑥ 注册
    │
    ├─ workspace_write  ──→  /workspace/mcp-builds/{name}/server.py（沙箱内）
    ├─ sandbox_execute  ──→  语法/结构自检 + 业务逻辑测试
    │
用户/前端确认提交
    ▼
POST /api/v1/mcp-builder/builds
    │
    ▼
MCPBuilderService.submit_build()
    ├─ 配额检查（默认 5 个/用户）
    ├─ （无 code 时）MCPCodeGenerator → ProviderManager.chat_stream()
    ├─ StaticSafetyChecker.analyze()  ← 违规直接拒绝落库
    ├─ 注册 MCPServer（pool=experimental, expires_at=now+TTL）
    └─ 落库 mcp_builds + mcp_logs
    ▼
POST /api/v1/mcp-builder/builds/{id}/test
    │
    ▼
StudioSandboxManager（宿主）
    │ UDS（/workspace/{session}/.agent.sock）
    ▼
sandbox-agent /mcp/start（容器内）
    │ stdio_client 启动子进程 → MCP 握手 → tools/list
    ├─ /mcp/call 逐工具验证 → test_cases 落库
    ▼
审核（平台开关 mcp_builder_requires_review）
    ├─ Admin: POST /builds/{id}/review → approved → 版本快照 mcp_versions
    └─ 关闭审核：测试通过即发布
    ▼
Celery beat（每 5 分钟）
    └─ expire_experimental → 过期 MCP 自动下线
```

---

## 3. Agent 配置

| 文件 | 内容 |
|------|------|
| `data/ai/mcp_builder.yaml` | Agent 配置：`agent-mcp-builder`，model `qwen3.7-plus`，temperature 0.2，max_tokens 8000，`tool_packs: [workspace, memory]`，studio.enabled + default_mode=studio + runtime_profile=analysis-core，`features.mcp_builder`（配额/TTL/产物目录元数据） |
| `data/ai/prompts/mcp_builder.md` | 六阶段系统提示词（约 14k 字符）：规划/搜索/编码/测试/文档/注册；含两份代码模板（本地 pandas 版 + NCBI httpx 版）、安全红线、"绝不代为提交"约束（注册须用户/前端触发 API） |
| `data/OmicHub.yaml` | `agents.enabled` 追加 `mcp_builder`（加载白名单） |
| `data/ai/prompts/router.md` | 路由候选表追加构建师条目（"创建/生成 MCP Server、给 AI 加新工具"类请求分派给它） |

**加载链路**：`agent_loader.load_agent_configs()` → 幂等落库 `agent_templates` → 会话时 `assemble_context()` 组装模型/Prompt/工具。Agent 是纯 YAML+Markdown 配置，非 Python 包。

**模型配置两处**：
- Agent 对话/生成：`mcp_builder.yaml` 的 `model` 字段（改后需重启 web）
- 后端 API 直连生成：`core/config.py` 的 `mcp_builder_default_model`（可被环境变量 `MCP_BUILDER_DEFAULT_MODEL` 或请求体 `model_name` 覆盖）

---

## 4. 安全检查器（`infrastructure/mcp/builder/safety.py`）

`StaticSafetyChecker.analyze(code) -> SafetyReport{passed, violations[], warnings[], dependencies[]}`，纯静态 AST 分析，不执行被测代码。

| 维度 | 规则 | 级别 |
|------|------|------|
| 语法 | `ast.parse` 失败 / 超 512KB | violation |
| import | 黑名单（subprocess/ctypes/pickle/socket/shutil/sys/threading/importlib…） | violation |
| import | 白名单外（mcp/pydantic/httpx/pandas/numpy + 标准库安全子集之外） | warning（人工审核兜底） |
| import | 相对导入 | violation |
| 调用 | `eval/exec/compile/open/getattr/__import__/globals…` 裸调用 | violation |
| 调用 | `.system/.popen/.exec*/.fork/.kill` 等属性调用（任意接收者） | violation |
| 调用 | `.loads/.load/.dumps/.dump` 仅当接收者为 pickle/marshal/shelve（不误伤 `json.dumps`） | violation |
| 属性 | `__globals__/__subclasses__/__bases__/__mro__…` dunder 访问 | violation |
| 字符串 | `/etc//proc//sys//root//dev/`、docker.sock | violation |
| 字符串 | 内网/元数据 IP | warning（egress proxy 兜底） |
| 结构 | 缺 `__exp_mcp_generated__ = True` 标记 | violation |
| 结构 | 缺 MCP handler（`list_tools`+`call_tool` 或 FastMCP `@tool`） | violation |

检查失败时构建以 `rejected` 状态落库（保留记录供用户查看违规项），不注册 Server。

---

## 5. 沙箱执行层

### 5.1 容器内端点（`deploy/studio/sandbox_agent.py`）

| 端点 | 行为 |
|------|------|
| `POST /mcp/start` | 路径校验（必须落在 /workspace 内）→ `mcp.client.stdio.stdio_client` 以当前解释器启动 server.py 子进程 → `ClientSession.initialize()` 握手 → `list_tools()` → 返回 `{server_id, path, tools}`；单容器上限 8 个 |
| `POST /mcp/call` | `session.call_tool(tool, arguments)`，30s 超时，返回 `{content, is_error}` |
| `GET /mcp/tools` | 重查工具清单（失效退回启动缓存） |
| `POST /mcp/stop` | 关闭 AsyncExitStack（子进程组随之终止） |
| `GET /mcp/list` | 列出运行中的实验 MCP |

子进程继承容器的全部隔离属性：非 root（uid 10001）、network_mode=none / egress 白名单、CPU/内存配额。无 TCP 端口暴露，宿主只经 UDS 可达。

### 5.2 宿主封装（`infrastructure/studio/manager.py`）

`start_mcp_server / stop_mcp_server / list_mcp_servers / mcp_list_tools / mcp_call_tool`——统一走 `_agent_call(session_id, method, endpoint)` 的 UDS httpx 封装，带 busy lease 防回收竞态。工作区预建目录含 `mcp-builds/`（chown 10001）。

### 5.3 镜像依赖

`deploy/studio/requirements-agent.txt` 增加 `mcp>=1.2.0`（重建镜像后生效：`deploy/studio/build.sh`）。

---

## 6. 数据模型

迁移 `h6i7j8k9l1m3`（down: `g4h5i6j7k8l9`），四张新表 + `mcp_servers` 扩展：

| 表 | 用途 | 关键字段 |
|----|------|----------|
| `mcp_builds` | 构建记录（核心） | user_id, requirement, generated_code, safety_report(JSON), mcp_server_id, version, parent_build_id（版本链）, status, test_cases(JSON), test_passed, build_doc, architecture_doc, model_used |
| `mcp_versions` | 版本快照 | mcp_server_id, version（与 server 联合唯一）, code_snapshot, tools_snapshot, changelog |
| `mcp_visibility` | 用户级共享授权（预留） | mcp_server_id+user_id 唯一, access_level, expires_at |
| `mcp_reviews` | 审核记录 | build_id, reviewer_id, decision, comment |
| `mcp_servers`（扩展） | — | pool(production/experimental/deprecated), expires_at, created_by, current_version, generation_meta(JSON), review_status, is_template |

**状态机**（`mcp_builds.status`）：`planning → coding → testing → reviewing → approved/rejected → published → deprecated`；审核 `request_changes` 回退到 `planning`。

**实体/值对象**：`domain/mcp/entities.py` MCPServer 扩展同名字段 + `is_expired()`；`value_objects.py` 新增 `ServerPool / BuildStatus / ReviewStatus / ReviewDecision / AccessLevel`。

---

## 7. API（`/api/v1/mcp-builder`，12 条路由）

| 方法 | 路径 | 权限 | 用途 |
|------|------|------|------|
| POST | `/builds` | User | 提交构建（附 code 直接检查；缺省 LLM 生成） |
| POST | `/generate` | User | 仅生成代码 + 安全预览，不落库 |
| GET | `/builds` | User | 我的构建历史（?status=&limit=） |
| GET | `/builds/{id}` | User（本人） | 构建详情 |
| DELETE | `/builds/{id}` | User（本人） | 删除构建（联动删其实验 MCP） |
| POST | `/builds/{id}/test` | User（本人） | 指定 session 沙箱内逐工具测试 |
| GET | `/review-queue` | Admin | 审核队列 |
| POST | `/builds/{id}/review` | Admin | 审核决定（approved 自动发布 + 版本快照） |
| GET | `/servers/experimental` | User | 我的实验 MCP 列表 |
| POST | `/servers/{id}/renew` | Owner/Admin | TTL 续期 |
| DELETE | `/servers/{id}` | Owner/Admin | 删除实验 MCP |
| POST | `/servers/{id}/invoke` | Owner/Admin | 经沙箱 UDS 桥接调用工具 |
| GET | `/servers/{id}/versions` | User | 版本历史 |
| POST | `/servers/{id}/rollback` | Owner/Admin | 回滚到指定版本 |

实验 MCP 的调用路径（invoke）：宿主 → UDS → sandbox-agent `/mcp/start`（确保子进程在）→ `/mcp/call` → 原路返回。不经过 `MCPClient` 的 stdio/sse 校验路径（生成代码从不落宿主文件系统）。

---

## 8. 生命周期与运维

| 事项 | 机制 |
|------|------|
| TTL 过期 | Celery beat `mcp-builder-expire-experimental`（每 5 分钟）→ `expire_stale_servers()`：过期实验 MCP 置 offline + 禁用；容器侧子进程随 Studio 空闲回收销毁 |
| 配额 | `mcp_builder_max_per_user`（默认 5），按活跃构建数计 |
| 默认 TTL | `mcp_builder_default_ttl_hours`（默认 24） |
| 审核开关 | `mcp_builder_requires_review`（默认 true；关闭则测试通过即发布） |
| 功能总开关 | `mcp_builder_enabled` |
| 审计 | 关键操作写 `mcp_logs`（source=builder，含 actor） |

**部署注意**（本仓库既有约束）：
- 改后端代码/YAML 后 `docker restart omichub-web`（不热重载）；改 Celery 任务同步重启 `omichub-worker` + `omichub-beat`
- 迁移用容器内 `/app/.venv/bin/alembic upgrade head`
- 沙箱镜像改了 `requirements-agent.txt` 后需 `deploy/studio/build.sh` 重建

---

## 9. 关键文件清单

```text
data/ai/mcp_builder.yaml                          # Agent 配置
data/ai/prompts/mcp_builder.md                    # 六阶段 Prompt + 代码模板
data/OmicHub.yaml                                 # agents.enabled 注册
data/ai/prompts/router.md                         # 路由候选表

src/omichub/infrastructure/mcp/builder/
├── safety.py                                     # AST 安全检查器
├── versioning.py                                 # SemVer 推导
├── generator.py                                  # LLM 代码生成（ProviderManager 封装）
└── doc_generator.py                              # build.md / architecture.md 模板

src/omichub/application/services/mcp_builder_service.py   # 编排中枢
src/omichub/application/schemas/mcp_builder.py            # DTO
src/omichub/api/v1/mcp_builder.py                         # 12 条路由
src/omichub/infrastructure/celery_app/tasks/mcp_builder.py # 过期清理

src/omichub/infrastructure/database/models/mcp_builder.py  # 4 个 ORM 模型
alembic/versions/h6i7j8k9l1m3_add_mcp_builder_tables.py    # 迁移

deploy/studio/sandbox_agent.py                    # /mcp/* 容器端点
deploy/studio/requirements-agent.txt              # mcp>=1.2.0
src/omichub/infrastructure/studio/manager.py      # host 侧 UDS 封装

tests/unit/mcp/                                   # 62 个 builder 单测
tests/unit/test_agent_loader_studio.py            # agent 加载回归测试
```

---

## 10. 后续项（设计文档 Phase 2/3 范畴）

| 项 | 基础已就位 | 待做 |
|----|-----------|------|
| 实验 MCP 的 LLM 自动路由 | generation_meta/tools 快照在库 | ChatService 工具发现纳入实验池（按 created_by 过滤） |
| 审核"转正"为正式 MCP | mcp_versions 快照 + review 状态机 | pool experimental→production 提升流程 + 前端管理页 |
| 前端页面 | API 完备 | `/admin/mcp-builder`（仪表盘/审核队列/版本对比）、`/studio/mcp-builder`（用户构建历史） |
| 反馈闭环 / 成本管控 | mcp_builds.tokens_consumed | mcp_feedback 表、token_budget_per_user |

# CygnusX Skill 体系架构（全生命周期）

> 基线日期：2026-09-18。本文由代码实勘得出，修正了旧文档中过时的描述；
> 与 `agent_framework_baseline.md` §5.2（Skill 契约）、`agent_framework_baseline.md` §12 与 §2.2（挂载与绑定，原 `agent_architecture_and_extension_guide.md` 已并入其中）互为补充，冲突时以本文为准。

## 0. 两套 Skill 体系（勿混淆）

本仓库存在**两套相互独立**的 Skill 体系（另见 `skills/SKILL_INSTALL_GUIDE.md`）：

| 体系 | 使用者 | 挂载方式 | 本文 |
|---|---|---|---|
| Kimi Code CLI Agent Skills | 仓库里的 AI 编码助手 | `.agents/skills/` 目录扫描，`/skill:<name>` 调用 | ❌ 不涉及 |
| **CygnusX 平台 Skill** | 平台业务 Agent（如 agent-scrna） | DB 索引 + 磁盘文件夹 + `skill_ids` 绑定 | ✅ 全文 |

## 1. 生命周期总览

```
[存储真相源]  data/ai/skill_marketplace/<skill_id>/SKILL.md   内置市场（约 600 个可装技能）
              data/ai/skills/<skill_id>/                       已安装技能（磁盘 = 内容真相源）
              skills / skill_versions / skill_invocations      DB 三表（索引 + 快照 + 审计）
                  │
[导入/安装]   五入口（市场 / GitHub / zip / Markdown / JSON）统一"预览 → 确认"管线
              + 阿里云官方源同步（ALIYUN_SKILLS_ENABLED 总开关，默认关闭）
              + 内置 Agent YAML 声明的市场技能自动安装（_ensure_configured_marketplace_skills）
                  │
[绑定]        AgentTemplateModel.skill_ids（JSONB）声明式绑定；注入上限 10 个
                  │
[发现]        assemble_context → L1 索引（name + description，约 100 tokens/技能）常驻 system prompt
              未绑定技能时不注入 use_skill / skill_resource 工具
                  │
[调用]        L2 use_skill 加载 SKILL.md 正文 → L3 skill_resource 读 references/ / assets/
              正文优先级：会话 skill_pins 快照 > 磁盘实时读取 > DB prompt 兜底
              ChatChunk(type="skill") 前端事件 + skill_invocations 审计落库
                  │
[版本]        双轨：frontmatter version（semver）+ 平台 revision（递增快照）
              更新自动 bump（description=minor，其余=patch）；回滚=还原快照+新快照；
              会话级 skill_pins 固定版本；check_update 比对 source_commit 检查上游更新
```

## 2. 存储与挂载

### 2.1 双层存储：磁盘是真相源，DB 是索引

| 层 | 位置 | 职责 |
|---|---|---|
| 磁盘 | `data/ai/skills/<skill_id>/` | 技能内容真相源：`SKILL.md` + `scripts/` + `references/` + `assets/` |
| 磁盘 | `data/ai/skill_marketplace/` | 内置市场：随仓库发布的可安装技能文件夹（约 600 个，含全部 `bio-*`） |
| DB | `skills` 表 | L1 元数据索引 + L2 正文缓存（`prompt` 列，兜底用） |
| DB | `skill_versions` 表 | 全量内容快照（revision 递增，审计/回滚/会话 pin 用） |
| DB | `skill_invocations` 表 | 每次 use_skill 的调用审计（版本、耗时、状态、会话/用户） |

配置项（`src/cygnusx/core/config.py`）：

- `skills_dir` = `data/ai/skills` —— 已安装技能库
- `skill_marketplace_dir` = `data/ai/skill_marketplace` —— 内置市场
- `aliyun_skills_*` —— 阿里云官方源（见 §5.3，默认关闭）

### 2.2 SKILL.md 解析规范（`src/cygnusx/infrastructure/skills/skillmd.py`）

- frontmatter 中 `name`、`description` **必填**（description 决定技能何时被模型命中），缺失即 `SkillParseError`
- `skill_id` 取 frontmatter `skill_id`，否则由 name 派生（slug 用**连字符**，对齐 agentskills.io 生态）；市场安装时以**文件夹名**为规范键，保证 DB/磁盘/市场三处一致
- 限额：单文件夹 ≤ 1MiB、单文件 ≤ 512KB、正文软限 20,000 字符（约 5000 tokens，超出仅告警）
- 安全：`DANGEROUS_PATTERNS` 对脚本静态扫描（`rm -rf /`、`curl | sh`、fork 炸弹等），命中仅告警不阻断

### 2.3 磁盘读写（`src/cygnusx/infrastructure/skills/skill_store.py`）

`write_skill_folder`（覆盖写整目录）/ `rewrite_skill_md`（只重写 SKILL.md 保留 L3 资源）/ `read_skill_body`（剥 frontmatter 读正文）/ `read_skill_resource`（**仅允许 references/ 与 assets/**，脚本永不进上下文，单次 200KB 上限）/ `remove_skill_folder`。

## 3. Agent 绑定与发现

### 3.1 绑定：声明式 skill_ids

- `AgentTemplateModel.skill_ids`（JSONB，`infrastructure/database/models/agent.py`）+ 用户级 `UserCapabilityModel.skill_ids`
- 内置 Agent 由 `data/ai/*.yaml` 的 `skill_ids` 初始声明；`AgentService.ensure_builtin_agents()` 幂等同步时**不会覆盖**管理员已保存的绑定（只同步 features 和 Studio 描述）
- **自动安装**：`agent_service.py` `_ensure_configured_marketplace_skills` —— YAML 声明了但未安装、且存在于内置市场的技能会自动 install（旧文档未提及的行为）
- 注入上限：`MAX_ACTIVE_SKILLS = 10`（`skill_service.py`）

### 3.2 发现：三层渐进式披露（`agent_service.py: assemble_context`）

| 层 | 内容 | 注入时机 | 成本 |
|---|---|---|---|
| L1 | name + description 索引 | 常驻 system prompt | ~100 tokens/技能 |
| L2 | SKILL.md 正文 | 模型命中后调 `use_skill` | 按需 |
| L3 | references/ assets/ 资源 | 正文要求时调 `skill_resource` | 按需 |

关键契约（与 baseline §5.2 一致）：

- `build_skill_tools(skills)`（`domain/skill/services.py`）在 skills 为空时返回 `[]` —— **未绑定有效技能时 use_skill / skill_resource 两个工具根本不注入**
- `use_skill` 的 `skill_id` 参数 enum 限定为已挂载技能，模型无法加载未授权技能
- Studio 会话例外：走 `studio_capabilities.py` 的 capability_catalog（只列元数据目录，用户/模型显式 `studio_capability_load` 后才注入全文，加载审计写 `sandbox_meta.capabilities`，保留最近 100 条）
- 平台内置 MCP 工具 `platform_list_agent_skills`（`infrastructure/mcp/presets.py`）可跨 Agent 枚举技能

## 4. 运行时调用

### 4.1 工具路由与执行

- 工具名只有两个：`use_skill`、`skill_resource`（`domain/skill/services.py` 常量；旧文档 `agentteams_room_plan.md`（现已并入 `deprecated/agentteams_room_architecture.md`）中的 `read_skill_resource` 是笔误，已修正）
- `langgraph_runtime.py`：`tool_name in SKILL_TOOL_NAMES` → 路由到 skills 节点
- `runtime_support.py: _execute_skill_tool`：
  1. 先在**已挂载** skills 中按 skill_id（或 name）匹配，未挂载直接报错
  2. `use_skill` 取正文优先级：**会话 pin 的 revision 快照 → 磁盘 `read_skill_body`（运行时实时读文件）→ DB `prompt` 兜底**
  3. `skill_resource` 只读 references/assets，二进制拒绝为文本

### 4.2 事件流与审计

- `chat/skill_execution.py: stream_skill_execution`：前后发 `ChatChunk(type="skill", phase=invoked/completed/failed)` SSE 事件；AgentTeams 房间投影为 `skill.finished` / `skill.failed` / `skill.manual_review` 发言
- 每次调用落 `skill_invocations`（skill_version、source、duration、session/message/user），管理端可查聚合统计
- 回灌截断：`SKILL_TOOL_MAX_CHARS = 24000`（技能回灌比普通工具结果宽松）

## 5. 安装 / 导入 / 同步

### 5.1 五入口统一"预览 → 确认"（`application/services/skill_import_service.py`）

| 入口 | 预览接口 | 说明 |
|---|---|---|
| 内置市场 | `GET /admin/skills/marketplace` + `POST .../marketplace/{id}/install` | 文件夹名为安装键；`overwrite=true` 即升级 |
| GitHub URL | `POST /admin/skills/import/github` | codeload tar.gz 整仓，支持 repo/tree/blob/raw 链接，记录 commit 前 12 位 |
| zip 上传 | `POST /admin/skills/import/zip` | zip 内仅一份 md 时降级为 Markdown 导入 |
| Markdown 文件 | `POST /admin/skills/import/markdown` | 单 SKILL.md |
| JSON 粘贴 | `POST /admin/skills/import/json` | 结构化定义 |

确认入库（`confirm_import`）统一动作：`write_skill_folder` 落盘 → upsert `skills` 行（含 version/author/source_*）→ `_snapshot_skill(source="import")` 快照。

### 5.2 管理端创建 / Studio 提炼

- 管理端 `POST /admin/skills` 直接创建（首版 revision=1）
- Studio 脚本提炼（`studio_skill_service.py` + `POST /studio/sessions/{id}/skills/extract`）：管理员从自己 Studio 会话工作区脚本创建全局 Skill；仅 `.py/.r/.sh/.bash`、256KB、密钥模式拦截、要求显式确认；并在会话 `sandbox_meta["skill_commands"]` 注册 `/skill:{id}` 命令

### 5.3 阿里云官方源（市场第二分组）—— 总开关默认关闭

> **2026-09-18 变更**：新增 `ALIYUN_SKILLS_ENABLED` 总开关（默认 `false`）。对本平台无外部技能源需求时保持关闭即可，AK 无需删除。

`.env`：

```bash
# ===== 阿里云 Skills（可选，默认关闭） =====
# false：技能市场隐藏「阿里云官方」分组，同步/安装接口短路返回（不触网、不读缓存）；
# true 后才会使用 AccessKey 通过 AgentExplorer OpenAPI 同步目录（未配置 AK 时回退 GitHub 仓库同步）。
ALIYUN_SKILLS_ENABLED=false
ALIYUN_SKILLS_ACCESS_KEY_ID=
ALIYUN_SKILLS_ACCESS_KEY_SECRET=
ALIYUN_SKILLS_REGION_ID=cn-hangzhou
```

关闭时的行为（`skill_import_service.py` 各入口短路）：

| 入口 | 关闭时行为 |
|---|---|
| `list_marketplace` | 只返回平台内置源条目，不读阿里云缓存目录 |
| `aliyun_status` / `sync_aliyun_marketplace` | 直接返回 `enabled=false, available=false`，不触网、不读缓存 |
| `install_aliyun` | 404：阿里云官方技能源未启用 |
| 前端 `SkillMarketSection.vue` | 隐藏「阿里云官方」筛选页签、同步元信息块和错误重试块；不触发自动同步 |

启用时的同步机制：

- 配置 AK → AgentExplorer OpenAPI（SearchSkills 分页同步目录元数据，安装时 GetSkillContent 按需拉 SKILL.md）
- 未配置 AK → 回退 GitHub `aliyun/alibabacloud-aiops-skills` tarball 同步
- 缓存写入 `aliyun_skills_cache_dir`（`/data/cygnusx/skill_marketplace_aliyun`，运行时产物不放只读 data/），manifest.json 原子写；失败保留旧缓存记 `last_error`
- 状态 DTO `AliyunMarketplaceStatusDTO` 新增 `enabled` 字段（默认 true），前端据此控制分组显隐

## 6. 版本管理

### 6.1 双轨版本

| 轨 | 字段 | 性质 |
|---|---|---|
| 语义版本 | `skills.version` | SKILL.md frontmatter 声明（如 `1.0.0`）；管理端更新时自动 bump：**description（触发条件）变更 = minor+1，其余 = patch+1**（无法解析 semver 则原样保留） |
| 平台快照 | `skill_versions.revision` | 递增序号 1,2,3…；创建/更新/覆盖导入/回滚均留全量快照，带 source（admin/import/rollback）+ changelog + 操作人 |

### 6.2 关键语义

- **回滚**：`POST /admin/skills/{id}/rollback` = 还原历史快照 + 以 source="rollback" 落新快照
- **会话版本固定**：会话首轮把每个挂载技能的 `max(revision)` 写入 `session.sandbox_meta["skill_pins"]`；use_skill 优先读 pin 的快照正文 —— **会话中途升级/回滚不影响进行中任务**
- **上游更新检查**：`POST /admin/skills/{id}/check-update` 基于 `source_commit` 与上游（GitHub API 最新 commit / 阿里云本地 manifest，零网络）比对；升级 = 市场/导入带 `overwrite` 重装 → 新快照
- **删除**：内置技能禁删；被 Agent 引用需 `force`；删 DB 行 + 磁盘文件夹，**版本快照保留**（审计与恢复）

## 7. API 端点清单（`api/v1/admin/skills.py`，均 AdminRequired）

| 分组 | 端点 |
|---|---|
| CRUD | `GET/POST /admin/skills`、`GET/PUT/DELETE /admin/skills/{id}`、`POST .../toggle`、`GET .../{id}/references`（被哪些 Agent 挂载） |
| 市场 | `GET /admin/skills/marketplace`、`POST .../marketplace/{id}/install` |
| 阿里云 | `GET .../marketplace/aliyun/status`、`POST .../marketplace/aliyun/sync`、`POST .../marketplace/aliyun/{id}/install` |
| 导入 | `POST .../import/{github,zip,markdown,json}` + `POST .../import/confirm` |
| 版本 | `GET .../{id}/versions`、`GET .../{id}/versions/{revision}`、`POST .../{id}/rollback`、`POST .../{id}/check-update` |
| 审计 | `GET .../invocation-stats`、`GET .../{id}/invocations` |

非管理端：`GET /api/v1/skills`（`chat.py`，用户侧启用列表，带 Studio 可见性过滤）；`POST /api/v1/studio/sessions/{id}/skills/extract`。

## 8. 数据库表与迁移（`infrastructure/database/models/skill.py` + alembic）

- `skills`：unique `skill_id`(100)、`(category, is_active)` 索引、version/author/source_type/source_ref/source_commit/has_scripts/frontmatter(JSON)
- `skill_versions`：FK CASCADE、unique `(skill_id, revision)`
- `skill_invocations`：版本/耗时/状态/会话/用户 + 3 索引
- 相关迁移：`e4f5a6b7c8d9`（建表）、`c9d0e1f2a3b4`（SKILL.md 标准化字段）、`n2o3p4q5r6s7`（版本快照表）、`f0a1b2c3d4e5`（调用审计表）、`e9f0a1b2c3d4`（skill_id 扩到 100，容纳阿里云长 ID）、`p0q1r2s3t4u5`（用户级能力）

## 9. 前端（`frontend/src/components/admin/skill/`）

- `SkillMarketSection.vue`：已安装表格 + 市场分组卡片 + 来源筛选（全部/平台内置/阿里云官方，阿里云页签受 `aliyunEnabled` 控制）+ 分类/安装状态/脚本筛选 +「安装到 Agent」批量指派
- `SkillMarketCard.vue` / `SkillInvocationCard.vue`：市场卡片与调用事件渲染
- 状态类型 `AliyunMarketStatus`（`types/skill.ts`）含 `enabled` 字段

## 10. 对旧文档的修正记录

| 旧文档 | 原描述 | 实况（本文） |
|---|---|---|
| `domain_prompt_sedimentation_2026-08.md:36` | skill 市场"36 技能" | 内置市场约 **600** 个技能文件夹 |
| `agentteams_room_plan.md`（已并入 `deprecated/agentteams_room_architecture.md`） | 工具名 `read_skill_resource` | 实为 `skill_resource` |
| `agent_execution_framework.md:72` | `skill_pins` 仅一句带过 | 完整语义见 §6.2 |
| 全部旧文档 | 无版本管理章节 | §6 双轨版本 + 快照/回滚/check-update |
| 全部旧文档 | 无外部源开关 | §5.3 `ALIYUN_SKILLS_ENABLED`（2026-09-18 新增，默认关） |
| `agent_architecture_and_extension_guide.md`（已并入 `agent_framework_baseline.md`） | 未提自动安装 | `_ensure_configured_marketplace_skills` 自动装 YAML 声明的市场技能（§3.1） |

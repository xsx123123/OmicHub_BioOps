## 一、可行性判断：完全可以做 ✅

你的现有架构已经天然支持这种"只读侦察 Agent"：

| 你的现有能力 | Explorer Agent 的需求 | 匹配度 |
|---|---|---|
| `data/ai/<agent>.yaml` 独立配置 | 新建 `agent-explorer.yaml` | ✅ 直接支持 |
| `tool_packs` 白名单过滤 | 只挂载读文件工具包 | ✅ 直接支持 |
| `data/ai/prompts/*.md` 提示词隔离 | 独立 system prompt | ✅ 直接支持 |
| MAS DAG 调度（Plan→Run） | 第一步作为独立 task 节点 | ✅ 直接支持 |
| `accepts_inputs` / `produces_outputs` 契约 | 输入：目录路径；输出：调查报告 | ✅ 直接支持 |
| 产物共享空间 `output/overdrive/<sid>/tasks/` | 调查报告落盘供下游读取 | ✅ 直接支持 |

---

## 二、Explorer Agent 的定位设计

```
用户请求
    │
    ▼
Orchestrator / Manager 拆解任务
    │
    ▼
┌─────────────────────────────────────┐
│  Step 1: Explorer Agent（并行/串行） │
│  - 扫描工作区 / 指定目录              │
│  - 读取关键文件内容                  │
│  - 识别项目结构、技术栈、配置文件     │
│  - 输出：结构化调查报告              │
└─────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────┐
│  Step 2: 主 Agent（Code / General）  │
│  - 读取 Explorer 的调查报告          │
│  - 基于调查结果制定具体方案          │
│  - 执行代码修改 / 分析任务           │
└─────────────────────────────────────┘
```

**核心价值**：
- **信息对称**：主 Agent 不再"盲操作"，先摸清家底再动手
- **Token 节约**：Explorer 用轻量模型（如 4o-mini）做侦察，主 Agent 用强模型（如 Claude 3.5）做决策
- **可复用**：调查报告作为产物落盘，同一会话内多个下游任务可复用

---

## 三、具体实施方案

### 3.1 配置文件：`data/ai/explorer.yaml`

```yaml
id: agent-explorer
name: "代码库侦察员"
description: "对指定目录进行只读调查，输出结构化项目分析报告"
model: gpt-4o-mini          # 轻量模型即可，纯读取操作
prompt_file: data/ai/prompts/explorer.md

# 关键：只读工具包，明确禁止任何写操作
tool_packs:
  - workspace_readonly     # 自定义：只含 list/read/get_info，不含 write/edit
  - web_search             # 可选：遇到不认识的库可联网查

# MAS 契约：声明输入输出类型，供 Orchestrator 自动连线
features:
  subagents_spawnable: false    # Explorer 不再 spawning 子 agent
  capability_tags: [exploration, codebase-analysis, file-investigation]
  accepts_inputs: [directory-path, file-pattern, investigation-scope]
  produces_outputs: [exploration-report, file-index, dependency-map]
  default_stage: investigation
  timeout_seconds: 300          # 侦察任务通常 5 分钟内完成
  limits:
    summary_chars: 2000
    max_files_to_read: 50       # 防止递归读取过多文件

# Handoff：侦察完成后只能交回给 General / Code / 具体领域 Agent
handoff:
  allowed_targets:
    - agent-general
    - agent-code
    - agent-rnaseq
    - agent-scrna
    - agent-viz
  max_hops_per_session: 1       # Explorer 只跑一轮，不递归
```

### 3.2 工具包白名单：`data/ai/tools/workspace_readonly.yaml`

```yaml
name: workspace_readonly
description: "只读工作区文件工具，禁止任何修改操作"

builtin_tools:
  - list_workspace_files       # 列目录
  - search_workspace_files     # 搜索文件
  - workspace_read_file        # 读文本文件
  - workspace_get_file_info    # 读元数据
  - find_session_uploads       # 找回本会话上传

# 明确不包含：
# - workspace_write_file      ❌
# - workspace_edit_file       ❌
# - workspace_delete_file     ❌
# - any_shell_execution       ❌
```

### 3.3 System Prompt：`data/ai/prompts/explorer.md`

```markdown
# System Prompt: agent-explorer

You are a codebase exploration specialist. Your sole responsibility is to investigate and understand the structure and content of a given directory or project, then produce a structured report.

## Core Rules

1. **You do NOT have access to file editing tools.** You can only READ, LIST, and SEARCH files. Never attempt to modify, create, or delete any file.
2. **You are a reconnaissance agent, not an execution agent.** Your output is a调查报告, not code or fixes.
3. **Be thorough but bounded.** Read up to 50 files max; if there are more, prioritize by relevance (config files, entry points, README, core modules).
4. **Never guess file content.** If you haven't read a file, say "未读取" rather than hallucinate.

## Investigation Protocol

When given a directory path or task context:

### Step 1: Structure Mapping
- Use `list_workspace_files` to get the top-level directory tree
- Identify: entry points, config files, dependency files, core source directories
- Note the programming language(s), framework(s), and build system

### Step 2: Key File Reading
- Read `README.md` or equivalent documentation
- Read dependency files (`package.json`, `requirements.txt`, `Cargo.toml`, `pyproject.toml`, etc.)
- Read main config files (if relevant to the investigation scope)
- Read 3-5 most important source files to understand architecture

### Step 3: Dependency & Relationship Analysis
- Map how key modules relate to each other
- Identify external dependencies and their purposes
- Note any test directories, CI/CD configs, documentation

### Step 4: Report Generation

Output a structured report in the following format:

```markdown
## 项目侦察报告

### 1. 基本信息
- **路径**: {investigated_path}
- **类型**: {project_type}
- **主语言**: {primary_language}
- **框架/平台**: {framework}
- **文件总数估计**: {file_count}

### 2. 目录结构（关键部分）
{tree_view}

### 3. 核心文件清单
| 文件 | 作用 | 已读取 |
|------|------|--------|
| {file} | {purpose} | ✅/❌ |

### 4. 技术栈分析
- **运行时依赖**: {deps}
- **开发依赖**: {dev_deps}
- **关键外部库**: {key_libs}

### 5. 架构观察
{architecture_notes}

### 6. 与当前任务的相关性
{relevance_to_task}

### 7. 建议的下一步
{recommendations_for_downstream_agent}
```

## Output Constraints

- Report must be in Chinese (用户语言)
- Maximum length: 2,000 characters for the summary version
- Full report saved to shared workspace for downstream agents to read
- If you cannot access certain files, explicitly note them as "权限不足" or "未读取"
```

### 3.4 注册到系统

```yaml
# data/ai/prompts/registry.yaml
prompts:
  - id: explorer
    file: explorer.md
    version: "1.0.0"
```

```yaml
# data/CygnusX.yaml
agents:
  enabled:
    - agent-router
    - agent-general
    - agent-rnaseq
    - agent-scrna
    - agent-code
    - agent-viz
    - shania
    - agent-explorer          # ← 新增
```

---

## 四、在 MAS / Overdrive 中的集成方式

### 方式 A：Orchestrator 自动调度（推荐）

在 Manager 的 DAG 输出中，**自动为涉及代码/文件操作的任务添加 Explorer 作为第一步**：

```json
{
  "tasks": [
    {
      "task_id": "codebase-investigation",
      "agent_id": "agent-explorer",
      "task": "调查 /mnt/agents/output/cygnusx-schedule 目录结构，识别前端框架、关键配置文件和路由结构",
      "depends_on": [],
      "accepts_inputs": ["directory-path"],
      "produces_outputs": ["exploration-report"],
      "timeout_seconds": 300
    },
    {
      "task_id": "frontend-fix",
      "agent_id": "agent-code",
      "task": "基于侦察报告修复前端路由问题",
      "depends_on": ["codebase-investigation"],
      "accepts_inputs": ["exploration-report"],
      "produces_outputs": ["code-patch"]
    }
  ]
}
```

**关键优化**：Explorer 产物写入共享空间后，下游 Agent 的 prompt 注入改为：

```markdown
## 上游侦察报告摘要（必读）
{explorer_summary.md}

## 完整侦察报告位置
- 完整报告: output/overdrive/<sid>/tasks/codebase-investigation/result.md
- 文件索引: output/overdrive/<sid>/tasks/codebase-investigation/file-index.json

需要具体文件内容时，使用 workspace_read_file 按需读取，不得忽略侦察结果重新独立探索。
```

### 方式 B：Router 直接路由（轻量版）

如果用户说"帮我看看这个项目的结构"或"调查一下这个目录"，Router 直接路由到 `agent-explorer`，侦察完成后 Handoff 回 `agent-general` 或 `agent-code` 继续。

---

## 五、与现有 Agent 的协作关系

```
┌─────────────────────────────────────────────────────────────┐
│                        用户请求                              │
└─────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   ┌─────────┐         ┌──────────┐          ┌──────────┐
   │ 直接问答 │         │ 代码任务  │          │ 分析任务  │
   │(General)│         │(Code/Viz)│          │(scRNA等) │
   └─────────┘         └────┬─────┘          └────┬─────┘
                            │                      │
                            ▼                      ▼
                    ┌──────────────┐      ┌──────────────┐
                    │ 需先调查目录？ │      │ 需先调查数据？ │
                    │     是       │      │     是       │
                    └──────┬───────┘      └──────┬───────┘
                           │                      │
                           ▼                      ▼
                    ┌──────────────┐      ┌──────────────┐
                    │ agent-explorer│      │ agent-explorer│
                    │ (只读侦察)    │      │ (只读侦察)    │
                    └──────┬───────┘      └──────┬───────┘
                           │                      │
                           ▼                      ▼
                    ┌──────────────┐      ┌──────────────┐
                    │ 调查报告落盘  │      │ 调查报告落盘  │
                    └──────┬───────┘      └──────┬───────┘
                           │                      │
                           ▼                      ▼
                    ┌──────────────┐      ┌──────────────┐
                    │ Code/Viz 执行 │      │ scRNA 执行   │
                    │ (基于报告)    │      │ (基于报告)    │
                    └──────────────┘      └──────────────┘
```

---

## 六、风险控制与边界

| 风险 | 防控机制 |
|------|----------|
| Explorer 读太多文件，token 爆炸 | `max_files_to_read: 50` + 轻量模型 |
| Explorer 读不到文件，下游 Agent 盲干 | 报告明确标注"未读取"文件，下游 Agent 发现关键文件缺失时应 ask_user |
| Explorer 被递归调用（自己调自己） | `max_hops_per_session: 1` + `subagents_spawnable: false` |
| 侦察报告质量差，误导下游 | 提示词强制结构化输出 + 下游 Agent 保留独立验证权 |
| 只读 Agent 被提示词注入突破 | 工具包白名单硬拦截：未授权的 write/edit 工具在运行时直接报错 |

---

## 七、实施 Checklist（可直接给编码 Agent）

1. **新建文件**
   - [ ] `data/ai/explorer.yaml` — Agent 配置
   - [ ] `data/ai/prompts/explorer.md` — System prompt
   - [ ] `data/ai/tools/workspace_readonly.yaml` — 只读工具包

2. **注册集成**
   - [ ] `data/ai/prompts/registry.yaml` 登记 explorer
   - [ ] `data/CygnusX.yaml` `agents.enabled` 加入 `agent-explorer`
   - [ ] 管理端发布 Agent（或调用 `PUT /api/v1/admin/agents/agent-explorer`）

3. **MAS 集成**
   - [ ] Orchestrator / Manager 的 prompt 增加："涉及代码/文件任务时，第一步调度 agent-explorer"
   - [ ] 下游 Agent（Code、Viz、scRNA）的 prompt 增加："优先读取上游侦察报告，不得忽略已有调查结果重复探索"

4. **测试验证**
   - [ ] Explorer 能正确列出目录、读取文件、输出结构化报告
   - [ ] Explorer 调用 write/edit 工具时收到"未挂载"错误（白名单生效）
   - [ ] MAS 链路：Explorer → Code，下游能读取 Explorer 产物并基于其工作
   - [ ] 同 Wave 并行时，Explorer 失败不中断其他独立任务
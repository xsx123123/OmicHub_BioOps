# Skill 候选区（Skill Candidate Area）

本目录存放由 `agent-skill-builder` 生成、但尚未通过人工/评审确认的 Skill 候选包。
候选包**不会被自动安装或挂载到任何 Agent**；必须经晋升流程进入
`data/ai/skill_marketplace/` 后，才会被平台识别并可供 Agent 挂载。

## 目录约定

```text
data/ai/skill_candidates/           # 仓库侧说明（本文件）
/workspace/skill-candidates/        # 沙箱工作区，agent-skill-builder 的写入位置
/workspace/skill-candidates/<skill_id>/
  ├── SKILL.md
  ├── references/
  │   ├── guide.md
  │   └── environment.md            # 可执行技能必填
  ├── scripts/                      # 可执行技能必填
  │   └── check_env.sh
  └── CANDIDATE_MANIFEST.json       # 候选元数据 + 待评审项
```

## 状态流转

```text
agent-skill-builder 生成候选
        │
        ▼
  skill-candidates/<skill_id>/   (status: candidate)
        │
        ├── 评审不通过 ──▶ 退回修改 / 废弃
        │
        └── 评审通过 ────▶ scripts/promote_skill_candidate.py
                              │
                              ▼
                    data/ai/skill_marketplace/<skill_id>/
                              │
                              ▼
                    在目标 Agent YAML 的 skill_ids 中声明
                              │
                              ▼
                    运行 scripts/sync_builtin_agents.py
                              │
                              ▼
                    平台自动安装并挂载到对应 Agent
```

## 评审 checklist

晋升前必须逐项确认：

- [ ] `SKILL.md` frontmatter 完整：`name`、`skill_id`、`version: 0.9.0`、`category`、`description`；
- [ ] `description` 使用"当【输入】且用户要求【意图】时触发"格式，边界清晰；
- [ ] 正文五段式齐全（何时使用、输入契约、执行步骤、输出契约、质控与限制）；
- [ ] 脚本实体已复制进 `scripts/`，无源仓库/宿主机绝对路径；
- [ ] `references/environment.md` 按 A/B/C/D 四级标注依赖可达性；
- [ ] 可执行技能带 `scripts/check_env.sh` 三重检查（命令/R/Python）；
- [ ] 包总量 ≤ 1MiB，单文件 ≤ 512KB；
- [ ] `CANDIDATE_MANIFEST.json` 的 `pending_review_items` 已处理或接受；
- [ ] skill_id 未与 `data/ai/skill_marketplace/` 或 `data/ai/skills/` 中现有 skill 冲突；
- [ ] 不会导致 L1 路由冲突（与相近 skill 的触发条件有足够区分度）。

## 晋升方式

### 方式一：半自动脚本（推荐）

```bash
# 从沙箱工作区晋升
uv run python scripts/promote_skill_candidate.py \
  --candidate /workspace/skill-candidates/my-skill \
  --admin-user-id '<管理员 UUID>'

# 仅预览，不复制
uv run python scripts/promote_skill_candidate.py \
  --candidate /workspace/skill-candidates/my-skill \
  --admin-user-id '<管理员 UUID>' \
  --dry-run
```

### 方式二：手动

1. 把 `/workspace/skill-candidates/<skill_id>/` 复制到 `data/ai/skill_marketplace/<skill_id>/`；
2. 删除或保留 `CANDIDATE_MANIFEST.json`（marketplace 不需要，但保留也无害）；
3. 在目标 Agent YAML 的 `skill_ids` 中加入该 skill_id；
4. 运行 `uv run python scripts/sync_builtin_agents.py` 或重启服务。

## 废弃与替换

- 废弃候选：直接删除 `/workspace/skill-candidates/<skill_id>/`；
- 替换候选：必须先用 `--replace` 显式授权，`promote_skill_candidate.py` 默认拒绝覆盖
  已存在的 marketplace skill。

## 与 MCP Builder 的对照

| 维度 | MCP Builder | Skill Builder |
| --- | --- | --- |
| 生成目标 | MCP Server（server.py） | Skill 包（SKILL.md + references/scripts） |
| 写入位置 | `/workspace/mcp-builds/<name>/` | `/workspace/skill-candidates/<skill_id>/` |
| 状态 | 实验态，TTL 24h | candidate，持久化到工作区 |
| 提交决策 | 用户手动提交 | 管理员运行晋升脚本或手动复制 |
| 治理核心 | AST 安全检查 | OSDP 合规 + 人工评审 checklist |

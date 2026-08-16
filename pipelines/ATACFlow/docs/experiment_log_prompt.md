# 实验记录整理提示词 / Experiment Log Generation Prompt

请根据我提供的 Git 仓库信息，生成一份**中英双语**的结构化开发实验记录（`EXPERIMENT_LOG.md`）。

要求：
- 所有**标题**采用英文（确保 markdown 锚点和外部引用稳定）。
- 所有**正文内容**采用**中英双语对照**格式：英文在前，中文紧跟其后（用括号包裹或换行并列），或者每个段落先用中文写、再用英文写（但同一小节内两种语言都要完整覆盖）。
- 核心代码注释、表格中的 `Role` / `Risk Factor`、版本时间线的说明等关键信息，必须同时出现中文和英文。
- 我需要的是"**按时间线梳理、带代码片段、突出逻辑变化**"的开发笔记，而不是简单的 commit message 罗列。

---

## 输出格式要求 / Output Format Requirements

文件必须严格遵循以下结构（参考 ATACFlow 的 `EXPERIMENT_LOG.md`），且全文为中英双语：

```markdown
# {项目名} Development & Experiment Log

> **Repository**: {项目名}
> **Version**: {当前版本，如 v0.0.5}
> **Period**: {YYYY-MM ~ YYYY-MM}
> **Generated From**: `git log` history with detailed code diffs

---

## Overview

用 2-3 句话概括这个仓库在本记录周期内的整体演进方向（例如：从初始搭建到加入某核心模块，再到某次大型重构）。

---

## Chronological Experiment Record

按日期升序排列。每一天作为一个 `### YYYY-MM-DD` 标题。

同一天可能有多个 commit，每个 commit 作为一个条目：

#### `{commit_hash}` - {版本号 + 简短标题}

**Scope**: （可选）一句话概括这次改动的范围/目标。

**Code Changes**:
- `文件路径`: 具体做了什么（新增/修改/删除，多少行）。如果涉及多个相关文件，用子 bullet 列出。
- 环境/配置变更也要记录。
- 如果有文件重命名或目录结构调整，单独说明。

**Key {Pipeline/Module/Function} Logic Introduced / Fixed / Refactored**:
- 对于关键逻辑，必须给出代码片段（```python / ```snakemake / ```bash 等）。
- 如果是一次 bug fix，用 diff 风格展示修改前后对比。
- 如果新增了核心函数，给出完整定义和注释。

如果某天包含 **Working Directory / Uncommitted** 的修改，单独作为一个条目：
#### {YYYY-MM-DD} (Working Directory / Uncommitted)

**Scope**: 当前工作区有哪些未提交的进展（WIP）。

**Code Changes in Working Directory**:
1. `文件路径`: 描述改动，给出 diff 或代码片段。

---

## Long-Unmodified Core Components (Compatibility Risk Alert)

扫描整个周期内**从未被修改过（或很久没改）**但又是核心依赖的文件，整理成表格：

| File | Last Modified | Role | Risk Factor |
|------|---------------|------|-------------|
| ... | ... | 这个文件是做什么的 | 如果未来动它，可能会破坏什么 |

---

## Version Timeline

用代码块列出版本演进时间线：

```
YYYY-MM-DD  vX.X.X  一句话说明
YYYY-MM-DD  vX.X.X  一句话说明
...
```
```

---

## 内容深度要求 / Content Depth Requirements

1. **不要只罗列 commit message** / Do not simply list commit messages。每个条目要展开说明：
   - 改了哪些文件？
   - 引入了什么新逻辑？
   - 修复了什么 bug？（最好给出 before/after diff）
   - 为什么这样改？（简要的业务/技术原因）

2. **代码片段要精简但准确**：
   - 只截取最能说明问题的 5-20 行。
   - 新增函数给出签名和核心逻辑。
   - bug fix 用 diff 格式展示关键行。

3. **版本号要连贯**：
   - 如果 commit message 里没有显式版本号，根据 tag 或我的描述推断。
   - 同一天多次提交尽量合并到同一个版本条目下，除非跨度很大。

4. **WIP 也要记录**：
   - 如果有未提交的工作区改动，在对应日期下单独作为一个 "Working Directory / Uncommitted" 条目。

5. **最后加一句 footer（中英双语）**：
   ```
   *Log generated from git history analysis. All code snippets are condensed representations of actual diffs.*
   *本日志基于 git 历史分析生成。所有代码片段均为实际 diff 的精简展示。*
   ```

---

## 输入信息 / Input Information

{在这里粘贴你的 git log、diff、仓库路径，或者直接告诉我仓库根目录 / Paste your git log, diff, repository path, or simply tell me the root directory of the repository}

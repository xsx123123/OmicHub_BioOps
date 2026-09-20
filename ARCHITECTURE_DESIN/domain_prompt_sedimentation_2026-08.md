# Multi-Agent 提示词渐进沉淀架构(冷启动 → 用量感知 → 人工沉淀)

> **时点说明**：本文件为 2026-08-06 时点的设计草案，所述计划已执行或已演进，部分引用（路径、行号）已失效；请勿按本文档再次执行，当前实现以代码为准。

> 日期:2026-08-06 · 状态:设计草案 v1
> 依赖:`docs/26.8.6/prompt/01_提示词框架现状与DomainPack设计.md`(Domain Pack 机制,下称"DP 设计")
> 关联:`docs/26.8.7/`(三模式问题排查)

---

## 1. 问题与愿景

**问题**:当用户提出一个系统没见过的分析任务类型(如 WGS 变异检测、蛋白组学)时,multi-agent 目前只有两种结局——靠 Python 关键词表误命中,或退化为普通对话。理想行为是三态生命周期:

```
阶段 0(未知)     阶段 1(观察)            阶段 2(沉淀)
新任务类型出现 → 模型用通用能力应答     → 同类请求用得多了     → 人工确认后注入系统
                 同时系统默默记录          管理端浮现"领域候选"    成为一等领域资产
                 (不打断用户)             (LLM 协助起草)        (热重载,零代码上线)
```

**关键约束**(用户明确提出):沉淀动作是**人工触发**的,不是自动学出来的;模型起草、人审发布。自动学习的风险(错误知识自我强化、提示注入污染)在本架构中被设计排除。

**结论先行**:现有架构**可以**承接这个能力,且 70% 的积木已经存在——热重载注册表(flow_registry 模式)、管理端 Agent CRUD(`api/v1/admin/agents.py`)、AI 用量埋点(`core/ai_metrics.py` 缓冲写库)、skill 市场、pgvector 知识库、以及 DP 设计中的"空 registry 安全降级"路径。缺的是一个把"未命中事件"变成"人工沉淀入口"的闭环,本文定义这个闭环。

---

## 2. 现状可行性评估

| 能力 | 现状 | 证据 |
|---|---|---|
| 未知任务安全降级(阶段 0 的基础) | ✅ DP 设计已定义:无 domain 命中 → Manager 通用规划 + 主动提问槽位,不误判 | DP 设计 §5.2/§6 |
| 领域资产热重载(阶段 2 生效的基础) | ✅ 模式成熟:`flow_repository.py:109-112` mtime 热重载 + 单文件失败不阻断;DomainRegistry 将沿用 | DP 设计 §6 |
| 管理端编辑 agent/prompt | ✅ Agent CRUD 全套(DB 级):`api/v1/admin/agents.py:28-80` | 已上线 |
| 用量埋点基础设施 | ✅ `core/ai_metrics.py` 缓冲聚合写库 + `ai_metrics_service.py` 趋势/告警查询 | 已上线 |
| 轻/中粒度知识载体 | ✅ skill 市场(36 技能,`use_skill` 按需加载)、pgvector 知识库(`knowledge_index_service.py` + `knowledge_search` 工具) | 已上线,利用率低 |
| **未命中事件记录(感知层)** | ❌ 不存在:路由/overdrive fallback 后无任何留痕 | 需新建 |
| **候选聚合与管理端浮现** | ❌ 不存在 | 需新建 |
| **LLM 起草 + 人审发布工作流** | ❌ 不存在 | 需新建 |

---

## 3. 总体架构:四环闭环

```
        ┌──────────────────────────────────────────────────────┐
        │                     运行时(自动)                      │
        │  用户消息 → 路由/超频认知层 → domain 命中?             │
        │     │是                          │否                  │
        │     ▼                          ▼                    │
        │  领域资产应答            ①感知:通用能力应答            │
        │                          + DomainMissEvent 落库      │
        └──────────────────────────│───────────────────────────┘
                                   ▼
        ┌──────────────────────────────────────────────────────┐
        │                  聚合层(定时,自动)                    │
        │  ②候选:beat 任务聚合 miss 事件 → 指纹聚类/计数        │
        │    超阈值 → domain_candidates 状态 candidate          │
        └──────────────────────────│───────────────────────────┘
                                   ▼
        ┌──────────────────────────────────────────────────────┐
        │                 沉淀层(人工主导,LLM 辅助)            │
        │  ③管理端"领域候选"页 → 查看样本会话 → 选择粒度:       │
        │    轻=知识库条目 / 中=skill / 重=Domain Pack          │
        │    LLM 从样本起草 → 人工编辑 → schema 校验 → 回放测试  │
        └──────────────────────────│───────────────────────────┘
                                   ▼
        ┌──────────────────────────────────────────────────────┐
        │                 生效层(自动,可回滚)                  │
        │  ④发布:写 data/ai/domains/<domain>.yaml(enabled)    │
        │    热重载生效 → 监控该领域 fallback 率变化            │
        │    异常 → enabled:false 一键回滚                      │
        └──────────────────────────────────────────────────────┘
```

---

## 4. ① 感知层:DomainMissEvent

### 4.1 记录时机(三个埋点)

| 埋点 | 位置 | 触发条件 |
|---|---|---|
| 路由未命中 | `chat_service.py` `_route_to_agent` fallback 到 general 处(:2375-2379) | LLM 路由置信度低或解析失败落 general,且消息疑似分析请求 |
| 超频无领域 | `_run_overdrive_turn` 规划阶段 | `_is_overdrive_planning_request`-like 判断中"全局规划词命中但无 domain 命中"(DP 机制上线后 = `registry.match_domains` 为空) |
| 兜底分工 | `_default_overdrive_assignments` 返回空或仅 general 兜底 | Manager 未给出有效分工且无领域规则命中 |

### 4.2 事件内容(新表 `domain_miss_events`)

| 字段 | 类型 | 说明 |
|---|---|---|
| id | uuid | |
| created_at | timestamptz | |
| user_id | uuid | 用于去噪(同一用户重复问算一次趋势) |
| session_id | varchar | 溯源样本会话(沉淀时给管理员看上下文) |
| source | enum | `router_fallback` / `overdrive_no_domain` / `default_assignment_fallback` |
| message_excerpt | varchar(500) | **脱敏后**的用户消息摘要(复用 `chat_service.py:4343` 的脱敏机制;文件路径/样本名替换为占位符) |
| message_fingerprint | varchar(64) | 聚合指纹,见 §5.1 |
| resolved_agent_id | varchar | 实际由谁应答(通常是 agent-general) |
| user_satisfied | bool/null | 后续 3 条消息内用户无"不对/重新/换个"类纠正 → 视为通用能力已胜任(此类不再进候选,见 §5.3) |

写入方式:复用 `core/ai_metrics.py` 的内存缓冲 + 周期 flush 模式,**不在请求路径同步写库**。

---

## 5. ② 候选聚合层

### 5.1 指纹与聚类

- 初级(规则):`message_fingerprint` = 消息中领域名词的规范化组合——对 excerpt 做 jieba/正则抽取名词性 n-gram(英文取小写词干),排序后 hash。同一指纹 ≈ 同一任务类型。
- 进阶(可选):对 excerpt 算 embedding(pgvector 现成),按余弦 0.85 聚类。**v1 只做规则指纹**,embedding 聚类留作 v2。

### 5.2 候选生成(beat 任务,每日一次)

新表 `domain_candidates`:

| 字段 | 说明 |
|---|---|
| fingerprint | 主键 |
| hit_count_7d / hit_count_30d | 滑动窗口计数 |
| sample_session_ids | 最多 5 个代表会话(供人工审阅) |
| suggested_domain | LLM 建议的 domain 标识(聚合任务顺便调一次 LLM 命名) |
| status | `candidate` / `drafting` / `published` / `dismissed` |
| draft_yaml | LLM 起草的 Domain Pack 草稿(§6.2) |
| reviewed_by / reviewed_at | 人审留痕 |

**浮现阈值**(可配,`core/config.py`):`hit_count_7d >= 10 AND distinct_users_7d >= 2`——避免单一用户的个性化需求污染公共领域库。

### 5.3 反候选(同样重要)

- `user_satisfied = true` 的事件不参与计数:模型通用能力已经答好了,**不需要**为它沉淀——这防止领域库无边界膨胀,呼应"提示词不能越来越重"的总原则;
- 连续两次被管理员 `dismissed` 的指纹永久进黑名单表,不再浮现。

---

## 6. ③ 沉淀层:三种粒度 + LLM 起草 + 人审

### 6.1 粒度决策树(管理端引导)

```
该候选的知识形态是什么?
├─ 经验性事实(阈值、坑、解读口径,如"DESeq2 低计数过滤经验")
│   → 轻:知识库条目(knowledge_index_service 灌库,立即生效,零 schema)
├─ 操作性流程(可复用的分析套路,如"ggtree 美化既有树的步骤")
│   → 中:skill(data/ai/skill_marketplace/,挂到相关 agent 的 skill_ids)
└─ 一类重复出现的任务(需要 intake 澄清、专属分工、路由判歧)
    → 重:Domain Pack(DP 设计 §4 schema 全量)
```

轻→重可以升级:知识库条目用多了发现需要槽位澄清,再提炼为 Domain Pack。

### 6.2 LLM 起草(管理端一键"生成草稿")

输入:候选的 5 个样本会话消息 + DP schema 的 JSON Schema 导出(参照 `application/schemas/flow.py:export_flow_json_schema` 的既有模式)。
输出:`draft_yaml`,填充 `match.domain_markers`、`intake.questions/slots`、`assignments.rules` 骨架。
**起草提示词里必须声明**:markers 从样本消息原文提取,不得虚构;`prompt_injections.manager_notes` ≤ 800 字符(schema 已有硬约束)。

### 6.3 人审与回放测试(发布闸门)

管理端编辑器提供三个闸门,全绿才允许发布:

1. **schema 校验**:复用 DP 的 `DomainPack` pydantic 模型(加载期校验规则直接复用,§4.3);
2. **回放测试**:用候选的样本消息跑 `registry.intake_questions / extract_slots / assignment_rules`(注册草稿到临时 registry 实例),与"当时实际发生了什么"并排展示——管理员直观看到"如果当时有这个 pack,系统会怎么问/怎么派";
3. **冲突检查**:新 pack 的 `domain_markers` 与现有 pack 的 markers 求交,交集非空时提示"可能与 omics 领域抢命中",要求人工确认优先级(字母序规则在 DP §5.3 已定义)。

### 6.4 权限

复用 `AdminRequired`(与 `admin/agents.py` 一致);发布动作写审计日志(谁、何时、发布了哪个 domain、diff)。

---

## 7. ④ 生效层:热重载、灰度与回滚

- **生效**:审核通过 → 写 `data/ai/domains/<domain>.yaml`(该目录纳入 git 管控,天然有版本史)→ DomainRegistry mtime 热重载,**无需重启**;
- **灰度**:schema 的 `enabled` 字段先以 `false` 落盘,管理员在候选页"启用"——等价于 Feature Flag;
- **回滚**:`enabled: false` 即下线,认知层立刻退回通用降级路径(因为降级是一等路径,回滚零风险);
- **效果监控**:每个已发布 domain 跟踪两个指标(复用 ai_metrics 趋势查询):①该领域消息的 fallback 率(应显著下降);②发布后 7 天内该 domain 命中的会话中用户纠正率(应不高于发布前)。异常时在管理端标黄。

---

## 8. 与既有设计的关系

| 依赖项 | 关系 |
|---|---|
| DP 设计(P1 registry) | **硬依赖**:感知层的"domain 命中与否"判定、回放测试、热重载全部建立在 DomainRegistry 之上。本文的闭环在 DP 的 P1–P4 完成后才有意义 |
| DP §8 回归用例 | 每个发布的 pack 应附带把样本消息固化为新的 R 用例,进入 `test_domain_pack_regression.py`——领域库增长的同时回归网同步变厚 |
| `docs/26.8.7` 排查 | 感知层埋点依赖路由 fallback 的可观测性,建议与 26.8.7 的 H2(路由失败静默)修复合并实施——同一块代码 |
| 知识库/skill | 本文的轻/中粒度出口就是这两个既有机制,不新建轮子 |

---

## 9. 分阶段实施

| 阶段 | 内容 | 前置 |
|---|---|---|
| V0(1–2 天) | `domain_miss_events` 表 + 三个埋点(缓冲写库)+ 脱敏 | 无(可先于 DP 上线,先攒数据) |
| V1(2–3 天) | `domain_candidates` + 每日聚合 beat + 管理端只读候选列表页 | V0 攒 1–2 周数据后调阈值 |
| V2(3–4 天) | LLM 起草 + schema 校验 + 回放测试 + 发布/回滚 | **DP 的 P1(registry)必须已完成** |
| V3(可选) | embedding 聚类、效果监控指标面板、知识库/skill 粒度的一键沉淀入口 | V2 |

**反模式声明**(写进开发规范):

1. ❌ 禁止"自动发布"——LLM 起草永远是草稿,人审是唯一发布通道;
2. ❌ 禁止把 miss 事件原文(未脱敏)写库或送入 LLM 起草——样本引用 session_id,起草时实时取数并脱敏;
3. ❌ 禁止为 `user_satisfied=true` 的任务沉淀——通用能力能胜任的不进领域库;
4. ❌ Domain Pack 不承载方法论细节(那是 skill/知识库的位置),`manager_notes` 800 字符上限不放宽。

---

## 10. 一句话总结

> 模型的通用能力负责"第一次也能答",DomainMiss 感知负责"记住被问了多少次",人工沉淀负责"常用的一劳永逸"——提示词的增长从"被动的、堆叠的"变成"有入口、有闸门、有回滚的资产化管理"。

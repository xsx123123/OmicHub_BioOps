# 协作室融合 Claude Science 设计理念：评估与实施方案

> 版本：v1.0 ｜ 日期：2026-08-21
> 输入材料：《Claude Science 逆向工程设计评论》（用户上传）
> **硬约束（用户原话，全文不可触碰）**：不修改平台愿景前提——L4 定位与"升级规则即成本闸门"、Manager 五项职责（接单/派单/验收/交付/例外处理）、专家层四段契约（capabilities/not_suitable_for/handoff_when/preferred_inputs，含 agent-data/agent-qc/agent-delivery 内部角色）、甲方完整回路（需求确认书→澄清卡→显式审批→进度时间线→交付验收→返工入口，系统不得替甲方作答）。

---

## Part 1 评估 verdict：契合矩阵

**总结论：Claude Science 的设计哲学与协作室现有架构是同一世界观的两个实现。吸收方式为"哲学层吸收、架构层不动"——愿景前提零改动。**

Claude Science 是单用户科研工作台（一个 operon 主 agent + 三个内部裁剪 agent）；协作室是多智能体 + 甲方治理的部门制平台。两者形态不同，但七条核心原则中六条在协作室已有对应锚点：

| # | Claude Science 原则 | 协作室现状锚点 | 判定 |
|---|---|---|---|
| 1 | Artifact-first（产物优先，显式保存才可见，引用用稳定 version_id） | proposed_submission 完成门（无产物不得交付）、A1 交付物化修复、MinIO 事件流对象化 | **增强吸收**（F1） |
| 2 | Provenance by construction（execution_log + artifact_versions[checksum/environment_snapshot/lineage] + artifact_dependencies DAG） | 审计总线、causation_event_id 因果链、MinIO 快照 envelope、B2 evidence 防伪 | **增强吸收**（F1，补产物级血缘） |
| 3 | Grounding over generation（compute don't confabulate；能查就查、inline assert 当场验、能力先 search_skills 再声称） | agent-data 数据契约预检、preferred_inputs 输入契约、B2 审计防伪 | **直接吸收**（F3 行为规范） |
| 4 | Purpose-shaped agents（用 excluded_tools/enable_thinking 做减法定角色，每个开关附 bench 证据） | 四段契约、chat_entry=false 内部角色、recruitable:false 人格分层 | **增强吸收**（F6/F7，补"测量证据注释"文化） |
| 5 | Progressive disclosure（description 级索引，按需加载正文） | 能力目录（capabilities catalog）、MCP 工具注册表 | **直接吸收**（F5） |
| 6 | Reviewer rubric（非对称举证：找到矛盾才定罪；claims + verification_checks 结构化判决；按证据位置加权严重度） | agent-qc 质量审计、Manager 验收职责 | **增强吸收**（F2，qc 从"审文本"升级为结构化判决） |
| 7 | 测量驱动（配置即调优记录，改动附 mean±stddev 实测） | 四档状态制、E2E 验收文化 | **直接吸收**（F7 工程文化） |
| 8 | Declarative compute（ENVS 声明 → Dockerfile/Slurm/Modal） | 无对应——属 L1 工具箱/算力编排层 | **不入协作室**，仅吸收 environment_snapshot 进血缘（见 F1） |
| 9 | Self-extension（skill-creator 在线造/改技能 + 量化 eval 闭环） | 无对应——与"升级规则即成本闸门 + 显式审批"冲突 | **降格**：离线 eval 闭环可用，在线自扩展不做（见 Part 4） |

**两条关键边界判定**：

1. **"解释而非命令"只是 prompt 写作风格，不是治理模型。** Claude Science 自己也是这么做的——它的 artifact 可见性、工具裁剪都是 harness 机制强制，不是靠 prompt 恳求。因此协作室的硬闸门（无 proposed_submission 不得交付、系统不得替甲方作答、显式审批、成本闸门）**继续留在代码里强制**，F6 的"解释风格"只应用于行为规范层（怎么写交付、怎么说明拒绝理由），不应用于闸门层。
2. **"LLM 是聪明的"第一性假设与甲方回路不冲突。** Claude Science 不信任模型的是"记忆与事实"（一切去查），信任的是"理解了 why 之后的边界判断"。协作室可以完全照搬这个分工：事实类（数据、血缘、花费、历史）一律查库查表；判断类（怎么拆解、怎么组织语言）给足 why。

---

## Part 2 吸收总原则（三条红线）

施工全程不可逾越：

1. **红线一：愿景前提不动。** L4 定位与成本闸门、Manager 五职责、专家四段契约、甲方完整回路，一个字不改。本方案所有落地项都是在这套骨架上"加装仪器"，不是改骨架。
2. **红线二：硬门留代码。** 完成门、审批、甲方作答权、token 配额，维持代码/状态机强制；Claude Science 风格只进入 prompt 与配置注释层。凡是"开了会出事"的约束，禁止依赖模型自觉。
3. **红线三：事实皆查询。** 吸收其最彻底的一条——agent 对"自己的事实"（血缘、花费、跑过什么、上游是谁）不许凭记忆回答，一律落到审计总线/血缘库查询。这与既有"前端表现不作系统事实证据"的工程原则同源。

---

## Part 3 落地项 F1–F7

> 每项结构：现状锚点 → Claude Science 借鉴 → 改造 spec → 验收。依赖关系见 Part 5 排期。

### F1 产物血缘：artifact_versions + 依赖 DAG（增强吸收，最高价值）

**现状锚点**：审计总线已有 business/operational 事件分级、causation_event_id 因果链；MinIO 化已把事件流对象化（cases/{case_id}/events/audit.jsonl + 快照 envelope）；A1 修复打通了产物注册。**缺的是产物级血缘**：哪个交付物由哪段代码/哪个任务产出、依赖哪些上游产物、内容指纹是什么。

**借鉴**：self-awareness 的三张表——execution_log（每次执行记 source + stdout + files_written 的 sha256）、artifact_versions（版本号 + checksum + environment_snapshot + lineage）、artifact_dependencies（产物 DAG：上游数据变了，沿 DAG 找哪些图要重跑）。

**改造 spec**：
- 新增 `case_artifact_versions` 表：artifact_id、version_no、case_id、producing_event_id（指向审计事件，复用因果链）、checksum_sha256、size、content_type、storage_uri（MinIO 对象键）、environment_snapshot（JSON：worker 版本、镜像/依赖锁摘要、关键参数）、created_at。
- 新增 `case_artifact_dependencies` 表：downstream_artifact_id、upstream_artifact_id、relation（input_to/derived_from）。
- 产物注册（现有 proposed_submission → 确认登记路径）时强制写入 version 行；Worker 上报产物时必须携带 `source_refs`（输入产物 id 列表 + 执行摘要），缺失则登记拒绝并回写 `room.artifact_rejected` 审计事件（例外显式化，不静默兜底）。
- 交付汇总（agent-delivery）生成甲方报告时，文末自动附"血缘清单"：每个交付物的 version_id、checksum、上游依赖一级展开。
- environment_snapshot 只记录"可复现所需的最小事实"（worker 版本 + 依赖锁哈希 + 参数），**不做** ENVS 声明式环境抽象（那是 L1 的事，见 Part 4）。

**验收**：
- 任意交付物可回答三个问题：谁产出的（producing_event_id 可追溯）、内容是否被篡改（checksum 重算比对）、上游变了影响谁（沿 DAG 查询）。
- 缺 source_refs 的产物登记被拒且审计可见。

### F2 证据化验收：agent-qc 升级为 claims + verification_checks（增强吸收）

**现状锚点**：Manager 验收职责已有完成门（产物结构 + 证据 + 质量指标）；agent-qc 定位是质量审计。**现状短板**：qc  verdict 是自然语言结论，不可统计、不可复核、误判率不可测。

**借鉴**：reviewer rubric 的可迁移结构（文档第三章，可直接当模板）：
1. **非对称举证原则**：找到矛盾才定罪，找不到不定罪——防假阳性的地基。
2. **按证据位置加权严重度**：持久产物（交付物）严格、即时对话宽松。
3. **唯一例外开口子**：对"声称已检索/已计算的可核对标识符"（如声称查了某数据库给出数值），找不到来源也定罪——这是抓编造引用的专门条款，边界划清。
4. **核查后才判**：能打开的来源必须打开，不许未尝试就报"无法验证"。
5. **不许报清单**：约整数、格式改动、保义改写等假阳性来源显式排除。

**改造 spec**：
- qc 输出从自由文本改为结构化 JSON：`claims[]`（从交付物中抽取的可证伪断言：断言原文、位置、类型）+ `checks[]`（每条 claim 的判决：pass/warn/fail/inconclusive + 证据指针 + 理由）。
- 判决落库 `qc_verification_checks` 表（case_id、claim_hash、verdict、evidence_event_id、reviewer_agent、created_at）——判决变成可统计的表行，qc 质量本身可测量（pass/warn/fail 分布、后续返工率交叉验证）。
- rubric 正文按上面五条结构写进 agent-qc 的 YAML，**用"解释 why"的风格**（见 F6），每条规则附"它防的是什么失败"。
- Manager 验收门升级：交付前要求 qc 的 checks 中 fail=0 且 inconclusive 有人工/甲方裁决路径；fail>0 走返工入口（既有甲方回路），禁止静默修复。

**验收**：
- qc  verdict 100% 结构化入库；随机抽 20 条历史交付，人工复核 qc 判决的假阳性/假阴性率可统计。
- 编造引用条款生效：构造"声称查了 ClinVar 给出频率"但实际未查的样本，qc 必须 fail。

### F3 反幻觉行为规范：compute, don't confabulate（直接吸收）

**现状锚点**：agent-data 管数据契约预检；preferred_inputs 契约已要求专家声明输入。**短板**：行为规范层没有明文"能查就查、不许编"的条款，也没有"能力先查注册表再声称"的约束（对应 v3 复审 C2 的回落静默问题）。

**借鉴**：operon working_style 三规矩——需要数据就取不许猜；取回的标识符才是真相之源；用技能前先 search_skills 确认存在，不脑补。

**改造 spec**（写进 agentteams 各角色 YAML 的 working_style 层，不动人格层）：
- Manager 与所有专家角色增加行为规范三条：①涉及数据/数值/文献的结论必须来自工具返回或产物血缘，禁止凭训练记忆给出具体数值；②声明"我能做 X"前先查能力目录确认 X 在 capabilities 内，不在则按 not_suitable_for/handoff_when 转交；③交付中引用其他产物必须用 version_id（不用文件名，防同名碰撞歧义）。
- 与既有修复衔接：能力目录查询失败/未命中时的行为显式化——回问甲方或转交，**禁止静默回落**（落实 v3 复审 C2 的既定结论）。

**验收**：构造"问一个需要真实数据的数值问题 + 数据库不可用"场景，专家必须显式报告无法获取并回问，不得编造数值。

### F4 自省查询面：审计总线的只读查询接口（增强吸收）

**现状锚点**：统一审计总线（audit-chain 查询）已是 L4 前置之一并落地。**短板**：查询面是给开发者/前端的，agent 自身（Manager 例外处理、qc 复核）没有结构化的"查自己历史"通道，只能依赖上下文记忆——记忆会漂移，日志不会。

**借鉴**：self-awareness 的 host.query——只读、scoped（自动限定当前 case/room）、配 schema 文档当"自我认知地图"；denied 清单（密钥类、攻击面配置类、宿主身份）纵深防御，且防别名绕过。

**改造 spec**：
- 审计总线新增只读查询端点（供 Bridge 内部角色调用）：`query_case_facts(room_id/case_id, 预置查询模板或受限 SQL)`，scope 强制限定当前 case；返回行数上限 + 服务端聚合（防行数截断低估）。
- 预置查询模板覆盖高频自省：本 case 已登记产物及版本、本 case 事件时间线、本 room 待办审批、产物血缘一级展开。
- denied 范围：API 密钥/worker token 表、其他租户/其他 room 数据、宿主基础设施信息——按词边界匹配拒绝，防别名绕过。
- schema 文档（表与列的说明）作为内部角色的可加载知识，对应 F5 的渐进暴露。

**验收**：Manager 处理"这个产物是哪来的"类例外时，审计事件显示其走了查询接口而非自由发挥；越 scope 查询被拒且有审计记录。

### F5 渐进暴露的能力目录（直接吸收）

**现状锚点**：能力目录（capabilities catalog）是派单依据；MCP 工具注册表已统一。**短板**：随着能力/工具增多，全量注入上下文会撑爆预算并淹没决策（Claude Science 用 29 skills + 87 数据源实测过这个问题）。

**借鉴**：三级渐进披露——常驻只有一句话 description（触发条件）；需要时加载正文；requirements 字段按需判断资源。description 不是说明书，是"触发分类器"（写清"什么时候该用它"，必要时可以强势，如"Stop and consult"式措辞）。

**改造 spec**：
- 能力目录条目拆两层：`summary`（一句话触发条件，常驻注入 Manager 派单上下文）+ `detail`（四段契约全文 + 输入示例，组队会诊/派单确认时才加载）。
- 每条能力的 description 按"触发分类器"标准重写：含适用场景与**不适用**场景（呼应 not_suitable_for），不写空泛能力吹嘘。
- Manager 派单 prompt 只注入 summary 层；选中候选后才加载 detail——这与三件套 D1（路由圈候选集 → LLM 组队会诊）天然衔接：路由层用 summary，会诊层用 detail。

**验收**：派单上下文 token 量可对比下降（附数字进配置注释，见 F7）；能力新增后无需改 Manager prompt 即可被发现。

### F6 Prompt 写作规范：解释而非命令（直接吸收，文化项）

**借鉴**：skill-creator 宣言——"If you find yourself writing ALWAYS or NEVER in all caps, that's a yellow flag — reframe and explain the reasoning"。解释把判断力交给模型，命令把模型变成查表机器；堆砌 MUST 是过拟合。

**改造 spec**：
- 存量 YAML/prompt 文件审查：把 ALWAYS/NEVER 式禁令改写为"规则 + 为什么 + 例外边界"。示例（反 emoji 类）：不写"禁止编造数据"，写"你给出的每个数值都会被 agent-qc 对照血缘库追溯（见 F2），编造数值会被判 fail 并触发返工——所以拿不到数据时，明确说拿不到并回问甲方，这比猜一个数对你更有利"。
- **红线二同时生效**：只改行为规范层的文风；完成门/审批/成本闸门的代码强制一字不动，prompt 里也不软化工单语义。
- 每条新 prompt 规则自检三问：它防的具体失败是什么？例外在哪？模型理解 why 后能否在规则没写到的场景自行正确判断？

**验收**：抽查改写后的角色文件，无全大写禁令残留；用边界 case 实测（规则没覆盖的场景），模型行为仍正确。

### F7 测量驱动文化：配置即调优记录（直接吸收，文化项）

**借鉴**：reviewer 关 thinking 的注释范式——"Measured (bench, 6 reps): thinking 占 72% token、召回零提升"，配置文件同时是实验日志；改动靠数字支持，不靠"感觉更好"。

**改造 spec**：
- 协作室相关配置（token 上限、并发数、超时、limit、快照阈值等"魔数"）注释规范：每个值回答"怎么知道是这个数"——实测数据、或上游契约（如服务端硬限 ≤100）、或显式标注"待测"。
- 配置/角色/prompt 类 PR 模板增加一栏：**证据**（bench 结果 / E2E 编号 / 上游契约引用）。
- 例外条款同步写明（借鉴其"什么改动可以不跑 eval"）：纯文案修正、注释更新可豁免。
- 离线 eval 闭环（Part 4 降格项）的产出物作为此类证据的首选来源。

**验收**：新增魔数配置 100% 带证据注释；CI 可对"新增数值配置无证据注释"告警（不阻断，先观察）。

---

## Part 4 降格与不入项（明确不做什么，同样重要）

### F8 Declarative compute（ENVS 声明式环境）→ 不入协作室

ENVS 解决的是"异构算力上一次定义处处运行"，属 L1 工具箱/算力编排层的命题。放进协作室会侵入 L1/L4 边界、稀释本方案焦点。**只吸收一个子集**：environment_snapshot 作为血缘字段进 F1（记录"产物在什么环境产生"的可复现最小事实），不做环境声明抽象。未来若 L1 要做环境管理，可单独立项再借鉴其 pip_phases 有序性等设计。

### F9 Self-extension（在线自我扩展）→ 降格为离线 eval 闭环

Claude Science 的 skill-creator 让系统在线造/改技能并量化迭代。**与愿景前提冲突**：协作室的能力变更必须走显式审批与成本闸门，agent 不得自行扩展能力面（这与"系统不得替甲方作答"同源——能力治理权在甲方/管理员）。

**降格吸收**：把它的 eval 方法论拿来做**离线**质量闭环——draft → test → 对照 eval（带配置 vs baseline）→ mean±stddev 报告 → 人工决策是否合入。首个应用场景：**Manager 组队质量评测**（呼应三件套 D1）：固定 20-30 个真实需求样本，对比"路由圈选 vs LLM 会诊"的组队方案质量与 token 成本，产出数据再决定组队策略权重。这把 F7 的"证据"要求落到了最有价值的配置上。

---

## Part 5 排期与总验收

### 与既有施工线的关系

当前双线任务书（三件套 ∥ 地基 e2e）**优先级不变、不打断**。本方案排在三件套之后作为独立批次，理由：F2/F4 依赖审计总线（已就绪），F5 与 D1 组队衔接（D1 落地后能力目录才有真实规模压力），F1 依赖 MinIO 化与产物注册（已就绪）。F3/F6/F7 是纯 YAML/规范项，无代码依赖，**可与三件套并行**由另一分支先行。

### 建议顺序

| 波次 | 内容 | 依赖 |
|---|---|---|
| W0（可立即并行） | F6 prompt 规范 + F7 配置证据规范 + F3 行为规范 | 无 |
| W1 | F1 产物血缘（表 + 登记硬约束 + 交付血缘清单） | 审计总线、MinIO 化（已就绪） |
| W2 | F2 证据化验收（qc 结构化判决 + rubric 改写） | F1（证据指针落到血缘） |
| W3 | F4 自省查询面 + F5 渐进暴露能力目录 | F1（查询内容含血缘）；F5 与 D1 衔接 |
| W4 | F9 离线 eval 闭环首用：Manager 组队质量评测 | 三件套 D1 落地 |

### 编码 Agent 提示词（paste-ready，按波次取用）

**W0 提示词**：

```
在协作室现有角色配置基础上做 prompt 工程规范化，禁止改动任何代码逻辑、状态机、API 行为：
1. 先读 agentteams 相关 YAML/prompt 文件（Manager 与专家角色），列出所有 ALWAYS/NEVER/必须/禁止 式禁令清单。
2. 逐条改写为"规则 + 为什么 + 例外边界"三段式：说明该规则防的具体失败、模型违反后会被什么机制抓到（完成门/qc 追溯/审计），给出例外情形。
3. 给 Manager 与专家角色增加三条行为规范：①数据/数值/文献结论必须来自工具返回或产物血缘，拿不到就明说并回问甲方，禁止凭记忆给数值；②声明能力前先查能力目录，不在 capabilities 内按 not_suitable_for/handoff_when 转交，禁止静默回落；③引用产物必须用 version_id 不用文件名。
4. 红线：完成门、显式审批、成本闸门、系统不得替甲方作答——这些语义的代码强制一处不动；prompt 层不得出现软化这些闸门的措辞。
5. 配置证据规范：找出协作室相关配置中的数值型"魔数"（token 上限/并发/超时/limit/快照阈值），逐个补注释说明取值依据（实测/上游契约/待测），并给出 PR 模板新增"证据"栏的文案。
交付：改动 diff + 禁令改写对照表 + 魔数注释清单。验收：边界 case 实测（规则未覆盖场景）行为正确；硬门相关代码零改动（git diff 证明）。
```

**W1–W4 提示词**：各波次开工前按 F1/F2/F4/F5/F9 的 spec 展开（结构：现状锚点 → 改造 spec 原文 → 验收条款），届时从本文档对应章节直接复制即可，不重复占位。

### 总验收 checklist（操作 → 期望现象 → 不通过处理）

| # | 验收项 | 操作 | 期望现象 | 不通过处理 |
|---|---|---|---|---|
| V1 | 产物血缘三问 | 任取一个交付物 | 能答：谁产出（事件可追溯）/内容未篡改（checksum 重算一致）/上游影响谁（DAG 可查） | 查登记链路哪环缺 source_refs |
| V2 | 登记硬约束 | 构造缺 source_refs 的产物上报 | 登记被拒 + room.artifact_rejected 审计可见 | 禁止静默兜底，查硬约束是否旁路 |
| V3 | qc 结构化 | 跑一个完整 case | checks 表有行、fail=0 才过完成门 | 查 qc 输出 schema 校验 |
| V4 | 编造引用条款 | 构造"声称查库实际未查"样本 | qc 判 fail，走返工入口 | 校准 rubric 例外条款边界 |
| V5 | 反幻觉行为 | 数据库不可用时问数值问题 | 显式报告无法获取并回问，零编造 | 检查行为规范是否注入对应角色 |
| V6 | 自省查询 | Manager 处理产物来源类例外 | 走查询接口且审计可见；越 scope 被拒 | 查 scope 限定与 denied 匹配 |
| V7 | 渐进暴露 | 对比派单上下文 token | 可量化下降（数字进注释）；新增能力免改 prompt 可发现 | 查 summary/detail 分层是否生效 |
| V8 | 硬门零软化 | git diff + 边界实测 | 完成门/审批/成本闸门代码零改动；prompt 无软化措辞 | 回退越界改动 |
| V9 | 愿景前提零改动 | 对照本文档开头硬约束逐条 | L4 定位/Manager 五职责/四段契约/甲方回路全部原样 | 整批回退，重新评审 |

---

## 附：本方案与用户既有文档的关系

- 与《协作室愿景深化三件套实现方案》：F5 衔接 D1 组队，F9 首用场景是评测 D1 质量；本方案不打断三件套施工。
- 与《Manager人格分层实施手册》：F3/F6 的行为规范写入 working_style 层，人格分层禁区（general.yaml 三模式共享）依然不可触碰。
- 与 v3 复审 8 项清单：F3 第②条落实 C2（回落静默显式化）的既定结论；F1 是 A1（交付物化）的血缘深化。
- 与安全止血（B1/B2/B3）：F1 的 checksum + producing_event_id 是 B2 evidence 防伪的产物级补强；F4 的 denied 设计复用 B 类安全审查的纵深防御思路。

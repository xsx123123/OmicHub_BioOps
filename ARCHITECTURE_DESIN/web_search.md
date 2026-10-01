# AgentSearch 网络搜索现状调研报告

**调研日期**: 2026-09-20
**调研方法**: 多源交叉验证（GitHub API 实测 + Hacker News Algolia API + searx.space 官方监控数据 + Web 搜索 + 本地部署核查）

---

## 执行摘要

AgentSearch（brcrusoe72/agent-search）是一个 2026 年 2 月创建的年轻项目：自托管搜索 API + MCP server，打包 SearXNG，零 API key、一条命令部署，定位为 Tavily/Exa/Serper 的开源替代。**81 stars / 13 forks、单维护者（64/65 次贡献）、无正式 release tag、7 月 7 日后主分支零 commit**——健康度属于"个人项目活跃期已过峰值"状态。技术上其 17 端点 + 分层提取 + Tor 匿名栈的设计在同类中独特，但其底层 SearXNG 引擎健康度是硬约束：**searx.space 官方监控数据显示 Brave（25/36 实例错误率≥50%）和 DuckDuckGo（21/40）当前大面积被上游封禁，Brave 恰是该项目 issue #45 专门 pin 版本保活的引擎**。结论：**作为自用/小团队的低成本搜索层 = 有条件 Go（须接受引擎可用性波动）；作为生产级 Tavily 替代 = No-Go（单维护者 + 引擎被封风险 + 无 SLA）**。对本平台（OmicHub/CygnusX）而言，现有 `search_provider_service` 的 provider 注册表已覆盖 Tavily/Exa/Bocha/Zhipu/SearXNG，引入 AgentSearch 的增量价值主要在分层内容提取（`/read` 9 级降级链）和 prompt injection 清洗，搜索主链路价值有限。

---

## 1. 项目健康度评估

| 指标 | 数值 | 趋势 | 数据来源 |
|------|------|------|----------|
| GitHub Stars | 81 | 缓慢增长（2026-02 创建） | GitHub API 实测 2026-09-20 |
| Forks | 13 | — | GitHub API |
| 最近 commit | **2026-07-07**（"docs: tone down README language"） | ⚠️ 主分支 2.5 个月零 commit | GitHub API |
| 总 commit 数 | 30 | 高度集中：6/5–6/9 共 16 个，6/21 单日 11 个 | GitHub API |
| 正式 Release | **无 tag**（CHANGELOG 有 "2.0.0" 和 "Unreleased" 条目但未打 tag） | 无版本化交付 | GitHub tags API（空） |
| Open issues | 7（其中 3 个是 Dependabot 自动 PR） | 响应慢：#47（9/12 提出 prepaid meter 方案）0 回复 | GitHub API |
| Merged PRs | 12 | 主要 merge 自己的分支 + Dependabot | GitHub API |
| 贡献者 | **2 人**（brcrusoe72 64 次、blueewhitee 1 次） | 单维护者项目 | GitHub contributors API |
| 社区活跃度 | HN 两次 Show HN（2026-04-21、04-23），各 5 points / 0-1 评论 | 无实质社区讨论 | hn.algolia.com API 实测 |
| PyPI SDK 下载 | `agent-search` 包最近一月 93 次、本周 11 次 | 极低，无外部用户证据 | pypistats.org API |
| 文档口径 | README 明确承认 "0 → 17 frameworks per hunt" 案例来自作者自己的 agent（"the wolf"） | 案例即作者自用 | README 原文 |
| CI 治理 | CodeQL + Dependabot + Compose 校验已配置（Unreleased 条目） | 治理完善但未发版 | CHANGELOG.md |
| 许可 | 根项目 MIT；mcp-server/ 子目录 **AGPL-3.0** | 双许可需注意 | README |

**健康度判定**：代码质量与工程治理（pinned digest、constant-time auth 比较、live smoke test）超出 81-star 项目的平均水准，但**发布纪律（无 tag）、社区规模（2 贡献者、93 月下载）、维护节奏（7 月后停更）**三项均指向"作者自用工具开源"而非"社区驱动项目"。依赖它需接受单点维护风险。

---

## 2. 技术能力验证

### 2.1 搜索引擎可用性

**第一手数据：searx.space 官方监控（93 个实例，2026-09-20 拉取）**

| 引擎 | 错误率≥50% 的实例数 | 错误率<20%（健康）的实例数 | 状态 |
|------|------|------|------|
| Google | 2/32 | **23/32** | ✅ 多数实例健康（Nokia UA 修复后回升，issue #6570 已关闭） |
| Bing | 1/8 | **7/8** | ✅ 健康（issue #4964 "Bing 结果不相关" 已通过 PR #6671 修复关闭） |
| Brave | **25/36** | 4/36 | ❌ 大面积 "too many requests"（issue 2026-07-12） |
| DuckDuckGo | 21/40 | 2/40 | ❌ CAPTCHA 频发（issue 2026-08-30 已修复但仍脆弱） |
| Startpage | 39/40 | 0/40 | ❌ 几乎全军覆没 |
| Wikipedia | 1/40 | 39/40 | ✅ 稳定 |

**本机直接探测（2026-09-20）**：Google 200、Bing 200、DuckDuckGo 202（challenge 页）、Brave 429（rate limited）——与监控数据一致。

**关键交叉验证**：AgentSearch 自己的 issue #45（2026-09-05，作者提交）承认 **"The March 2026 SearXNG pin left Brave, DuckDuckGo, and Google unresponsive, so ordinary /search collapsed onto Bing junk"**，处置方式是把 SearXNG pin 到 2026.9.5。这直接印证：AgentSearch 的默认搜索质量随 SearXNG 引擎被封状态大幅波动，且**当前（2026.9.5 pin）Brave/DuckDuckGo 仍是大面积故障引擎**——#45 修复的是 pin 过旧的问题，而非引擎本身。

**官方文档 vs 实测差异**：README 宣称 bundled 配置启用 25 引擎，并把 Google/Startpage/Yahoo/Reddit 归为 "best-effort explicit sources rather than defaults because they are commonly blocked or empty"——这一表述与 searx.space 实测一致（诚实），但意味着**默认兜底引擎恰是 Brave/DDG 这两个当前故障最重的**。

### 2.2 内容提取能力

- **提取链**：README 宣称 10 级降级（direct → readability → UA rotation → browser render → Wayback → Google Cache → search-about → custom adapters → PDF → YouTube transcript），SSRF 防护、prompt injection 检测、paywall 检测内建于每次请求。
- **JS 渲染**：独立 `/providers/browser/fetch` 端点，ephemeral context + 高成本资源类型默认阻断。**官方明确声明"报告 CAPTCHA/challenge 页而非绕过"**——不做反爬对抗，这是设计取舍不是缺陷。
- **直接提取成功率**：**未验证**。项目无可公开查询的性能指标页，tests 全部 mock SearXNG（README 自述），live 集成测试需自建实例。README 中无任何成功率数字。
- **Paywall 检测**：有检测逻辑（`killchain.py`），检测到后走 Wayback/Google Cache 降级——Google Cache 的可用性 README 自己承认 "unreliable"。
- **本机核查**：本机 `ipsa` 容器（dbrademan/ipsa）是**蛋白质注释平台（PeptideAnnotator），与 AgentSearch 无关**；本机未部署 AgentSearch，无法做 live 端点验证。

**判定**：提取架构设计（分层降级 + 失败上报 + evolver 自适应）在开源同类中独特且有深度，但**无独立实测数据佐证宣称的效果**，宣称指标均出自作者自己的 agent 案例。

---

## 3. 替代方案对比矩阵

| 方案 | 成本（每千次查询） | 自托管 | 提取能力 | 维护难度 | 推荐指数 |
|------|------|------|------|------|------|
| **AgentSearch** | 免费（服务器成本自理） | ✅ Docker 一条命令 | ✅ 多策略 + 浏览器渲染 + prompt injection 清洗（同类独有） | 中（SearXNG 引擎 pin 需人工盯） | ★★★☆☆（自用）；★★☆☆☆（生产） |
| **SearXNG 原生** | 免费 | ✅ | ❌（只给链接） | 中低（社区 37k stars、日更活跃） | ★★★☆☆ |
| **Tavily** | ~$8 PAYG（批量有效价可低至 ~$0.58–1.50） | ❌ | 基础 | 零 | ★★★★☆ |
| **Exa** | $5（agentic Re Search $10） | ❌ | 基础 | 零 | ★★★★☆（语义/学术查询最强） |
| **SerpAPI** | ~$5.50（批量）~$15（Starter） | ❌ | ❌ | 零 | ★★☆☆☆（涨价后性价比降） |
| **Brave Search API** | $3–5 | ❌ | AI Grounding 附加 | 零 | ★★★★☆（批量最便宜） |
| **Jina Reader** | 免费层 20 RPM 无 key；付费 ~$0.02/1M tokens | 部分 | ✅ 单页渲染强 | 零 | ★★★☆☆ |
| **Firecrawl** | 免费层 ~500 credits；托管付费 | ✅（开源版） | ✅ 站点级爬取最强 | 零（托管）/中（自托管） | ★★★★☆ |
| **Crawl4AI** | 免费 | ✅ | ✅（Playwright + LLM 抽取，83k stars） | 中（0.x 版本未到 1.0） | ★★★★☆（自托管爬取首选） |
| **ScrapeGraph AI** | 免费（LLM 费用另计） | ✅ | ✅ LLM 驱动管道（31k stars） | 中高（LLM 成本） | ★★★☆☆ |
| **Bing Search API（已死）** | — | — | — | — | ☠️ 2025-08-11 已退役，仅存量合同可用；替代品 Azure "Grounding with Bing" 无免费层、绑定 AI Agents |

**成本交叉验证**：Tavily 官方价 2025 年从 $5/1k 涨到 $8/1k（多来源确认）；SerpAPI Starter 从 $50/mo 涨到 $75/mo；Brave Data for AI $3/1M 起为批量最便宜。**自托管经济账**：AgentSearch 栈（SearXNG ~0.1-0.5 核 / 100-250MB + Redis + API 容器）可跑在最低配 VPS（~$5/月），日均 1 万次查询摊薄后 < $0.02/千次——比任何托管 API 便宜 1-2 个数量级，前提是接受引擎可用性波动和运维时间成本。

**AgentSearch 定位辨析**：它不是与 Tavily 同层的"搜索质量"竞争者，而是**"Tavily 的成本曲线 + 原生 SearXNG 没有的 agent 专属加工层"**（去重、跨引擎评分、injection 清洗、失败分析进化）。其独特卖点在加工层而非搜索质量——搜索质量上限被 SearXNG 锁死。

---

## 4. 生产部署建议

### 4.1 适合场景

- **个人/小团队的 agent 搜索层**：日均几百到几千次查询，一台低配 VPS 即可，成本趋近于零。
- **数据出域敏感场景**：查询词不经过第三方 API（Tor 栈更进一步，ISP 只见 Cloudflare TLS 和 Snowflake 流量）。
- **需要统一提取接口**：`/read` 一站式 10 级降级 + Wayback 兜底，替代自拼 requests+readability+playwright。
- **学术/垂直搜索为主的 agent**：`/search/strategy` 的 academic 模式直连 arXiv/Crossref/OpenAlex/Semantic Scholar（不经被封的通用引擎），是当前最稳的路径。

### 4.2 不适合场景

- **需要 SLA 的生产服务**：单维护者、无 release、引擎可用性随上游波动，无法承诺可靠性。
- **日均 10 万+ 查询**：瓶颈不在算力（SearXNG 单实例 1.2 QPS 均值毫无压力）而在**上游引擎 IP 级封禁**——需要代理池/多出口 IP 架构，AgentSearch 未提供任何此类能力，README 自己也说高并发应把 query logging 移到外部库（SQLite WAL 是瓶颈）。
- **反爬对抗需求**：浏览器渲染明确报告 CAPTCHA 而不绕过；需要对抗的场景应选商业方案或 residential 代理 + 自建。
- **多租户**：bearer auth 是"共享服务 token"，非多用户授权系统（README 原文）。

### 4.3 部署架构建议

若采用，建议：**standard 栈（:3939）承载日常查询，`/engines` 端点纳入监控告警**（引擎状态是活文档）；academic/community/code 等 strategy 模式优先于 general 模式（前者走直连 provider 不受引擎封禁影响）；pinned SearXNG digest 升级前按作者要求先在 throwaway 容器做 live 引擎对比；不用 Tor 栈除非确有匿名需求（Snowflake 实测吞吐仅 ~30-80 KB/s，Tor Project 官方 issue #40021 确认，search 场景勉强可用但明显变慢）。

---

## 5. 风险提示

### 5.1 技术风险

- **单维护者**：64/65 次贡献来自同一人，bus factor = 1。
- **无 release tag**：CHANGELOG 存在但从未打 tag，升级只能追 main 分支。
- **引擎 pin 策略是双刃剑**：pin 保稳定但积累漂移，#45 事件（March pin 导致三引擎全灭、搜索塌缩到 Bing 垃圾结果）证明了这类故障的真实发生方式。
- **MCP SDK 版本锁**：mcp 依赖被刻意锁在 1.27.x（issue #48 正在讨论放开到 <2.3.0），与 SDK 2.x 生态存在版本摩擦（本平台 2026-09-17 审计已发现 SDK 2.0 inputSchema bug 误报 stdio MCP 的同类问题）。
- **SQLite 遥测**：in-memory 遥测重启即失，query stats 用 SQLite WAL，高并发需外移（README 自认）。

### 5.2 法律风险

- **ToS 违规是现实约束**：Google ToS 明确禁止自动化访问 Search 结果；SearXNG 类元搜索本质上违反上游引擎 ToS。但判例面（hiQ v. LinkedIn、Meta v. Bright Data）显示**公开数据抓取的实际法律后果主要是 IP 封禁而非诉讼**，个人/小规模自托管风险极低。
- **规模化即风险升级**：商业用途、公开托管实例、大流量会显著提高风险敞口。
- **Tor 栈的合规悖论**：匿名化在隐私敏感场景是卖点，但在企业合规审计中可能反而成为红灯（出口流量不可审计）。
- **数据隐私**：自托管意味着查询数据不出域，这是相对托管 API 的合规优势（Tavily/Exa 均可见查询内容）。

### 5.3 运维风险

- **引擎被封频率**：searx.space 数据显示 Brave/DDG/Startpage 当前是重灾区；Google 靠 UA 猫鼠游戏维持（#6359 → Nokia UA → #6570 再次失效的循环）。**pin 的 digest 越旧，故障面越大**——这是必须持续投入的运维项。
- **CAPTCHA 处理**：项目不做绕过（设计如此），遇到即降级或失败，需接受结果质量波动。
- **单点故障**：Tor/Snowflake 栈实测 30-80 KB/s 且志愿代理高流失（arXiv 1904.08595 + Tor issue #40021/#40058），CoreDNS→Cloudflare DoT 是单依赖。
- **SearXNG 版本更新策略**：AgentSearch 用 pinned digest，**不会自动跟随 SearXNG 上游修复**——上游引擎适配修复（如 Bing PR #6671）需要项目方主动 re-pin 才能受益。

---

## 6. 结论与行动建议

### 结论：有条件 Go（自用层）；No-Go（生产替代）

- **Go 的条件**：定位为"低成本搜索 + 统一提取层"，接受引擎波动，保持学术/垂直 strategy 模式为主路径，监控 `/engines`。
- **No-Go 的边界**：不可作为唯一搜索依赖进入有可靠性要求的生产链路；不可指望它替代 Tavily 的搜索质量——它替代的是 Tavily 的**账单**，不是 Tavily 的**效果**。

### 分阶段实施路径（针对本平台）

1. **不引入（当前状态，推荐）**：OmicHub `search_provider_service` 的 provider 注册表（Tavily/Exa/Bocha/Zhipu/SearXNG/scrape）已覆盖主流路径，SearXNG 预设已存在；AgentSearch 的增量价值仅在提取层，而平台现有 WebFetch/爬取链路可满足当前需求。
2. **试点引入（若提取需求升级）**：单容器部署 standard 栈（不启 Tor），仅消费 `/read`、`/read/batch`、`/search/extract` 三个端点作为提取增强层，搜索主链路仍走现有 provider 注册表；`/engines` 纳入现有健康审计（对照 2026-09-17 MCP 健康审计模式）。
3. **观察期触发条件**：项目打出第一个 release tag、维护者恢复 commit 节奏、或 mcp SDK 2.x 兼容落地（issue #48 合并）时，重新评估升级为搜索层候选。

---

## 附录

### 参考链接

**官方/一手数据**
- AgentSearch 仓库：https://github.com/brcrusoe72/agent-search
- searx.space 官方实例监控（instances.json，2026-09-20 拉取）：https://searx.space
- SearXNG 仓库（37,384 stars，日更）：https://github.com/searxng/searxng
- Hacker News（Algolia API 实测）：https://hn.algolia.com/api/v1/search?query=AgentSearch
- PyPI 下载统计：https://pypistats.org/package/agent-search

**SearXNG 引擎健康相关 issue（一手）**
- Brave "too many requests"（2026-07-12）：searxng/searxng issues
- DuckDuckGo captcha（2026-08-30，已修复）：searxng/searxng issues
- Google Nokia UA 封禁循环 #6570（引用 #6359/#6546）：https://github.com/searxng/searxng/issues/6570
- Bing 结果不相关 #4964（已由 PR #6671 修复）：https://github.com/searxng/searxng/issues/4964

**AgentSearch 关键 issue（一手）**
- #45 SearXNG pin 到 2026.9.5 保活 Brave/DDG：https://github.com/brcrusoe72/agent-search/issues/45
- #47 prepaid meter 提议（0 回复）：https://github.com/brcrusoe72/agent-search/issues/47
- #48 mcp SDK 版本放宽讨论：https://github.com/brcrusoe72/agent-search/issues/48

**托管 API 定价**
- Tavily：https://tavily.com（$8/1k PAYG，1k 免费/月）
- Exa：https://exa.ai（$5/1k，Re Search $10/1k）
- SerpAPI：https://serpapi.com（Starter $75/mo）
- Brave Search API：https://brave.com/search/api（Data for AI $5/1M 起）

**竞品仓库（GitHub API 实测 stars，2026-09-20）**
- Firecrawl：182,486 | Crawl4AI：83,949 | ScrapeGraph AI：31,151 | Jina Reader：12,024 | mcp-searxng：1,249

**行业背景**
- Bing Search API 2025-08-11 退役（TechCrunch / Azure 官方通告）：https://techcrunch.com/2025/05/01/microsoft-retires-bing-search-api-developers-scramble/
- Tor Snowflake 吞吐 30-80 KB/s（Tor GitLab issue #40021；arXiv 1904.08595）
- SearXNG 官方资源文档（0.1-0.5 核 / 100-250MB / worker ~100MB）：https://docs.searxng.org

**中文社区**
- 检索到同名/类似中文项目（Tiger-Leo/agent-search，中文场景聚合器）与 cnbang 对比文，但**未找到针对 brcrusoe72/agent-search 的独立中文社区评测**——标注：中文社区独立评价缺失。

### 数据验证方法说明

| 数据项 | 验证方式 | 置信度 |
|------|------|------|
| 仓库指标（stars/commits/issues/contributors） | GitHub REST API 直接拉取，双命令交叉（gh + curl） | 高 |
| 引擎可用性 | searx.space 官方监控 93 实例聚合 + 本机直接 curl 探测上游（Google 200/Bing 200/DDG 202/Brave 429） | 高（两独立来源一致） |
| AgentSearch 引擎故障自述 | 项目自己 issue #45 原文 | 高 |
| 托管 API 定价 | Web 搜索多来源（官方站 + CloudZero/Bright Data 对比文），注意 Tavily $5→$8 的口径差 | 中高 |
| 竞品 stars | GitHub API 单来源 | 高（数字本身）/ 低（未交叉验证第二时间点） |
| Snowflake 吞吐 | Tor 官方 issue + arXiv 论文，两独立来源 | 高 |
| AgentSearch 提取成功率 | **未验证**——项目无公开指标，tests mock 上游 | 无数据 |
| HN/Reddit 社区反馈 | HN 经 Algolia API 实测（两次 Show HN，各 5 points）；Reddit 引用来自搜索摘要，**未直接访问原帖，标注为低置信** | 中低 |
| 本机部署核查 | `ipsa` 容器实为蛋白质注释平台，确认与 AgentSearch 无关；本机未部署 AgentSearch | 高 |

**核心不确定项汇总**：① AgentSearch 17 端点的 live 可用性与提取成功率（本机未部署，官方无公开指标）；② Reddit/HN 上独立用户实测的深度细节；③ Tavily 批量档有效单价随套餐变动，引用时须以官方页为准。

---

# 附：SearXNG 自托管搜索已落地（2026-09-21 实施记录）

依据上文结论第 2 阶段（试点引入），已完成 SearXNG 自托管实例部署并接入平台网络搜索主链路。**零代码改动**——平台 `search_provider_service` 早已内建 searxng provider 预设（`SEARCH_PROVIDER_PRESETS`）+ 前端管理页 + `WebSearchService._searxng` 适配器，缺的只是实例与配置。

## 落地架构

```
┌────────────────────────────────────────────────────────┐
│                 CygnusX 平台（现状，未改动）              │
│  chat web_search 工具 (runtime_support.py:939)          │
│        │                                               │
│  SearchProviderService.search_default()                │
│        │  读 search_provider_configs 表（is_default）    │
│  WebSearchService (provider_id="searxng")              │
│        │  GET {base_url}/search?q=&format=json          │
└────────┼───────────────────────────────────────────────┘
         │ http://searxng:8080（cygnusx_app_net 内部）
┌────────▼───────────────────────────────────────────────┐
│              SearXNG 自托管栈（新增）                     │
│  searxng       :8898→8080  pin 2026.9.19-e831fc2a1     │
│    ├─ settings.yml：limiter:false + JSON 格式启用        │
│    ├─ 引擎分片按健康度（见下表）                          │
│  searxng-cache redis:7    内部网络，不暴露端口            │
└────────────────────────────────────────────────────────┘
```

## 交付物

| 文件 | 内容 |
|------|------|
| `deploy/docker/docker-compose.searxng.yml` | SearXNG + Redis 两容器；加入 `cygnusx_app_net`；资源限制 0.5 核/256M；healthcheck `/healthz` |
| `deploy/docker/docker-compose.yml` | `cygnusx-web` 同时加入稳定命名的 `cygnusx_app_net`，与独立 SearXNG 栈连通 |
| `deploy/docker/searxng/settings.yml` | 引擎白名单/黑名单（基于本报告 §2.1 调研数据）；`limiter: false`（私有实例官方推荐）；JSON 格式启用 |

## 关键实施决策

| 决策 | 选择 | 理由 |
|------|------|------|
| 镜像 tag | `2026.9.19-e831fc2a1`（日期+commit digest） | Docker Hub 无 `2026.9.12` tag；pin digest 防漂移，升级前先做 live 引擎对比 |
| 宿主机端口 | **8898** | 方案文档原定 8888 已被 cygnusx-nginx 占用 |
| limiter | `false` | 私有实例仅平台容器访问，limiter 会拦无浏览器指纹的 JSON API 调用（SearXNG 官方推荐私有实例关闭） |
| 部署路径差异 | 代码/配置卷挂载，DB 注册 | 未采用方案文档 §3 的独立 Provider 类——平台已有 provider 注册表，重写反而制造双注册表债（对照 [[L4 愿景实现状态]] 双注册表教训） |
| Wikidata | live 验证后补禁 | 首启后 `unresponsive_engines` 报 `Suspended: too many requests`，重启后空 |

## 引擎配置（2026-09-20 调研 + 2026-09-21 live 验证）

| 引擎 | 状态 | 依据 |
|------|------|------|
| Google / Bing | ✅ 启用 | searx.space 23/32、7/8 实例健康；本机探测 200 |
| Wikipedia / GitHub / StackOverflow / arXiv / PubMed / Bing News / Reuters | ✅ 启用 | 直连 API 类，稳定 |
| Brave / DuckDuckGo / Startpage / Qwant | ❌ 禁用 | 错误率≥50% 实例占比 25/36、21/40、39/40、30/37 |
| Wikidata | ❌ 禁用 | 本实例 live：`Suspended: too many requests` |

## 平台侧配置（DB，非代码）

主栈和 SearXNG 栈必须使用同一个 Docker 网络。主栈 compose 已为 `web` 加入
`cygnusx_app_net`，SearXNG compose 通过同名外部网络加入。该网络由 `make docker-network`
统一创建（也可手动创建），不依赖两个 Compose 项目的启动顺序：

```bash
make docker-network
docker compose -f deploy/docker/docker-compose.searxng.yml up -d
# 网络变更后必须重建 web，使运行中的容器获得新网络
docker compose --env-file .env -f deploy/docker/docker-compose.yml up -d --force-recreate web
docker network inspect cygnusx_app_net
```

`make docker-reload` 已包含 SearXNG 栈的启动步骤；它会先清理旧的 `cygnusx-*` 容器，再重新
启动主栈和 SearXNG。单独执行 `docker compose -f deploy/docker/docker-compose.searxng.yml up -d`
也可以只启动或重启搜索服务。

验证容器内的 DNS 和 HTTP 链路：

```bash
docker exec cygnusx-web getent hosts searxng
docker exec cygnusx-web curl -fsS 'http://searxng:8080/search?q=test&format=json' | jq '.results | length'
```

不要把平台侧 `base_url` 填成宿主机可见但容器不可解析的地址；在 `cygnusx-web` 容器内应填写
`http://searxng:8080`。如果后端不是 Docker 容器运行，则应改填宿主机发布端口对应的地址，
例如 `http://127.0.0.1:8898`。

```sql
-- search_provider_configs
searxng: base_url=http://searxng:8080, is_enabled=true, is_default=true
zhipu : 保留 enabled，is_default=false（降为备用）
```

首次接入或网络配置变更后使用 `docker compose ... up -d --force-recreate web`，确保运行中的
`cygnusx-web` 获得共享网络；仅修改数据库里的 provider 配置时，`docker restart cygnusx-web`
即可生效（provider 配置无缓存键，重启即读新值）。

## 验证结果（2026-09-21 全部通过）

| 验证项 | 结果 |
|------|------|
| 宿主机 JSON 搜索 `:8898` | 36 条结果，`unresponsive_engines: []` |
| 平台容器内访问 `http://searxng:8080` | 200，36 条 |
| `test_provider('searxng')` | 连接成功 |
| `availability()` | available=True / "SearXNG 自建" |
| `search_default` 英文查询 | 5 条（PMC/Nature/ScienceDirect，2.0s） |
| `search_default` 中文查询 | 5 条（知乎/教程，2.3s） |

## 与方案文档（`docs/info/26.9.21/web_s.md`）的差异说明

方案文档中的多实例+学术专用实例、Redis 两级缓存、智能路由、熔断器、Prometheus 告警均为**远期扩展，本次未实施**——当前查询量下单实例已足够（本机实测均值 2s/查询，SearXNG 官方口径 0.1-0.5 核/100-250MB 单实例 1.2 QPS 均值无压力）。后续触发条件：日均查询量接近千级、或学术检索需求明确时，按方案文档 Phase 2/3 扩展。降级路径已天然存在：SearXNG 故障时管理后台切回 zhipu 即可（同表 is_default 切换，无需改代码）。

## 运维要点

- **升级镜像**：先在 throwaway 容器做 live 引擎对比，再改 compose 里的 pin tag（对照 AgentSearch issue #45 的 March pin 事故——pin 过旧导致三引擎全灭）。
- **引擎健康巡检**：`curl http://localhost:8898/search?q=test&format=json | jq '.unresponsive_engines'`；非空时按 settings.yml 注释里的 searx.space 数据决定禁用与否。
- **日志**：`docker logs searxng`；配置变更 `docker restart searxng`（settings.yml 为 rw 卷挂载，容器内 sed 亦可，但宿主机文件属主是容器 UID 977，宿主机直改需注意权限）。
- **回退**：管理后台 → 搜索服务商 → 智谱 Zhipu → 设为默认，即刻回退到付费 API 链路。

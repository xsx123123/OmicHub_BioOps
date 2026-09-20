# Europe PMC MCP 检索工具

`europe_pmc_search` 是内置 `cygnusx-platform` MCP 的只读开放网络工具，面向生物医学研究问题检索 Europe PMC。

## 输入

- `query`：必填。推荐使用 2–4 个核心概念或短语，通过 `AND` / `OR` 联合。
- `max_results`：返回 1–20 条，默认 8；研究计划和问答推荐保留 5–8 条。
- `year_from` / `year_to`：可选发表年份范围。
- `open_access_only`：可选，仅保留开放获取论文。

## 处理流程

1. 请求 Europe PMC REST API 的 `core` 结果，候选数高于最终返回数。
2. 统一 PMID、PMCID、DOI、作者、期刊、年份、摘要和可追溯链接。
3. 按原始研究问题对题名和摘要执行嵌入语义分数与关键词覆盖度混合重排。
4. 未配置嵌入模型或嵌入服务失败时，自动回退到标题加权的词项重排。
5. 去重后仅返回最相关结果，不下载或解析论文全文。

## 配置

环境变量可覆盖以下设置：

- `WEB_SEARCH_SEMANTIC_RERANK_ENABLED=true`
- `WEB_SEARCH_EMBEDDING_MODEL=<embedding model>`；留空时复用 `AGENT_MEMORY_EMBEDDING_MODEL`。
- `WEB_SEARCH_REFINEMENT_CACHE_TTL_SECONDS=86400`

查询精炼结果优先写入 Redis，并保留进程内降级缓存；相同研究问题在 TTL 内不会重复触发模型精炼。

## 边界

- 工具结果用于证据发现，不代表论文质量、因果关系或临床有效性已经得到确认。
- 摘要缺失时仅返回书目信息，Agent 应明确证据限制。
- 医疗高风险结论仍需结合原文、研究设计和专业人员复核。

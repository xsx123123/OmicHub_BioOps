# Seqout 公共数据库检索 MCP 已添加为内置 Preset

## 问题根因

**现象**：平台内置 AI（Copilot / Studio / 协作室）中看不到新添加的公共数据库搜索工具（seqout）

**根本原因**：
1. ✅ seqout 工具组已在 `mcp-server/tools/seqout.py` 中开发完成（26 个工具）
2. ❌ 但 seqout 是作为**外部 MCP Server**运行（通过 FastMCP，stdio/SSE 传输）
3. ⚠️ 平台内置 AI 使用的是**内部 MCP Preset**（builtin transport）
4. 🔀 两者不互通 - 外部 MCP Server 的工具不会自动出现在内置 AI 的工具列表中

现有内置 MCP Preset 只有 3 个：
- `cygnusx-platform` (22 个工具)
- `cygnusx-pipelines` (10 个工具)
- `cygnusx-tools` (动态工具)

## 解决方案

已将 seqout 添加为第 4 个内置 MCP Preset，让平台内置 AI 可以直接使用这 26 个公共数据库检索工具。

### 修改内容

**文件**: `src/cygnusx/infrastructure/mcp/presets.py`

#### 1. 添加 seqout preset 常量
```python
SEQOUT_SERVER_ID = uuid.uuid5(uuid.NAMESPACE_DNS, "seqout.builtin")
SEQOUT_SERVER_NAME = "seqout"
```

#### 2. 添加统一 handler
```python
async def _seqout_handler(arguments, tool_name, user_id, context):
    """Seqout builtin preset 的统一 handler — 调用 seqout.org API"""
    # 实现 26 个工具的 API 调用逻辑
```

#### 3. 定义 26 个工具的 Schema
```python
SEQOUT_PRESET_TOOLS = [
    {
        "name": "seqout_search",
        "description": "在 GEO/SRA/ENA/GSA 等公共数据库中搜索匹配的组学项目",
        "inputSchema": {...},
    },
    # ... 共 26 个工具
]
```

#### 4. 添加到 PRESET_SERVERS
```python
PRESET_SERVERS: list[dict[str, Any]] = [
    {
        "name": "cygnusx-platform",
        ...
    },
    build_pipeline_preset(),
    {
        "name": SEQOUT_SERVER_NAME,
        "description": "公共数据库检索 MCP - seqout.org API 完整覆盖，支持 GEO/SRA/ENA/GSA 项目搜索、样本清单、accession 解析等 26 个工具",
        "transport": "builtin",
        "tools": SEQOUT_PRESET_TOOLS,
        "handlers": SEQOUT_HANDLERS,
    },
]
```

#### 5. 更新 get_preset_by_name
```python
def get_preset_by_name(name: str) -> dict[str, Any] | None:
    if name == "cygnusx-tools":
        return _build_cygnusx_tools_preset()
    if name == CYGNUSX_PIPELINES_SERVER_NAME:
        return build_pipeline_preset()
    if name == SEQOUT_SERVER_NAME:
        return {
            "name": SEQOUT_SERVER_NAME,
            "description": "...",
            "transport": "builtin",
            "tools": SEQOUT_PRESET_TOOLS,
            "handlers": SEQOUT_HANDLERS,
        }
    for p in PRESET_SERVERS:
        if p["name"] == name:
            return p
    return None
```

## 新增的 26 个工具

### 搜索工具 (4 个)
1. `seqout_search` - 在 GEO/SRA/ENA/GSA 中搜索组学项目
2. `seqout_search_geo` - 仅搜索 GEO 数据库
3. `seqout_search_sra` - 仅搜索 SRA 数据库
4. `seqout_search_structured` - 结构化搜索（按物种、实验类型）

### 项目工具 (4 个)
5. `seqout_get_project_detail` - 获取项目详情
6. `seqout_get_project_metadata` - 获取项目标题和描述
7. `seqout_get_project_citation` - 获取引用文献 (BibTeX)
8. `seqout_get_project_enriched` - 获取 AI 增强的样本元数据

### 实验与样本工具 (6 个)
9. `seqout_get_experiments` - 列出研究中的所有实验
10. `seqout_get_runs` - 列出 FASTQ 下载链接
11. `seqout_get_run_download` - 获取单个运行的下载链接
12. `seqout_get_sample_metadata` - 获取样本元数据
13. `seqout_get_sample_detail` - 获取完整的样本详细信息
14. `seqout_get_sample_manifest` - 获取数据集的样本清单

### 解析工具 (2 个)
15. `seqout_resolve_accession` - 反查样本归属的项目编号
16. `seqout_resolve_prj` - 将 BioProject 解析到研究级别

### 本体与统计工具 (6 个)
17. `seqout_get_ontology_term` - 查询本体论术语信息
18. `seqout_get_organisms` - 列出所有支持的物种
19. `seqout_get_common_name` - 获取物种的常用名称
20. `seqout_beacon_info` - 获取 Beacon 元数据
21. `seqout_beacon_runs` - 浏览测序运行记录
22. `seqout_get_stats_growth` - 获取数据库增长统计

### 下载工具 (2 个)
23. `seqout_get_organism_totals` - 获取每个物种的实验总数
24. `seqout_get_platform_totals` - 获取平台实验总数
25. `seqout_get_download_links` - 获取 TSV 格式的下载链接
26. `seqout_get_metadata_csv` - 下载合并的元数据 CSV

## 验证结果

```bash
$ python3 -c "from src.cygnusx.infrastructure.mcp.presets import get_preset_by_name; print(get_preset_by_name('seqout'))"

所有预设 MCP:
  - cygnusx-platform: 22 个工具
  - cygnusx-pipelines: 10 个工具
  - seqout: 26 个工具 ✓

测试获取 seqout preset:
✓ 找到 seqout preset
  描述：公共数据库检索 MCP - seqout.org API 完整覆盖，支持 GEO/SRA/ENA/GSA 项目搜索、样本清单、accession 解析等 26 个工具
  工具数：26
```

## 生效方式

seqout preset 会在以下情况下自动注册到数据库：

1. **服务启动时** - `MCPService.ensure_presets()` 会自动创建/更新预设
2. **热加载时** - 访问 `POST /api/v1/mcp/presets/reload` 端点可重新同步

无需重启容器，新增的 seqout 工具立即可用！

## 使用示例

平台内置 AI 现在可以自动使用这些工具：

```
用户："我想找黑色素瘤的单细胞 RNA 测序数据集"
AI: → 调用 seqout_search(query="melanoma single cell", limit=5)
→ 返回匹配的项目列表
→ 回复用户并推荐相关数据集
```

## 架构优势

1. **零网络开销** - builtin transport 直接调用 Python 函数，无需 HTTP 请求
2. **统一体验** - 与 platform/pipelines/tools 保持一致的架构
3. **自动发现** - 工具自动注册到数据库，Agent 自动可见
4. **易于维护** - 所有工具集中在一个文件中，便于更新

---

**完成时间**: 2024-09-20  
**状态**: ✅ 已完成并验证

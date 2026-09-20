# Seqout MCP Tools — 完整 API 覆盖

## 概述

Seqout MCP Server 提供了对 [seqout.org](https://seqout.org) 公共数据库检索 API 的**完整覆盖**，包含 **26 个 MCP Tools**，涵盖搜索、项目详情、样本清单、本体论查询、统计分析和下载链接等所有主要功能。

## 架构定位

在 CygnusX 的 **"自主规划与工具链调度"** 架构中，本 MCP Server 承担前置的 **公共数据检索与元数据解析（Data Ingestion & Discovery）** 职能。

### 核心设计原则

1. **上下文窗口保护** - 所有返回列表的工具都有限制参数，防止大模型调用时因返回超长 JSON 导致上下文窗口爆炸
2. **统一错误处理** - 所有工具捕获速率限制 (429)、超时、HTML 错误页等非 JSON 响应
3. **规范输出格式** - 遵循 `{success, summary, data, next_steps?}` 统一返回格式
4. **只读工具** - 所有工具均为只读操作，无破坏性风险

## 工具分类与映射

### 1. Search Tools (4 个)

| Tool Name | API Endpoint | Description | Context Limit |
|-----------|--------------|-------------|---------------|
| `seqout_search` | `GET /search` | 在 GEO/SRA/ENA/GSA 中搜索组学项目 | limit=5 (default) |
| `seqout_search_geo` | `GET /search/geo` | 仅搜索 GEO 数据库 | limit=5 (default) |
| `seqout_search_sra` | `GET /search/sra` | 仅搜索 SRA 数据库 | limit=5 (default) |
| `seqout_search_structured` | `GET /search/structured` | 使用元数据过滤器结构化搜索 | limit=5 (default) |

**示例**:
```python
# 搜索单细胞黑色素瘤数据集
result = await seqout_search(query="melanoma single cell", limit=3)
# 返回: {"success": true, "summary": "找到 3 个项目", "data": [...]}
```

### 2. Project Tools (4 个)

| Tool Name | API Endpoint | Description |
|-----------|--------------|-------------|
| `seqout_get_project_detail` | `GET /project/{accession}` | 获取项目详细元数据 |
| `seqout_get_project_metadata` | `GET /project/{accession}/metadata` | 获取项目标题和描述 |
| `seqout_get_project_citation` | `GET /project/{accession}/cite` | 获取 BibTeX 引用文献 |
| `seqout_get_project_enriched` | `GET /project/{accession}/enriched` | 获取 AI 增强的样本元数据 |

**示例**:
```python
# 查看 GSE12345 项目详情
result = await seqout_get_project_detail(accession="GSE12345")
```

### 3. Experiment & Sample Tools (7 个)

| Tool Name | API Endpoint | Description |
|-----------|--------------|-------------|
| `seqout_get_experiments` | `GET /project/{study}/experiments` | 列出研究中的所有实验 |
| `seqout_get_runs` | `GET /project/{study}/runs` | 列出 FASTQ 下载链接 |
| `seqout_get_run_download` | `GET /run/{run}` | 获取单个运行的下载链接 |
| `seqout_get_sample_metadata` | `GET /sample/{accession}` | 获取样本元数据 |
| `seqout_get_sample_detail` | `GET /sample-detail/{accession}` | 获取完整的样本详细信息 |
| `seqout_get_sample_manifest` | `GET /geo/series/{accession}/samples` | 获取数据集的样本清单 |

**示例**:
```python
# 获取样本清单（用于筛选目标样本）
result = await seqout_get_sample_manifest(accession="GSE120575", max_samples=30)
# 返回结构化的 characteristics 字段，包含组织来源、处理组标记
```

### 4. Resolution Tools (2 个)

| Tool Name | API Endpoint | Description |
|-----------|--------------|-------------|
| `seqout_resolve_accession` | `GET /accession/{accession}/project` | 反查样本归属的项目编号 |
| `seqout_resolve_prj` | `GET /prj/{prj_accession}` | 将 BioProject 解析到研究级别 |

**示例**:
```python
# 从 GSM 编号反查 GSE 项目
result = await seqout_resolve_accession(accession="GSM123456")
# 返回: {"accession": "GSE12345", ...}
```

### 5. Ontology & Statistics Tools (6 个)

| Tool Name | API Endpoint | Description |
|-----------|--------------|-------------|
| `seqout_get_ontology_term` | `GET /ontology/term` | 查询本体论术语信息 |
| `seqout_get_organisms` | `GET /organisms` | 列出所有支持的物种 |
| `seqout_get_common_name` | `GET /common-name` | 获取物种的常用名称 |
| `seqout_beacon_info` | `GET /beacon/info` | 获取 Beacon 元数据 |
| `seqout_beacon_runs` | `GET /beacon/runs` | 浏览测序运行记录 |
| `seqout_get_stats_growth` | `GET /stats/growth` | 获取数据库增长统计 |
| `seqout_get_organism_totals` | `GET /stats/organism-totals` | 获取每个物种的实验总数 |
| `seqout_get_platform_totals` | `GET /stats/platform-totals` | 获取平台实验总数或过滤选项 |

### 6. Download Tools (2 个)

| Tool Name | API Endpoint | Description |
|-----------|--------------|-------------|
| `seqout_get_download_links` | `GET /project/{study}/runs/download` | 获取 TSV 格式的下载链接 |
| `seqout_get_metadata_csv` | `GET /project/{study}/metadata/download` | 下载合并的元数据 CSV |

## 上下文窗口保护策略

为防止大模型调用时因返回超长 JSON 导致上下文窗口爆炸，所有返回列表的工具都设置了默认限制：

- **Search 工具**: `limit=5` (默认最多返回 5 条结果)
- **Sample Manifest**: `max_samples=30` (默认最多返回 30 个样本)
- **Beacon Runs**: `limit=10` (默认最多返回 10 条记录)

用户可以根据需要调整这些参数，但建议保持较小值以保持上下文轻量化。

## 错误处理

所有工具都实现了统一的错误处理机制：

1. **速率限制 (429)**: 返回友好的错误消息 "触发速率限制 (Rate Limit)，请稍后重试"
2. **HTML 错误页**: 检测并拒绝 HTML 响应，避免 JSONDecodeError
3. **超时**: 15 秒超时设置，返回 "请求超时" 错误
4. **无效 Accession**: 返回失败状态和描述性错误消息

## 与 CygnusX 工作流对接

当 Agent 调用上述 MCP 工具完成检索后，可以直接组装出平台底层的声明式执行配置：

```yaml
pipeline:
  name: "scRNA-Seq Analysis from Public GEO"
  version: "1.0"
  
inputs:
  study_accession: "GSE151530"  # 由 seqout_search 确定
  target_samples:               # 由 seqout_get_sample_manifest 筛选
    - GSM4579998
    - GSM4579999
  
steps:
  - name: "fetch_metadata"
    tool: "download_gse_data"
    params:
      format: "anndata"
      
  - name: "run_seurat_qc"
    container: "registry.cygnusx.org/bio/seurat:v5"
    script: "qc_and_harmony.R"
```

## 测试验证

完整的测试套件位于 `tests/test_seqout_tools.py`，包含：

- ✅ 26 个工具的独立功能测试
- ✅ 输出格式一致性验证（遵循 CygnusX 规范）
- ✅ 错误处理和优雅降级测试
- ✅ 上下文窗口保护验证

运行测试：
```bash
cd mcp-server
pytest tests/test_seqout_tools.py -v
```

## 启动与配置

### 1. 启用工具组

确保 `config.yaml` 中启用了 seqout 工具组：

```yaml
tool_groups:
  seqout: true
```

### 2. 注册到 Agent

在本地或容器环境启动时，在 `mcp_settings.json` 中配置：

```json
{
  "mcpServers": {
    "cygnusx-seqout": {
      "command": "python",
      "args": ["-m", "mcp.server"],
      "env": {
        "PYTHONUNBUFFERED": "1"
      }
    }
  }
}
```

### 3. 启动自校验

启动时会自动执行 tools.yaml 一致性检查，确保：
- `_GROUP_REGISTRY` 中的注册与 tools.yaml 声明一致
- FastMCP 实际注册的工具与 yaml 声明匹配

## 扩展指南

如需添加更多工具或修改现有工具行为：

1. **新增工具**: 在 `tools/seqout.py` 中添加新的 async 函数，使用 `@mcp.tool()` 装饰器
2. **更新注册表**: 在 `register()` 函数中将新工具添加到注册列表
3. **声明元数据**: 在 `tools.yaml` 的 `seqout` 组中添加工具声明
4. **编写测试**: 在 `tests/test_seqout_tools.py` 中添加对应的测试用例

## 参考资源

- [Seqout API 文档](https://seqout.org/api)
- [ARCHITECTURE.md](./ARCHITECTURE.md) - 平台 MCP 架构规范
- [README.md](./README.md) - MCP Server 使用说明

## 版本历史

- **v2.0** (2026-09): 完整 API 覆盖，从 4 个工具扩展到 26 个工具
- **v1.0** (2026-09): 初始实现，包含 4 个核心工具

---

**维护者**: CygnusX Platform Team  
**最后更新**: 2026-09-19

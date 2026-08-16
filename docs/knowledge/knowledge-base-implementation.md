# OmicHub 知识库实现说明

> 本文说明当前代码真实采用的知识库路径、目录与数据库的关系、检索入口，以及 PDF/图片混合检索的实现边界。
> 26.8.8

## 1. 先给结论

OmicHub 的 AI 知识库检索**不是每次提问时扫描 `docs/knowledge` 目录**。实际流程是：

```text
用户问题
  ↓
knowledge_search 工具
  ↓
VectorRetrievalService
  ↓
PostgreSQL: kb_documents + kb_chunks
  ├─ pgvector 向量召回
  ├─ 关键词召回（向量不可用时兜底）
  └─ 关键词重排
  ↓
返回标题、分类、摘要、章节和 /knowledge/{doc_id} 引用
```

因此，文件“放在 `docs/knowledge/rna-seq` 或 `docs/knowledge/sc-seq`”本身并不会自动让 AI 搜到；必须先通过导入/同步脚本写入数据库并建立 `kb_chunks`。

管理员知识库管理页同样读取数据库资源，而不是扫描文件夹。仓库内置的 `qc` 和 `cloud` 资源由
`KnowledgeBaseService.ensure_builtin_bases()` 在列表请求时幂等创建；这保证管理页始终能配置它们的
可见性和 AI 检索开关。资源出现不代表正文已经导入，文档数量仍以对应导入脚本的实际结果为准。

## 2. 当前目录与文件类型

知识库源文件统一放在 `docs/knowledge/` 下：

```text
docs/knowledge/
├── meta.yaml                    # 文档中心导航配置，不是 AI 检索路由表
├── rna-seq/                     # RNA-seq 入口 Markdown 与论文 PDF
├── sc-seq/                      # 单细胞 Markdown 笔记、图片、PDF 等附件
├── atac-seq/                    # ATAC-seq 领域资料
└── qc/                          # 测序 QC、文件格式、工具笔记与附件
```

领域目录遵循“Markdown 作为入口、附件留在同目录”的约定。附件可以是 PDF、PNG、JPG、WEBP、GIF、BMP、TIFF 或 SVG。

`meta.yaml` 主要服务于知识库页面的树形导航和文件阅读回退；它不会决定 AI 只搜索 RNA-seq 还是只搜索单细胞。AI 是否能搜到某个领域，取决于对应文档是否已导入 `kb_documents`，以及所属知识库的 `ai_searchable`、`is_enabled` 状态。

## 3. 文件如何进入数据库

### 3.1 RNA-seq

`scripts/import_rnaseq_knowledge.py` 将：

- `docs/knowledge/rna-seq/RNA-seq.md` 导入为 `doc_id=rnaseq-overview`；
- 文档归入 `kb_id=rnaseq`；
- 重写 Markdown 中的本地附件路径为 `/docs-static/knowledge/...`；
- 发布修订后调用 `KnowledgeIndexService` 建立分块和向量。

RNA-seq 目录中与入口文档同级的 PDF/图片也会加入附件文本块，即使 Markdown 没有显式链接它们。

### 3.2 单细胞 RNA-seq

`scripts/import_scseq_knowledge.py` 会递归扫描 `docs/knowledge/sc-seq/**/*.md`：

- 每个 Markdown 文件对应一个稳定的 `scseq-<hash>` 文档 ID；
- 顶层目录作为分类；
- 文档归入 `kb_id=scseq`；
- 本地图片/PDF 链接重写为 `/docs-static/...`；
- 每个文档发布后调用 `KnowledgeIndexService`；
- Markdown 同级的 PDF/图片会一起进入该文档的附件索引块。

该领域通常不需要显示在实验室知识库导航中，但只要知识库 `scseq` 的 `ai_searchable=true` 且 `is_enabled=true`，AI 就可以检索它。

### 3.3 QC

`scripts/import_qc_knowledge.py` 会递归扫描 `docs/knowledge/qc/**/*.md`：

- 每篇 Markdown 使用稳定文档 ID 并归入 `kb_id=qc`；
- 相对附件链接改写为 `/docs-static/knowledge/qc/...`；
- Markdown 引用的 PDF 提取正文，图片写入说明、尺寸和可用时的 OCR 文本；
- `docs/knowledge/qc/README.md` 作为目录，并登记未在旧笔记中显式引用的图片/PDF；
- 知识库设置为 `ai_searchable=true`、`is_enabled=true`，供 `knowledge_search` 统一召回。

导入命令：

```bash
python scripts/import_qc_knowledge.py --validate-sources
python scripts/import_qc_knowledge.py --auto-admin
```

### 3.4 Cloud

`scripts/import_cloud_knowledge.py` 会递归扫描 `docs/knowledge/cloud/**/*.md`，将文档归入
`kb_id=cloud`。除 Markdown 外，索引器还会提取 PDF 正文、DOCX/PPTX 文本以及图片说明、尺寸和
可用时的 OCR 文本。`docs/knowledge/cloud/README.md` 登记主题入口和旧笔记中未显式引用的图片。

```bash
python scripts/import_cloud_knowledge.py --validate-sources
python scripts/import_cloud_knowledge.py --auto-admin
```

### 3.5 文件同步与向量重建

- `scripts/sync_knowledge_from_files.py`：根据 `meta.yaml` 同步已登记的 Markdown 文档，并建立附件索引。
- `scripts/reindex_knowledge_vectors.py`：读取数据库中已发布文档的当前修订，重新生成所有 Markdown、PDF 和图片附件分块/向量。
- `DocsService`：管理员发布或更新文档时调用同一套 `KnowledgeIndexService`，不会产生第二套索引逻辑。

### 3.6 部署启动自动校验

Web 应用启动后会在后台运行一次 `KnowledgeIndexService.ensure_published_indexes()`：

- 自动检查所有已发布文档的当前修订、同级附件内容和 embedding 模型；
- chunk 内容哈希和 embedding 模型都未变化时直接跳过，不重复调用 embedding 服务；
- PDF/图片新增、删除、内容变化或更换 embedding 模型时自动重建；
- PostgreSQL 使用 advisory lock，多个 Web 副本同时启动时只允许一个副本执行；
- 该任务失败不会阻塞 Web 启动，日志会提示仍可手动执行重建脚本。

因此正常部署不需要手动执行一次全量脚本。首次导入尚未进入数据库的新 Markdown 文件仍需要先运行对应导入脚本；启动自动任务负责已导入文档的索引校验与附件重建。

典型维护顺序：

```bash
# 先同步/导入源文件（需要管理员 UUID）
python scripts/import_rnaseq_knowledge.py --admin-user-id <UUID>
python scripts/import_scseq_knowledge.py --admin-user-id <UUID>

# 源文件变化或更换 embedding 模型后，重建已发布文档索引
python scripts/reindex_knowledge_vectors.py
```

## 4. AI 检索如何决定“去哪里搜”

### 4.1 工具入口

模型调用 `knowledge_search`，执行器位于：

```text
src/omichub/application/services/studio_tools.py::_knowledge_search
```

该执行器只负责校验参数并委托：

```text
src/omichub/application/services/vector_retrieval_service.py::VectorRetrievalService.search_knowledge
```

它不会根据文件夹名称在运行时分支；所有已经发布且可搜索的知识库会进入同一检索候选集。

### 4.2 权限和知识库过滤

检索在召回前应用以下过滤：

1. `kb_documents.status == 1`，只看已发布文档；
2. 项目可见性：平台公共文档，或当前项目自己的文档；
3. 未绑定知识库的旧文档仍兼容；
4. 绑定知识库时必须满足 `knowledge_bases.ai_searchable=true`、`is_enabled=true`；
5. 项目知识库不能泄露给无关项目。

所以“去哪里检索”的真实判断是**数据库状态和权限过滤**，不是 `meta.yaml` 的目录顺序。

### 4.3 召回与排序

1. 使用配置项 `agent_memory_embedding_model` 生成查询向量；
2. 如果向量可用，在 `kb_chunks.embedding` 上执行余弦距离召回；
3. 如果 embedding 失败、维度不匹配、pgvector 不可用或没有向量，回退到标题/正文 `ILIKE` 关键词召回；
4. 对候选结果进行关键词重排；
5. 返回前 `limit` 条引用，每条包含 `doc_id/title/category/excerpt/section_path/url/score`。

目前是“向量 + 关键词”的混合召回，不是 BM25，也不是独立的图片向量库。

## 5. PDF 与图片混合检索

### 5.1 统一索引入口

新增的：

```text
src/omichub/application/services/knowledge_asset_service.py
```

会在 `KnowledgeIndexService.index_document()` 中运行。它不会改变数据库表结构，而是把附件内容转换成带标题的文本块，然后复用原有的分块、embedding 和关键词索引：

```text
Markdown 正文
  + ## 附件PDF：...
  + ## 附件图片：...
  ↓
KnowledgeIndexService._split()
  ↓
kb_chunks
```

这样 PDF/图片和 Markdown 使用同一套权限、向量模型、关键词召回和排序逻辑。

### 5.2 PDF

对同级或 Markdown 引用的 PDF：

- 使用 `pypdf` 逐页提取文本；
- 每页前加入 `[第 N 页]` 标记；
- 附件文件名和 `/docs-static/knowledge/...` 地址写入索引文本；
- 解析失败不会阻断整篇 Markdown 入库，只记录跳过日志。

PDF 是扫描件、没有文本层或文本编码异常时，`pypdf` 可能提取不到正文；这时需要对 PDF 先做 OCR，或在服务器安装并配置适合的 OCR 流程。

### 5.3 PNG/JPG 等图片

图片进入索引时包含：

- 文件名；
- Markdown 图片的 alt 文本（如果存在）；
- 图片尺寸（Pillow 可用时）；
- Tesseract 可执行文件存在时的 `chi_sim+eng` OCR 文本；
- `/docs-static/knowledge/...` 静态资源地址。

当前实现是“图片元数据/描述/OCR 混合检索”，**不是视觉 embedding，也不会凭空理解一张没有文字、没有 alt、文件名也没有语义的图片内容**。如果要支持真正的视觉语义检索，下一阶段应增加图片 embedding 或多模态模型描述缓存，并单独存储图片向量。

### 5.4 限制与安全

- 每篇 Markdown 最多处理 64 个附件；
- 单个附件最多写入 40,000 字符；所有附件合计最多 1,500,000 字符；
- 只允许解析源 Markdown 同目录下的本地文件，拒绝路径越权、外链、`data:` URL 和任意绝对路径；
- 解析器失败只跳过单个附件，不影响其他文档；
- 同一文件在 Markdown 引用和同级附件扫描中只索引一次。

## 6. 当前检索结果与引用

检索结果的 `url` 仍然是 `/knowledge/{doc_id}`，用于打开知识库文档；附件的静态地址同时写入对应索引块，模型可以从摘要中看到实际 PDF/图片文件。前端阅读器通过 `/docs-static/knowledge/...` 访问原始附件。

因此当前的引用粒度是“知识库文档 + 附件块”，还不是独立的“PDF 页码引用”或“图片区域坐标引用”。PDF 页码会保留在 chunk 文本中，便于模型在回答中说明页码。

## 7. 部署与验证清单

Python 依赖已加入项目：

- `pypdf`：PDF 文本提取；
- `pillow`：常见图片尺寸和格式读取。

如果需要中文/英文图片 OCR，还要在运行环境安装 Tesseract，并确保 `tesseract` 在 `PATH` 中。建议部署后执行：

```bash
uv sync
# 可选：检查 OCR 命令是否存在
tesseract --version

python scripts/import_rnaseq_knowledge.py --admin-user-id <UUID> --dry-run
python scripts/import_scseq_knowledge.py --admin-user-id <UUID> --dry-run
python scripts/reindex_knowledge_vectors.py
```

验证重点：

1. `kb_documents` 中存在 `rnaseq` / `scseq` 文档；
2. `kb_chunks` 中出现 `附件PDF` / `附件图片` 分块；
3. 配置 embedding 模型时，chunk 具有 1024 维向量；
4. embedding 不可用时，关键词检索仍能命中附件文件名、OCR 和 PDF 文本；
5. `knowledge_search` 返回的 `section_path` 能区分正文与附件块；
6. 前端能打开返回的 `/docs-static/knowledge/...` 附件。

## 8. 重要边界

知识库搜索和联网搜索是两条不同链路：

- `knowledge_search`：只查本平台已导入、已发布且有权限的 `kb_*` 数据；
- `web_search`：在知识库没有结果、覆盖不足或问题需要时效核验时查外部资料。

模型不应把 PDF/图片附件解析结果伪装成网络来源；最终答案需要区分知识库附件、知识库 Markdown、外部网页和模型通用知识。

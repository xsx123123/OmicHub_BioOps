# OmicHub 知识库目录

`docs/knowledge/` 是 OmicHub 仓库内所有知识库源文件的统一存放目录。后续新增知识库不再放入
日期版本目录或其他 `docs/` 子目录。

实现、导入、权限过滤、向量/关键词召回以及 PDF/图片混合索引的完整说明见
[`knowledge-base-implementation.md`](knowledge-base-implementation.md)。

## 目录约定

- 单篇、无附件的知识文档可以直接保存为 `docs/knowledge/<document>.md`。
- 包含多篇文档、PDF、图片或其他附件的领域知识库使用
  `docs/knowledge/<knowledge-base-id>/` 独立目录。
- 领域知识库的入口 Markdown、附件和该知识库专属资源应保存在同一个领域目录内。
- 需要显示在实验室知识库导航中的入口文档，必须登记到 `docs/knowledge/meta.yaml`。
- 需要进入数据库向量/全文索引的知识库，应由对应导入脚本从 `docs/knowledge/` 读取，不应引用
  日期版本目录。

## 当前领域知识库

| 知识库 | 入口文件 | 导入方式 |
| --- | --- | --- |
| RNA-seq | `docs/knowledge/rna-seq/RNA-seq.md` | `scripts/import_rnaseq_knowledge.py` |
| ATAC-seq | `docs/knowledge/atac-seq/ATAC-seq.md` | `scripts/import_atacseq_knowledge.py` |
| 单细胞 RNA-seq | `docs/knowledge/sc-seq/sc-seq.md` | `scripts/import_scseq_knowledge.py` |
| 测序与生信质量控制 | `docs/knowledge/qc/README.md` | `scripts/import_qc_knowledge.py` |
| 云计算与平台运维 | `docs/knowledge/cloud/README.md` | `scripts/import_cloud_knowledge.py` |

管理后台的知识库列表来自数据库表 `knowledge_bases`，不会直接扫描目录。内置的 `qc` 与 `cloud`
资源会在管理员打开知识库管理页时由 `KnowledgeBaseService` 幂等补齐，因此即使尚未导入正文也会先
显示对应知识库；正文篇数在执行各自导入脚本后更新。

## 平台帮助知识

面向普通用户的平台功能说明应维护在 `docs/knowledge/platform/`，并在
`meta.yaml` 中登记后由 `scripts/sync_knowledge_from_files.py` 同步。当前入口为：

| 文档 | 说明 |
| --- | --- |
| `platform/ai-assistants-and-overdrive.md` | AI 助手职责、超频模式（Overdrive）、协作边界与常见问题 |

不要将 `data/ai/README.md`、`data/ai/update_agent.md`、Agent YAML、系统提示词或架构草稿
直接作为用户知识库正文导入。这些文件是开发和运行配置，可能包含内部实现、过期说明或不适合向
普通用户展示的操作细节。平台能力、Agent 职责或入口发生变化时，应从这些源文件核对后，更新
对应的用户帮助文档，再执行同步。

`wiki/` 是用户、管理员和开发者共用的平台说明，已作为 `meta.yaml` 的 `collections` 集合自动
同步：脚本会索引其中所有 Markdown 页面，并跳过只提供侧边栏导航的 `wiki/_Sidebar.md`。因此
更新 Wiki 后无需复制 Markdown；重新运行同步脚本即可将最新正文写入数据库和检索索引。

本地同步示例：

```bash
python scripts/sync_knowledge_from_files.py \
  --meta-yaml docs/knowledge/meta.yaml \
  --auto-admin
```

## 新增知识库示例

```text
docs/knowledge/example-kb/
├── README.md
├── example-kb.md
├── file/
└── image/
```

新增后应同步检查：

1. `meta.yaml` 中的 `id` 唯一且 `file` 使用相对 `docs/knowledge/` 的路径；
2. Markdown 内附件路径在领域目录内可解析；
3. 导入脚本、测试、Agent Prompt 和 README 不再引用旧目录；
4. `/docs-static/knowledge/...` 静态资源路径和 AI 检索结果可正常访问。

QC 目录包含多篇 Markdown 和大量附件，应使用专用导入脚本：

```bash
python scripts/import_qc_knowledge.py --validate-sources
python scripts/import_qc_knowledge.py --auto-admin --dry-run
python scripts/import_qc_knowledge.py --auto-admin
```

导入时 PDF 使用文本提取，图片使用文件说明与可用时的 OCR 文本建立检索块；图片中的精确数值仍应
回到原图复核。

# 实验室知识库

CygnusX 知识库以 Markdown 作为可审阅的源内容，以数据库中的文档版本、分块和检索索引作为运行时
权威副本。修改仓库中的 Markdown 后，必须执行同步，网页端和 AI 检索才会看到更新。

## 内容来源

| 来源 | 用途 | 同步方式 |
| --- | --- | --- |
| `docs/knowledge/` | 实验室 SOP、方法说明和面向用户的平台帮助 | `docs/knowledge/meta.yaml` 中显式 `items` |
| `wiki/` | 平台、部署、运维、开发和安全说明 | `meta.yaml` 的 `collections` 自动发现所有正文页面 |
| `wiki/_Sidebar.md` | Wiki 导航 | 不进入检索正文 |

`data/ai/` 的 Agent YAML、提示词和内部架构草稿仅作为核对来源。它们可能包含运行细节或过期设计，
不应原样同步给普通用户；应先整理为稳定的帮助文档。

## 同步与重建

```bash
# 开发或部署环境：同步 Markdown 到数据库并建立/更新索引
make sync-knowledge

# 仅需重建数据库中已发布文档的分块与向量索引时
make knowledge-reindex
```

也可以在容器内直接执行：

```bash
docker exec cygnusx-web python scripts/sync_knowledge_from_files.py \
  --meta-yaml docs/knowledge/meta.yaml \
  --auto-admin
```

同步会为新增文档创建初始版本；内容变化时归档旧版本、创建新版本并重新索引。同步需要数据库中已有
管理员，用于记录版本编辑者。

## 检索与权限

- 文档按照状态、发布版本和访问范围进入检索；AI 不应把没有实际检索到的内容称为知识库证据。
- 文本按块建立关键词和向量索引；附件可按其类型纳入解析和索引。
- 管理端编辑文档后，数据库版本优先于仓库中的旧副本；要以仓库内容覆盖时，重新运行同步。
- 知识库检索用于补充平台已沉淀的信息；涉及最新论文、软件版本或新闻时仍需按需使用外部检索。

## 新增或更新文档

1. 将稳定、面向目标读者的 Markdown 放入 `docs/knowledge/`，或更新对应 Wiki 正文。
2. `docs/knowledge/` 的入口文档在 `meta.yaml` 添加唯一 `id`、标题、分类和相对路径；Wiki 不需要
   逐篇重复登记。
3. 检查文档中的相对链接、图片和附件路径。
4. 运行 `make sync-knowledge`，然后用平台聊天的 `knowledge_search` 验证目标术语能被召回。

完整实现细节见 `docs/knowledge/knowledge-base-implementation.md`。

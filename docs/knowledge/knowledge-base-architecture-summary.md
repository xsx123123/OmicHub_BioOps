# 实验室知识库实现方式与架构汇总

本文汇总 OmicHub「实验室知识库」模块当前的实现方式与系统架构，方便团队成员快速理解其工作原理、扩展方式与注意事项。

---

## 1. 功能定位

知识库是 OmicHub 内置的生信文档管理系统，目前命名为「实验室知识库」，核心能力包括：

- **文档浏览**：左侧树形目录 + 右侧 Markdown 渲染阅读
- **在线编辑**：管理员可直接在浏览器内编辑、保存 Markdown 文档
- **图片上传**：编辑时支持拖拽/粘贴上传图片，自动落到静态资源目录
- **目录大纲**：阅读器右侧提供 `MdCatalog` 大纲，随滚动高亮
- **AI 检索**：通过 MCP（Model Context Protocol）内置 `search_knowledge` 工具，AI 助手可检索知识库内容
- **静态资源服务**：图片等资源通过 `/docs-static/` 路径由 FastAPI + Nginx 提供

---

## 2. 系统架构

整体采用「**文件即数据源**」的轻量架构：知识库源文件统一存储在仓库
`docs/knowledge/` 中，通过 `meta.yaml` 注册。单篇文档可直接放在根目录，包含 Markdown、
PDF、图片等多项资源的领域知识库应使用独立子目录；详细约定见 `docs/knowledge/README.md`。

```
Frontend (Vue 3)                          Backend (FastAPI)                         Data (docs/)
├─ KnowledgeView.vue                      ├─ api/v1/docs.py                         docs/knowledge/
│  ├─ DocTree.vue                         │  ├─ GET  /docs/knowledge                ├─ meta.yaml
│  ├─ DocReader.vue                       │  ├─ GET  /docs/knowledge/:docId         ├─ *.md
│  └─ DocEditor.vue                       │  ├─ PUT  /docs/knowledge/:docId         └─ figure/
│                                         │  └─ POST /docs/knowledge/upload
├─ types/knowledge.ts                     ├─ services/docs_service.py
└─ router/index.ts                        ├─ middleware/rbac.py
                                          ├─ main.py 挂载 /docs-static
                                          └─ mcp/presets.py → search_knowledge

docs/knowledge/
├─ meta.yaml
├─ README.md
├─ *.md
└─ <knowledge-base-id>/
   ├─ <entry>.md
   ├─ file/
   └─ image/
```

---

## 3. 数据层：`docs/knowledge/`

### 3.1 导航配置 `meta.yaml`

```yaml
title: "实验室知识库"
items:
  - id: "getting-started"
    title: "快速入门"
    file: "getting-started.md"
    category: "上手指南"
```

- `id`：URL 和 API 的唯一标识
- `file`：对应 Markdown 文件名
- `category`：前端按此聚合成树形目录

### 3.2 文档正文与领域子目录

无附件的单篇文档可使用 `docs/knowledge/*.md`。领域知识库应使用
`docs/knowledge/<knowledge-base-id>/`，并在 `meta.yaml` 的 `file` 字段中填写相对
`docs/knowledge/` 的入口路径，例如：

```yaml
- id: rnaseq-overview
  title: RNA-seq 原理、实验与分析流程
  file: rna-seq/RNA-seq.md
  category: RNA-seq 知识库
```

Markdown 文件中图片使用相对路径引用，例如：

```markdown
![描述](./figure/0R3A1502.jpg)
```

### 3.3 运行时副本

知识库还有一个运行时副本位于 `/data/omichub/omichub_data/knowledge/`，方便整库 `rsync` 备份和迁移；但在线编辑和读取仍以仓库内 `docs/knowledge/` 为准。

---

## 4. 后端实现

### 4.1 核心文件

| 文件 | 职责 |
|------|------|
| `src/omichub/application/services/docs_service.py` | 业务逻辑：读写 YAML/Markdown |
| `src/omichub/api/v1/docs.py` | 4 个知识库接口 + 文档中心接口 |
| `src/omichub/main.py` | 挂载 `/docs-static` 静态资源 |
| `src/omichub/infrastructure/mcp/presets.py` | MCP 知识库检索工具 |

### 4.2 API 接口

| 方法 | 路径 | 权限 |
|------|------|------|
| `GET` | `/api/v1/docs/knowledge` | 登录用户 |
| `GET` | `/api/v1/docs/knowledge/{doc_id}` | 登录用户 |
| `PUT` | `/api/v1/docs/knowledge/{doc_id}` | 管理员 |
| `POST` | `/api/v1/docs/knowledge/upload` | 管理员 |

### 4.3 安全设计

- **路径遍历防护**：`DocsService._resolve_doc_path()` 通过 `Path.resolve().relative_to(section_dir)` 确保只能访问 `meta.yaml` 中已注册的文档，且路径必须位于 `docs/knowledge/` 内
- **原子写入**：保存时先写 `.md.tmp`，再 `Path.replace()` 替换原文件，避免写一半损坏
- **图片上传限制**：白名单扩展名（`png/jpg/gif/svg/webp`），单文件最大 10MB，文件名使用 UUID

### 4.4 MCP AI 检索

AI 助手通过 `knowledge_search` 工具进入 `studio_tools.py`，再由
`VectorRetrievalService` 对 `kb_documents` / `kb_chunks` 执行权限过滤、pgvector 向量召回、
关键词回退和重排。Markdown、PDF 文本和图片元数据/OCR 都进入同一套 chunk 索引；
`docs/knowledge/meta.yaml` 主要负责知识库页面导航，不是 AI 检索路由表。完整流程见
`docs/knowledge/knowledge-base-implementation.md`。

---

## 5. 前端实现

### 5.1 核心组件

| 文件 | 职责 |
|------|------|
| `frontend/src/views/KnowledgeView.vue` | 主视图：状态管理、CRUD、布局 |
| `frontend/src/components/knowledge/DocTree.vue` | 左侧树形目录（Naive UI NTree） |
| `frontend/src/components/knowledge/DocReader.vue` | 阅读模式（MdPreview + MdCatalog） |
| `frontend/src/components/knowledge/DocEditor.vue` | 编辑模式（MdEditor + 图片上传） |
| `frontend/src/types/knowledge.ts` | 类型定义 |

### 5.2 路由与布局

- 路由：`/knowledge` 和 `/knowledge/:docId`
- `meta: { fullscreen: true }`：让 `DefaultLayout` 使用原生滚动条 + flex 约束，实现局部滚动
- 进入页面未指定文档时，默认选中第一个叶子节点

### 5.3 图片路径解析

`DocReader.vue` 渲染前通过正则替换，把 Markdown/HTML 中的相对路径：

```markdown
![alt](figure/xxx.png)
![alt](./figure/xxx.png)
<img src="./figure/xxx.jpg" alt="...">
```

统一解析为后端静态资源 URL：

```markdown
![alt](/docs-static/knowledge/figure/xxx.png)
```

### 5.4 编辑与图片上传

`DocEditor.vue` 使用 `md-editor-v3` 的 `MdEditor`，编辑时拖拽/粘贴图片会并发上传到 `/docs/knowledge/upload`，后端返回 URL 后自动插入 Markdown。

### 5.5 主题适配

`DocReader` 和 `DocEditor` 都同步了应用主题变量，暗黑模式下将 `md-editor-v3` 的背景色映射到平台变量 `--neutral-card`，避免编辑器/预览区出现白底或纯黑色差。

---

## 6. 静态资源与部署

### 6.1 FastAPI 挂载

```python
# src/omichub/main.py
docs_static_path = Path("docs")
if docs_static_path.is_dir():
    app.mount("/docs-static", StaticFiles(directory=docs_static_path), name="docs-static")
```

`docs/knowledge/figure/xxx.png` 可通过 `/docs-static/knowledge/figure/xxx.png` 访问。

### 6.2 Nginx 配置

开发环境使用 `^~` 前缀匹配，防止正则规则抢占：

```nginx
location ^~ /docs-static/ {
    proxy_pass http://omichub_backend;
}
```

---

## 7. 关键设计决策

| 决策 | 说明 |
|------|------|
| **文件存储而非数据库** | 文档直接存 `.md`，便于 Git 版本控制、离线编辑、批量导入 |
| **原子写入** | `.tmp` → `replace`，防止写入中断导致文件损坏 |
| **路径遍历防护** | `_resolve_doc_path()` 限制只能访问 `meta.yaml` 已注册的文件 |
| **fullscreen 路由** | 使用原生滚动条 + flex 约束，实现局部滚动，避免全局滚动 |
| **运行时副本** | `/data/omichub/omichub_data/knowledge/` 用于备份迁移，在线服务仍以仓库为准 |

---

## 8. 当前限制与可优化点

- **AI 检索边界**：当前已经支持向量 + 关键词混合召回，以及 PDF 文本和图片元数据/OCR；
  还没有图片视觉 embedding、图片区域定位或独立的 PDF 页级引用表
- **无版本历史**：编辑直接覆盖原文件，未内置 Git 版本或历史回滚
- **无全文搜索 UI**：前端目前没有搜索框，仅能通过 AI 检索调用
- **分类只有一级**：`category` 是单级字符串，未支持多级目录

---

## 9. 如何新增一篇知识库文档

1. 在 `docs/knowledge/` 下新建 `.md` 文件
2. 在 `docs/knowledge/meta.yaml` 中添加对应条目（`id`、`title`、`file`、`category`）
3. 如需配图，将图片放入 `docs/knowledge/figure/`，正文中使用 `./figure/xxx.png` 引用
4. 刷新前端页面即可在左侧目录看到新文档

---

> 本文档保留为架构摘要；实现细节与混合检索说明见
> `docs/knowledge/knowledge-base-implementation.md`。

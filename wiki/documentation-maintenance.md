# Wiki 维护与知识库同步

Wiki 是 OmicHub 面向用户、管理员和开发者的稳定说明层。它不复制全部仓库 Markdown，而是从当前实现
和权威文档中提炼可操作、可检索的内容；日期归档、实施草稿、内部提示词和自动生成报告不作为 Wiki
正文来源。

## 更新原则

1. 先核对当前代码、`.env.example`、`Makefile`、根目录 `README.md` 和对应模块的正式文档。
2. 变更功能时同时更新对应 Wiki 页面、导航页和面向用户的知识库说明。
3. 有时间敏感或环境相关的内容，写清适用条件，并链接到命令帮助或配置模板，而不是复制易过期值。
4. 不把密钥、真实服务器地址、用户数据路径、内部系统提示词或未审核设计方案写入 Wiki。

## 当前主题与核对来源

| Wiki 主题 | 优先核对来源 |
| --- | --- |
| 快速开始、部署、运维、安全 | `README.md`、`.env.example`、`Makefile`、`deploy/` |
| AI、Agent、超频和工作台 | `data/ai/`、`src/omichub/application/services/`、`ARCHITECTURE_DESIN/`、测试 |
| 知识库 | `docs/knowledge/`、知识库服务和同步脚本 |
| Flow、工具和生信分析 | `flows/`、`tool_configs/`、`pipelines/` |
| 前端与 API | `frontend/`、`src/omichub/api/`、DTO 和相关测试 |

## 知识库索引

`docs/knowledge/meta.yaml` 已将 `wiki/**/*.md` 定义为自动集合；同步时会索引每篇正文，并排除
`wiki/_Sidebar.md`。编辑 Wiki 后运行：

```bash
make sync-knowledge
```

若仅需要重建既有文档的检索分块和向量，可运行 `make knowledge-reindex`。

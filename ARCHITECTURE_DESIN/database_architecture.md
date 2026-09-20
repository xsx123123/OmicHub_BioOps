# CygnusX 数据库模块（Database Infrastructure）架构基线

> **用途**：记录 database 基础设施模块的最终接受架构——连接管理、ORM 模型注册契约、仓储分层策略、迁移与 schema 治理、可观测性与管理端健康页。新增表、模型、仓储或迁移前必须阅读本文。
>
> **最后更新**：2026-09-18
> **适用范围**：`src/cygnusx/infrastructure/database/`、`src/cygnusx/domain/*/repositories.py`、`alembic/`、`scripts/check_migrations.py`、`scripts/check_schema_drift.py`、管理端「数据库健康」页。

> **合并说明（2026-09-18）**：本文档新增文末附录《Terminal 与参考基因组模块更新记录》，内容自 `log_architecture.md` 原 §9.2–§9.6（terminal 资源配置、参考基因组前端/路由、JBrowse 配置模型、cygnusxtools 参考库离线构建）整段迁入（该几节与日志主题无关），并与 §11 参考基因组章节互为交叉引用；日志本体架构仍以 `log_architecture.md` 为准。

---

## 1. 概述

database 模块是平台唯一的持久化基础设施层，承载 87 张 ORM 管理表（另有外部组件表 `mem0_memories` 由 mem0 自建自管），服务 Web（FastAPI）、Worker（Celery）、Beat 三类进程。

核心设计原则：

1. **Alembic 是 schema 的唯一事实来源**：禁止 `Base.metadata.create_all` 自动建表（只建新表、不补列，曾导致 `users.storage_quota` 缺列引发登录 500）。
2. **每个迁移建表的都必须有对应 ORM 模型并注册进 models 包**——autogenerate 对账依赖完整 metadata，遗漏的表会被误判为待删除。
3. **`alembic revision --autogenerate` 必须产生空迁移**：ORM metadata 与实际 schema 保持零漂移，差异必须当日消除（见 §6.4）。
4. **仓储两级分层**：核心域走 domain 接口 + SQLAlchemy 实现；轻量/查询域允许服务层直连模型（显式接受的架构模式，不是债）。
5. **跨事件循环连接零容忍**：Web 用连接池，Worker/后台线程一律 NullPool，杜绝 "Future attached to a different loop"。

---

## 2. 总体架构

```text
api/v1/**.py                    FastAPI 路由（依赖注入 DbSession / AdminRequired）
      │
application/services/**.py      应用服务
      │  ├─ 核心域：注入 domain 仓储接口（IUserRepository / IFileRepository / ...）
      │  └─ 轻量域：直接 select(Model)（chat / goal / overdrive / schedule / knowledge / ...）
      ▼
domain/*/repositories.py        仓储接口（Protocol / ABC）——仅核心域
      ▼
infrastructure/database/
  ├─ base.py            Base(DeclarativeBase) + TimestampMixin
  ├─ session.py         引擎/会话工厂单例 + 连接池仪表 + 只读副本
  ├─ vector.py          pgvector 自定义类型（不依赖 pgvector 包）
  ├─ models/            39 个模型模块，__init__.py 全量导入注册（87 表）
  └─ repositories/      17 个仓储实现模块，__init__.py 统一导出（24 类）
      ▼
alembic/                        88+ 迁移，单 root 单 head；容器 entrypoint upgrade head
      ▼
scripts/check_migrations.py     迁移链健康检查（CI/本地）
scripts/check_schema_drift.py   metadata ↔ 真实库对账（entrypoint fail-fast）
```

---

## 3. 连接与会话管理（session.py）

`src/cygnusx/infrastructure/database/session.py`

### 3.1 引擎形态（按进程角色分流）

| 进程 | 池类 | 说明 |
| --- | --- | --- |
| Web（`service_name == "web"`） | `AsyncAdaptedQueuePool` | 容量参数来自 `database_pool_size` / `database_max_overflow` / `database_pool_timeout_seconds` / `database_pool_recycle_seconds`；**禁止显式传同步 QueuePool**（SQLAlchemy 会拒绝），只传容量参数。 |
| Worker / Beat | `NullPool` | Celery 任务可由 `asyncio.run()` 建新事件循环，保留连接会跨循环报错。 |
| 后台线程 | `create_unpooled_engine()` | 短生命周期引擎，调用方负责 `dispose()`。 |

所有引擎统一 `pool_pre_ping=True`、`echo=settings.app_debug`。

### 3.2 只读副本

`readonly_database_url` 非空时，`get_readonly_engine()` / `get_readonly_session_factory()` 提供指向只读副本的独立池；未配置时**回退主库同一实例**，调用方无需判断。用途：报表、列表等读多场景分流。写路径永远走 `get_session_factory()`。

### 3.3 连接池可观测性

`_instrument_pool()` 通过 SQLAlchemy pool 事件导出四个 OTel/Prometheus 指标（`cygnusx.database.pool.*`：checked_out、checkouts、connects、invalidations），带 `service` 与 `pool` 标签。

### 3.4 生命周期

- `init_db()`：仅预热引擎（懒初始化建池），**不建表**；schema 由 entrypoint 的 `alembic upgrade head` 负责（`deploy/docker/entrypoint.sh`）。
- `close_db()`：先 dispose 只读引擎再 dispose 主引擎，两个工厂一并清空。
- `get_db()`（FastAPI 依赖）：`yield session → commit`，异常 `rollback` 并上抛。

---

## 4. ORM 模型层契约

### 4.1 基类与混入

`base.py`：`Base(DeclarativeBase)`；`TimestampMixin` 提供 `created_at` / `updated_at`（`DateTime(timezone=True)`，`server_default=func.now()`）。新表默认带 Mixin。

### 4.2 models 包注册契约（强制）

`models/__init__.py` 必须**导入每个模型类**并列入 `__all__`：

- 导入即注册到 `Base.metadata`，alembic env 与漂移检查只导入 models 包，不逐模块导入；
- `__all__` 与 import 清单必须严格一致——历史事故：`AgentTeamsRoomMemberModel` / `AgentTeamsTurnRecordModel` 进了 `__all__` 却漏了 import，`from models import *` 直接 AttributeError；
- 由 `tests/unit/test_database_module_contracts.py` 三条测试兜底：`__all__` 全部可解析、每个模型模块的表都已注册、env.py 排除集与 metadata 无交集。

### 4.3 模型 ↔ schema 对齐规则

模型 metadata 必须忠实描述迁移建出的真实 schema（2026-09 对齐专项的结论）：

- **列类型以 DB 为准**：DB 是 `JSONB` 模型就写 `JSONB`（不写 `sa.JSON`）；DB 是 `TIMESTAMP(timezone=True)` 模型就写 `DateTime(timezone=True)`。
- **约束形态以 DB 为准**：DB 是 unique constraint，模型用 `UniqueConstraint`（同名），不要用 `Index(unique=True)` 近似——autogenerate 会视为差异。
- **索引名以 DB 为准**：`ix_*` / `idx_*` 不一致会产生 drop+create 噪音。
- **PostgreSQL 专有索引要在 `__table_args__` 补全**：HNSW 向量索引需带 `postgresql_using="hnsw"`、`postgresql_ops={"embedding": "vector_cosine_ops"}`、`postgresql_where`。
- **模型声明了但 DB 缺失的索引/约束**：不得从模型删除充数，必须出迁移补建（见 §6.4 流程）。

### 4.4 pgvector

`vector.py` 自带 `Vector(dimensions)` UserDefinedType（cosine_distance 走 `<=>`），刻意不引入 `pgvector` Python 包依赖。绑定侧校验维度与有限值，结果侧解析 `[]` 字符串。

### 4.5 relationship 与懒加载纪律

`AsyncSession` 下访问未 preload 的 `lazy="select"` relationship 会抛 `MissingGreenlet`。规则：

- **新 relationship 默认 `lazy="selectin"`**（正面例子：`knowledge_document.py`）；一对多且非必用的可保持默认，但服务层访问点必须显式 `selectinload` / `joinedload`；
- 存量关系（`report.py` 的 files/report、`chat.py` 的 messages/session）维持默认 + 调用方 preload 的现状——已审计全部访问点均有配套，**改动收益低于回归风险，冻结不动**；
- 服务层优先直接 `select()` 目标模型，而非借助 relationship 遍历（chat 域即此风格）。

---

## 5. 仓储分层策略（接受的两级模式）

### 5.1 核心域：domain 接口 + 实现

domain 层定义 Protocol/ABC（`domain/*/repositories.py`），infrastructure 提供 SQLAlchemy 实现。当前 19 个接口全部有实现且方法比对无缺失（user、task、file×4、cookie×5、festival claim、mcp、sandbox、skill、terminal、ai conversation、ai_provider、flow）。

**租户隔离纪律**：文件域等接口所有方法首参 `user_id`，查询统一 `WHERE user_id = ?`，在数据访问层杜绝跨租户水平越权（见 `domain/file/repositories.py` 模块 docstring）。

**第三类：有实现无接口**：24 个仓储实现类中有 5 个（`MASRepository`、`TeamRepositoryImpl`、`ReportRepositoryImpl`、`SqlAlchemyNotificationRepository`、`SqlAlchemyAnnouncementRepository`）在 infrastructure 提供实现但未建对应 domain 接口。按 §5.2 的升格判据处理：出现复用或接口替换需求时再补接口，此前维持现状。（flow 域的 `FileSystemFlowRepository` 虽不显式继承，但结构上满足 `IFlowRepository` Protocol，不属于此类。）

### 5.2 轻量域：服务层直连模型（显式接受）

chat（13 模型）、goal、overdrive、schedule、knowledge_*、project、blast、agent、agent_memory、audit_log、api_key、search_provider、site_settings、mcp_builder、ai_metric 等域**不建仓储**，服务层直接构造查询。判据：

- 以读/写单个聚合为主、无复杂不变量需要仓储封装；
- 查询形态贴近 ORM，包一层仓储只是透传；
- 该域没有面向接口替换实现的需求（测试 mock 具体类即可）。

**何时升格为仓储**：出现第二个消费方需要复用同一组查询、或需要在接口层替换实现（如测试替身、缓存层）时，先补 domain 接口再迁移调用点。

### 5.3 repositories 包统一导出

`repositories/__init__.py` 导出全部 24 个实现类。服务层一律从包级导入：

```python
from cygnusx.infrastructure.database.repositories import SqlAlchemyUserRepository
```

禁止深路径 `...repositories.user_repository` 导入（历史两种风格并存，以包级为准收敛）。

### 5.4 已清理的孤儿件（2026-09-11）

- 删除 `IResultArchiveRepository` + `ResultArchive` 实体 + `FileDomainService`（无实现、无调用方的纯死代码）；
- 删除 `FestivalConfigRepository` ABC（节日配置的实际权威来源是 YAML：`application/services/festival_service.py` 的 `FestivalConfigYamlLoader`，DB 只存领取记录）。

---

## 6. 迁移与 schema 治理

### 6.1 流程

1. 改模型 → `alembic revision --autogenerate -m "..."` → **人工审查生成的迁移**（autogenerate 是草稿不是结论）；
2. 本地 `alembic upgrade head` 验证 upgrade/downgrade；
3. 跑 `scripts/check_migrations.py`（链健康）与 `scripts/check_schema_drift.py`（对真实库对账）；
4. 容器启动由 entrypoint 执行 `alembic upgrade head` + 漂移检查 fail-fast。

### 6.2 check_migrations.py

解析全部迁移文件的 `revision` / `down_revision` / `depends_on`（兼容注解与裸赋值两种写法）：依赖必须存在、单 root、拓扑连通、`alembic heads` 唯一。

### 6.3 check_schema_drift.py

方向只做"代码需要的，库里必须有"：metadata 的表/列必须存在；库中多出的表/列只告警。`alembic_version` 与外部组件表 `mem0_memories` 在忽略清单。用于发现"版本戳已推进但 DDL 未生效"（手工 DDL / create_all / 备份恢复）这类 `upgrade head` 发现不了的漂移。

### 6.4 零漂移纪律（autogenerate 空 diff）

2026-09-11 对齐专项把 88 个迁移与 39 个模型模块积累的全部 metadata 差异一次性清零（模型对齐 DB 形态 + 汇总迁移 `s1t2u3v4w5x6_sync_schema_with_orm_metadata` 补齐 DB 缺失的 17 个索引、1 个外键与 17 列 comment）。此后：

- 每次改模型后跑 autogenerate 探测，upgrade body 应为空（除本次预期变更）；
- 出现非预期 diff 时，按 §4.3 判断方向：模型描述错了就改模型，DB 缺东西就出迁移，**禁止用删模型声明的方式消 diff**。

### 6.5 外部组件表

`alembic/env.py` 的 `_NON_ORM_TABLES = {"mem0_memories"}`：autogenerate 跳过非本项目管理的表，防止误生成 drop_table。只有"非本项目迁移建表"的外部表才允许进这个集合——本项目迁移建表的（含 `mcp_logs`）一律要有 ORM 模型并注册。历史教训：`mcp_logs` 曾被当作"无 ORM 外部表"排除，但服务层实际在用 `MCPLogModel` 读写，表结构变更完全脱离迁移链——已修复并纳入正常管理。

---

## 7. 管理端「数据库健康」页

只读观测入口，面向管理员（`AdminRequired`）：

- **后端**：`src/cygnusx/api/v1/admin/database.py`，注册于 `/admin/database`：
  - `GET /health`：alembic 库版本戳 vs 代码 head（ScriptDirectory，不连库）、同步状态、public 表计数、连接池占用快照、只读副本配置状态；
  - `GET /drift`：与 `check_schema_drift.py` 同逻辑的实时对账（缺失表/列、多余表）。
- **前端**：`frontend/src/views/AdminDatabaseHealthView.vue` + `frontend/src/api/admin/database.ts`，路由懒加载、管理员守卫、管理菜单入口。
- **样式**：遵循 `ARCHITECTURE_DESIN/frontend.md`——只消费语义令牌（`--neutral-card` / `--neutral-border` / `--arco-*`，明暗主题自适应）；PageHeader + `#actions` 刷新（`:loading`，禁止整页 reload）；表格全部固定列宽 + `scroll-x` + `row-key`；状态同时以文字 + `NTag` 颜色表达；加载 `NSkeleton`/`NSpin`、空态 `NEmpty`、失败保留上下文 + 重试。

---

## 8. 新增表/模型/仓储 Checklist

- [ ] 模型文件放 `models/<domain>.py`，继承 `Base`（按需 `TimestampMixin`）；
- [ ] 在 `models/__init__.py` 同时补 import 与 `__all__`（两条缺一不可）；
- [ ] relationship 默认 `lazy="selectin"`；FK 显式 `ondelete`；
- [ ] 出迁移并人工审查；PostgreSQL 专有索引参数补全；
- [ ] autogenerate 复跑确认为空 diff；`check_migrations.py` / `check_schema_drift.py` 全绿；
- [ ] 核心域补 domain 接口 + 实现并加入 `repositories/__init__.py`；轻量域直连模型需在服务层注释说明；
- [ ] 涉及展示的，前端按 `frontend.md` 验收清单走一遍。

---

## 9. 已知限制与后续路线

1. **轻量域测试覆盖薄**：17 个仓储中多数尚无直接单测，database 层现有测试集中在契约（`test_database_module_contracts.py`）、连接池（`test_database_session_pool.py`）、report 仓储与 pgvector 迁移契约。后续按域补仓储级测试。
2. **只读副本未启用**：`readonly_database_url` 基建就绪，尚无服务切流；首个候选是报表/列表类只读查询。
3. **存量 relationship 冻结**（见 §4.5）：新增访问点必须自查 preload，依赖 code review 与 MissingGreenlet 报错暴露。
4. **租户隔离**：文件域已在仓储层强制 `user_id` 过滤；轻量域直连模型的查询依赖服务层自觉，后续可引入行级安全（RLS）评估。

---

## 10. 2026-09-11 搭建变更记录

| 变更 | 文件 | 说明 |
| --- | --- | --- |
| 修复 `__all__` 契约 | `models/__init__.py` | 补 `AgentTeamsRoomMemberModel` / `AgentTeamsTurnRecordModel` / `MCPLogModel` 导入 |
| mcp_logs 纳管 | `models/mcp_log.py`、`alembic/env.py` | 模型对齐迁移 DDL（timestamptz + server_default）；`_NON_ORM_TABLES` 改为 `{"mem0_memories"}` |
| schema 对齐专项 | 21 个模型文件 + 迁移 `s1t2u3v4w5x6` | 消除全部 autogenerate diff（类型/约束/索引名/HNSW/comment），DB 侧补 17 索引 + 1 FK + 17 列 comment |
| 仓储包导出 | `repositories/__init__.py` | 8 → 24 个实现类统一导出 |
| 只读副本基建 | `session.py`、`core/config.py` | `get_readonly_engine()` / `get_readonly_session_factory()`，未配置回退主库 |
| 孤儿清理 | `domain/file/`、`domain/festival/` | 删除 `FileDomainService`、`IResultArchiveRepository`、`ResultArchive`、`FestivalConfigRepository` |
| 漂移脚本 | `scripts/check_schema_drift.py` | 忽略 `mem0_memories`，消除常驻告警 |
| 契约测试 | `tests/unit/test_database_module_contracts.py` | models/repositories/env 排除集/只读回退 6 条 |
| 管理端健康页 | `api/v1/admin/database.py`、前端 `AdminDatabaseHealthView.vue` | /health + /drift，样式遵循 frontend.md |
| 参考基因组详情增强 | `reference_genomes/{indexer,service,schema,api}.py`、前端 `ReferenceGenomeDetailView.vue` | 见 §11：CDS/UTR 基因模型图、GO Slim、启动子序列、外部链接、JBrowse/BLAST 联动 |

---

## 11. 参考基因组数据库（reference_genomes 模块）演进记录与 TODO

> 本模块不走 Alembic/ORM：每版本一个离线构建的 SQLite（`gene_index.db`，FTS5），
> 构建器 `src/cygnusx/reference_genomes/indexer.py`，运行期只读。
> schema 演进靠"解析器幂等 + 全量重建"，增量模式用 `_ensure_column` / `CREATE TABLE IF NOT EXISTS` 兜底旧库。
> 关联：本模块的前端升级/路由、JBrowse 配置模型扩展与 `cygnusxtools refdb` 离线构建等更新记录见文末附录《Terminal 与参考基因组模块更新记录》（2026-09-18 自 log_architecture.md §9.2–9.6 迁入）。

### 11.1 2026-09-11 已实现（第一、二梯队）

1. **基因模型图区分 CDS / UTR / 外显子**：GFF3 解析新增 `CDS` / `five_prime_UTR` / `three_prime_UTR` → `transcripts.feature_ranges`（JSON）；前端 Summary tab 按比例绘制 CDS 高块 / UTR 矮块 / 内含子折线（带图例、坐标轴、链方向），旧索引自动退化为纯外显子图。
2. **GO Slim 功能分类**：新解析器 `goslim`（`ATH_GO_GOSLIM.txt.gz` 18 列 TSV）→ `goslim_annotations` 表；基因详情 DTO 新增 `goslim` 段，前端 GO tab 顶部展示。
3. **启动子序列**：`GET .../sequence?type=promoter&upstream=2000`，按链方向取 TSS 上游区间（越界自动 clamp）；前端 Sequence tab 新增 Promoter 按钮。
4. **外部分库链接**：Summary 新增「外部链接」行——拟南芥基因（`AT[1-5MC]G\d+`）跳 TAIR / Ensembl Plants，所有基因可跳 NCBI Gene 检索。
5. **JBrowse 2 联动**：抽屉顶部「JBrowse 查看」按钮，按 `version_id` 匹配 `jbrowseApi.listAssemblies()` 的 assembly（无匹配自动隐藏），深链 `/tools/jbrowse?assembly=&region=chr:start-end`。**前置条件**：`tool_configs/jbrowse/jbrowse_config.yaml` 需为对应版本注册 assembly 并填 `version_id`。
6. **一键 BLAST**：Sequence tab「去 BLAST」按钮，`storeSequenceHandoff('blast', ...)` → `/tools/blast` 自动填充查询序列。**前置条件**：参考基因组 FASTA 需注册为 BLAST 库（管理端上传或 `blast_db.yaml` + sync-from-yaml）。

### 11.2 TODO（第三梯队：需新增数据源，工作量大）

- [ ] **蛋白域 / 基因家族注释（Pfam / InterPro）**：hypothetical protein 类基因的功能判断第一线索。需跑 InterProScan（或下载 TAIR 现成域注释），索引器新增 `domain` 解析器 + `protein_domains` 表，前端详情页加「蛋白结构域」段。
- [ ] **直系 / 旁系同源基因（ortholog / paralog）**：跨物种 ortholog 表（OrthoDB / Ensembl Compara 现成结果导入），索引器加 `orthologs` 表，详情页加「同源基因」段并支持跨版本/跨物种跳转。
- [ ] **表达量 / 变异信息**：RNA-seq atlas 表达热图（按组织/处理）、变异（VCF）密度轨——属"数据库升级为分析平台"方向，依赖业务数据积累，建议先做表达矩阵的版本挂载契约（哪个版本挂哪套表达数据）。
- [ ] **基因别名（synonyms）检索**：GFF3 属性（`Alias` / `synonym`）与 TAIR 别名表未入索引，搜旧名/别名找不到基因。索引器 `genes` FTS 表加 `synonyms` 列（逗号分隔），解析时顺手收集——改动小，建议优先于上面三项安排。

### 11.3 操作备忘

- 重建索引：`python -m cygnusx.reference_genomes.indexer build --version tair10`（可用 `--config` 覆盖注册表路径；`--only go` 仅重建 GO/GO Slim 段）。
- **线上配置覆盖**：运行实例用 `REFERENCE_GENOMES_YAML=/data/omichub/omichub_data/reference/reference_genomes.yaml`（本机 data_root 为 /data/omichub）；repo 内 `refdata/reference_genomes.yaml` 是容器路径约定（/data/cygnusx/...）。新增 files 条目要两边同步（goslim 已同步）。
- JBrowse 联动前置：`tool_configs/jbrowse/jbrowse_config.yaml` 已注册 `arabidopsis_tair10`（`version_id: tair10`，复用参考库 FASTA/GFF3）；部署环境 data_root 不同（如 /data/omichub）时需同步调整 fasta/fai 绝对路径，按钮在 assembly 存在且 `fasta_exists` 时才显示。
- BLAST 联动前置：参考基因组 FASTA 需注册为 BLAST 库（`/admin/blast-databases` 上传，或 `tool_configs/blast/blast_db.yaml` + `POST /blast/admin/databases/sync-from-yaml`）。
- GO 注释完整性：`go_annotations` 主键 `(gene_id, go_id)` + `INSERT OR IGNORE`，同基因同 GO 的多证据码只留第一条；查询侧已改 `LEFT JOIN go_terms`（词条缺失不再静默丢注释）+ `ORDER BY` 确定性返回。
- 压缩文件陷阱：TAIR 部分 `.gz` 实为 ZIP 封装（`ATH_GO_GOSLIM.txt.gz`），解析器一律走 `_open_text_auto` 按魔数嗅探，禁止仅按扩展名选 gzip。

---

## 附录：Terminal 与参考基因组模块更新记录（2026-09-18 自 log_architecture.md §9.2–9.6 迁入）

> 迁移说明：以下 A.1–A.5 为 `log_architecture.md` 原 §9.2–§9.6 整段迁入（原文与日志主题无关），内容未作改写，编号映射为 A.x（原 §9.x）以便溯源。交叉引用：参考基因组模块（`reference_genomes`）的架构定位、索引器演进记录与 TODO 见本文 §11。

### A.1（原 §9.2）云端沙盒终端资源配置链路

- `tool_configs/terminal/terminal_config.yaml` 仍作为资源配置源，后端配置加载器按 mtime 热重载，无需重启服务。
- `GET /api/v1/terminal/config` 新增运行时配置接口，向前端返回 `enabled`、`default_resources` 和 `max_resources`。
- `frontend/src/stores/terminal.ts` 的滑块上限跟随 `terminal_config.yaml` 的 `max_resources`（经 `GET /api/v1/terminal/config` 下发），镜像列表和运行时配置会一起加载；`DEFAULT_MAX_MEMORY_MB=4096` / `DEFAULT_MAX_CPU_CORES=4.0` 仍保留，仅作为运行时配置缺失时的兜底默认值。
- `frontend/src/components/terminal/ResourceSettings.vue` 使用自适应刻度，避免 16GB/32GB 这类大内存上限导致滑块刻度拥挤。
- `src/cygnusx/infrastructure/terminal/docker_manager.py` 在创建容器前按 `max_resources` 夹紧 memory、CPU、pids 和 tmpfs，保证绕过前端的请求也不会突破 YAML 硬上限。

### A.2（原 §9.3）参考基因组库升级为数据库模块

- `frontend/src/mock/referenceGenomes.ts` 按 PRD 将原「单一 Genome 列表」升级为 `SpeciesDatabase -> GenomeVersion -> DataFiles` 模型，覆盖 FASTA、GFF、GO、KEGG 四类数据文件，并保留 `MOCK_GENOMES` 等兼容导出，避免旧页面一次性断裂。
- 新模型增加基因中心视图所需的 `Gene`、`Transcript`、`GOAnnotation`、`KEGGAnnotation`、`GeneVersionMapping` 结构，支持基因检索、注释查看和跨版本 ID 映射。
- `frontend/src/views/ReferenceGenomesView.vue` 改为数据库列表页，展示物种、版本、数据文件构建状态和汇总指标；`frontend/src/views/ReferenceGenomeDetailView.vue` 改为版本详情页，提供概览、基因、功能注释、版本映射、数据文件等标签页。
- 后续已落地为独立后端模块：新增 `src/cygnusx/reference_genomes/api.py`，在 `src/cygnusx/api/v1/router.py` 挂载到 `/api/v1/reference-genomes`（物种/版本/基因搜索/序列/GO/KEGG/统一搜索）；前端 `frontend/src/api/referenceGenomes.ts` 对接真实接口，`ReferenceGenomesView.vue` / `ReferenceGenomeDetailView.vue` 已改用真实 API，不再依赖前端静态 mock 数据。

### A.3（原 §9.4）前端入口与路由兼容

- `frontend/src/layouts/DefaultLayout.vue` 将主导航「参考基因组」入口调整为「数据库」，入口路径切到 `/database`，并保留 `/reference-genomes` 与 `/reference-genomes/:id` 的高亮兼容。
- `frontend/src/router/index.ts` 新增 `/database` 与 `/database/:id` 路由；旧 `/reference-genomes` 路由继续指向同一页面，避免历史链接失效。
- 前端「代码沙盒」独立入口已从主导航移除，`/sandbox` 兼容跳转到 `/tools/terminal`；云端沙盒终端作为统一执行环境入口保留在生信工具箱和管理员终端管理中。
- `frontend/src/config/homeQuickEntries.ts` 将首页快捷入口同步为「数据库」，避免首页、侧边栏和实际路由命名不一致。

### A.4（原 §9.5）JBrowse 配置模型兼容扩展

- `src/cygnusx/tools/jbrowse/config.py` 为 `AssemblyConfig` 增加 `common_name`、`taxonomy_id`、`version_id`、`version_name`、`assembly_name`、`category`、`icon`、`is_default`、`status`、`release_date`、`stats`、`data_files` 等数据库模块字段。
- `src/cygnusx/tools/jbrowse/schema.py` 与 `frontend/src/types/jbrowse.ts` 同步扩展 DTO 类型，前端可从现有 JBrowse 接口读取更丰富的数据库版本元数据。
- `src/cygnusx/tools/jbrowse/service.py` 新增统一 `_assembly_to_dto` 转换逻辑，列表与详情接口共享同一字段映射，减少字段漂移。
- `tool_configs/jbrowse/jbrowse_config.yaml` 示例加入数据库版本元数据与数据文件配置，同时保留原 `fasta`、`fai` 字段，JBrowse 浏览器加载链路不变。

### A.5（原 §9.6）参考数据库离线构建边界

- `scripts/pyproject.toml` 新增为 `cygnusxtools` 独立安装配置，`scripts/cygnusxtools` 作为可安装 CLI 工具包，推荐通过 `pip install -e ./scripts` 安装；根目录 `pyproject.toml` 也保留 `cygnusxtools` console script，便于整个平台 editable install 时同时获得工具命令。
- `cygnusxtools` 的 argparse formatter 统一封装在 `scripts/cygnusxtools/utils/argparse.py`，优先使用 `rich-argparse` 美化 Usage、命令组、参数名、metavar 和默认值展示；缺少依赖时回退到标准库 `ArgumentDefaultsHelpFormatter`，方便源码调试。
- `cygnusxtools refdb build` 用于从 FA、GFF、GO、KO、KEGG 原始文件生成 `database.sqlite`、FASTA `.fai`、`database_manifest.json`、`jbrowse_assembly_snippet.yaml` 和 `build_report.json`。
- 该命令不挂接 Web API、Celery Worker 或前端操作，管理员应在独立计算节点、登录终端或维护窗口手动运行，避免大文件解析和索引构建给平台服务造成压力。
- 平台侧只注册生成好的 `path`、`index_path`、`db_path` 和 `build_status=ready`，通过 `tool_configs/jbrowse/jbrowse_config.yaml` 读取现成资产；当前不在平台内执行 FA/GFF/KO/KEGG 转换。
- `scripts/README.md` 记录 cygnusxtools 的安装方式、目录结构、扩展规范；`docs/update_info/26.6/offline_reference_database_build.md` 记录输入格式、构建命令、SQLite 表结构、注册步骤和排查清单。

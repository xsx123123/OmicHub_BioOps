# 数据目录结构说明

CygnusX 的运行时数据统一收口在宿主机 `/data/cygnusx` 下。为让数据目录更加清爽，**数据库、缓存、参考基因组、知识库、欢迎词**等五类核心数据已集中迁移至 `/data/cygnusx/cygnusx_data/` 子目录；用户上传、任务产物、下载工具等仍直接落在 `/data/cygnusx` 根下。

## 顶层目录总览

```
/data/cygnusx/                      # 平台数据根目录（storage.data_root）
├── cygnusx_data/                   # ★ 集中数据区（本次迁移收口目录）
│   ├── _pgdata/                    # PostgreSQL 数据库（bind mount）
│   ├── _redis/                     # Redis 持久化（bind mount）
│   ├── jbrowse/                    # JBrowse 2 参考基因组与预设轨道
│   ├── knowledge/                  # 实验室知识库运行时副本
│   └── welcome/                    # 管理员登录欢迎词（预生成 + 轮询游标）
├── users/                          # 用户私有数据（上传 / 分析结果 / 富集产物）
├── uploads/                        # 分片上传中转目录
├── bin/                            # 外置二进制工具（EBIDownload 等）
├── refdata/                        # 公共数据集
└── .tmp/                           # 临时文件
```

## cygnusx_data 子目录详解

### 1. `_pgdata/` — PostgreSQL 数据库

- **路径**：`/data/cygnusx/cygnusx_data/_pgdata`
- **挂载**：Docker bind mount → 容器内 `/var/lib/postgresql/data`（见 `deploy/docker/docker-compose.yml` 的 `db` 服务）
- **属主**：`uid=70`（postgres），权限 `700`，**切勿手动 chmod / chown**，否则 PG 拒启
- **内容**：用户账号 / 密码 / 配额、任务与样本元数据、AI 会话历史、技能与助手配置等全部关系型数据
- **迁移特性**：`rsync -a` 需保留属主；跨机迁移时务必先停 `cygnusx-db` 再同步，避免写中途复制导致不一致
- **备份建议**：优先用 `pg_dump` 逻辑备份；物理备份（直接拷贝目录）必须停库后进行

### 2. `_redis/` — Redis 持久化

- **路径**：`/data/cygnusx/cygnusx_data/_redis`
- **挂载**：Docker bind mount → 容器内 `/data`（见 `docker-compose.yml` 的 `cache` 服务）
- **属主**：`uid=999`（redis），权限 `755`
- **内容**：`dump.rdb` 持久化文件、Celery 任务队列（broker DB 1 / result DB 2）、限流计数、统计缓存
- **特性**：缓存类数据，丢失不致命（重建即可），但队列中的待执行任务会丢；迁移前建议停 `cygnusx-cache`

### 3. `jbrowse/` — JBrowse 2 参考基因组与预设轨道

- **路径**：`/data/cygnusx/cygnusx_data/jbrowse`
- **结构**：
  ```
  jbrowse/
  ├── ref/human_hg38/                # 参考基因组
  │   ├── GRCh38.p14.genome.fa       # ~3.3 GB FASTA
  │   └── GRCh38.p14.genome.fa.fai   # 索引
  └── tracks/human_hg38/             # 预设公共轨道
      └── gencode.v50.basic.annotation.gff3   # ~3.2 GB 基因注释
  ```
- **配置来源**：`tool_configs/jbrowse/jbrowse_config.yaml` 中的 `assemblies[*].fasta/fai` 与 `preset_tracks` 绝对路径
- **访问方式**：经 nginx `/tracks/` 路径流式读取（HTTP Range Request）。因 `cygnusx_data` 仍位于 `data_root`（`/data/cygnusx`）之下，`to_tracks_uri()` 自动换算为 `/tracks/cygnusx_data/jbrowse/...`，nginx alias 无需改动
- **新增基因组**：在 `jbrowse/ref/<species>/` 放 FASTA + `.fai`，并在 `jbrowse_config.yaml` 的 `assemblies` 追加一项，调用 `POST /api/v1/jbrowse/config/reload` 热生效
- **体积**：参考基因组与注释文件较大（单文件可达数 GB），迁往对象存储时建议按物种打包

### 4. `knowledge/` — 实验室知识库运行时副本

- **路径**：`/data/cygnusx/cygnusx_data/knowledge`
- **内容**：`meta.yaml`（导航配置）+ `*.md`（正文）+ `figure/`、`video/`（配图与视频）
- **数据来源**：仓库内 `docs/knowledge/`（Git 源码管控）的运行时副本
- **读取方式**：平台在线知识库由后端 `DocsService` 读取**仓库内** `docs/knowledge/`（容器内 `/app/docs/knowledge`，支持管理员在线编辑回写）；本目录为其在数据区的镜像副本，便于整库 `rsync` 备份 / 迁移
- **同步**：仓库 `docs/knowledge/` 内容更新后，重新执行 `cp -a docs/knowledge/. /data/cygnusx/cygnusx_data/knowledge/` 即可刷新副本

### 5. `welcome/` — 管理员登录欢迎词

- **路径**：`/data/cygnusx/cygnusx_data/welcome`
- **文件**：
  - `welcome.yaml` — 预生成的欢迎词数组（启动时不足 20 条自动调默认 AI provider 补齐）
  - `welcome_state.yaml` — 轮询游标（`next_index`，单调递增，重启不丢）
- **配置来源**：`src/cygnusx/core/config.py` 的 `welcome_yaml` / `welcome_state_yaml`
- **特性**：运行时仅读盘 + 游标前进（< 1ms），零 LLM 调用延迟；两文件缺失时回退内置兜底文案，不影响登录

## 其余根目录（未迁移）

| 目录 | 说明 | 为何不迁入 cygnusx_data |
|------|------|--------------------------|
| `users/<user_id>/` | 用户私有数据（上传 / 结果 / 富集） | 由 `storage.data_root + users_subdir` 拼接，路径深耦合于业务代码，保持原位避免大面积改造 |
| `uploads/` | 分片上传中转 | 临时数据，与用户目录同属文件存储层 |
| `bin/` | EBIDownload 等外置二进制 | 工具类，随镜像 / 对象存储分发，非运行时数据 |
| `refdata/` | 公共数据集 | 独立数据集，按需管理 |
| `.tmp/` | 临时文件 | 易失数据 |

> 以上目录仍位于 `data_root`（`/data/cygnusx`）之下，`rsync /data/cygnusx` 可整体带走全部数据（含 `cygnusx_data`）。

## 迁移涉及到的配置 / 脚本

本次迁移同步修改了以下文件中的硬编码路径：

| 文件 | 修改内容 |
|------|----------|
| `deploy/docker/docker-compose.yml` | `db` / `cache` 的 bind mount 改为 `cygnusx_data/_pgdata`、`cygnusx_data/_redis` |
| `deploy/docker/docker-compose.prod.yml` | 生产环境 `db` 的 bind mount 同步修改 |
| `src/cygnusx/core/config.py` | `welcome_yaml` / `welcome_state_yaml` 指向 `cygnusx_data/welcome/` |
| `tool_configs/jbrowse/jbrowse_config.yaml` | `assemblies.fasta/fai` 与 `preset_tracks.file` 指向 `cygnusx_data/jbrowse/` |

> 容器内 `/data/cygnusx` 挂载、nginx `/tracks/` alias、`storage.data_root` 均**未改动**——因为 `cygnusx_data` 仍是 `data_root` 的子目录，所有基于 `data_root` 的换算逻辑（如 `to_tracks_uri`）天然兼容。

## 快速迁移 / 备份

```bash
# 整库迁移（含数据库 + 缓存 + 参考基因组 + 用户数据）
# 1. 先停服，避免写中途复制
docker compose -f deploy/docker/docker-compose.yml down
docker compose -f deploy/docker/docker-compose.worker.yml down

# 2. 增量同步（断点续传）
sudo rsync -aP --info=progress2 /data/cygnusx/ <目标机>:/data/cygnusx/

# 3. 目标机拉起
docker compose -f deploy/docker/docker-compose.yml up -d
docker compose -f deploy/docker/docker-compose.worker.yml up -d
docker exec cygnusx-web uv run alembic upgrade head
```

> ⚠️ `_pgdata` 属主为 postgres（uid 70），`rsync` 必须加 `-a`（或 `--numeric-ids`）保留属主；NFS 不适合存放 PG 数据（一致性风险），请用本地 SSD 或块存储。

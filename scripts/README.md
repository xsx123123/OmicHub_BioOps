# omichubtools 工具目录

`scripts/` 现在作为 OmicHub 离线维护工具包 `omichubtools` 的源码目录。目标是把部署、数据准备、数据库构建、巡检等重型或管理员操作收敛到一个可安装的 CLI 中，避免把转换任务压到 Web 服务或 Celery 任务链路上。

## 安装方式

推荐只安装工具包本身：

```bash
pip install -e ./scripts
```

如果你同时需要安装整个平台，也可以在项目根目录执行：

```bash
pip install -e ./
```

安装后会注册命令，帮助信息由 `rich-argparse` 美化显示：

```bash
omichubtools --help
omichubtools version
omichubtools refdb build --help
```

未安装时，也可以用源码路径调试：

```bash
PYTHONPATH=scripts python -m omichubtools --help
PYTHONPATH=scripts python -m omichubtools refdb build --help
```

新自动化脚本统一使用 `omichubtools refdb build ...`。

## 当前命令结构

```text
omichubtools
├── version                         # 查看工具版本、Python 运行环境和外部工具状态
├── refdb
│   └── build                       # 离线构建 FA/GFF/GO/KO/KEGG 参考数据库资产
└── build-reference-database        # refdb build 的兼容别名
```

## 脚本与文件清单

`scripts/` 目录下既有可直接运行的独立脚本，也有正在演进的 `omichubtools` 离线 CLI 包。下面分别说明每个文件/脚本的作用。

### 顶层独立维护脚本

| 脚本 | 作用 | 典型用法 |
| --- | --- | --- |
| `check_migrations.py` | 检查 Alembic 迁移链的健康状况：解析所有迁移文件的 `revision` / `down_revision` / `depends_on`，验证依赖是否存在、root 唯一、拓扑连通，并可选调用 `alembic heads` 确认 head 唯一。 | `python scripts/check_migrations.py` |
| `download_jbrowse2.sh` | 一键下载 JBrowse 2 Web 静态产物（默认 v2.15.1）到 `pipelines/jbrowse2/`，供 nginx 以 `/jbrowse2/` 路径提供静态资源。 | `./scripts/download_jbrowse2.sh` |
| `init_admin.py` | 首次部署时初始化管理员账号。支持通过环境变量自定义用户名、邮箱和密码；生产环境必须设置 `OMICHBUB_INIT_ADMIN_PASSWORD`。若启用饼干系统，会自动为管理员创建饼干账户。 | `python scripts/init_admin.py` |
| `init_cookies.py` | 初始化默认的饼干（资源计费）定价策略，包括 RNA-seq、ATAC-seq、scRNA-seq 任务定价、CPU/内存费率、沙盒费用以及新用户注册赠送。 | `python scripts/init_cookies.py` |
| `import_atacseq_knowledge.py` | 全量同步 `docs/knowledge/atac-seq/` 中的 Markdown，并保留全部 PDF/图片静态附件，写入独立 `atacseq` AI 检索知识库。 | `python scripts/import_atacseq_knowledge.py --admin-user-id <UUID>` |
| `migrate_knowledge_base.py` | 一次性迁移：将 `docs/knowledge/meta.yaml` 中声明的 Markdown 文档导入数据库，生成初始版本并关联编辑者。建议在 `alembic upgrade head` 之后执行。 | `python scripts/migrate_knowledge_base.py --admin-user-id <UUID>` |
| `render_worker_config.py` | 读取 `data/worker_config.yaml`，校验 `paths` 配置，将 `shared_data_dir` / `pipeline_dir` 渲染为 shell 兼容的 env 文件 `data/.worker-config.env`，供 Docker Compose 插值使用。 | `python scripts/render_worker_config.py` |
| `sync_knowledge_from_files.py` | 增量同步 `meta.yaml` 登记的 Markdown 与 Wiki 集合。QC、Cloud 等递归领域目录由各自专用导入脚本处理；本地 Docker 环境可统一执行 `make sync-knowledge`。 | `python scripts/sync_knowledge_from_files.py --auto-admin` |
| `worker-compose.sh` | 启动 Worker 的包装脚本：先调用 `render_worker_config.py` 生成 env 文件，再 source 后执行 `docker compose -f deploy/docker/docker-compose.worker.yml`。 | `./scripts/worker-compose.sh up -d` |

### omichubtools 包内文件

| 文件 | 作用 |
| --- | --- |
| `pyproject.toml` | `omichubtools` 独立包的安装配置（`pip install -e ./scripts`），定义依赖、入口脚本、构建后端和 ruff 配置。 |
| `omichubtools/__init__.py` | 包初始化，暴露 `__version__`。 |
| `omichubtools/__main__.py` | 支持以 `python -m omichubtools` 方式启动 CLI。 |
| `omichubtools/cli.py` | CLI 顶层入口：注册全局参数、`version`、`refdb build` 以及兼容别名 `build-reference-database`。 |
| `omichubtools/commands/__init__.py` | 命令模块包标记。 |
| `omichubtools/commands/reference_database.py` | `refdb build` 命令的完整实现：解析 FASTA/GFF/GO/KO/KEGG 输入，生成 SQLite 数据库、`.fai` 索引、manifest 和 JBrowse 配置片段。 |
| `omichubtools/config/default.yaml` | 包内默认日志配置（标签、级别、样式）。 |
| `omichubtools/config/software.yaml` | 软件元信息（版本、作者、描述）和外部工具声明（如 `samtools`）。 |
| `omichubtools/utils/argparse.py` | 自定义 `OmicHubHelpFormatter`，基于 `rich-argparse` 美化帮助输出，并提供无 Rich 时的降级。 |
| `omichubtools/utils/configuration.py` | 配置加载：读取包内 YAML，支持项目级 `omichubtools.yaml` / `omichubtools.local.yaml` 覆盖。 |
| `omichubtools/utils/logo.py` | 终端 logo 显示，支持 Rich 和 rich-gradient 渐变效果，无依赖时降级为纯文本。 |
| `omichubtools/utils/log_utils.py` | loguru + Rich 日志初始化，支持拦截标准 logging、捕获 warning、文件日志和分级别控制台输出。 |
| `omichubtools/utils/version.py` | `version` 命令实现：展示 Python 运行时、平台、依赖包版本和外部工具状态。 |

## 参考数据库离线构建

典型命令：

```bash
omichubtools refdb build \
  --species-id Lsat \
  --version-id Lsat_v11 \
  --version-name v11 \
  --assembly-name Lsat.1.v11 \
  --scientific-name "Lactuca sativa" \
  --common-name "生菜" \
  --fasta /data/omichub/omichub_data/db/Lsat/v11/Lsat.1.v11.fa \
  --gff /data/omichub/omichub_data/db/Lsat/v11/Lsat.1.v11.gff3 \
  --go /data/omichub/omichub_data/db/Lsat/v11/go_annotations.tsv \
  --go-terms /data/omichub/omichub_data/db/Lsat/v11/go_terms.tsv \
  --ko /data/omichub/omichub_data/db/Lsat/v11/ko_annotations.tsv \
  --kegg /data/omichub/omichub_data/db/Lsat/v11/kegg_annotations.tsv \
  --out-dir /data/omichub/omichub_data/db/Lsat/v11/build \
  --force
```

输出文件：

| 文件 | 用途 |
| --- | --- |
| `database.sqlite` | SQLite 查询库，包含 GFF feature、gene、transcript、GO term、GO、KO、KEGG 注释 |
| `*.fai` | FASTA 随机访问索引 |
| `database_manifest.json` | 构建清单 |
| `jbrowse_assembly_snippet.yaml` | 可合并到 `tool_configs/jbrowse/jbrowse_config.yaml` 的配置片段 |
| `build_report.json` | 构建统计和排查报告 |

`--go-terms` 可传 GO term TSV/CSV 或 `go-basic.obo`，用于把两列 `gene_id/go_id` 文件补全为带 term/namespace 的注释。`--kegg` 支持 `gene_id/kegg_id`、`gene_id/pathway_id` 和 `ko_id/pathway_id` 三类表。

CLI 帮助输出使用 `rich-argparse`，会保留参数默认值并用 Rich 样式突出命令、分组、参数名和 metavar。

平台只注册这些生成好的文件路径，不在 API 或 Worker 中执行转换。

## 包结构概览

```text
scripts/
├── pyproject.toml
├── omichubtools/
│   ├── __init__.py
│   ├── __main__.py
│   ├── cli.py
│   ├── commands/
│   │   ├── __init__.py
│   │   └── reference_database.py
│   ├── config/
│   │   ├── __init__.py
│   │   ├── default.yaml
│   │   └── software.yaml
│   └── utils/
│       ├── __init__.py
│       ├── argparse.py
│       ├── configuration.py
│       ├── logo.py
│       ├── log_utils.py
│       └── version.py
├── check_migrations.py
├── download_jbrowse2.sh
├── init_admin.py
├── init_cookies.py
├── migrate_knowledge_base.py
├── render_worker_config.py
├── sync_knowledge_from_files.py
└── worker-compose.sh
```

各文件/脚本的具体作用见上文「脚本与文件清单」。
```

## 配置覆盖

`omichubtools` 默认读取包内配置：

- `scripts/omichubtools/config/software.yaml`
- `scripts/omichubtools/config/default.yaml`

后续如需要项目级覆盖，可在当前工作目录放置：

- `omichubtools.yaml`
- `omichubtools.local.yaml`

或者使用全局参数传入：

```bash
omichubtools --config ./my-tools.yaml version
```

## 后续扩展规范

新增子命令建议遵循以下方式：

1. 在 `scripts/omichubtools/commands/` 下新增独立模块，例如 `downloads.py`、`deploy.py`。
2. 模块中提供 `add_<command>_arguments(parser)` 和 `run_<command>(args)`，保持 argparse 入口清晰。
3. 在 `scripts/omichubtools/cli.py` 注册到对应 subparser。
4. 重型任务必须保持离线执行，不要在 Web API、Celery Worker 或前端点击链路中隐式触发。
5. 输出产物写入 `/data/omichub/omichub_data/...` 或显式 `--out-dir`，并生成可审计的 manifest/report。
6. 新命令完成后同步更新本文档和必要的架构文档。

## 与 gpse 工具模块的关系

本目录复用了 gpse 中 `logo.py`、`log_utils.py`、`version.py`、`configuration.py` 的设计思路，但没有在运行时 import 外部 gpse 仓库。原因是 `pip install -e ./scripts` 部署时不能依赖另一个本地 checkout。

当前实现提供同类能力：

- `utils/logo.py`：启动 logo，支持 rich/rich-gradient 可选增强。
- `utils/log_utils.py`：loguru + rich 控制台日志，rich 不存在时自动降级。
- `utils/version.py`：展示 Python、依赖包和外部工具状态。
- `utils/configuration.py`：包内 YAML 配置 + 项目级覆盖。

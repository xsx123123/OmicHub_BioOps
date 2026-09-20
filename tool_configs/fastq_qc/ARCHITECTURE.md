# FASTQ 极速质控：架构与后续实施清单

本文档是 `FASTQ 极速质控` 工具的实现交接说明。配置基线已在同目录的 `config.yaml` 中就绪；后续开发应以该文件为唯一的平台默认参数来源。

## 目标与边界

- 输入：用户上传的单端（SE）或双端（PE）FASTQ / FASTQ.GZ 文件。
- 处理：逐样本使用 `fastp` 完成质量评估与清洗，再使用 `MultiQC` 汇总所有成功样本。
- 输出：清洗后 FASTQ、每样本 `fastp.json` / HTML、批次 MultiQC HTML / parquet、任务摘要和下载压缩包。
- 图表：单样本页面读取 `fastp.json`；批次页面由后端读取 `multiqc.parquet` 并输出 JSON，前端使用 Plotly 重绘。
- 不做：浏览器不直接解析 parquet，也不直接调用 MultiQC Python API。

## 配置层（已完成）

| 文件 | 作用 |
| --- | --- |
| `fastq_qc/config.yaml` | 镜像、队列、资源、fastp / MultiQC 默认参数、数据目录与启动检查。 |
| `tools_setting.yaml` | 已将 `fastq-qc` 工具卡片的 `config_dir` 指向 `fastq_qc`。 |
| `fastq_qc/README.md` | 配置使用方式与运行边界。 |

任务创建时必须将 `fastp.defaults` 与前端提交的允许覆盖项合并，写入 `${storage.root}/{task_id}/task.yaml`。任务启动之后只使用该快照，禁止再读取会变化的全局参数作为本次任务输入。

## 目标目录结构

```text
src/cygnusx/tools/fastq_qc/
├── __init__.py
├── api.py                 # FastAPI router，声明 prefix=/qc、tags=["FASTQ QC"]
├── config.py              # config.yaml 的 Pydantic 模型、mtime 热重载加载器
├── schema.py              # 请求/响应 DTO 与任务状态枚举
├── service.py             # 创建、查询、取消、下载和图表数据服务
├── runner.py              # fastp / multiqc 命令构造与进程执行封装
├── chart_service.py       # fastp.json / multiqc.parquet 转前端 JSON
└── tasks.py               # Celery `qc.run_pipeline` 任务

src/cygnusx/infrastructure/celery_app/
└── celery.py              # 注册 QC 队列路由（如项目未自动发现任务）

deploy/docker/
├── Dockerfile.worker      # 安装或构建 cygnusx/qc-worker 镜像
└── docker-compose.yml     # 挂载 tool_configs 和 QC 数据根目录，启动 QC Worker
```

## 运行架构

```text
前端工具页
    │ POST /api/v1/qc/tasks
    ▼
FastAPI：校验输入、创建数据库任务、写 task.yaml、投递 Celery
    │ queue=qc
    ▼
QC Celery Worker（cygnusx/qc-worker）
    ├── 对每个样本执行 fastp
    ├── 写 reports/{sample}.fastp.json 与 output/*.clean.fastq.gz
    ├── 对成功样本执行 multiqc
    └── 回写任务进度、摘要、失败样本与最终状态
    │
    ├──────────► MySQL：任务列表/状态/摘要
    └──────────► ${storage.root}/{task_id}/：所有文件产物

前端轮询或 WebSocket
    │ GET /api/v1/qc/tasks/{task_id}
    ├──► 单样本图表：fastp.json → JSON
    ├──► 批次图表：multiqc.parquet → JSON
    └──► 下载/预览：result.zip / multiqc_report.html
```

## 任务状态机

```text
PENDING
  └──> QUEUED
        └──> RUNNING_FASTP
              └──> RUNNING_MULTIQC
                    ├──> SUCCESS
                    ├──> PARTIAL
                    └──> FAILED

PENDING / QUEUED / RUNNING_FASTP / RUNNING_MULTIQC
  └──> CANCELED
```

- `PARTIAL`：至少一个样本成功并完成 MultiQC，但存在失败样本。
- `FAILED`：所有样本失败、MultiQC 失败、缺少要求的产物或 Worker 异常。
- 每个样本完成后更新 `done`、`total` 与 `current_sample`，前端不依赖日志文本判断进度。

## API 契约

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `POST` | `/api/v1/qc/tasks` | 校验样本、创建任务快照并投递。 |
| `GET` | `/api/v1/qc/tasks` | 读取数据库中的任务列表和摘要。 |
| `GET` | `/api/v1/qc/tasks/{task_id}` | 状态、进度、参数快照、失败样本和产物信息。 |
| `GET` | `/api/v1/qc/tasks/{task_id}/samples/{sample}/chart` | 由 `fastp.json` 提供单样本图表数据。 |
| `GET` | `/api/v1/qc/tasks/{task_id}/multiqc/plots` | 由 parquet 提供跨样本图表数据。 |
| `GET` | `/api/v1/qc/tasks/{task_id}/report.html` | 返回或代理 MultiQC HTML 预览。 |
| `GET` | `/api/v1/qc/tasks/{task_id}/download` | 首次按需生成并缓存 `result.zip`。 |
| `DELETE` | `/api/v1/qc/tasks/{task_id}` | 撤销 Celery 任务并标记取消；文件清理由保留策略决定。 |

创建请求中的 `params` 必须只接受 `config.fastp.overridable` 白名单字段。不得接收命令字符串、文件系统路径覆盖、`threads`、超时或镜像信息。

## Worker 实施要求

### 镜像

- 镜像：`cygnusx/qc-worker:${image.tag}`。
- 必需软件：`fastp >= 0.24`、`multiqc >= 1.29`、Python、`pyarrow` 或 `polars`。
- Worker 启动时执行 `validation.on_worker_start`：`fastp --version`、MultiQC 最低版本检查及 `storage.root` 写权限检查。
- API 服务与 Worker 都应以只读方式挂载 `tool_configs`，并通过 `CYGNUSX_TOOL_CONFIGS` 定位其根目录。

### fastp 命令规则

- 每个样本都指定 `-j reports/{sample}.fastp.json` 与 `-h reports/{sample}.fastp.html`。
- SE：`-i R1 -o output/{sample}.clean_R1.fastq.gz`。
- PE：额外使用 `-I R2 -O output/{sample}.clean_R2.fastq.gz`，且仅在 `detect_adapter_for_pe=true` 时添加 `--detect_adapter_for_pe`。
- 将 `qualified_quality_phred`、`unqualified_percent_limit`、`n_base_limit`、`length_required`、`trim_to_len`、`adapter_trim`、`correction` 与 `compression_level` 显式映射为受控参数。
- 每样本日志写入 `logs/{sample}.fastp.log`，并遵守 `fastp.timeout_per_sample`。

### MultiQC 与产物校验

- 仅将成功产生 `*.fastp.json` 的样本输入 MultiQC。
- 使用 `multiqc reports/ -o multiqc/ -n multiqc_report.html -f --no-ansi -m fastp`，再附加受控的 `multiqc.extra_args`。
- 当 `require_parquet=true` 时，必须存在：
  - `multiqc/multiqc_report.html`
  - `multiqc/multiqc_data/multiqc.parquet`
- 缺少任一必需产物时任务状态为 `FAILED`，并记录具体缺失路径。

## 数据模型与文件布局

```text
${storage.root}/{task_id}/
├── task.yaml
├── input/                  # 可选：任务私有输入副本或链接信息
├── output/                 # 清洗后的 FASTQ
├── reports/                # 每样本 fastp JSON / HTML
├── multiqc/                # multiqc_report.html 与 multiqc_data/multiqc.parquet
├── logs/                   # fastp 与 multiqc 日志
└── result.zip              # 首次下载时生成的缓存文件
```

建议数据库任务实体至少保存：`id`、`name`、`status`、`progress_done`、`progress_total`、`current_sample`、`params_snapshot`、`summary`、`failed_samples`、`celery_task_id`、`created_at`、`started_at`、`finished_at` 与 `error_message`。

摘要应从每个 `fastp.json` 提取并入库，至少包含总 reads、保留 reads、保留率、Q20、Q30、GC 含量与 duplication；任务列表不应扫描任务目录或解析大文件。

## 图表数据契约

### 单样本

`chart_service.py` 解析 `reports/{sample}.fastp.json`，为前端返回 before / after 两组数据：

- 基础统计：reads、bases、Q20/Q30、GC、过滤/保留率。
- Per-base quality、per-base content、GC distribution、N content。
- Adapter content、duplication、overrepresented sequences 与 K-mer（数据存在时）。

接口仅返回重绘所需 JSON；完整 `fastp.html` 可作为附加下载或预览，不应作为主要图表实现。

### 批次

使用 `polars` 或 `pyarrow` 读取 `multiqc.parquet`，按 plot 和样本组装稳定 JSON。响应需包含：`plot_id`、`title`、坐标轴信息、series 和样本筛选元数据。不要将 DataFrame、parquet 文件或 MultiQC Python 对象直接暴露给浏览器。

## 开发顺序

1. **后端基础**：创建 `fastq_qc` 子包、Pydantic 配置加载器和 `fastq_qc_config_yaml` 设置项。
2. **任务持久化**：添加数据库模型/迁移、状态转换和任务快照写入。
3. **Worker**：实现安全的参数到 argv 映射、逐样本幂等执行、日志、超时与产物校验。
4. **API**：实现创建、列表、详情、取消、报告和下载接口。
5. **图表服务**：先实现 `fastp.json` 单样本解析，再实现 parquet 批次解析。
6. **前端**：接入现有 FASTQ 页面，完成创建表单、任务列表、进度、图表与下载。
7. **部署**：构建 QC Worker 镜像，配置 `qc` 队列、挂载与数据目录权限。
8. **测试与上线**：覆盖 SE/PE、部分失败、取消、重试、产物缺失和大批量任务场景。

## 验收清单

- [ ] `GET /api/v1/tools` 中 `fastq-qc` 的 `config_dir` 为 `fastq_qc`。
- [ ] Worker 启动校验 fastp、MultiQC 版本和数据目录写权限。
- [ ] SE 与 PE 输入均能输出对应 clean FASTQ、fastp JSON / HTML。
- [ ] 不合规的前端参数被拒绝，资源限制不能被覆盖。
- [ ] 成功任务生成 MultiQC HTML 与 parquet。
- [ ] 单样本和批次图表接口均返回前端可直接绘制的 JSON。
- [ ] 个别样本失败时任务为 `PARTIAL` 并保留成功样本结果。
- [ ] 重试不会重复计算已有 `fastp.json` 的样本。
- [ ] 取消任务后不再继续运行，并能正确显示 `CANCELED`。
- [ ] 首次下载创建 `result.zip`，重复下载复用缓存。

## 关键风险

- 大文件处理：不将 FASTQ、fastp JSON 或 parquet 全量读入 API 内存；解析应流式或限制单次返回量。
- 路径安全：上传文件路径必须限定在平台管理的数据根目录，并拒绝路径穿越。
- 命令安全：只通过参数白名单构造 argv 列表，禁止拼接 shell 字符串。
- 任务隔离：每个任务只访问自己的任务目录；下载接口必须执行用户权限校验。
- 可观测性：保留命令日志、版本信息、参数快照和失败原因，方便复现与定位。

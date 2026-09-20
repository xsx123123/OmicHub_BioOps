# FASTQ 极速质控配置

本目录保存 FASTQ 极速质控工具的运行时默认配置。API 服务和 Celery QC Worker 都必须将仓库根目录挂载到 `CYGNUSX_TOOL_CONFIGS`（默认 `/app/tool_configs`），并读取 `fastq_qc/config.yaml`。

## 运行链路

1. API 使用 `fastp.defaults` 初始化任务参数，仅接受 `fastp.overridable` 中的前端覆盖项。
2. API 将合并结果、样本清单和镜像版本写入 `${storage.root}/{task_id}/task.yaml`。
3. Worker 对每个样本执行 `fastp`，将 JSON/HTML 写入 `reports/`，清洗后的 FASTQ 写入 `output/`。
4. Worker 用 `multiqc.modules` 聚合成功的 `fastp` JSON，产出 HTML 报告和 `multiqc_data/multiqc.parquet`。
5. 后端解析 `fastp.json` 供单样本图表使用，并解析 parquet 供批次汇总图表使用。

## 配置边界

- `resources`、队列超时和 `fastp.threads` 是平台资源限制，不能由前端任务参数覆盖。
- `fastp.overridable` 是唯一允许前端覆盖的平台参数白名单。
- `multiqc.min_version` 固定为 `1.29` 或更高，因为批次图表依赖 parquet 输出。
- `extra_args` 仅用于管理员临时追加原生命令参数；修改前应先在隔离环境验证。

## Worker 启动检查

Worker 启动时应依次执行 `validation.on_worker_start` 中的检查：确认 `fastp` 可执行、MultiQC 版本满足最低要求，以及 `storage.root` 对 Worker 可写。

完整实现契约、Celery 流程、API 和前端图表数据路径见 `docs/26.7.18/CygnusX_FASTQ质控模块实现方案.md`。

切换到主项目继续开发前，先阅读本目录的 `ARCHITECTURE.md`；其中列出了目标代码结构、API 契约、Worker 规则、开发顺序和验收清单。

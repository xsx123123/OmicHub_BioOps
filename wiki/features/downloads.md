# 数据下载

平台「数据下载」入口统一承载公共数据库下载与云对象存储直拉，复用现有 `Task` 聚合根。

## 架构

```text
前端 /downloads
  ↓ POST /api/v1/downloads
DownloadService
  → 创建 Task(flow_id="ebi_download")
  → 投递 Celery run_download(task_id)
Celery
  → source=sra: EBIDownload
  → source=cloud_storage: ossutil/tosutil/obsutil
```

下载完成后文件自动出现在「数据管理」。

## 公共数据库下载（EBI/NCBI）

启用步骤：

```bash
cd pipelines/EBIDownload
CC=clang cargo build -p ebidownload-cli --release

mkdir -p /data/cygnusx/bin
cp target/release/EBIDownload /data/cygnusx/bin/
cp EBIDownload.yaml /data/cygnusx/bin/
```

Worker 需安装 `sra-tools`：

```bash
mamba install -n base -c bioconda sra-tools
```

环境变量：

```bash
ENABLE_EBI_DOWNLOAD=true
EBI_DOWNLOAD_BINARY=/data/cygnusx/bin/EBIDownload
EBI_DOWNLOAD_YAML=/data/cygnusx/bin/EBIDownload.yaml
```

## 云存储直拉

| 云商 | URI 前缀 | 默认二进制 |
|---|---|---|
| 阿里云 OSS | `oss://bucket/path` | `/data/cygnusx/bin/ossutil` |
| 火山引擎 TOS | `tos://bucket/path` | `/data/cygnusx/bin/tosutil` |
| 华为云 OBS | `obs://bucket/path` | `/data/cygnusx/bin/obsutil` |

环境变量：

```bash
ENABLE_CLOUD_STORAGE_DOWNLOAD=true
CLOUD_OSSUTIL_BINARY=/data/cygnusx/bin/ossutil
CLOUD_TOSUTIL_BINARY=/data/cygnusx/bin/tosutil
CLOUD_OBSUTIL_BINARY=/data/cygnusx/bin/obsutil
```

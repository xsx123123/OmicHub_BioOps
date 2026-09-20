# 08 · 存储迁移方案（NAS + 对象存储）

> 目标：从单机 bind mount `/data/cygnusx` 迁移到高速 NAS + 对象存储，支撑万人级与集群部署
> 原则：分层存储、热温冷分级、应用层无感切换

## 一、当前存储架构问题

### 1.1 现状

```
宿主机 /data/cygnusx (bind mount)
├── users/{user_id}/raw/           # 用户原始上传（FASTQ 等）
├── users/{user_id}/results/{task_id}/  # 分析结果
├── .tmp/{upload_id}/              # 分片上传临时
├── .conda_envs/                   # Snakemake conda 环境
├── welcome/                       # 欢迎词 YAML
└── bin/                           # EBIDownload 二进制
```

web 与 worker 通过共享同一宿主 `/data/cygnusx` 实现数据交换。

### 1.2 问题

| # | 问题 | 等级 | 万人级影响 |
|---|------|------|-----------|
| T-1 | 单机磁盘容量上限 | P0 | 万人 FASTQ 数据 PB 级，单机不可承载 |
| T-2 | 无冗余（磁盘损坏即丢数据） | P0 | 组学数据是核心资产 |
| T-3 | 路径硬编码宿主 | P0 | `/home/zj/pipeline/RNAFlow/snakefile` 不可移植 |
| T-4 | bind mount 无法跨节点 | P0 | K8s Pod 调度到任意节点都需访问同一数据 |
| T-5 | 无生命周期管理 | P1 | 原始 FASTQ 永久占用高速存储 |
| T-6 | 无版本控制 | P1 | 结果文件被覆盖无法回溯 |
| T-7 | 无带宽隔离 | P2 | 大文件下载占用全带宽，影响分析任务 IO |

## 二、目标存储架构

```
┌─────────────────────────────────────────────────────┐
│              应用层（FastAPI / Celery）              │
│   FileService 抽象层（StorageBackend 接口）          │
├──────────────┬──────────────────┬───────────────────┤
│  热存储 NAS  │  温存储 NAS      │  冷存储 OSS       │
│  (原始上传)  │  (分析结果)      │  (归档/历史)      │
│  高速 SSD    │  标准 SSD        │  低成本对象存储   │
│  ReadWriteMany│  ReadWriteMany  │  ReadWriteMany    │
├──────────────┴──────────────────┴───────────────────┤
│  元数据层：PostgreSQL file_records 表               │
│  （storage_backend + storage_key + tier 字段）       │
└─────────────────────────────────────────────────────┘
```

### 2.1 三级存储分层

| 层级 | 存储 | 用途 | 访问频率 | 价格(阿里云) |
|------|------|------|----------|-------------|
| **热存储** | NAS SSD | 原始上传、活跃任务工作目录、conda envs | 高（实时读写） | ¥1.0/GB/月 |
| **温存储** | NAS 效率型 | 分析结果、近期报告 | 中（下载/查看） | ¥0.35/GB/月 |
| **冷存储** | OSS 标准/低频/归档 | 历史数据归档、大文件备份 | 低 | ¥0.12/0.08/0.033/GB/月 |

### 2.2 数据生命周期

```
原始上传 → 热存储 NAS（立即可用于分析）
    │
    │ 分析任务读取
    ▼
分析结果 → 温存储 NAS（30 天内可下载）
    │
    │ 30 天未访问
    ▼
归档 → OSS 低频/归档（长期保留，按需取回）
    │
    │ 90 天未访问 + 标记可删
    ▼
清理 → 删除（或仅保留元数据记录）
```

## 三、应用层改造（StorageBackend 抽象）

### 3.1 当前问题

`FileService` 直接操作 `Path(settings.storage_path)` 本地文件系统，无法切换后端。

### 3.2 抽象接口设计

```python
# domain/file/storage_backend.py
from abc import ABC, abstractmethod
from pathlib import Path

class StorageBackend(ABC):
    """存储后端抽象 — 本地/NAS/OSS 统一接口"""

    @abstractmethod
    async def upload(self, key: str, data: bytes | Path, metadata: dict = None) -> str:
        """上传，返回 storage_uri"""

    @abstractmethod
    async def download(self, key: str, dest: Path | None = None) -> bytes:
        """下载到本地或返回 bytes"""

    @abstractmethod
    async def get_presigned_url(self, key: str, expires: int = 3600) -> str:
        """获取预签名下载 URL（对象存储专用，NAS 返回代理 URL）"""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """删除"""

    @abstractmethod
    async def exists(self, key: str) -> bool:
        """是否存在"""

    @abstractmethod
    async def move(self, src_key: str, dest_key: str, dest_backend: "StorageBackend" = None) -> str:
        """移动（可跨后端，用于生命周期迁移）"""
```

### 3.3 三个实现

```python
# infrastructure/storage/local_backend.py
class LocalStorageBackend(StorageBackend):
    """本地/NAS 文件系统（开发环境 + 热存储）"""
    # 直接 Path 操作，现有 FileService 逻辑迁移至此

# infrastructure/storage/oss_backend.py
class OSSStorageBackend(StorageBackend):
    """阿里云 OSS / S3 对象存储"""
    # 用 oss2 SDK，upload 用分片上传，download 用预签名 URL
    # 大文件直接返回预签名 URL 给前端，不经后端中转

# infrastructure/storage/tiered_backend.py
class TieredStorageBackend(StorageBackend):
    """分层存储 — 按文件 tier 路由到不同后端"""
    def __init__(self, hot: LocalStorageBackend, cold: OSSStorageBackend):
        self._hot = hot
        self._cold = cold

    async def upload(self, key, data, metadata=None):
        tier = metadata.get("tier", "hot")
        if tier == "hot":
            return await self._hot.upload(key, data, metadata)
        return await self._cold.upload(key, data, metadata)

    async def download(self, key, dest=None):
        # 先查 hot，miss 查 cold
        if await self._hot.exists(key):
            return await self._hot.download(key, dest)
        return await self._cold.download(key, dest)
```

### 3.4 FileService 改造

```python
# FileService 注入 StorageBackend
class FileService:
    def __init__(self, db: AsyncSession, storage: StorageBackend | None = None):
        self._storage = storage or get_default_storage()  # 工厂按配置返回

    async def save_chunk(self, ...):
        # 原 Path 写入 → self._storage.upload(key, chunk)
        ...

    async def download_file(self, file_id, user_id):
        file = await self._repo.get_by_id(file_id)
        # 对象存储：返回预签名 URL，前端直连 OSS（不经后端中转，省带宽）
        if file.storage_backend == "oss":
            return await self._storage.get_presigned_url(file.storage_key)
        # NAS：返回 FileResponse 流式
        return await self._storage.download(file.storage_key)
```

### 3.5 数据模型扩展

```python
# FileRecordModel 新增字段
storage_backend: str = "local"   # local / oss / s3
storage_key: str = ""            # 对象存储 key 或 NAS 相对路径
storage_tier: str = "hot"        # hot / warm / cold
last_accessed_at: datetime = None  # 生命周期判断依据
```

Alembic 迁移：给 file_records 加 4 列 + 索引 `idx_file_storage_tier`。

## 四、NAS 配置（K8s PVC）

### 4.1 阿里云 NAS CSI 驱动

```yaml
# StorageClass — 极速型 NAS（最高 200MB/s/TiB，亚毫秒延迟）
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nas-ssd
provisioner: nasplugin.csi.alibabacloud.com
parameters:
  volumeAs: subpath
  server: xxx.nas.aliyuncs.com
  path: /cygnusx-hot
  archiveOnDelete: "false"
reclaimPolicy: Retain
volumeBindingMode: Immediate
---
# 温存储 — 效率型 NAS（更低成本）
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: nas-efficiency
provisioner: nasplugin.csi.alibabacloud.com
parameters:
  volumeAs: subpath
  server: xxx.nas.aliyuncs.com
  path: /cygnusx-warm
---
# PVC
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: cygnusx-hot
spec:
  accessModes: [ReadWriteMany]   # 关键：多 Pod 同时读写
  storageClassName: nas-ssd
  resources: {requests: {storage: 5Ti}}
```

### 4.2 关键：ReadWriteMany

NAS 的核心价值是 `ReadWriteMany` —— 多个 Web Pod + 多个 Worker Pod 可同时挂载同一卷读写。这是本地盘 / EBS 无法做到的，也是集群调度的前提。

## 五、对象存储配置（OSS）

### 5.1 OSS Bucket 规划

```
cygnusx-data/                      # 主 bucket
├── archive/{user_id}/{file_id}    # 归档文件
├── backup/                        # 数据库/配置备份
├── reports/{task_id}/             # 长期报告归档
└── logs/                          # 审计/任务日志归档

cygnusx-static/                    # 静态资源 bucket
├── uploads/avatar/                # 头像
├── uploads/chat-attachments/      # 聊天附件
└── assets/                        # 公共资源
```

### 5.2 直传优化（大文件不经后端中转）

```python
# POST /api/v1/files/presign-upload
# 前端拿预签名 URL 直接 PUT 到 OSS，后端只记录元数据
@router.post("/files/presign-upload")
async def presign_upload(req: PresignUploadRequest, user: CurrentUser):
    key = f"uploads/{user.id}/{uuid4()}/{req.filename}"
    url = oss_client.sign_put(key, expires=3600, content_type=req.content_type)
    return {"upload_url": url, "key": key}
```

前端用 `axios.put(presigned_url, file)` 直传 OSS，5GB 文件不占后端带宽。

### 5.3 生命周期规则

```bash
# OSS 生命周期：30 天未访问转低频，90 天转归档
ossutil lifecycle --id cygnusx-lifecycle \
  --rule "archive/ 30 Days IA, 90 Days Archive" \
  oss://cygnusx-data
```

## 六、路径硬编码修复

### 6.1 流程 snakefile 路径

**当前**：`flows/rna_seq.yaml` 硬编码 `/home/zj/pipeline/RNAFlow/snakefile`

**修复**：
```yaml
# flows/rna_seq.yaml
execution:
  snakefile: "flows/rna_seq/Snakefile"   # 相对项目根
  # 或容器化后：
  container_image: "cygnusx/flow-rnaseq:v1.0"
  snakefile: "/workflow/Snakefile"       # 容器内绝对路径
```

`TaskService` 提交时 resolve 为绝对路径，校验在白名单目录内。

### 6.2 config.py 路径配置

**当前**：`welcome_yaml`、`snakemake_conda_prefix`、`sandbox_data_dir`、`ebi_download_binary` 全硬编码 `/data/cygnusx`。

**修复**：全部改为基于 `storage_path` 派生：
```python
welcome_yaml: str = ""  # 空则默认 f"{storage_path}/welcome/welcome.yaml"
snakemake_conda_prefix: str = ""  # 空则默认 f"{storage_path}/.conda_envs"
# 用 @field_validator 在空时填充默认值
```

## 七、迁移路线

| 阶段 | 时间 | 目标 | 步骤 |
|------|------|------|------|
| 1 | 3 天 | 抽象层落地 | StorageBackend 接口 + LocalBackend（不改行为） |
| 2 | 3 天 | OSS Backend | OSSStorageBackend + 预签名上传/下载 |
| 3 | 2 天 | FileService 改造 | 注入 backend，file_records 加字段 |
| 4 | 1 天 | NAS 接入 | K8s NAS StorageClass + PVC，web/worker 挂载 |
| 5 | 2 天 | 数据迁移 | 热数据 rsync 到 NAS，冷数据 ossutil 迁 OSS |
| 6 | 1 天 | 生命周期任务 | Celery Beat 定时把 30 天未访问文件迁 OSS |
| 7 | 持续 | 监控 | 存储用量、IO 延迟、迁移成功率监控 |

## 八、成本对比

| 方案 | 1TB/月 | 10TB/月 | 100TB/月 |
|------|--------|---------|----------|
| 本地 SSD（单机） | ¥300（硬件摊销） | ¥3000（需多机） | ¥30000（不可行） |
| 阿里云 NAS SSD | ¥1000 | ¥10000 | ¥100000 |
| 阿里云 OSS 标准 | ¥120 | ¥1200 | ¥12000 |
| 混合（20%热 NAS + 80% OSS） | ¥296 | ¥2960 | ¥29600 |

**结论**：分层存储比纯 NAS 省 70%，比纯本地盘省 90%（且具备高可用+弹性）。

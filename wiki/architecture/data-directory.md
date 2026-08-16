# 数据目录结构

平台运行时数据统一收口在宿主机 `/data/omichub`。

## 顶层目录

```text
/data/omichub/
├── omichub_data/          # 集中数据区
│   ├── _pgdata/           # PostgreSQL 数据
│   ├── _redis/            # Redis 持久化
│   ├── jbrowse/           # JBrowse 2 参考基因组与轨道
│   ├── knowledge/         # 知识库运行时副本
│   └── welcome/           # 管理员欢迎词与轮询游标
├── users/{user_id}/       # 用户私有数据
├── uploads/               # 分片上传中转
├── bin/                   # 外置二进制（EBIDownload 等）
├── refdata/               # 公共数据集
└── .tmp/                  # 临时文件
```

## `omichub_data` 子目录

| 目录 | 作用 | 备注 |
|---|---|---|
| `_pgdata/` | PostgreSQL 全部关系型数据 | bind mount，属主 postgres uid 70，`rsync` 需 `-a` |
| `_redis/` | Redis 持久化、Celery 队列、限流缓存 | 缓存类，丢失可重建 |
| `jbrowse/` | 参考基因组 FASTA + 注释轨道 | 经 nginx `/tracks/` 流式读取 |
| `knowledge/` | 知识库运行时附件与迁移数据 | 已发布正文、版本和检索索引以数据库为准 |
| `welcome/` | 预生成欢迎词与轮询游标 | 启动时不足 20 条自动调 AI 补齐 |

## 迁移/备份

```bash
make docker-down-all
sudo rsync -aP --info=progress2 /data/omichub/ <目标机>:/data/omichub/
```

迁移前同时备份数据库、`.env`、`data/worker_config.yaml` 和外部对象存储配置。恢复后运行迁移、健康
检查和知识库索引验证；不要只复制 `docs/knowledge/` 就假设在线知识库内容已恢复。

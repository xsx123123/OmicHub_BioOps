# 运维操作

本章节面向运维人员，汇总日常排障、日志查询、Makefile 命令与数据库迁移管理的速查信息。

## 内容导航

- [常用命令](common-commands) — Makefile 命令速查表
- [问题排查](troubleshooting) — 常见故障现象与排查路径

## 关键目录

```text
/data/cygnusx/
├── cygnusx_data/       # 集中数据区（DB、Redis、JBrowse、知识库、欢迎词）
├── users/<user_id>/    # 用户私有数据
├── uploads/            # 分片上传中转
├── bin/                # 外置二进制（EBIDownload、ossutil 等）
├── logs/               # 统一日志根目录
└── .tmp/               # 临时文件
```

## 日志入口

```bash
# 实时跟踪应用日志
tail -f /data/cygnusx/logs/app/cygnusx.log

# 只看 ERROR
tail -f /data/cygnusx/logs/app/error.log

# 按任务查 Celery 日志
tail -f /data/cygnusx/logs/celery/tasks/{task_id}.log

# Nginx 5xx
jq 'select(.status >= 500)' /data/cygnusx/logs/nginx/access.log
```

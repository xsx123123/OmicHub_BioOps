"""Celery 配置常量"""

# 队列名称
QUEUE_LOCAL = "analysis.local"
QUEUE_REMOTE = "analysis.remote"
QUEUE_DEFAULT = "analysis"

# 任务优先级
PRIORITY_HIGH = 10
PRIORITY_NORMAL = 5
PRIORITY_LOW = 1

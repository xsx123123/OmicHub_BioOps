"""ARQ Worker 启动入口。

用法：
    python -m omichub.infrastructure.task_queue.arq_worker

或在 docker-compose 中：
    command: python -m omichub.infrastructure.task_queue.arq_worker
"""

from __future__ import annotations

from arq.cli import cli

from omichub.infrastructure.task_queue.arq_jobs import WorkerSettings

if __name__ == "__main__":
    cli(WorkerSettings)

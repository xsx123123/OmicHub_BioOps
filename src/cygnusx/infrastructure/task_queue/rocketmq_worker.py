"""RocketMQ consumer for CygnusX tasks.

Usage:
    python -m cygnusx.infrastructure.task_queue.rocketmq_worker --queues analysis,phylo_tree
"""

from __future__ import annotations

import argparse
import logging
import signal
import threading
from typing import Any

from cygnusx.core.config import get_settings
from cygnusx.infrastructure.task_queue.rocketmq import (
    decode_envelope,
    execute_task,
    publish_task,
    topic_for,
)

logger = logging.getLogger(__name__)


def _consume(message: Any) -> int:
    from rocketmq.client import ConsumeStatus

    try:
        envelope = decode_envelope(message.body)
        execute_task(
            envelope,
            retry=lambda item: publish_task(
                task_name=item["task_name"],
                args=item["args"],
                kwargs=item["kwargs"],
                task_id=item["task_id"],
                queue=item["queue"],
                countdown=30,
                attempt=item["attempt"],
            ),
        )
    except ValueError:
        logger.exception("RocketMQ 无效任务消息，已丢弃")
        return ConsumeStatus.CONSUME_SUCCESS
    except Exception:  # noqa: BLE001
        logger.exception("RocketMQ 基础设施错误，稍后重试消息")
        return ConsumeStatus.RECONSUME_LATER
    return ConsumeStatus.CONSUME_SUCCESS


def main() -> None:
    parser = argparse.ArgumentParser(description="Run CygnusX RocketMQ task consumer")
    parser.add_argument("--queues", default="analysis", help="Comma-separated logical queues")
    args = parser.parse_args()

    try:
        from rocketmq.client import PushConsumer
    except ImportError as exc:  # pragma: no cover - deployment dependency
        raise SystemExit("缺少 rocketmq-client-python，无法启动 RocketMQ worker") from exc

    settings = get_settings()
    consumers = []
    for queue in (item.strip() for item in args.queues.split(",")):
        if not queue:
            continue
        consumer = PushConsumer(f"{settings.rocketmq_consumer_group_prefix}-{queue}")
        consumer.set_name_server_address(settings.rocketmq_namesrv_addr)
        consumer.subscribe(topic_for(queue), "*")
        consumer.register_message_listener(_consume)
        consumer.start()
        consumers.append(consumer)
    if not consumers:
        raise SystemExit("至少需要指定一个逻辑队列")
    logger.info("RocketMQ worker started for queues=%s", args.queues)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    try:
        stopped.wait()
    finally:
        for consumer in consumers:
            consumer.shutdown()


if __name__ == "__main__":
    main()

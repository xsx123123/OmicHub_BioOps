"""Task transport routing tests for Celery/RocketMQ coexistence."""

from unittest.mock import MagicMock, patch

import pytest

from omichub.infrastructure.task_queue.dispatcher import enqueue_task


@pytest.fixture
def task() -> MagicMock:
    task = MagicMock()
    task.name = "omichub.tools.blast.tasks.run_blast_search"
    task.queue = "blast_search"
    return task


def test_enqueue_uses_celery_when_backend_is_celery(
    task: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "omichub.infrastructure.task_queue.dispatcher.get_settings",
        lambda: MagicMock(task_queue_backend="celery", rocketmq_task_routes=[]),
    )

    enqueue_task(task, "task-1", task_id="task-1", queue="blast_search")

    task.apply_async.assert_called_once_with(
        args=("task-1",), kwargs={}, task_id="task-1", queue="blast_search"
    )


def test_enqueue_uses_rocketmq_when_backend_is_rocketmq(
    task: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "omichub.infrastructure.task_queue.dispatcher.get_settings",
        lambda: MagicMock(task_queue_backend="rocketmq", rocketmq_task_routes=[]),
    )

    with (
        patch("omichub.infrastructure.task_queue.dispatcher.publish_task") as publish,
        patch("omichub.infrastructure.task_queue.dispatcher.store_task_state") as store,
    ):
        result = enqueue_task(task, "task-1", task_id="task-1", queue="blast_search")

    assert result.id == "task-1"
    publish.assert_called_once_with(
        task_name=task.name,
        args=["task-1"],
        kwargs={},
        task_id="task-1",
        queue="blast_search",
        countdown=None,
    )
    store.assert_called_once_with("task-1", "PENDING")
    task.apply_async.assert_not_called()


def test_hybrid_routes_only_matching_tasks_to_rocketmq(
    task: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "omichub.infrastructure.task_queue.dispatcher.get_settings",
        lambda: MagicMock(
            task_queue_backend="hybrid", rocketmq_task_routes=["omichub.tools.blast.tasks.*"]
        ),
    )

    with (
        patch("omichub.infrastructure.task_queue.dispatcher.publish_task") as publish,
        patch("omichub.infrastructure.task_queue.dispatcher.store_task_state"),
    ):
        enqueue_task(task, "task-1", task_id="task-1")

    publish.assert_called_once()


def test_hybrid_leaves_unmatched_tasks_on_celery(
    task: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    task.name = "omichub.infrastructure.celery_app.tasks.analysis.run_snakemake"
    monkeypatch.setattr(
        "omichub.infrastructure.task_queue.dispatcher.get_settings",
        lambda: MagicMock(
            task_queue_backend="hybrid", rocketmq_task_routes=["omichub.tools.blast.tasks.*"]
        ),
    )

    enqueue_task(task, "task-1")

    task.apply_async.assert_called_once_with(args=("task-1",), kwargs={})

"""待办计划自动推进测试：成功执行写操作工具后 in_progress→done、pending→in_progress。

模型经常只在任务开始时调用一次 update_plan（全 pending），之后不再更新，
导致已完成任务的待办卡片长期停留在"待执行"；advance_plan_steps 让卡片状态
跟随真实执行进度。Agent 显式调用 update_plan 时仍以其返回的最新计划为准。
"""

from cygnusx.application.services.studio_tools import advance_plan_steps


def test_no_in_progress_returns_none() -> None:
    """计划尚未开始（全 pending）或已全部完成时无需推进。"""
    assert advance_plan_steps([]) is None
    assert advance_plan_steps([{"title": "a", "status": "pending"}]) is None
    assert advance_plan_steps([{"title": "a", "status": "done"}]) is None


def test_advance_marks_current_done_and_next_in_progress() -> None:
    """常规推进：in_progress 标 done，首个 pending 标 in_progress。"""
    result = advance_plan_steps(
        [
            {"title": "加载数据", "status": "done"},
            {"title": "差异分析", "status": "in_progress"},
            {"title": "绘制火山图", "status": "pending"},
        ]
    )
    assert result == [
        {"title": "加载数据", "status": "done"},
        {"title": "差异分析", "status": "done"},
        {"title": "绘制火山图", "status": "in_progress"},
    ]


def test_advance_only_first_in_progress() -> None:
    """多个 in_progress 时只推进第一个（异常状态下的保守行为）。"""
    result = advance_plan_steps(
        [
            {"title": "a", "status": "in_progress"},
            {"title": "b", "status": "in_progress"},
            {"title": "c", "status": "pending"},
        ]
    )
    assert result is not None
    assert [step["status"] for step in result] == ["done", "in_progress", "in_progress"]


def test_advance_final_step_completes_plan() -> None:
    """最后一步完成：全 done，无 pending 可推进。"""
    result = advance_plan_steps([{"title": "a", "status": "in_progress"}])
    assert result == [{"title": "a", "status": "done"}]


def test_advance_does_not_mutate_input() -> None:
    """返回新列表，不修改入参（调用方可能继续使用原计划）。"""
    steps = [{"title": "a", "status": "in_progress"}, {"title": "b", "status": "pending"}]
    snapshot = [dict(step) for step in steps]
    result = advance_plan_steps(steps)
    assert steps == snapshot
    assert result is not None
    assert result[0]["status"] == "done"

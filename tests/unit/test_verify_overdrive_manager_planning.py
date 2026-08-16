from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

MODULE_PATH = Path(__file__).parents[2] / "scripts" / "verify_overdrive_manager_planning.py"
SPEC = importlib.util.spec_from_file_location("verify_overdrive_manager_planning", MODULE_PATH)
assert SPEC and SPEC.loader
verification = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verification
SPEC.loader.exec_module(verification)


def _messages(*, latency_ms: float = 500, content: str = "按实际任务生成计划"):
    started = datetime.now(UTC)
    return [
        {
            "role": "user",
            "content": "TnpD 建树",
            "metadata_json": {},
            "created_at": started,
        },
        {
            "role": "assistant",
            "content": content,
            "metadata_json": {"planning_mode": "llm"},
            "created_at": started + timedelta(milliseconds=latency_ms),
        },
    ]


def _run(tasks):
    return {"run_id": "overdrive:test", "tasks": tasks}


def test_live_verifier_accepts_twenty_genome_anchor_chain() -> None:
    evidence = verification.evaluate_session(
        "session-20",
        _messages(),
        _run(
            [
                {"task_id": "tnpd-homolog-search", "depends_on": []},
                {"task_id": "tnpd-phylogeny", "depends_on": ["tnpd-homolog-search"]},
            ]
        ),
        minimum_latency_ms=100,
        require_phylo_anchors=True,
        require_shards=False,
    )

    assert evidence.passed is True
    assert evidence.latency_ms == 500
    assert evidence.task_ids == ["tnpd-homolog-search", "tnpd-phylogeny"]


def test_live_verifier_accepts_two_hundred_genome_shards() -> None:
    evidence = verification.evaluate_session(
        "session-200",
        _messages(),
        _run(
            [
                {"task_id": "tnpd-homolog-search-shard-1", "depends_on": []},
                {"task_id": "tnpd-homolog-search-shard-2", "depends_on": []},
                {
                    "task_id": "tnpd-phylogeny",
                    "depends_on": [
                        "tnpd-homolog-search-shard-1",
                        "tnpd-homolog-search-shard-2",
                    ],
                },
            ]
        ),
        minimum_latency_ms=100,
        require_phylo_anchors=True,
        require_shards=True,
    )

    assert evidence.passed is True
    assert evidence.shard_design is True


def test_live_verifier_rejects_template_speech_and_sub_100ms_reply() -> None:
    evidence = verification.evaluate_session(
        "session-fast",
        _messages(latency_ms=9.7, content="已按系统发育领域契约固定执行链"),
        _run([]),
        minimum_latency_ms=100,
        require_phylo_anchors=True,
        require_shards=False,
    )

    assert evidence.passed is False
    assert any("禁用模板话术" in error for error in evidence.errors)
    assert any("低于 100.0ms" in error for error in evidence.errors)
    assert any("缺少 tnpd-homolog-search" in error for error in evidence.errors)

"""Live（真实服务）AgentTeams 地基 e2e 验收套件：E2E-7 / E2E-2 / E2E-9 / E2E-10。

与进程内默认用例（test_hi_no_case_e2e.py 等）互补：本文件直接打真实 HTTP 栈
（主后端 + Bridge + MinIO + Redis + PG），禁止 mock Bridge/MinIO。

门控（与 test_acceptance_profile.py 风格一致，默认 skip，不影响 CI）：

    AGENTTEAMS_LIVE_E2E=1 \
    CYGNUSX_E2E_BASE_URL=http://localhost:8000 \
    CYGNUSX_E2E_TOKEN=<平台 JWT access token> \
    uv run pytest tests/e2e/agentteams/test_live_foundation_e2e.py -v

可选 Bridge 侧直查（E2E-9 事件计数对账）：
    AGENTTEAMS_E2E_BRIDGE_URL=http://localhost:8088 \
    AGENTTEAMS_E2E_MANAGER_TOKEN=<bioops-manager token>

注意：真实服务版默认进 CI 需要 CI 环境带 compose 服务矩阵，属后续 CI 增强；
本文件当前为人工/夜间验收入口。
"""

from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest

RUN_LIVE = os.environ.get("AGENTTEAMS_LIVE_E2E") == "1"
BASE_URL = os.environ.get("CYGNUSX_E2E_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("CYGNUSX_E2E_TOKEN", "")
BRIDGE_URL = os.environ.get("AGENTTEAMS_E2E_BRIDGE_URL", "").rstrip("/")
MANAGER_TOKEN = os.environ.get("AGENTTEAMS_E2E_MANAGER_TOKEN", "")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not (RUN_LIVE and TOKEN),
        reason="set AGENTTEAMS_LIVE_E2E=1 with CYGNUSX_E2E_TOKEN to run against a live stack",
    ),
]

API = "/api/v1/agent-teams"


def _client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=30,
    )


def _bridge_client() -> httpx.Client:
    return httpx.Client(
        base_url=BRIDGE_URL,
        headers={"X-Bridge-Identity": "bioops-manager", "X-Bridge-Token": MANAGER_TOKEN},
        timeout=10,
    )


def _wait_manager_reply(client: httpx.Client, room_id: str, since: float, timeout_s: float = 60) -> list[dict]:
    """轮询房间事件流，直到出现一条 Manager 终端回复（ask_user/agent_message/proposal）。"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        events = _fetch_all_room_events(client, room_id)
        terminal = [
            e
            for e in events
            if e.get("event_type") in {"room.ask_user", "room.agent_message", "room.proposal"}
        ]
        if terminal:
            return events
        time.sleep(3)
    pytest.fail(f"Manager did not reply within {timeout_s}s in room {room_id}")


def _wait_multi_expert_summary(
    client: httpx.Client, room_id: str, timeout_s: float = 120
) -> list[dict]:
    """Wait for two worker replies followed by one Manager terminal reply."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        events = _fetch_all_room_events(client, room_id)
        worker_replies = [
            event
            for event in events
            if event.get("event_type") == "room.agent_message"
            and (event.get("payload") or {}).get("payload", {}).get("role") == "worker"
        ]
        manager_replies = [
            event
            for event in events
            if event.get("event_type") == "room.agent_message"
            and (event.get("payload") or {}).get("payload", {}).get("role")
            in {"bioops-manager", "manager"}
        ]
        if len(worker_replies) >= 2 and manager_replies:
            return events
        time.sleep(3)
    pytest.fail(
        f"two expert replies and a Manager summary were not observed within {timeout_s}s "
        f"in room {room_id}"
    )


def _event_content(event: dict) -> str:
    payload = event.get("payload") or {}
    nested = payload.get("payload") if isinstance(payload, dict) else {}
    if isinstance(nested, dict):
        return str(nested.get("content") or "")
    return ""


def _fetch_all_room_events(client: httpx.Client, room_id: str, page_limit: int = 100) -> list[dict]:
    """按游标翻页拉取全量房间事件；空页视为终止（防御分页死循环：最多 50 页）。"""
    events: list[dict] = []
    cursor: str | None = None
    for _ in range(50):
        params: dict[str, object] = {"limit": page_limit}
        if cursor:
            params["cursor"] = cursor
        resp = client.get(f"{API}/rooms/{room_id}/events", params=params)
        resp.raise_for_status()
        body = resp.json()
        page = body.get("events", [])
        events.extend(page)
        next_cursor = body.get("next_cursor")
        if not next_cursor or not page:
            break
        cursor = next_cursor
    return events


def _create_room(client: httpx.Client, title: str) -> str:
    resp = client.post(f"{API}/rooms", json={"title": title, "origin": "manual"})
    assert resp.status_code == 201, f"create room failed: {resp.status_code} {resp.text[:300]}"
    return str(resp.json()["room_id"])


def test_live_e2e7_hi_creates_no_case() -> None:
    """E2E-7：新房间发 'hi' → 无 Case 创建、无立项卡、仅 Manager 对话回复。"""
    with _client() as client:
        room_id = _create_room(client, f"live-e2e7-{uuid.uuid4().hex[:8]}")
        sent = client.post(f"{API}/rooms/{room_id}/messages", json={"content": "hi"})
        sent.raise_for_status()

        events = _wait_manager_reply(client, room_id, since=time.monotonic())
        detail = client.get(f"{API}/rooms/{room_id}")
        detail.raise_for_status()
        room = detail.json()

        assert room["case_id"] is None, "hi 不得创建 Case"
        assert room["has_pending_proposal"] is False, "hi 不得生成立项卡"
        case_events = [e for e in events if str(e.get("event_type", "")).startswith("case.")]
        assert not case_events, f"hi 不得产生 Case 级事件: {[e['event_type'] for e in case_events]}"
        manager_replies = [
            e for e in events if e.get("event_type") in {"room.ask_user", "room.agent_message"}
        ]
        assert len(manager_replies) == 1, f"应仅一条 Manager 回复，实际 {len(manager_replies)}"


def test_live_multi_expert_consultation_is_summarized_by_manager() -> None:
    """真实栈回放用户原话：两位专家先答，Manager 再汇总且不发执行澄清卡。"""
    content = "@单细胞分析师 @可视化助手 你们两个可以搭配干活吗"
    with _client() as client:
        room_id = _create_room(client, f"live-multi-expert-{uuid.uuid4().hex[:8]}")
        sent = client.post(f"{API}/rooms/{room_id}/messages", json={"content": content})
        sent.raise_for_status()

        events = _wait_multi_expert_summary(client, room_id)
        worker_replies = [
            event
            for event in events
            if event.get("event_type") == "room.agent_message"
            and (event.get("payload") or {}).get("payload", {}).get("role") == "worker"
        ]
        manager_replies = [
            event
            for event in events
            if event.get("event_type") == "room.agent_message"
            and (event.get("payload") or {}).get("payload", {}).get("role")
            in {"bioops-manager", "manager"}
        ]
        manager_reply = _event_content(manager_replies[-1])

        print("\n=== Manager replay ===\n" + manager_reply)
        assert len(worker_replies) >= 2
        assert manager_reply
        assert not [event for event in events if event.get("event_type") == "room.ask_user"]
        assert "收到你的执行请求" not in manager_reply
        assert "请上传文件或填写工作区路径" not in manager_reply
        assert "单细胞" in manager_reply
        assert "可视化" in manager_reply


def test_live_e2e2_events_limit_boundary() -> None:
    """E2E-2：limit 超上界不得被 422 抹平（期望钳制或可分页），下界 1 可用。"""
    with _client() as client:
        room_id = _create_room(client, f"live-e2e2-{uuid.uuid4().hex[:8]}")
        client.post(f"{API}/rooms/{room_id}/messages", json={"content": "hi"}).raise_for_status()

        ok = client.get(f"{API}/rooms/{room_id}/events", params={"limit": 1})
        assert ok.status_code == 200
        assert len(ok.json()["events"]) == 1

        for over in (101, 200):
            resp = client.get(f"{API}/rooms/{room_id}/events", params={"limit": over})
            assert resp.status_code != 422, (
                f"limit={over} 被 422 抹平（期望钳制到 100 或分页拉取）: {resp.text[:200]}"
            )


def test_live_e2e9_cursor_pagination_no_dup_no_missing() -> None:
    """E2E-9：游标翻页遍历全程不重不漏、可终止，且与 Bridge 侧事件计数一致。"""
    with _client() as client:
        room_id = _create_room(client, f"live-e2e9-{uuid.uuid4().hex[:8]}")
        for text in ("hi", "hi again", "谢谢"):
            client.post(
                f"{API}/rooms/{room_id}/messages", json={"content": text}
            ).raise_for_status()
        _wait_manager_reply(client, room_id, since=time.monotonic())

        # 小页翻页：验证不重不漏 + 可终止
        seen: list[str] = []
        cursor: str | None = None
        pages = 0
        while pages < 50:
            params: dict[str, object] = {"limit": 7}
            if cursor:
                params["cursor"] = cursor
            body = client.get(f"{API}/rooms/{room_id}/events", params=params).json()
            page = body.get("events", [])
            seen.extend(str(e["event_id"]) for e in page)
            cursor = body.get("next_cursor")
            pages += 1
            if not page:
                assert not cursor, (
                    "分页终止性缺陷：空页仍返回 next_cursor（游标死循环，复审 A2 回归）"
                )
                break
            if not cursor:
                break
        assert len(seen) == len(set(seen)), "游标分页出现重复事件"

        # 与 Bridge 侧事实源计数对账（可选：需 Bridge 凭证）
        if BRIDGE_URL and MANAGER_TOKEN:
            with _bridge_client() as bridge:
                resp = bridge.get(f"/cases/room-{room_id}/events", params={"limit": 100})
                resp.raise_for_status()
                bridge_events = resp.json().get("events", [])
                assert len(seen) == len(bridge_events), (
                    f"房间视图 {len(seen)} 条 vs Bridge 事实源 {len(bridge_events)} 条，存在丢失"
                )


def test_live_e2e10_flow_report_export_and_controlled_download() -> None:
    """E2E-10：真实 Case 可生成离线报告，并经 JWT 受控通道下载可打开 HTML。"""
    with _client() as client:
        created = client.post(
            f"{API}/cases",
            json={"intent": f"live flow report export {uuid.uuid4().hex[:8]}"},
        )
        assert created.status_code == 201, (
            f"create case failed: {created.status_code} {created.text[:300]}"
        )
        case_id = str(created.json()["case_id"])
        try:
            exported = client.post(f"{API}/cases/{case_id}/reports/flow")
            assert exported.status_code == 201, (
                f"flow report failed: {exported.status_code} {exported.text[:300]}"
            )
            report = exported.json()
            assert report["artifact_path"].startswith("reports/flow-")
            assert report["artifact_path"].endswith(".html")
            assert len(report["checksum_sha256"]) == 64
            assert report["size_bytes"] > 0

            downloaded = client.get(
                f"{API}/cases/{case_id}/artifacts/{report['artifact_path']}",
                params={"download": "true"},
            )
            downloaded.raise_for_status()
            assert "text/html" in downloaded.headers.get("content-type", "")
            html = downloaded.text
            assert "协作流程报告" in html
            assert case_id in html
            assert "环境快照" in html
            assert "content_checksum_sha256" in html
        finally:
            cancelled = client.post(
                f"{API}/cases/{case_id}/cancel",
                json={"reason": "live flow report acceptance completed"},
            )
            assert cancelled.status_code in {200, 409}, cancelled.text[:300]

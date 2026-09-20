"""E2E-17 staging 实测：能力咨询修复 V1-V5（live 栈，真实 LLM）。

对应《协作室能力咨询误入接单流程-调研核对与修复实施计划》Part 7：
- V1 咨询无状态泄漏：未立项房间发「你可以干什么呀」→ 回复无「已接收/规划阶段」、无澄清卡
- V2 能力回答接地：自述能力均在能力目录内、无「质量管控」越权自述
- V3 闲聊无澄清卡：发「hi」→ 简短回应、无 ask_user、无状态页脚
- V4 接单回归：发要素齐全的执行类需求 → 正常出立项确认卡（room.proposal_confirm）
- V5 零接单侧事件：咨询交互零 room.proposal_* 事件

运行：CYGNUSX_E2E_TOKEN=<jwt> uv run python scripts/poc/e2e17_capability_consultation.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
from pathlib import Path

import httpx

BASE_URL = os.environ.get("CYGNUSX_E2E_BASE_URL", "http://localhost:8000").rstrip("/")
TOKEN = os.environ.get("CYGNUSX_E2E_TOKEN") or Path("/tmp/e2e_token.txt").read_text().strip()
API = "/api/v1/agent-teams"
OUT_DIR = Path("evidence/e2e-2026-08-21/E2E-17")

BANNED_STATE_WORDS = ["已接收", "规划阶段", "received", "planning"]
EXECUTE_REQUEST = (
    "我有一批人的 RNA-seq 计数矩阵，处理组和对照组各 3 个生物学重复，"
    "参考基因组 GRCh38。帮我做差异表达分析，交付差异基因表、火山图和 GO 富集结果。"
)


TERMINAL_EVENT_TYPES = {"room.ask_user", "room.agent_message", "room.proposal", "room.proposal_confirm"}


def client() -> httpx.Client:
    return httpx.Client(
        base_url=BASE_URL,
        headers={"Authorization": f"Bearer {TOKEN}"},
        timeout=30,
    )


def create_room(c: httpx.Client, title: str) -> str:
    r = c.post(f"{API}/rooms", json={"title": title, "origin": "manual"})
    r.raise_for_status()
    return str(r.json()["room_id"])


def post(c: httpx.Client, room_id: str, content: str) -> None:
    c.post(f"{API}/rooms/{room_id}/messages", json={"content": content}).raise_for_status()


def fetch_events(c: httpx.Client, room_id: str) -> list[dict]:
    events: list[dict] = []
    cursor = None
    for _ in range(50):
        params: dict = {"limit": 100}
        if cursor:
            params["cursor"] = cursor
        body = c.get(f"{API}/rooms/{room_id}/events", params=params).json()
        page = body.get("events", [])
        events.extend(page)
        cursor = body.get("next_cursor")
        if not cursor or not page:
            break
    return events


def wait_reply(c: httpx.Client, room_id: str, timeout_s: float = 180) -> list[dict]:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        events = fetch_events(c, room_id)
        if any(e.get("event_type") in TERMINAL_EVENT_TYPES for e in events):
            return events
        time.sleep(4)
    raise TimeoutError(f"room {room_id} 超时无 Manager 终端回复")


def terminal_payloads(events: list[dict]) -> list[tuple[str, str]]:
    """提取终端回复事件的 (event_type, 文本内容)。"""
    out = []
    for e in events:
        if e.get("event_type") in TERMINAL_EVENT_TYPES:
            payload = e.get("payload") or {}
            inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
            text = str(inner.get("content") or inner.get("summary") or payload.get("summary") or "")
            out.append((str(e.get("event_type")), text))
    return out


def main() -> int:
    results: dict[str, dict] = {}
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"e2e17_{time.strftime('%Y%m%dT%H%M%S')}.json"

    def dump() -> None:
        overall = all(v.get("pass") for v in results.values()) and not any(
            k.endswith("_error") for k in results
        )
        report = {"base_url": BASE_URL, "overall_pass": overall, "results": results}
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    with client() as c:
        # ---- V1/V2：能力咨询 ----
        try:
            room_a = create_room(c, f"e2e17-consult-{uuid.uuid4().hex[:8]}")
            post(c, room_a, "你可以干什么呀")
            events_a = wait_reply(c, room_a)
            replies_a = terminal_payloads(events_a)
            text_a = "\n".join(t for _, t in replies_a)
            ask_a = [e for e in events_a if e.get("event_type") == "room.ask_user"]
            proposal_a = [
                e for e in events_a if str(e.get("event_type", "")).startswith("room.proposal")
            ]
            hits_a = [w for w in BANNED_STATE_WORDS if w in text_a]
            results["V1"] = {
                "pass": not hits_a and not ask_a,
                "banned_words_hit": hits_a,
                "ask_user_events": len(ask_a),
                "reply_excerpt": text_a[:600],
            }
            results["V2"] = {
                "pass": "质量管控" not in text_a,
                "quality_control_self_claim": "质量管控" in text_a,
                "reply_excerpt": text_a[:600],
            }
            results["V5_consult_room"] = {
                "pass": not proposal_a,
                "proposal_events": [e.get("event_type") for e in proposal_a],
            }
        except Exception as exc:  # noqa: BLE001 — 分段落盘，单阶段失败不丢已有结果
            results["V1_V2_error"] = {"pass": False, "error": str(exc)}
        dump()

        # ---- V3：闲聊 ----
        try:
            room_b = create_room(c, f"e2e17-hi-{uuid.uuid4().hex[:8]}")
            post(c, room_b, "hi")
            events_b = wait_reply(c, room_b)
            replies_b = terminal_payloads(events_b)
            text_b = "\n".join(t for _, t in replies_b)
            ask_b = [e for e in events_b if e.get("event_type") == "room.ask_user"]
            proposal_b = [
                e for e in events_b if str(e.get("event_type", "")).startswith("room.proposal")
            ]
            hits_b = [w for w in BANNED_STATE_WORDS if w in text_b]
            room_b_detail = c.get(f"{API}/rooms/{room_b}").json()
            results["V3"] = {
                "pass": not ask_b and not hits_b,
                "banned_words_hit": hits_b,
                "ask_user_events": len(ask_b),
                "reply_excerpt": text_b[:400],
                "reply_chars": len(text_b),
            }
            results["V5_hi_room"] = {
                "pass": not proposal_b and room_b_detail.get("case_id") is None,
                "proposal_events": [e.get("event_type") for e in proposal_b],
                "case_id": room_b_detail.get("case_id"),
            }
        except Exception as exc:  # noqa: BLE001
            results["V3_error"] = {"pass": False, "error": str(exc)}
        dump()

        # ---- V4：接单回归 ----
        try:
            room_c = create_room(c, f"e2e17-exec-{uuid.uuid4().hex[:8]}")
            post(c, room_c, EXECUTE_REQUEST)
            events_c = wait_reply(c, room_c)
            proposal_c = [
                e for e in events_c if str(e.get("event_type", "")).startswith("room.proposal")
            ]
            ask_c = [e for e in events_c if e.get("event_type") == "room.ask_user"]
            room_c_detail = c.get(f"{API}/rooms/{room_c}").json()
            results["V4"] = {
                "pass": bool(proposal_c) or bool(room_c_detail.get("has_pending_proposal")),
                "proposal_events": [e.get("event_type") for e in proposal_c],
                "ask_user_events": len(ask_c),
                "has_pending_proposal": room_c_detail.get("has_pending_proposal"),
                "terminal_replies": [
                    {"type": t, "excerpt": x[:300]} for t, x in terminal_payloads(events_c)
                ],
            }
        except Exception as exc:  # noqa: BLE001
            results["V4_error"] = {"pass": False, "error": str(exc)}
        dump()

    overall = all(v.get("pass") for v in results.values())
    report = {"base_url": BASE_URL, "overall_pass": overall, "results": results}
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nreport: {out}")
    return 0 if overall else 1


if __name__ == "__main__":
    sys.exit(main())

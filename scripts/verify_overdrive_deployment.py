#!/usr/bin/env python3
"""Collect repeatable deployment-acceptance evidence for Overdrive v2.

The default path is read-only.  The optional broker exercise is deliberately
guarded because it stops the shared Redis service for a short staging-only
failure-recovery check.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

REQUIRED_TASKS = {
    "cygnusx.infrastructure.celery_app.tasks.overdrive.advance_run",
    "cygnusx.infrastructure.celery_app.tasks.overdrive.replan_run",
    "cygnusx.infrastructure.celery_app.tasks.overdrive.run_assistant_job",
    "cygnusx.infrastructure.celery_app.tasks.overdrive.run_manager_review_job",
}
REQUIRED_QC_EVENTS = {"assistant_result_ready", "manager_review_ready"}


@dataclass
class CheckResult:
    name: str
    passed: bool
    command: list[str]
    returncode: int
    stdout: str
    stderr: str


class AcceptanceError(RuntimeError):
    """A deployment acceptance requirement was not met."""


class AcceptanceRunner:
    def __init__(self, repository_root: Path, evidence_dir: Path) -> None:
        self.repository_root = repository_root
        self.evidence_dir = evidence_dir
        self.results: list[CheckResult] = []

    def run(self, name: str, command: Sequence[str], *, required: bool = True) -> str:
        completed = subprocess.run(
            list(command),
            cwd=self.repository_root,
            text=True,
            capture_output=True,
            check=False,
        )
        result = CheckResult(
            name=name,
            passed=completed.returncode == 0,
            command=list(command),
            returncode=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
        )
        self.results.append(result)
        if required and not result.passed:
            raise AcceptanceError(f"{name} failed (exit {completed.returncode})")
        return completed.stdout

    def assert_contains(self, name: str, output: str, required_values: set[str]) -> None:
        missing = sorted(value for value in required_values if value not in output)
        result = CheckResult(
            name=name,
            passed=not missing,
            command=[],
            returncode=0 if not missing else 1,
            stdout=output,
            stderr="" if not missing else f"Missing values: {', '.join(missing)}",
        )
        self.results.append(result)
        if missing:
            raise AcceptanceError(result.stderr)

    def write_evidence(self, *, run_id: str, broker_exercised: bool) -> None:
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "run_id": run_id,
            "broker_exercised": broker_exercised,
            "passed": all(result.passed for result in self.results),
            "checks": [asdict(result) for result in self.results],
        }
        (self.evidence_dir / "acceptance.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True, help="Existing real Overdrive run to inspect")
    parser.add_argument(
        "--evidence-dir",
        type=Path,
        help="Directory for command outputs and summary JSON (default: output/acceptance/<run-id>-<UTC time>)",
    )
    parser.add_argument(
        "--environment",
        default=os.environ.get("APP_ENV", ""),
        help="Target environment; broker exercise accepts staging only",
    )
    parser.add_argument(
        "--qc-unavailable-run-id",
        help="Optional staging run planned while agent-qc is unavailable; verifies explicit downgrade metadata",
    )
    parser.add_argument(
        "--broker-run-id",
        help="Staging run already in REPLANNING for the optional broker failure-recovery exercise",
    )
    parser.add_argument(
        "--exercise-broker-recovery",
        action="store_true",
        help="Temporarily stop and restart the Redis broker after replan preflight checks",
    )
    parser.add_argument(
        "--confirm-broker-outage",
        action="store_true",
        help="Required together with --exercise-broker-recovery",
    )
    parser.add_argument(
        "--broker-outage-seconds",
        type=float,
        default=5.0,
        help="How long to leave Redis stopped during the staging exercise (default: 5)",
    )
    parser.add_argument(
        "--recovery-timeout-seconds",
        type=float,
        default=120.0,
        help="Maximum time to wait for replan recovery after Redis returns (default: 120)",
    )
    return parser.parse_args()


def main_compose(root: Path) -> list[str]:
    return ["docker", "compose", "-f", str(root / "deploy/docker/docker-compose.yml")]


def worker_compose(root: Path) -> list[str]:
    return [str(root / "scripts/worker-compose.sh")]


def db_query_command(root: Path, sql: str) -> list[str]:
    return main_compose(root) + [
        "exec",
        "-T",
        "db",
        "psql",
        "-U",
        os.environ.get("POSTGRES_USER", "cygnusx"),
        "-d",
        os.environ.get("POSTGRES_DB", "cygnusx"),
        "-v",
        "ON_ERROR_STOP=1",
        "-t",
        "-A",
        "-c",
        sql,
    ]


def required_infrastructure_checks(runner: AcceptanceRunner) -> None:
    root = runner.repository_root
    compose = main_compose(root)
    runner.run("main-compose-services", compose + ["ps", "db", "cache", "web", "beat"])
    runner.run(
        "postgres-ready",
        compose
        + [
            "exec",
            "-T",
            "db",
            "pg_isready",
            "-U",
            os.environ.get("POSTGRES_USER", "cygnusx"),
            "-d",
            os.environ.get("POSTGRES_DB", "cygnusx"),
        ],
    )
    redis_output = runner.run(
        "redis-ping",
        compose + ["exec", "-T", "cache", "sh", "-ec", 'redis-cli -a "$REDIS_PASSWORD" ping'],
    )
    runner.assert_contains("redis-pong", redis_output, {"PONG"})
    runner.run("worker-compose-services", worker_compose(root) + ["ps", "worker"])
    ping_output = runner.run(
        "celery-ping",
        worker_compose(root)
        + [
            "exec",
            "-T",
            "worker",
            "celery",
            "-A",
            "cygnusx.infrastructure.celery_app.celery",
            "inspect",
            "ping",
        ],
    )
    if "pong" not in ping_output.lower():
        raise AcceptanceError("Celery inspect ping did not return pong")
    registered = runner.run(
        "celery-registered-tasks",
        worker_compose(root)
        + [
            "exec",
            "-T",
            "worker",
            "celery",
            "-A",
            "cygnusx.infrastructure.celery_app.celery",
            "inspect",
            "registered",
        ],
    )
    runner.assert_contains("overdrive-task-registration", registered, REQUIRED_TASKS)
    runner.run("alembic-current", compose + ["exec", "-T", "web", "alembic", "current"])
    tables = runner.run(
        "overdrive-tables",
        db_query_command(
            root,
            "SELECT string_agg(tablename, ',' ORDER BY tablename) FROM pg_tables "
            "WHERE schemaname = 'public' AND tablename IN "
            "('overdrive_runs', 'overdrive_events', 'overdrive_commands');",
        ),
    )
    runner.assert_contains(
        "overdrive-persistence-tables",
        tables,
        {"overdrive_runs", "overdrive_events", "overdrive_commands"},
    )


def inspect_run(runner: AcceptanceRunner, run_id: str, *, require_replanning: bool = False) -> dict[str, object]:
    root = runner.repository_root
    status_clause = "AND status = 'REPLANNING'" if require_replanning else ""
    sql = f"""
WITH target AS (
  SELECT * FROM overdrive_runs WHERE run_id = '{run_id.replace("'", "''")}' {status_clause}
), event_summary AS (
  SELECT
    count(*) AS event_count,
    min(sequence) AS first_sequence,
    max(sequence) AS last_sequence,
    count(*) FILTER (WHERE event_type = 'assistant_result_ready'
      AND payload->>'task_id' = 'independent-qc') AS qc_result_events,
    count(*) FILTER (WHERE event_type = 'manager_review_ready'
      AND payload->>'task_id' = 'independent-qc') AS qc_review_events,
    count(*) FILTER (WHERE event_type = 'plan_revision_requested') AS revision_events,
    count(*) FILTER (WHERE event_type = 'replanning_started') AS replanning_events,
    count(*) FILTER (WHERE event_type = 'plan_confirmation_requested') AS confirmation_events,
    count(*) FILTER (WHERE event_type = 'replanning_failed') AS replanning_failed_events
  FROM overdrive_events WHERE run_id = '{run_id.replace("'", "''")}'
)
SELECT json_build_object(
  'run_id', target.run_id,
  'status', target.status,
  'event_cursor', target.event_cursor,
  'plan_version', target.plan->>'version',
  'plan_hash', target.plan->>'hash',
  'qc_mode', target.plan->'summary'->'independent_qc'->>'mode',
  'replan_lock', target.control->>'replan_lock',
  'qc_task_present', jsonb_path_exists(target.tasks,
    '$[*] ? (@.task_id == "independent-qc" && @.agent_id == "agent-qc")'),
  'qc_has_dependencies', jsonb_path_exists(target.tasks,
    '$[*] ? (@.task_id == "independent-qc" && @.depends_on.size() > 0)'),
  'event_count', event_summary.event_count,
  'first_sequence', event_summary.first_sequence,
  'last_sequence', event_summary.last_sequence,
  'qc_result_events', event_summary.qc_result_events,
  'qc_review_events', event_summary.qc_review_events,
  'revision_events', event_summary.revision_events,
  'replanning_events', event_summary.replanning_events,
  'confirmation_events', event_summary.confirmation_events,
  'replanning_failed_events', event_summary.replanning_failed_events,
  'qc_result_status', qc_result.status,
  'qc_answer', qc_result.result->>'answer'
)
FROM target CROSS JOIN event_summary
LEFT JOIN LATERAL (
  SELECT status, result
  FROM overdrive_task_results
  WHERE run_id = target.run_id AND task_id = 'independent-qc'
  ORDER BY attempt DESC
  LIMIT 1
) AS qc_result ON TRUE;
"""
    output = runner.run("run-state" if not require_replanning else "replan-precondition", db_query_command(root, sql))
    if not output.strip():
        state = "REPLANNING" if require_replanning else "an existing"
        raise AcceptanceError(f"Run {run_id!r} was not found in {state} state")
    try:
        return json.loads(output.strip().splitlines()[-1])
    except json.JSONDecodeError as exc:
        raise AcceptanceError(f"Run query returned invalid JSON: {output}") from exc


def require_qc_evidence(state: dict[str, object]) -> None:
    if state.get("qc_task_present") is not True or state.get("qc_has_dependencies") is not True:
        raise AcceptanceError("Run has no independent agent-qc task depending on upstream work")
    if int(state.get("qc_result_events") or 0) < 1 or int(state.get("qc_review_events") or 0) < 1:
        raise AcceptanceError("Run has not recorded both independent QC result and manager review events")
    if int(state.get("event_count") or 0) != int(state.get("last_sequence") or 0):
        raise AcceptanceError("Run event sequence is not contiguous from sequence 1")
    answer = str(state.get("qc_answer") or "")
    conclusion = next(
        (
            value
            for value in ("通过", "返工", "人工复核")
            if f"质量结论：{value}" in answer or f"QC结论：{value}" in answer
        ),
        None,
    )
    if conclusion is None:
        raise AcceptanceError("Independent QC result does not contain a machine-readable quality conclusion")
    if state.get("status") in {"DELIVERING", "COMPLETED"} and conclusion != "通过":
        raise AcceptanceError("A non-passing independent QC conclusion reached delivery")


def require_qc_downgrade_evidence(state: dict[str, object]) -> None:
    if state.get("qc_task_present") is True:
        raise AcceptanceError("QC-unavailable run unexpectedly contains an independent QC task")
    if state.get("qc_mode") != "degraded":
        raise AcceptanceError("QC-unavailable run does not declare independent QC degradation in plan summary")


def exercise_broker_recovery(runner: AcceptanceRunner, args: argparse.Namespace, broker_run_id: str) -> None:
    if args.environment != "staging":
        raise AcceptanceError("Broker failure exercise is restricted to --environment staging")
    if not args.confirm_broker_outage:
        raise AcceptanceError("Broker failure exercise requires --confirm-broker-outage")
    if args.broker_outage_seconds <= 0:
        raise AcceptanceError("--broker-outage-seconds must be greater than zero")

    initial_state = inspect_run(runner, broker_run_id, require_replanning=True)
    initial_version = int(initial_state.get("plan_version") or 0)
    initial_confirmations = int(initial_state.get("confirmation_events") or 0)
    initial_hash = str(initial_state.get("plan_hash") or "")
    compose = main_compose(runner.repository_root)
    try:
        runner.run("broker-stop", compose + ["stop", "cache"])
        time.sleep(args.broker_outage_seconds)
    finally:
        runner.run("broker-start", compose + ["start", "cache"])

    deadline = time.monotonic() + args.recovery_timeout_seconds
    last_state: dict[str, object] | None = None
    while time.monotonic() < deadline:
        last_state = inspect_run(runner, broker_run_id)
        recovered = (
            int(last_state.get("plan_version") or 0) > initial_version
            and int(last_state.get("confirmation_events") or 0) > initial_confirmations
            and str(last_state.get("plan_hash") or "") != initial_hash
            and not last_state.get("replan_lock")
            and last_state.get("status") != "REPLANNING"
        )
        failed_cleanly = int(last_state.get("replanning_failed_events") or 0) >= 1 and not last_state.get("replan_lock")
        if recovered:
            return
        if failed_cleanly:
            raise AcceptanceError("Replanning converged to an explicit failure instead of a new confirmation")
        time.sleep(2)
    raise AcceptanceError(f"Replanning did not recover before timeout; last state: {last_state}")


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parents[1]
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    evidence_dir = args.evidence_dir or root / "output" / "acceptance" / f"{args.run_id}-{stamp}"
    runner = AcceptanceRunner(root, evidence_dir)
    try:
        required_infrastructure_checks(runner)
        run_state = inspect_run(runner, args.run_id)
        require_qc_evidence(run_state)
        if args.qc_unavailable_run_id:
            require_qc_downgrade_evidence(inspect_run(runner, args.qc_unavailable_run_id))
        if args.exercise_broker_recovery:
            if not args.broker_run_id:
                raise AcceptanceError("Broker failure exercise requires --broker-run-id in REPLANNING state")
            exercise_broker_recovery(runner, args, args.broker_run_id)
    except (AcceptanceError, OSError, subprocess.SubprocessError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        runner.write_evidence(run_id=args.run_id, broker_exercised=args.exercise_broker_recovery)
        print(f"Evidence: {evidence_dir}", file=sys.stderr)
        return 1
    runner.write_evidence(run_id=args.run_id, broker_exercised=args.exercise_broker_recovery)
    print(f"PASS: Overdrive deployment acceptance evidence written to {evidence_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

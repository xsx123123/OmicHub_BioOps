# Collection attempt — 2026-08-19

## Scope guard

- No application, frontend, Bridge, Gateway, database, Redis, or worker code was edited.
- This directory contains only forensic documentation and a GET-only collector.

## Local evidence inventory

The configured historical Bridge persistence locations are:

```text
audit_log_path = /tmp/omichub-agentteams-bridge-audit.jsonl
case_store_path = /tmp/omichub-agentteams-bridge-cases.json
```

The local filesystem search found neither file. The application logs under `logs/` also contain no match for the exact Case prompt, `room.route_decision`, `room.ask_user`, `room.user_message`, `wi_context_resolve`, or `work_item.claimed` for this Case.

An adjacent retained workspace, `/home/zj/zj_code_libarary/OmicHub_BioOps`, was also searched. Its largest logs end at **August 16, 2026 08:53:56**, before the incident's documented August 18/19 review period, and contain no match for the original prompt or incident-specific markers (`wi_context_resolve`, `通用 bioops 运维校验`, `已根据你的授权自动批准`, or `运行保护已触发`). They contain unrelated test/demo Case records (`case-1`, `bioops_001`) only and are not evidence for this incident.

## Access attempt

The configured Bridge URL is the internal Docker hostname `http://omichub-agentteams-bridge:8080`. There are no listening TCP ports in this execution environment. Docker inspection could not run because access to `/var/run/docker.sock` was denied:

```text
permission denied while trying to connect to the Docker daemon socket at unix:///var/run/docker.sock
```

Consequently, no historical Case ID, Bridge snapshot, audit event, Gateway request/response, Redis stream, or Matrix event was available to export. This is an evidence-access limitation, not evidence that the events did not occur.

## Next collection command

Run from an environment that can reach the same Bridge instance and has a manager token. It performs only HTTP `GET` requests:

```bash
python evidence/agentteams-case-forensics-20260819/collect_case_evidence.py \
  --bridge-url "$AGENTTEAMS_BRIDGE_URL" \
  --bridge-token "$AGENTTEAMS_BRIDGE_MANAGER_TOKEN" \
  --case-id '<historical-case-id>' \
  --output-dir evidence/agentteams-case-forensics-20260819/runtime-export
```

The resulting `event-table.md`, raw Case events/snapshot/manifest, and task-level events/artifacts are the minimum data needed to replace the runtime-evidence gaps in `report.md`.

## Additional negative checks (continuation)

- Codex history, Codex session JSONL, Claude project records, and shell histories were searched for the original prompt, `case_id`, `file://cb79a200`, `wi_context_resolve`, and the approval text; no matching Case export or identifier was found.
- Chromium `History` databases found under the accessible home tree contain no OmicHub/AgentTeams room URL or Bridge endpoint visit.
- Container/database storage locations (`/var/lib/docker`, `/var/lib/containers`, user container data, `/var/lib/postgresql`, `/var/lib/redis`, and `/tmp`) contain no configured Bridge Case JSON or audit JSONL file.
- These checks strengthen the conclusion that the missing runtime evidence is external to the accessible worktree and home-state artifacts; they do not prove the Case never existed.

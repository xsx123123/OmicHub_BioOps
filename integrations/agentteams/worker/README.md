# AgentTeams Worker claim adapter

`claim_next.py` is a controller-agnostic Worker entrypoint. It retrieves the authenticated
Worker's Bridge inbox, atomically claims one `pending` Work Item, and prints a JSON task envelope
to stdout. It neither executes analysis tools nor contains CygnusX database, Docker, filesystem,
or shell capabilities.

The AgentTeams/HiClaw release-specific Worker resource can use the container image built from this
directory as a pre-skill command or invoke the script directly. Pass secrets through the target
platform's secret reference, never command-line arguments or a committed environment file:

```bash
export AGENTTEAMS_BRIDGE_BASE_URL=https://bridge.example.internal/v1
export AGENTTEAMS_WORKER_IDENTITY=quality-auditor
export AGENTTEAMS_BRIDGE_TOKEN=...
python3 integrations/agentteams/worker/claim_next.py
```

The command prints `{"assignment":null}` when no pending Work Item exists. A `409` from the Claim
endpoint means another Worker already claimed the item; run the command again to read the current
inbox. Use `--dry-run` only to inspect the next assignment without claiming it.

## Production read-only runtime

`production_runner.py` is the non-demo resource-pool entrypoint for all 14 recruitable expert
identities. A pool replica receives the configured expert token set, checks every identity inbox
with bounded concurrency, and always uses the matching role credential for claim, heartbeat, and
Bridge `execute-readonly` calls. Scale `agentteams-worker-professional-pool` by capacity instead of
creating one permanently dedicated service per role.

The runtime supports only the fixed read-only Gateway capability for its identity. It cannot
submit workflows, cancel tasks, write files, access database/Redis/Docker credentials, or receive
the Gateway Manager token. Work Items that need an approval or a write-capable action must be
handled by a dedicated, approval-gated Worker runtime rather than this process.

Configure the pool with `AGENTTEAMS_WORKER_IDENTITIES`, the matching
`AGENTTEAMS_<IDENTITY>_TOKEN` variables from `deploy/agentteams/worker.env`, and
`AGENTTEAMS_WORKER_MAX_CONCURRENT`. The production Compose profile defaults to two replicas;
override `AGENTTEAMS_PROFESSIONAL_POOL_REPLICAS` and
`AGENTTEAMS_PROFESSIONAL_POOL_CONCURRENCY` for measured capacity needs.

## Controlled acceptance runner

`worker_runner.py` is the container entrypoint used by the `agentteams-acceptance` Compose
profile. It is deliberately not a scientific skill runtime: it can auto-complete only a read-only
assignment whose Case ID has the configured acceptance prefix, and only when
`AGENTTEAMS_WORKER_AUTOCOMPLETE_DEMO=true` is explicitly set. This allows an isolated deployment
check to prove `worker.inbox_polled → work_item.claimed → skill.finished` across independent
identities without allowing the runner to act on production Cases.

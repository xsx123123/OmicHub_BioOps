# ADR 0001: MAS control plane, workspace and execution boundary

**Status:** Accepted for Phase 0 implementation on July 18, 2026.

## Decision

- Keep Redis and Celery as the initial MAS transport and task substrate; durable delivery will use a PostgreSQL transactional Outbox before Redis Stream publishing.
- Treat `/data/cygnusx/runs/<run_id>` as the sole server-side run workspace and expose it to execution containers only as `/workspace`.
- Store large inputs and outputs as files plus artifact metadata; A2A events may contain only bounded summaries and artifact pointers.
- Keep raw-data cache entries content-addressed by verified SHA-256 and make run references read-only.
- Route all execution through allowlisted images, write roots and resource policy. MAS tools never receive a Docker socket or privileged container access.
- Permit nested Apptainer only through a dedicated compute-node runtime contract, never through the web or general worker containers.
- Treat QC quality gates as deterministic structured checks. A user override must be represented as an approval/audit record rather than a model assertion.

## Consequences

- Existing single-agent chat and Studio paths remain unchanged until a user-approved MAS plan enters execution.
- The later persistence layer must preserve event IDs, dedupe keys, state versions and artifact versions as durable audit data.
- Future migration from Redis Stream to another transport must retain the A2A envelope and at-least-once consumer semantics.

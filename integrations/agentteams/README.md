# AgentTeams integration boundary

This directory implements the converged AgentTeams design defined in
`data/ai/update/AgentTeams_VISION_FINAL.md` and
`data/ai/update/AgentTeams_CONVERGENCE_PLAN.md`.

- `bridge/`: independently deployable REST adapter; it never imports OmicHub internals.
- `teams/`: AgentTeams role identities and capability boundaries.
- `skills/`: stable input/output and failure-handling contracts.
- `demo/`: repeatable preflight success/block and staging-only full workflow driver.

The Bridge covers Phase 1 operations (`list_flows`, `preflight`, task submit/get/cancel) and
Phase 2 foundations (role identity, human-gateway-issued scoped short-lived approvals,
idempotency, Case state persistence, quality decisions, evidence events, and delivery
manifests). The chat UI reads, creates, confirms, cancels, and previews Case artifacts through an
authenticated OmicHub server-side proxy. Shared production state uses Redis while preserving the
same Bridge contracts and never reaching into OmicHub services or its database.

The browser never receives a Bridge secret or invokes Worker operations. OmicHub filters Case
reads by `requester_ref` using a server-only Manager identity; high-risk operations remain in
AgentTeams and the dedicated approval gateway.

For a separately deployed staging Bridge, run the safe preflight success and blocked demos from
`demo/README.md`. The full workflow mode requires explicit staging approval opt-in and a real
OmicHub demo task payload; it is not a substitute for human approval in production.

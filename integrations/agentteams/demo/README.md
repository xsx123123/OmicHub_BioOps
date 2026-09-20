# AgentTeams Bridge repeatable demo

This runbook targets a **separately deployed Bridge and CygnusX staging environment**. It never
starts the Controller, never uses an CygnusX database, and never reads `/data/cygnusx`.

## Prerequisites

1. Start the Bridge with real non-placeholder production/staging credentials.
2. Create a dedicated CygnusX demo project and configure a real `rna_seq` demo input.
3. Export the minimum service identity tokens required by the selected mode:

```bash
export DEMO_BRIDGE_URL=https://agentteams-bridge.example.internal
export DEMO_BIOOPS_MANAGER_TOKEN=...
export DEMO_DATA_STEWARD_TOKEN=...
```

The script generates a unique Case ID and prints only Case/task/manifest references. Do not put
raw sample data, filesystem paths, approvals, or secrets in shell history or committed files.

## Safe success and exception evidence

Run these first; neither command submits a workflow:

```bash
python3 integrations/agentteams/demo/run_bridge_demo.py \
  --mode preflight-success --project-id demo-project

python3 integrations/agentteams/demo/run_bridge_demo.py \
  --mode preflight-blocked --project-id demo-project
```

The success path must end in `approval_pending`; the blocked path must end in `preflight_blocked`
with a `MISSING_SAMPLE_SHEET` finding. Open the resulting Case in `/agent-teams/cases/{case_id}`
to demonstrate the Case state, Work Item, and audit event evidence.

## Staging-only full workflow path

Create a local, untracked `task.json` containing a valid existing `TaskSubmitRequest` body. Use
the actual staging project references and parameters; do not copy real patient or production data.
For `staging-success`, the script first runs the exact `flow_id`, `sample_sheet`, and
`comparisons` from this file through preflight, then submits the same unchanged payload. It refuses
to submit if that preflight fails, so `task.json` cannot be used to replace approved inputs.

```bash
export DEMO_APPROVAL_AUTHORITY_TOKEN=...
export DEMO_WORKFLOW_OPERATOR_TOKEN=...
export DEMO_QUALITY_AUDITOR_TOKEN=...
export DEMO_DELIVERY_REPORTER_TOKEN=...

python3 integrations/agentteams/demo/run_bridge_demo.py \
  --mode staging-success \
  --project-id demo-project \
  --task-json ./task.json \
  --allow-automated-demo-approval
```

`--allow-automated-demo-approval` is deliberately required because the command mints an internal
short-lived Bridge approval token. It is only for controlled staging demonstrations and must not
replace a real human approval card in production. The script waits for a real CygnusX terminal
task status, runs the quality gate only after `success`, and closes the Case to emit a real
manifest reference.

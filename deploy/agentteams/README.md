# CygnusX AgentTeams sidecar deployment

> 协作档位、Bridge 前置条件和专业 Worker 边界请参阅
> `docs/configuration/多Agent协作配置指南.md`。

This Compose project is deliberately independent of `deploy/docker/docker-compose.yml`.
It deploys only the CygnusX Bridge: AgentTeams Controller, Matrix, MinIO, and optional
Higress remain AgentTeams-owned services and should join `cygnusx_agentteams_control`
through a dedicated gateway rather than the CygnusX application network.

## Run the Bridge

```bash
cp bridge.env.example bridge.env
cp gateway.env.example gateway.env
# Replace every placeholder with deployment-managed secrets.
docker network create cygnusx_bridge_gateway
docker compose -f docker-compose.agentteams.yml up --build -d
```

Bridge 镜像默认从阿里云 PyPI 镜像安装 Python 依赖。若当前网络到该镜像较慢，
可在执行 Compose 前切换镜像；该变量只影响构建阶段：

```bash
PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple \
  docker compose -f docker-compose.agentteams.yml build cygnusx-agentteams-bridge
```

For a local development-only startup, `gateway.env` may use
`GATEWAY_ENVIRONMENT=development` with Matrix settings left empty. Production requires
deployment-managed Gateway and Matrix credentials; do not commit either environment file.

The host health port binds to `127.0.0.1:8088` by default. CygnusX reaches the Bridge over the
dedicated Docker network; do not change `AGENTTEAMS_BRIDGE_BIND_HOST` to `0.0.0.0` unless an
approved gateway/firewall policy requires a host-facing endpoint.

The Bridge starts a dedicated `cygnusx-agentteams-state` Redis service on a separate internal
network. It owns the shared Case snapshot, atomic lease/claim lock, idempotency receipts, and
append-only audit stream. Workers are intentionally **not** attached to that network: they can
only call the Bridge API. Production `bridge.env` must set `BRIDGE_STATE_STORE_URL`; file-backed
Bridge state remains a development-only fallback.

### Controlled multi-Worker acceptance check

For a non-production integration check, the `agentteams-acceptance` Compose profile starts three
separate constrained Workers for `agent-code`, `agent-viz`, and `agent-scrna`:

```bash
docker compose -f docker-compose.agentteams.yml \
  --profile agentteams-acceptance up --build -d
```

These Workers only poll their own Bridge identity. Their auto-complete behavior is explicitly
enabled only in this profile and accepts only read-only Work Items whose Case ID begins with
`agentteams-acceptance-`; all other Work Items remain for the configured official Worker skill
runtime. A successful acceptance Case contains, for each identity, ordered Case audit events
`worker.inbox_polled`, `work_item.claimed`, and `skill.finished`. Do not enable this profile for
production scientific work.

Run the corresponding opt-in live test only against this no-model profile, with deployment-
managed Manager credentials supplied through the shell rather than files committed to Git:

```bash
export AGENTTEAMS_ACCEPTANCE_E2E=1
export AGENTTEAMS_E2E_BRIDGE_URL=http://127.0.0.1:8088/v1
export AGENTTEAMS_E2E_MANAGER_TOKEN=replace-with-manager-token
uv run pytest -q tests/e2e/agentteams/test_acceptance_profile.py
```

The test creates a prefixed Case, assigns one read-only item to each of `agent-code`,
`agent-viz`, and `agent-scrna`, verifies their ordered audit evidence, then cancels the Case.

Before starting either Worker profile, inject only the three role-scoped tokens into the Compose
process, ideally from a deployment secret manager:

```bash
export AGENTTEAMS_AGENT_CODE_TOKEN=...
export AGENTTEAMS_AGENT_VIZ_TOKEN=...
export AGENTTEAMS_AGENT_SCRNA_TOKEN=...
export AGENTTEAMS_AGENT_RNASEQ_TOKEN=...
export AGENTTEAMS_AGENT_DATA_TOKEN=...
export AGENTTEAMS_AGENT_ATACSEQ_TOKEN=...
export AGENTTEAMS_AGENT_SCRNA_UPSTREAM_TOKEN=...
export AGENTTEAMS_AGENT_SCRNA_INTEGRATION_TOKEN=...
export AGENTTEAMS_AGENT_SCRNA_ADVANCED_TOKEN=...
export AGENTTEAMS_AGENT_QC_TOKEN=...
export AGENTTEAMS_AGENT_DELIVERY_TOKEN=...
export AGENTTEAMS_AGENT_CLOUD_OPS_TOKEN=...
export AGENTTEAMS_AGENT_GENERAL_TOKEN=...
export AGENTTEAMS_AGENT_MCP_BUILDER_TOKEN=...
export AGENTTEAMS_ANALYSIS_WORKER_TOKEN=...
```

Workers do not load `bridge.env`. This prevents them from inheriting the Gateway Manager token,
approval signing secret, CygnusX integration credential, or other Worker identities.

For the repository's integrated development reload, use:

```bash
make docker-reload
```

It runs `make agentteams-worker-env` first. That target extracts the 14 expert identity tokens
plus the specialized `analysis-worker` token from deployment-managed `bridge.env` into ignored
`worker.env` with mode `0600`, then starts the `agentteams-production` profile.
To start only this sidecar stack, run `make docker-up-agentteams`.

### Production read-only Worker profile

The `agentteams-production` profile starts real, role-scoped `agent-rnaseq`, `agent-code`,
`agent-viz`, and `agent-scrna` Worker processes. A Worker receives only its own Bridge token: it claims a Work
Item, sends heartbeats, and asks the Bridge to call the Gateway's fixed read-only consultation
endpoint. The Gateway Manager token stays inside the Bridge container and is never mounted into
a Worker.

```bash
docker compose -f docker-compose.agentteams.yml \
  --profile agentteams-production up --build -d
```

Before enabling this profile, configure `BRIDGE_GATEWAY_URL` and
`BRIDGE_GATEWAY_MANAGER_TOKEN` in the deployment-managed `bridge.env`. The profile is intended
for read-only consultation only; workflow submission, cancellation, file writes, and Pipeline
execution remain on the approval-gated Bridge routes.

The quality Worker is intentionally conservative: it reads only Bridge-provided logical artifact
references and records `manual_review`; it never auto-approves a scientific result. A human
quality reviewer must decide whether to close the resulting delivery Case.

The delivery Worker records a `delivery.closeout_recommended` evidence event and completes its
delivery Work Item, but does not call Case close. Closing remains a human-controlled action using
the quality decision already persisted by the Bridge.

Use the tracked Bridge and Worker environment examples as separately managed templates for the
AgentTeams control plane, private object storage, and optional gateway deployment. Those services
must not receive CygnusX database, Redis, Docker socket, or user-volume credentials.

The Bridge must be given a restricted CygnusX service identity. It may call only public
CygnusX HTTP endpoints and must not receive PostgreSQL, Redis, Docker socket, user-data
volume, or workflow-directory access. The external `cygnusx_bridge_gateway` is a dedicated
gateway network: expose only the CygnusX API gateway on it, never the database, Redis, or
Worker services. The `agentteams_control` network remains internal to AgentTeams services.

## AgentTeams wiring

- Team identities: `integrations/agentteams/teams/bioops-delivery.yaml`
- Skill contracts: `integrations/agentteams/skills/contracts.yaml`
- Bridge API: `http://cygnusx-agentteams-bridge:8080/v1`

### Latency acceptance gate

Phase 4 must use real browser/control-plane timings rather than unit-test timings. Export at least
20 samples for each metric as JSONL, measuring `event_to_frontend_ms` from the Bridge audit
event's `recorded_at` timestamp until the matching `event_id` is rendered, and
`approval_accept_ms` from the confirmation click until the API response is accepted:

```json
{"metric":"event_to_frontend_ms","duration_ms":842}
{"metric":"approval_accept_ms","duration_ms":317}
```

Run the hard gate against the v1.1 budgets (event visibility P95 ≤ 3000 ms; approval acceptance
P95 ≤ 1000 ms):

```bash
python3 deploy/agentteams/verify_latency_budget.py /path/to/agentteams-latency.jsonl
```

The command exits non-zero when either sample set is too small or its P95 exceeds the budget;
retain its JSON report with the deployment acceptance evidence.

### Case cursor migration gate

The Case event cursor migration is deliberately staged. New deployments default to
`AGENTTEAMS_CASE_CURSOR_MIGRATION_MODE=dual_write`: both the new
`agentteams_case_cursors` table and the legacy session `sandbox_meta` cursor fields are written,
and the background watcher records the latest comparison result in
`sandbox_meta.agentteams_case_cursor_migration`. Any mismatch emits a structured warning with the
session identifier.

Keep `dual_write` enabled until the scheduled watcher reports zero mismatches for three
consecutive days. Then set `AGENTTEAMS_CASE_CURSOR_MIGRATION_MODE=new_only` and restart the
CygnusX web/worker processes; the next watcher/consumer pass removes the legacy fields. If an
incident occurs during or after cutover, set the mode to `legacy_only` to read and write only the
legacy cursor values while the issue is investigated. Do not remove the cursor migration table
until the rollback window has expired.

Use a separate secret per identity through `X-Bridge-Identity` and `X-Bridge-Token`. Production
professional Workers run as the scalable `agentteams-worker-professional-pool`; each claim still
uses the exact target identity token even though one replica can service multiple capabilities.
Task submission and cancellation also require a short-lived, action-scoped approval token
issued only by the separate `approval-authority` gateway after a human approval card is
resolved. The Bridge writes its own append-only JSONL audit index; CygnusX remains
authoritative for task state, logs, and artifacts. The Bridge volume persists only Case
references, approval/audit evidence, and delivery manifests—never FASTQ, BAM, reference
genomes, or raw user files.

### Worker work inbox

An AgentTeams/HiClaw Worker must not list every Case and then self-select work. After its
official release-specific Team/Worker resource is created, configure the Worker to poll its own
Bridge identity against `GET /v1/work-items/assigned`. The endpoint returns only that identity's
`pending` or `in_progress` Work Items plus logical project/task references; it never exposes the
preflight input snapshot, raw task specification, requester identity, or another Worker's items.
For each `pending` item, first call
`POST /v1/cases/{case_id}/work-items/{work_item_id}/claim`. The Bridge atomically changes the
target Work Item to `in_progress`; a second Worker receives `409`, and the item can be reclaimed
only after its configured deadline expires. Then use the returned `case_id` and `work_item_id`
when calling the matching skill contract. Manager uses the normal Case APIs to assign work and
cannot call the Worker inbox or claim endpoints.

### CygnusX 上游身份

Bridge 调用 CygnusX 现有 HTTP API 时必须以一个专用、最小权限的 CygnusX 集成用户执行，
使任务归属、取消权限和审计记录可追溯。生产 `bridge.env` 在
`BRIDGE_CYGNUSX_SERVICE_TOKEN`（Bearer）和 `BRIDGE_CYGNUSX_API_KEY`（`X-API-Key`）之间
**只能配置一个**；推荐后者。通过该集成用户登录 CygnusX 后，在
`POST /api/v1/auth/api-keys` 创建专用 Key，写入部署管理的 `bridge.env`，明文只保存到
受控 secret store。不要复用个人用户 JWT，也不要把 Key 写入仓库、前端环境变量或
AgentTeams Worker 配置。建议该 Key 仅声明 `flows:read`、`tasks:read`、
`tasks:submit` 与 `tasks:cancel` 四个 scopes；CygnusX 会在对应 API 路径上执行此限制。
此外必须设置 `BRIDGE_CYGNUSX_INTEGRATION_TOKEN`，其值与 CygnusX 的
`AGENTTEAMS_INTEGRATION_TOKEN` 一致，用于启动时和热重载时读取只读能力 Registry 快照。

## CygnusX 协作中心代理

The browser never calls the Bridge directly and must never receive a Worker or Manager secret.
To enable the authenticated Case list, detail, event evidence, and Case creation page in CygnusX,
copy the tracked root `.env.example` block into the deployment-managed `.env`, then configure
the following server-side environment variables:

```bash
AGENTTEAMS_BRIDGE_ENABLED=true
AGENTTEAMS_BRIDGE_URL=http://cygnusx-agentteams-bridge:8080
AGENTTEAMS_BRIDGE_MANAGER_TOKEN=replace-with-bioops-manager-token
AGENTTEAMS_BRIDGE_DATA_STEWARD_TOKEN=replace-with-data-steward-token
AGENTTEAMS_BRIDGE_APPROVAL_TOKEN=replace-with-approval-authority-token
AGENTTEAMS_BRIDGE_WORKFLOW_OPERATOR_TOKEN=replace-with-workflow-operator-token
AGENTTEAMS_BRIDGE_TIMEOUT_SECONDS=10
```

Then bring the main CygnusX stack up with the optional network override. Start the Bridge stack
first so it creates `cygnusx_bridge_gateway`:

```bash
docker compose \
  -f deploy/docker/docker-compose.yml \
  -f deploy/agentteams/docker-compose.cygnusx-proxy.yml \
  up -d web
```

The main `deploy/docker/docker-compose.yml` does not join this network by default, so local and
existing deployments remain unchanged until this override is selected. CygnusX uses the Manager
token only inside its backend to filter Case records by the current authenticated user. On Case
creation it uses the separate Data Steward token solely to assign and run the read-only
`project-preflight` Work Item. Approval, submission, cancellation, quality decisions, and manifest
closure remain controlled by the dedicated AgentTeams identities and approval gateway.

The optional override explicitly preserves the Web service's existing app, data, Worker, and
Sandbox networks before adding `cygnusx_bridge_gateway`; do not replace it with a one-network
override, or the Web service will lose access to its existing dependencies.

When the Case owner confirms a `approval_pending` Case in CygnusX, the backend—not the browser—
uses the separate approval-authority identity to mint a short-lived, case-scoped approval token and
the separate workflow-operator identity to submit the task. The browser never receives either
identity secret or the approval token.

## Deployment preflight

Before starting a real staging demonstration, validate the deployment-managed files rather than
the committed templates. This command refuses `replace-*` / `change-me-*` values and missing
Worker identities; it does not start containers or submit any tasks.

```bash
python3 deploy/agentteams/preflight.py \
  --bridge-env deploy/agentteams/bridge.env \
  --cygnusx-env .env \
  --gateway-env deploy/agentteams/gateway.env
```

After the Bridge is running, add a read-only health probe. Use the host-reachable port or an
internal service URL appropriate for the environment:

```bash
python3 deploy/agentteams/preflight.py \
  --bridge-env deploy/agentteams/bridge.env \
  --cygnusx-env .env \
  --gateway-env deploy/agentteams/gateway.env \
  --check-health \
  --bridge-url http://127.0.0.1:8088 \
  --gateway-url http://127.0.0.1:8089
```

健康探针默认会在 Bridge 刚启动时重试 5 次；如需只检查一次可传
`--health-retries 1`。

## Deprecated Matrix transport smoke test

This optional legacy transport check is retained only for deployments that still operate Matrix.
It is not an CygnusX product entry, and AgentTeams chat no longer depends on Element. The command
creates one disposable room and therefore still requires explicit confirmation.

```bash
export AGENTTEAMS_GATEWAY_MANAGER_TOKEN="<deployment-managed-manager-token>"
python3 deploy/agentteams/matrix_gateway_smoke.py \
  --gateway-url http://127.0.0.1:8089 \
  --confirm-write
```

Legacy deployments can also verify external Matrix return traffic with a bounded wait window:

```bash
python3 deploy/agentteams/matrix_gateway_smoke.py \
  --gateway-url http://127.0.0.1:8089 \
  --wait-external-seconds 120 \
  --confirm-write
```

## AgentTeams / HiClaw Controller deployment

For a shared or production deployment, install the official AgentTeams Helm chart into a
separate Kubernetes namespace. Keep the Controller API, optional Matrix transport, MinIO, and
Higress console private; expose only the authenticated Bridge/Gateway endpoints required by the
approved network policy. CygnusX does not require an Element Web deployment.

```bash
helm repo add higress.io https://higress.io/helm-charts
helm repo update
helm install agentteams higress.io/agentteams \
  --namespace agentteams-system --create-namespace \
  --render-subchart-notes \
  --set credentials.llmApiKey="$AGENTTEAMS_LLM_API_KEY" \
  --set credentials.adminPassword="$AGENTTEAMS_ADMIN_PASSWORD" \
  --set gateway.publicURL="https://agentteams.example.internal"
```

The exact Worker, Team, Manager, and Human resource schema is release-specific. Apply the
role boundaries in `integrations/agentteams/teams/bioops-delivery.yaml` and the API contracts
in `integrations/agentteams/skills/contracts.yaml` when creating those official resources; do
not invent a local CRD format or mount the CygnusX Worker data volume into AgentTeams Workers.

### Control-plane acceptance gate

Before assigning a real Worker or starting the repeatable demo, apply the namespace-wide
default-deny policy after installing the official chart. Then add release-specific allow policies
only for Controller/Worker-to-Bridge traffic, Controller internal services, and the approved
Matrix/MinIO gateways. Do not allow direct egress to CygnusX PostgreSQL, Redis, Docker, or data
volumes.

```bash
kubectl apply -f deploy/agentteams/kubernetes/network-policy.default-deny.yaml
kubectl apply -f deploy/agentteams/kubernetes/bridge-cluster.yaml
kubectl apply -f deploy/agentteams/kubernetes/network-policy.runtime.yaml
python3 deploy/agentteams/verify_control_plane.py \
  --namespace agentteams-system
```

Before applying `bridge-cluster.yaml`, replace the two image references with the built and
signed Bridge/Worker images, create `cygnusx-agentteams-bridge-runtime` from the production
Bridge secret, create `cygnusx-agentteams-worker-tokens` with one key per Worker role, and point
`BRIDGE_STATE_STORE_URL` at managed Redis. The Worker secret must not contain Gateway, approval,
or CygnusX integration credentials.

`verify_control_plane.py` is read-only and controller-schema agnostic. It checks that the target
namespace exists, that a namespace-wide ingress/egress default-deny policy is active, and that
running Pods are non-privileged with no host-network, Docker socket, CygnusX data, database,
Redis, or workflow mounts. A failure is a deployment gate: fix the Helm values or explicit
allow policies before creating Team/Worker resources. The verifier deliberately does not claim
that a Controller release's Team CRD is valid; validate those resources with the official chart
version's CRDs and admission webhooks.

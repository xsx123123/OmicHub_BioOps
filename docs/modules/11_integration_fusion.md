# OmicHub "AI Copilot & Interactive Code Sandbox" Integration Fusion Plan

> **Version**: v1.0  
> **Date**: 2025-01  
> **Status**: Architecture Design  
> **Scope**: Integration of AI Copilot and interactive code-execution sandbox into the existing OmicHub monolith (Vue3 + FastAPI + PostgreSQL + Redis + Celery + Snakemake + Docker Compose)

---

## Table of Contents

1. [User Management System Integration](#1-user-management-system-integration)
2. [Data Mounting System Integration](#2-data-mounting-system-integration)
3. [Nextflow/Snakemake Workflow Engine Integration](#3-nextflowsnakemake-workflow-engine-integration)
4. [Microservice Decomposition & Communication](#4-microservice-decomposition--communication)
5. [Deployment Architecture](#5-deployment-architecture)
6. [Backward Compatibility](#6-backward-compatibility)
7. [Appendix: SQL Schema Definitions](#7-appendix-sql-schema-definitions)
8. [Appendix: API Reference](#8-appendix-api-reference)
9. [Appendix: Docker & Build Configurations](#9-appendix-docker--build-configurations)
10. [Appendix: Decision Matrix & Risk Assessment](#10-appendix-decision-matrix--risk-assessment)

---

## 0. Architecture Overview

### 0.1 Integration Philosophy

The fusion adheres to three core principles:

| Principle | Description | Implementation |
|-----------|-------------|----------------|
| **Security First** | Data isolation at the OS level, not application level | Per-user Docker namespaces, read-only mounts, no root in sandbox |
| **Progressive Enhancement** | Existing features remain untouched; new capabilities are additive | Feature flags, separate API prefixes, optional service startup |
| **Unified Experience** | Single authentication, single project context, seamless context switching | Shared JWT, WebSocket session affinity, project-aware Agent prompts |

### 0.2 High-Level Integration Diagram

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              OmicHub Platform                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐  ┌─────────────┐  │
│  │   Vue3 SPA   │  │  Copilot UI  │  │  Sandbox IDE │  │   Chat UI   │  │
│  │  (Existing)  │  │   (New)      │  │   (New)      │  │  (Existing) │  │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘  └──────┬──────┘  │
│         │                 │                  │                 │        │
│         └─────────────────┴──────────────────┴─────────────────┘        │
│                                       │                                 │
│                              WebSocket  (Unified)                       │
│                                       │                                 │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │                        FastAPI Application                        │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │  │
│  │  │  Auth    │ │ Project  │ │  Task    │ │  Chat    │ (Existing) │  │
│  │  │  Router  │ │ Router   │ │ Router   │ │ Router   │            │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │  │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐           │  │
│  │  │ Copilot  │ │ Sandbox  │ │  MCP     │ │ Artifact │ (New)    │  │
│  │  │ Router   │ │ Router   │ │ Router   │ │ Router   │            │  │
│  │  └──────────┘ └──────────┘ └──────────┘ └──────────┘           │  │
│  │  ┌────────────────────────────────────────────────────────────┐ │  │
│  │  │           Sandbox Orchestrator (Internal Module)            │ │  │
│  │  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │ │  │
│  │  │  │  Session     │  │  Docker      │  │  File System     │  │ │  │
│  │  │  │  Manager     │  │  Manager     │  │  Manager         │  │ │  │
│  │  │  └──────────────┘  └──────────────┘  └──────────────────┘  │ │  │
│  │  └────────────────────────────────────────────────────────────┘ │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                              │                                          │
│                    ┌─────────┼─────────┐                                │
│                    │         │         │                                │
│              ┌─────┴───┐ ┌───┴────┐ ┌──┴────────┐  ┌──────────────┐  │
│              │PostgreSQL│ │ Redis  │ │  Celery   │  │ Docker Daemon│  │
│              │ (Shared) │ │(Shared)│ │  Workers  │  │  (Sandbox)   │  │
│              └──────────┘ └────────┘ └───────────┘  └──────────────┘  │
│                              │                          │              │
│                              │                   ┌──────┴──────┐       │
│                              │                   │  Sandbox    │       │
│                              │                   │ Containers  │       │
│                              │                   │ (Per-Session)│      │
│                              │                   └─────────────┘       │
│  ┌───────────────────────────┘                                          │
│  │  External: MCP Servers (WorkflowMCP, ToolMCP, etc.)                 │
│  └──────────────────────────────────────────────────────────────────────┘
└─────────────────────────────────────────────────────────────────────────┘
```

### 0.3 Key Design Decisions Summary

| # | Decision | Rationale |
|---|----------|-----------|
| 1 | **Monolith extension (Option A)** | Keep Copilot + Sandbox inside existing FastAPI app; independent scaling not yet required |
| 2 | **Token-injection for sandbox auth** | Short-lived one-time tokens injected via env vars; no long-lived credentials in containers |
| 3 | **Project-scoped mounts** | Each sandbox sees only the currently active project's data via Docker volume mounts |
| 4 | **Two-mode workflow execution** | Mode B (MCP-mediated) for Agent automation; Mode A (direct CLI) for expert users |
| 5 | **Sandbox container per session** | One sandbox container per WebSocket session; session affinity via Redis |

---

## 1. User Management System Integration

### 1.1 Authentication Integration

#### 1.1.1 JWT Reuse Strategy

**Decision: Full reuse of existing JWT authentication.**

The sandbox module does **not** implement a separate authentication system. All sandbox-related API endpoints (`/api/v1/sandbox/*`) are protected by the existing JWT middleware.

**Authentication Flow:**

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐
│   Browser    │────▶│  FastAPI Main    │────▶│  JWT Middleware  │
│  (Vue3 SPA)  │     │  (Protected)     │     │  (Existing)      │
└──────────────┘     └────────┬─────────┘     └────────┬─────────┘
                              │                         │
                              │   Token Valid?          │
                              │ ◄───────────────────────┘
                              │   Yes: user_id + roles
                              ▼
                     ┌──────────────────┐
                     │ Sandbox Router   │
                     │ (Copilot/Sandbox)│
                     └────────┬─────────┘
                              │ user_id, project_id
                              ▼
                     ┌──────────────────┐
                     │ Sandbox Session  │
                     │ Manager          │
                     └──────────────────┘
```

#### 1.1.2 Sandbox Container Identity Verification

The critical question: *How does the sandbox container know which user it belongs to, and how is that trust established?*

**Approach: Short-lived Session Token (One-Time Token)**

```python
# Token generation (in Sandbox Session Manager)
import secrets
import hashlib

def generate_sandbox_token(session_id: str, user_id: int, project_id: int) -> str:
    """Generate a one-time token for sandbox container authentication."""
    random_component = secrets.token_urlsafe(32)
    token_payload = f"{session_id}:{user_id}:{project_id}:{random_component}"
    token = hashlib.sha256(token_payload.encode()).hexdigest()
    return token
```

**Token Lifecycle:**

| Phase | Action | TTL |
|-------|--------|-----|
| Creation | Token generated when container starts | - |
| Injection | Token injected as env var `SANDBOX_AUTH_TOKEN` | - |
| Validation | Token validated on every WebSocket connection | - |
| Expiration | Token invalidated when container stops | Session lifetime |
| Renewal | Token rotated every 15 minutes (optional) | 15 min sliding window |

**Token Validation Flow:**

```
1. Frontend opens WebSocket: wss://api/sandbox/ws/{session_id}
   Headers: Authorization: Bearer <JWT_TOKEN>

2. FastAPI validates JWT → gets user_id

3. FastAPI looks up session in Redis:
   Key: sandbox:session:{session_id}
   Value: {user_id, project_id, container_id, token_hash, status}

4. FastAPI checks user_id matches session owner

5. FastAPI proxies WebSocket to sandbox container's internal port
   (Docker network communication, no external exposure)

6. Sandbox container accepts the connection (same Docker network)
   No additional auth needed within the network
```

**Key Security Properties:**

- Token is **never exposed** to the frontend JavaScript
- Token is **scoped** to a specific (user_id, project_id, session_id) triple
- Token is **single-use** per container lifecycle
- Token validation uses **Redis** as the single source of truth
- Sandbox containers are **not directly exposed** to the external network

#### 1.1.3 Guest/Trial User Sandbox Restrictions

```python
# Permission tiers for sandbox access
SANDBOX_PERMISSION_TIERS = {
    "guest": {
        "can_execute_code": False,           # Read-only code viewing
        "can_access_sandbox": False,         # Cannot open sandbox
        "max_cpu_cores": 0,
        "max_memory_mb": 0,
        "max_execution_time_sec": 0,
        "max_disk_mb": 0,
        "allowed_projects": [],
        "available_datasets": ["demo_pbmc"],  # Only demo datasets
        "description": "Guests cannot use sandbox"
    },
    "trial": {
        "can_execute_code": True,
        "can_access_sandbox": True,
        "max_cpu_cores": 2,
        "max_memory_mb": 4096,               # 4 GB
        "max_execution_time_sec": 1800,       # 30 minutes per session
        "max_disk_mb": 2048,                  # 2 GB temp space
        "allowed_projects": ["trial_*"],
        "available_datasets": ["demo_pbmc", "demo_tumor"],
        "description": "Trial users with limited resources"
    },
    "standard": {
        "can_execute_code": True,
        "can_access_sandbox": True,
        "max_cpu_cores": 4,
        "max_memory_mb": 16384,              # 16 GB
        "max_execution_time_sec": 7200,       # 2 hours per session
        "max_disk_mb": 10240,                 # 10 GB temp space
        "allowed_projects": ["*"],            # All owned projects
        "available_datasets": ["*"],          # All available datasets
        "description": "Standard subscribed users"
    },
    "premium": {
        "can_execute_code": True,
        "can_access_sandbox": True,
        "max_cpu_cores": 8,
        "max_memory_mb": 32768,              # 32 GB
        "max_execution_time_sec": 28800,      # 8 hours per session
        "max_disk_mb": 51200,                 # 50 GB temp space
        "allowed_projects": ["*"],
        "available_datasets": ["*"],
        "gpu_enabled": True,                  # GPU access
        "description": "Premium users with GPU"
    },
    "admin": {
        "can_execute_code": True,
        "can_access_sandbox": True,
        "max_cpu_cores": -1,                  # Unlimited
        "max_memory_mb": -1,                  # Unlimited
        "max_execution_time_sec": -1,         # Unlimited
        "max_disk_mb": -1,                    # Unlimited
        "allowed_projects": ["*"],            # All projects
        "available_datasets": ["*"],
        "gpu_enabled": True,
        "description": "Admin with full access"
    }
}
```

---

### 1.2 Permission Integration

#### 1.2.1 Sandbox Execution Permission Model

**Decision: All authenticated users (except guests) can execute code. Resource limits vary by tier.**

```python
# Permission check middleware
class SandboxPermissionMiddleware:
    async def check_sandbox_permission(self, user: User, action: str) -> PermissionResult:
        tier = SANDBOX_PERMISSION_TIERS.get(user.sandbox_tier, "trial")

        if not tier["can_execute_code"] and action == "execute":
            raise SandboxPermissionDenied("Code execution not allowed for this user tier")

        if not tier["can_access_sandbox"] and action == "access":
            raise SandboxPermissionDenied("Sandbox access not allowed for this user tier")

        return PermissionResult(
            allowed=True,
            tier=tier,
            limits={
                "cpu_cores": tier["max_cpu_cores"],
                "memory_mb": tier["max_memory_mb"],
                "execution_time_sec": tier["max_execution_time_sec"],
                "disk_mb": tier["max_disk_mb"]
            }
        )
```

#### 1.2.2 Data Access Permission Matrix

| User Action | Data Source | Permission Check | Enforcement |
|-------------|-------------|-------------------|-------------|
| Mount project data | `/data/projects/{user_id}/{project_id}` | Project ownership / sharing | Mount-time Docker volume option |
| Mount shared data | `/data/shared/` | Any authenticated user | Read-only mount |
| Write output | `/tmp/sandbox_{session_id}/` | Session ownership | Writable only to own session |
| Access task results | `/data/tasks/{task_id}/` | Task ownership check | Application-layer check before mount |
| Access uploads | `/data/uploads/{user_id}/` | User ownership | Mount specific user directory |

#### 1.2.3 Resource Quota Enforcement

**Quota enforcement points:**

```
┌─────────────────────────────────────────────────────────────┐
│                    Quota Enforcement Pipeline                │
│                                                             │
│  1. API Request Layer (FastAPI middleware)                  │
│     └─ Check if user has remaining session quota            │
│     └─ Enforce max concurrent sandbox sessions              │
│                                                             │
│  2. Container Creation Layer (Sandbox Orchestrator)         │
│     └─ Apply Docker resource constraints (CPU, Memory)      │
│     └─ Set container-level disk quota (xfs_quota)           │
│                                                             │
│  3. Execution Layer (Sandbox Runtime)                       │
│     └─ Timeout enforcement (Linux timeout command)          │
│     └─ Memory limit enforced by Docker cgroup               │
│                                                             │
│  4. Cleanup Layer (Background Job)                          │
│     └─ Session TTL check via Redis expiry                   │
│     └─ Automatic container termination on timeout           │
│                                                             │
│  5. Billing/Usage Tracking (Background Job)                 │
│     └─ Log resource usage per session                       │
│     └─ Update usage counters in PostgreSQL                  │
└─────────────────────────────────────────────────────────────┘
```

#### 1.2.4 SQL Table Definitions

```sql
-- ============================================================
-- 1. user_sandbox_quotas: Per-user sandbox resource quotas
-- ============================================================
CREATE TABLE user_sandbox_quotas (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Tier assignment (determines base limits)
    tier            VARCHAR(32) NOT NULL DEFAULT 'trial'
                        CHECK (tier IN ('guest', 'trial', 'standard', 'premium', 'admin')),

    -- Computed / remaining quotas (updated periodically)
    sessions_used_month   INTEGER NOT NULL DEFAULT 0,
    sessions_limit_month  INTEGER NOT NULL DEFAULT 50,
    cpu_hours_used_month  DECIMAL(10,2) NOT NULL DEFAULT 0.0,
    cpu_hours_limit_month DECIMAL(10,2) NOT NULL DEFAULT 100.0,
    memory_gb_hours_used  DECIMAL(10,2) NOT NULL DEFAULT 0.0,
    memory_gb_hours_limit DECIMAL(10,2) NOT NULL DEFAULT 500.0,

    -- Current active sessions
    active_sessions       INTEGER NOT NULL DEFAULT 0,
    max_concurrent_sessions INTEGER NOT NULL DEFAULT 2,

    -- Custom overrides (NULL = use tier default)
    custom_cpu_cores      INTEGER,
    custom_memory_mb      INTEGER,
    custom_disk_mb        INTEGER,
    custom_max_timeout_sec INTEGER,

    -- GPU quota (premium only)
    gpu_hours_used_month  DECIMAL(10,2) NOT NULL DEFAULT 0.0,
    gpu_hours_limit_month DECIMAL(10,2) NOT NULL DEFAULT 0.0,

    -- Billing cycle
    billing_cycle_start   DATE NOT NULL DEFAULT CURRENT_DATE,
    billing_cycle_end     DATE NOT NULL DEFAULT (CURRENT_DATE + INTERVAL '30 days'),

    -- Metadata
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT uq_usq_user UNIQUE (user_id)
);

-- Indexes
CREATE INDEX idx_usq_user_id ON user_sandbox_quotas(user_id);
CREATE INDEX idx_usq_tier ON user_sandbox_quotas(tier);
CREATE INDEX idx_usq_billing_cycle ON user_sandbox_quotas(billing_cycle_start, billing_cycle_end);

-- Trigger: Reset monthly quotas on billing cycle boundary
CREATE OR REPLACE FUNCTION reset_monthly_sandbox_quotas()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.billing_cycle_start != OLD.billing_cycle_start THEN
        NEW.sessions_used_month := 0;
        NEW.cpu_hours_used_month := 0;
        NEW.memory_gb_hours_used := 0;
        NEW.gpu_hours_used_month := 0;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_reset_sandbox_quotas
    BEFORE UPDATE ON user_sandbox_quotas
    FOR EACH ROW
    EXECUTE FUNCTION reset_monthly_sandbox_quotas();

-- ============================================================
-- 2. user_sandbox_permissions: Granular sandbox permissions
-- ============================================================
CREATE TABLE user_sandbox_permissions (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,

    -- Feature toggles
    can_access_sandbox          BOOLEAN NOT NULL DEFAULT FALSE,
    can_execute_code            BOOLEAN NOT NULL DEFAULT FALSE,
    can_execute_workflows       BOOLEAN NOT NULL DEFAULT FALSE,
    can_install_packages        BOOLEAN NOT NULL DEFAULT FALSE,
    can_access_gpu              BOOLEAN NOT NULL DEFAULT FALSE,
    can_persist_artifacts       BOOLEAN NOT NULL DEFAULT FALSE,
    can_share_artifacts         BOOLEAN NOT NULL DEFAULT FALSE,
    can_access_shared_datasets  BOOLEAN NOT NULL DEFAULT TRUE,

    -- Workflow-specific permissions
    allowed_workflow_categories VARCHAR(256)[] DEFAULT ARRAY['basic'],  -- e.g., 'basic', 'advanced', 'clinical'
    max_workflow_parallel_jobs  INTEGER DEFAULT 2,

    -- Package installation whitelist/blacklist
    allowed_pypi_packages       TEXT[],
    blocked_pypi_packages       TEXT[],

    -- Admin override fields
    admin_override              BOOLEAN DEFAULT FALSE,
    override_reason             TEXT,
    granted_by                  INTEGER REFERENCES users(id),
    granted_at                  TIMESTAMP WITH TIME ZONE,

    created_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT uq_usp_user UNIQUE (user_id)
);

CREATE INDEX idx_usp_user_id ON user_sandbox_permissions(user_id);

-- ============================================================
-- 3. sandbox_usage_logs: Detailed usage tracking for billing/auditing
-- ============================================================
CREATE TABLE sandbox_usage_logs (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id      VARCHAR(64) NOT NULL,

    -- Session lifecycle
    started_at      TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    ended_at        TIMESTAMP WITH TIME ZONE,
    duration_sec    INTEGER,

    -- Resource allocation
    cpu_cores_allocated   INTEGER NOT NULL,
    memory_mb_allocated   INTEGER NOT NULL,
    disk_mb_allocated     INTEGER NOT NULL,
    gpu_allocated         BOOLEAN DEFAULT FALSE,

    -- Actual resource usage (from Docker stats)
    cpu_seconds_used      DECIMAL(10,2),
    memory_mb_peak        INTEGER,
    disk_mb_used          INTEGER,

    -- Context
    project_id            INTEGER REFERENCES projects(id),
    workflow_id           INTEGER,
    terminated_reason     VARCHAR(32) CHECK (terminated_reason IN (
        'user_exit', 'timeout', 'quota_exceeded', 'error', 'admin_kill', 'system_shutdown'
    )),

    -- Metadata
    sandbox_image         VARCHAR(128) NOT NULL,
    created_at            TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT uq_sul_session UNIQUE (session_id)
);

CREATE INDEX idx_sul_user_id ON sandbox_usage_logs(user_id);
CREATE INDEX idx_sul_session_id ON sandbox_usage_logs(session_id);
CREATE INDEX idx_sul_time_range ON sandbox_usage_logs(started_at, ended_at);
CREATE INDEX idx_sul_project ON sandbox_usage_logs(project_id);

-- ============================================================
-- 4. sandbox_artifacts: Persisted code/output from sandbox sessions
-- ============================================================
CREATE TABLE sandbox_artifacts (
    id              SERIAL PRIMARY KEY,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id      VARCHAR(64) NOT NULL,
    project_id      INTEGER REFERENCES projects(id),

    -- Artifact metadata
    name            VARCHAR(256) NOT NULL,
    artifact_type   VARCHAR(32) NOT NULL
        CHECK (artifact_type IN ('code_cell', 'notebook', 'plot', 'data_file', 'report', 'workflow')),

    -- Storage
    storage_path    TEXT NOT NULL,        -- Relative path in user's project storage
    file_size_bytes BIGINT,
    checksum        VARCHAR(64),          -- SHA-256

    -- Context
    parent_session_id   VARCHAR(64),
    source_chat_message_id INTEGER REFERENCES chat_messages(id),
    description         TEXT,
    tags                TEXT[],

    -- Visibility
    is_shared       BOOLEAN DEFAULT FALSE,
    shared_token    VARCHAR(64),          -- Public share token

    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    CONSTRAINT uq_sa_path UNIQUE (user_id, project_id, storage_path)
);

CREATE INDEX idx_sa_user ON sandbox_artifacts(user_id);
CREATE INDEX idx_sa_session ON sandbox_artifacts(session_id);
CREATE INDEX idx_sa_project ON sandbox_artifacts(project_id);
CREATE INDEX idx_sa_type ON sandbox_artifacts(artifact_type);
```

---

### 1.3 Session Association

#### 1.3.1 Chat Session ↔ Sandbox Session Relationship

**Design: Many-to-Many with Context Binding**

A chat session can spawn multiple sandbox sessions (one per project), and a sandbox session can be referenced by multiple chat messages.

```sql
-- ============================================================
-- 5. sandbox_sessions: Active and historical sandbox sessions
-- ============================================================
CREATE TABLE sandbox_sessions (
    id              SERIAL PRIMARY KEY,

    -- Identifiers
    session_id      VARCHAR(64) NOT NULL UNIQUE,  -- Public session UUID
    internal_token  VARCHAR(128) NOT NULL,        -- One-time auth token

    -- Ownership and context
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id      INTEGER REFERENCES projects(id),
    chat_session_id INTEGER REFERENCES chat_sessions(id),  -- Optional parent chat session

    -- Container info
    container_id    VARCHAR(64),                    -- Docker container ID
    container_name  VARCHAR(128),                   -- Docker container name
    sandbox_image   VARCHAR(128) NOT NULL,

    -- Resource allocation
    cpu_cores       INTEGER NOT NULL DEFAULT 2,
    memory_mb       INTEGER NOT NULL DEFAULT 4096,
    disk_mb         INTEGER NOT NULL DEFAULT 2048,
    gpu_enabled     BOOLEAN DEFAULT FALSE,

    -- Networking (internal Docker network)
    internal_ip     INET,
    internal_port   INTEGER DEFAULT 8888,

    -- Session state machine
    status          VARCHAR(32) NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending',      -- Session requested, container not yet created
            'creating',     -- Container creation in progress
            'ready',        -- Container running, accepting connections
            'executing',    -- Code currently running
            'paused',       -- Session paused (resource conservation)
            'error',        -- Container error
            'terminating',  -- Shutdown in progress
            'terminated',   -- Clean shutdown
            'expired'       -- TTL expired
        )),

    -- Project context (which data is mounted)
    mounted_project_ids INTEGER[],  -- Currently mounted project(s)
    mounted_dataset_ids INTEGER[],  -- Currently mounted shared datasets

    -- Timing
    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at      TIMESTAMP WITH TIME ZONE,
    last_activity_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at      TIMESTAMP WITH TIME ZONE,  -- Computed from quota

    -- Termination tracking
    terminated_at   TIMESTAMP WITH TIME ZONE,
    terminated_by   INTEGER REFERENCES users(id),
    termination_reason VARCHAR(64),

    -- Recovery
    kernel_state    JSONB,  -- Jupyter kernel state for recovery (future)
    checkpoint_path TEXT,   -- Path to session checkpoint (future)

    CONSTRAINT uq_ss_session UNIQUE (session_id)
);

CREATE INDEX idx_ss_user_id ON sandbox_sessions(user_id);
CREATE INDEX idx_ss_chat_session ON sandbox_sessions(chat_session_id);
CREATE INDEX idx_ss_status ON sandbox_sessions(status);
CREATE INDEX idx_ss_project ON sandbox_sessions(project_id);
CREATE INDEX idx_ss_expires ON sandbox_sessions(expires_at);

-- ============================================================
-- 6. chat_message_sandbox_links: Links chat messages to sandbox artifacts
-- ============================================================
CREATE TABLE chat_message_sandbox_links (
    id              SERIAL PRIMARY KEY,
    message_id      INTEGER NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    session_id      VARCHAR(64) NOT NULL REFERENCES sandbox_sessions(session_id),

    -- Link type
    link_type       VARCHAR(32) NOT NULL
        CHECK (link_type IN (
            'code_generated',     -- AI generated code in this message
            'execution_result',   -- Code was executed, result in this message
            'artifact_created',   -- An artifact was created from this message
            'session_started',    -- This message started a sandbox session
            'session_referenced'  -- This message references an existing session
        )),

    -- Optional artifact reference
    artifact_id     INTEGER REFERENCES sandbox_artifacts(id),

    -- Execution metadata
    execution_status VARCHAR(32),
    execution_duration_ms INTEGER,

    created_at      TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(message_id, session_id, link_type)
);

CREATE INDEX idx_cmsl_message ON chat_message_sandbox_links(message_id);
CREATE INDEX idx_cmsl_session ON chat_message_sandbox_links(session_id);
```

#### 1.3.2 Session Relationship Diagram

```
┌──────────────────┐     1:N     ┌──────────────────┐
│  chat_sessions   │◄───────────│ sandbox_sessions │
│  (existing)      │             │ (new)            │
│  - id            │             │ - id             │
│  - user_id       │             │ - chat_session_id│
│  - title         │◄────────────│ - user_id        │
│  - created_at    │   N:M via   │ - project_id     │
└──────────────────┘  messages  │ - session_id     │
        │                       └──────────────────┘
        │ 1:N                             │
        ▼                                 │ 1:N
┌──────────────────┐                      ▼
│  chat_messages   │      ┌──────────────────────────┐
│  (existing)      │      │ chat_message_sandbox_links│
│  - id            │◄────►│ - message_id             │
│  - session_id    │      │ - session_id             │
│  - role          │      │ - link_type              │
│  - content       │      │ - artifact_id            │
└──────────────────┘      └──────────────────────────┘
                                     │
                                     ▼
                          ┌──────────────────┐
                          │ sandbox_artifacts│
                          │ (new)            │
                          └──────────────────┘
```

**Relationship Rules:**

1. **One chat session can have multiple sandbox sessions** (e.g., one per project)
2. **One sandbox session belongs to one primary chat session** (for context continuity)
3. **One chat message can reference multiple sandbox artifacts** (via link table)
4. **One sandbox session can produce multiple artifacts**, each linked to the originating message

#### 1.3.3 State Recovery After Re-login

```
Scenario: User starts a sandbox session, logs out, logs back in later

1. Session Persistence:
   - Sandbox session state is stored in PostgreSQL (sandbox_sessions table)
   - Active container info is stored in Redis (with TTL = session expiry)

2. Reconnection Flow:
   ┌──────────┐     ┌──────────────┐     ┌──────────────┐     ┌──────────────┐
   │  User    │────▶│  Re-login    │────▶│  List active │────▶│  Resume or  │
   │  returns │     │  (new JWT)   │     │  sessions    │     │  create new │
   └──────────┘     └──────────────┘     └──────────────┘     └──────────────┘

3. Resume Policy (configurable):
   ┌────────────────────────────────────────────────────────────────────────┐
   │ If container still running:                                            │
   │   - Reconnect WebSocket to existing container                          │
   │   - Restore kernel state (variables, imports)                          │
   │   - Show notification: "Resumed previous session"                      │
   │                                                                        │
   │ If container stopped (within retention window):                        │
   │   - Option to "Restore session" (re-create container, re-run cells)    │
   │   - Or start fresh                                                     │
   │                                                                        │
   │ If past retention window:                                              │
   │   - Show artifact history                                              │
   │   - Option to "Start new session from artifacts"                       │
   │   - Previous outputs preserved in sandbox_artifacts table              │
   └────────────────────────────────────────────────────────────────────────┘
```

**Redis Session State (for fast lookup):**

```redis
# Session state (TTL = session expiry)
HSET sandbox:session:{session_id} \
    user_id {user_id} \
    project_id {project_id} \
    container_id {container_id} \
    status {status} \
    token_hash {token_hash} \
    internal_ip {ip} \
    internal_port {port} \
    last_activity {timestamp}
EXPIRE sandbox:session:{session_id} {ttl_seconds}

# User's active sessions (for quick listing)
SADD sandbox:user_sessions:{user_id} {session_id}

# Project's active sandboxes (for concurrency limit)
SADD sandbox:project_sessions:{project_id} {session_id}
```

---

## 2. Data Mounting System Integration

### 2.1 Mounting Strategy Design

#### 2.1.1 Container Mount Layout

```
Each sandbox container sees the following filesystem:

/
├── workspace/                          # Working directory (Jupyter root)
│   ├── data/                           # Project data (read-only or read-write)
│   │   ├── raw/                        # Raw input files
│   │   ├── processed/                  # Processed data (Seurat objects, etc.)
│   │   └── results/                    # Previous analysis results
│   ├── shared/                         # Shared reference datasets (read-only)
│   │   ├── references/                 # Reference genomes
│   │   ├── annotations/                # Gene annotations
│   │   └── demo_datasets/              # Demo datasets
│   ├── output/                         # Session output (read-write)
│   │   ├── plots/                      # Generated plots
│   │   ├── tables/                     # Generated tables
│   │   └── exports/                    # Exportable files
│   ├── uploads/                        # User uploads (read-only)
│   └── .session/                       # Session metadata (hidden)
│       ├── config.json                 # Session config
│       └── token                       # Auth token (not accessible to user code)
│
├── etc/sandbox/                        # System config (read-only, host-managed)
│   ├── entrypoint.sh                   # Container entrypoint
│   └── limits.conf                     # Resource limits
│
└── tmp/                                # Temp directory (size-limited tmpfs)
    └── sandbox/
```

#### 2.1.2 Docker Volume Mount Specification

```python
# Mount configuration for a sandbox container
def get_container_mounts(user_id: int, project_id: int, session_id: str) -> list[dict]:
    """Generate Docker mount configurations for a sandbox session."""

    mounts = [
        # 1. Project data (primary read-only mount)
        {
            "type": "bind",
            "source": f"/data/projects/{user_id}/{project_id}",
            "target": "/workspace/data",
            "read_only": True,
            "consistency": "cached"  # macOS optimization, ignored on Linux
        },

        # 2. Shared reference data (read-only)
        {
            "type": "bind",
            "source": "/data/shared",
            "target": "/workspace/shared",
            "read_only": True
        },

        # 3. User uploads (read-only)
        {
            "type": "bind",
            "source": f"/data/uploads/{user_id}",
            "target": "/workspace/uploads",
            "read_only": True
        },

        # 4. Session output (read-write, temporary)
        {
            "type": "bind",
            "source": f"/tmp/sandbox_{session_id}/output",
            "target": "/workspace/output",
            "read_only": False
        },

        # 5. Session metadata (read-only, host-managed)
        {
            "type": "bind",
            "source": f"/tmp/sandbox_{session_id}/.session",
            "target": "/workspace/.session",
            "read_only": True
        },

        # 6. Tmpfs for /tmp (memory-backed, size-limited)
        {
            "type": "tmpfs",
            "target": "/tmp/sandbox_tmp",
            "tmpfs_size": "512m"
        }
    ]

    # 7. Task results mount (if user has completed tasks for this project)
    task_mounts = get_task_result_mounts(user_id, project_id)
    mounts.extend(task_mounts)

    return mounts
```

#### 2.1.3 Project-Specific Mount Matrix

| Data Category | Source Path | Container Path | Mode | Condition |
|---------------|-------------|----------------|------|-----------|
| Active project data | `/data/projects/{uid}/{pid}` | `/workspace/data` | ro | Always |
| User uploads | `/data/uploads/{uid}` | `/workspace/uploads` | ro | If uploads exist |
| Shared references | `/data/shared` | `/workspace/shared` | ro | Always |
| Demo datasets | `/data/shared/demo_datasets` | `/workspace/shared/demo_datasets` | ro | Trial users only |
| Task results | `/data/tasks/{task_id}` | `/workspace/tasks/{task_id}` | ro | Per-completed-task |
| Session output | `/tmp/sandbox_{sid}/output` | `/workspace/output` | rw | Always |
| Session config | `/tmp/sandbox_{sid}/.session` | `/workspace/.session` | ro | Always |

---

### 2.2 Dynamic Mounting Mechanism

#### 2.2.1 Project Switching Flow

```
User switches project in UI:

┌──────────┐     ┌──────────────┐     ┌──────────────────┐     ┌──────────────┐
│  User    │────▶│  Vue3 emits  │────▶│  POST /sandbox/  │────▶│  Sandbox     │
│  selects │     │  'switch-    │     │  {session_id}/   │     │  Orchestrator│
│  project │     │   project'   │     │  switch_project  │     │              │
└──────────┘     └──────────────┘     └──────────────────┘     └──────┬───────┘
                                                                       │
                                                                       ▼
                                                              ┌──────────────────┐
                                                              │ 1. Validate user │
                                                              │    has access to │
                                                              │    new project   │
                                                              └────────┬─────────┘
                                                                       │
                                                                       ▼
                                                              ┌──────────────────┐
                                                              │ 2. Graceful stop │
                                                              │    (save state)  │
                                                              └────────┬─────────┘
                                                                       │
                                                                       ▼
                                                              ┌──────────────────┐
                                                              │ 3. Unmount old   │
                                                              │    project data  │
                                                              └────────┬─────────┘
                                                                       │
                                                                       ▼
                                                              ┌──────────────────┐
                                                              │ 4. Mount new     │
                                                              │    project data  │
                                                              └────────┬─────────┘
                                                                       │
                                                                       ▼
                                                              ┌──────────────────┐
                                                              │ 5. Update        │
                                                              │    sandbox_      │
                                                              │    sessions row  │
                                                              └────────┬─────────┘
                                                                       │
                                                                       ▼
                                                              ┌──────────────────┐
                                                              │ 6. Resume with   │
                                                              │    new data      │
                                                              └──────────────────┘
```

**Implementation Options:**

| Approach | Description | Pros | Cons |
|----------|-------------|------|------|
| A. Container restart | Stop container, change mounts, start new | Clean, simple | State loss (kernel variables), slow |
| B. Symlink swap | Keep container running, swap symlinks inside | Fast, no restart | Complex internal coordination |
| C. New container | Create new container with new mounts, migrate state | Clean isolation | Double resource usage during migration |
| **D. OverlayFS layers** (recommended) | Use OverlayFS to layer new project on top | Seamless, fast | Requires careful cleanup |

**Recommended: Approach A (Container Restart with State Preservation)**

```python
async def switch_project(session_id: str, new_project_id: int, user: User):
    """Switch sandbox session to a different project."""
    session = await get_sandbox_session(session_id)

    # 1. Validate access
    if not await check_project_access(user.id, new_project_id):
        raise PermissionDenied(f"No access to project {new_project_id}")

    # 2. Save current kernel state (if supported)
    kernel_state = await save_kernel_state(session.container_id)

    # 3. Stop current container
    await stop_container(session.container_id, timeout=30)

    # 4. Update mounts
    new_mounts = get_container_mounts(user.id, new_project_id, session_id)

    # 5. Start new container with new mounts
    new_container = await start_container(
        image=session.sandbox_image,
        mounts=new_mounts,
        resources=get_resource_limits(user),
        env=get_container_env(session, user)
    )

    # 6. Restore kernel state (if available)
    if kernel_state:
        await restore_kernel_state(new_container.id, kernel_state)

    # 7. Update session record
    await update_session(session_id, {
        "project_id": new_project_id,
        "container_id": new_container.id,
        "status": "ready",
        "mounted_project_ids": [new_project_id]
    })

    return {"status": "switched", "new_project_id": new_project_id}
```

#### 2.2.2 New Data Detection

```python
# Option 1: Inotify-based file watching (Linux only)
# Option 2: Polling-based detection
# Option 3: Event-driven (OmicHub API triggers sandbox refresh)

# Recommended: Option 3 (Event-driven via API)
class SandboxDataRefreshHandler:
    """Handle data updates from the main OmicHub system."""

    async def on_file_uploaded(self, user_id: int, project_id: int, file_path: str):
        """Called when user uploads a new file to a project."""
        # Find active sandbox sessions for this user+project
        sessions = await get_active_sessions(user_id=user_id, project_id=project_id)
        for session in sessions:
            await notify_session_data_refresh(session.session_id, {
                "event": "file_uploaded",
                "path": file_path,
                "message": f"New file available: {os.path.basename(file_path)}"
            })

    async def on_task_completed(self, task_id: int, user_id: int, project_id: int):
        """Called when an analysis task completes."""
        sessions = await get_active_sessions(user_id=user_id, project_id=project_id)
        for session in sessions:
            # Dynamically mount new task results
            task_mount = {
                "type": "bind",
                "source": f"/data/tasks/{task_id}",
                "target": f"/workspace/tasks/{task_id}",
                "read_only": True
            }
            await add_live_mount(session.container_id, task_mount)
            await notify_session_data_refresh(session.session_id, {
                "event": "task_completed",
                "task_id": task_id,
                "message": f"Task {task_id} results now available"
            })
```

#### 2.2.3 Lazy Loading for Large Files

```python
# For large files (h5ad, h5, bam), use chunked/remote access
# instead of loading entire file into memory

# Strategy: Install streaming data access libraries in sandbox image
LAZY_LOAD_LIBRARIES = {
    "hdf5": ["h5py", "anndata"],           # Chunked HDF5 access
    "zarr": ["zarr", "anndata[zarr]"],     # Zarr backend for AnnData
    "remote": ["fsspec", "s3fs", "gcsfs"], # Remote file system access
    "dask": ["dask", "dask-array"],        # Out-of-core computation
}

# Example: Access large h5ad without full load
LAZY_LOAD_TEMPLATE = '''
import scanpy as sc

# For large files, use backed mode (memory-mapped)
adata = sc.read_h5ad('/workspace/data/large_dataset.h5ad', backed='r')

# Now you can inspect without loading full matrix:
print(adata.shape)  # (100000, 30000)
print(adata.obs.head())  # Metadata is loaded, matrix is not

# Subset before materializing:
subset = adata[adata.obs.cell_type == 'T_cell', :1000].to_memory()
'''

# Auto-detect large files and suggest lazy loading
async def suggest_lazy_loading(session_id: str, file_list: list[str]):
    """Analyze files and suggest lazy loading strategies."""
    suggestions = []
    for file_path in file_list:
        size_mb = get_file_size_mb(file_path)
        if size_mb > 500:  # Files > 500MB
            ext = os.path.splitext(file_path)[1]
            if ext in ['.h5ad', '.h5', '.loom']:
                suggestions.append({
                    "file": file_path,
                    "size_mb": size_mb,
                    "suggestion": "Use backed='r' mode for memory-mapped access",
                    "code_snippet": f"adata = sc.read_h5ad('{file_path}', backed='r')"
                })
    return suggestions
```

---

### 2.3 Data Security

#### 2.3.1 Isolation Strategy: Defense in Depth

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Isolation Layers                             │
│                                                                     │
│  Layer 1: Docker Container Isolation                                │
│  ├─ Separate PID namespace (process isolation)                      │
│  ├─ Separate network namespace (network isolation)                  │
│  ├─ Separate mount namespace (filesystem isolation)                 │
│  └─ User namespace mapping (root in container → non-root on host)   │
│                                                                     │
│  Layer 2: Volume Mount Strategy                                     │
│  ├─ Only mount paths belonging to the session user                  │
│  ├─ Read-only mounts for all source data                            │
│  ├─ Read-write only for session-specific output directory           │
│  └─ No mount of /data root (prevents traversal)                     │
│                                                                     │
│  Layer 3: Container Runtime Security                                │
│  ├─ --security-opt no-new-privileges:true                           │
│  ├─ --cap-drop ALL (drop all capabilities)                          │
│  ├─ --cap-add CHOWN,SETUID,SETGID (minimal for package install)     │
│  ├─ Read-only root filesystem                                       │
│  └─ Seccomp profile for system call filtering                       │
│                                                                     │
│  Layer 4: Resource Limits                                           │
│  ├─ CPU cgroup limits                                               │
│  ├─ Memory cgroup limits (hard + swap)                              │
│  ├─ Disk quota (xfs_quota or overlay size)                          │
│  ├─ Network egress rate limiting                                    │
│  └─ Process count limits (pids cgroup)                              │
│                                                                     │
│  Layer 5: Application-Level Controls                                │
│  ├─ Execution timeout                                               │
│  ├─ Network egress allowlist (allowed external hosts)               │
│  ├─ Package installation allowlist                                  │
│  └─ Audit logging of all executed code                              │
└─────────────────────────────────────────────────────────────────────┘
```

#### 2.3.2 Path Traversal Prevention

```python
# Defense: Multiple layers prevent ../../ attacks

# Layer 1: Mount point isolation
# The container only sees /workspace/data, which is already scoped to
# /data/projects/{user_id}/{project_id}. There is no way to traverse
# above /workspace/data because the parent directories don't exist
# in the container's mount namespace.

# Layer 2: Symlink validation
async def validate_symlinks(container_id: str) -> list[str]:
    """Check for suspicious symlinks in sandbox workspace."""
    result = await docker_exec(container_id, [
        "find", "/workspace/output", "-type", "l", "-ls"
    ])
    suspicious = []
    for line in result.split("\n"):
        link_target = parse_symlink_target(line)
        if ".." in link_target or link_target.startswith("/"):
            suspicious.append(link_target)
    return suspicious

# Layer 3: Read-only root filesystem
# All directories except /workspace/output are mounted read-only
# Preventing writes to /etc, /usr, etc.

# Layer 4: AppArmor/SELinux profile
# Additional MAC restrictions preventing access outside container scope
SANDBOX_APPARMOR_PROFILE = """
profile sandbox_container flags=(attach_disconnected,mediate_deleted) {
    # Allow all within /workspace
    /workspace/** rwk,

    # Read-only for system libraries
    /usr/lib/** r,
    /lib/** r,
    /etc/** r,

    # Deny all other paths
    deny /** w,
}
"""
```

#### 2.3.3 Temporary Space Cleanup Strategy

```python
# Cleanup strategy with configurable retention
CLEANUP_STRATEGY = {
    # Immediate cleanup
    "immediate": {
        "description": "Clean up immediately on session end",
        "trigger": "session_terminated",
        "retention_hours": 0,
        "preserved_items": []  # Nothing preserved
    },

    # Short retention (default for trial)
    "short": {
        "description": "Keep for 1 hour after session end",
        "trigger": "session_terminated",
        "retention_hours": 1,
        "preserved_items": ["plots/*.png", "plots/*.pdf", "*.csv", "*.xlsx"]
    },

    # Medium retention (default for standard)
    "medium": {
        "description": "Keep for 24 hours after session end",
        "trigger": "session_terminated",
        "retention_hours": 24,
        "preserved_items": [
            "plots/**",
            "tables/**",
            "reports/**",
            "exports/**",
            "*.ipynb"
        ]
    },

    # Long retention (default for premium)
    "long": {
        "description": "Keep for 7 days after session end",
        "trigger": "session_terminated",
        "retention_hours": 168,
        "preserved_items": ["**/*"]  # Preserve everything
    },

    # Persist to project (manual action)
    "persist_to_project": {
        "description": "User explicitly saves outputs to project",
        "trigger": "user_action",
        "destination": "/data/projects/{user_id}/{project_id}/sandbox_outputs/{session_id}/",
        "preserved_items": ["**/*"]
    }
}

# Cleanup scheduler (runs every 15 minutes)
async def cleanup_expired_sessions():
    """Background job to clean up expired sandbox sessions."""
    expired_sessions = await db.fetchall("""
        SELECT session_id, user_id, terminated_at, termination_reason
        FROM sandbox_sessions
        WHERE status IN ('terminated', 'expired')
        AND cleaned_up_at IS NULL
        AND terminated_at < NOW() - INTERVAL '1 hour'
    """)

    for session in expired_sessions:
        # Get user's retention policy
        user_quota = await get_user_quota(session["user_id"])
        retention = CLEANUP_STRATEGY[user_quota.retention_policy]

        # Check if retention period has passed
        elapsed_hours = (datetime.now() - session["terminated_at"]).total_seconds() / 3600
        if elapsed_hours >= retention["retention_hours"]:
            # 1. Persist items matching preservation rules
            for pattern in retention["preserved_items"]:
                await persist_matching_files(session["session_id"], pattern)

            # 2. Delete container output directory
            output_dir = f"/tmp/sandbox_{session['session_id']}/output"
            await aiofiles.os.rmtree(output_dir, ignore_errors=True)

            # 3. Delete session metadata
            session_dir = f"/tmp/sandbox_{session['session_id']}/.session"
            await aiofiles.os.rmtree(session_dir, ignore_errors=True)

            # 4. Mark as cleaned up in database
            await db.execute("""
                UPDATE sandbox_sessions
                SET cleaned_up_at = NOW()
                WHERE session_id = $1
            """, session["session_id"])

            logger.info(f"Cleaned up sandbox session {session['session_id']}")
```

#### 2.3.4 Cleanup Policy Summary

| User Tier | Auto-Cleanup Delay | Preserved Outputs | Manual Persist |
|-----------|-------------------|-------------------|----------------|
| Guest | N/A (no sandbox) | N/A | N/A |
| Trial | 1 hour | Plots only | Yes |
| Standard | 24 hours | Plots, tables, reports | Yes |
| Premium | 7 days | Everything | Yes |
| Admin | Configurable | Everything | Yes |

---


## 3. Nextflow/Snakemake Workflow Engine Integration

### 3.1 Two Execution Modes

#### 3.1.1 Mode A: Direct CLI Execution (Sandbox → Snakemake/Nextflow)

In this mode, the sandbox container has the workflow engines installed locally. Advanced users write or modify workflow parameters and execute directly.

```python
# Mode A: Direct execution configuration
MODE_A_CONFIG = {
    "available_commands": {
        "snakemake": {
            "binary": "/opt/miniconda3/bin/snakemake",
            "version": "7.x",
            "default_args": ["--cores", "4", "--use-conda", "--rerun-incomplete"],
            "max_cores": 8,
            "timeout_sec": 7200,
            "description": "Execute Snakemake workflows directly"
        },
        "nextflow": {
            "binary": "/opt/nextflow/nextflow",
            "version": "23.x",
            "default_args": ["-resume", "-with-report", "report.html"],
            "max_cores": 8,
            "timeout_sec": 7200,
            "description": "Execute Nextflow workflows directly"
        }
    },

    # Workflow template locations inside sandbox
    "workflow_templates": {
        "rna_seq": "/workspace/shared/workflows/rna_seq/",
        "sc_rna_seq": "/workspace/shared/workflows/sc_rna_seq/",
        "atac_seq": "/workspace/shared/workflows/atac_seq/",
        "chip_seq": "/workspace/shared/workflows/chip_seq/",
    },

    # Restrictions
    "restrictions": {
        "allowed_workflow_dirs": ["/workspace/shared/workflows/"],
        "blocked_args": ["--drmaa", "--cluster", "--kubernetes", "--google-lifesciences"],
        "max_execution_time": 7200,
        "require_dry_run_first": True,  # Must run --dry-run before actual execution
    }
}
```

**Mode A Execution Flow:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Mode A: Direct CLI Execution                     │
│                                                                     │
│  1. User writes/modifies workflow code in sandbox IDE               │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │ Snakemake                                               │    │
│     │ configfile: "config.yaml"                               │    │
│     │ samples: {input: "data/samples.tsv"}                    │    │
│     │ ...                                                     │    │
│     └─────────────────────────────────────────────────────────┘    │
│                                                                     │
│  2. User clicks "Run Workflow"                                    │
│     → Frontend sends execute request via WebSocket                │
│                                                                     │
│  3. Sandbox Orchestrator pre-validates:                           │
│     a. Check --dry-run first (must pass)                          │
│     b. Validate blocked arguments                                 │
│     c. Check resource limits (cores, time)                        │
│                                                                     │
│  4. Execute in sandbox container:                                 │
│     cd /workspace/output && \                                     │
│     snakemake --cores 4 --use-conda --rerun-incomplete            │
│                                                                     │
│  5. Real-time output streaming via WebSocket                      │
│     → Frontend shows live logs                                    │
│                                                                     │
│  6. Results saved to /workspace/output/                           │
│     → User can download or persist to project                     │
└─────────────────────────────────────────────────────────────────────┘
```

#### 3.1.2 Mode B: MCP-Mediated Execution (Agent → MCP → Task API → Celery)

In this mode, the AI Agent submits workflows through the MCP protocol, leveraging the existing Celery task infrastructure.

```python
# Mode B: MCP-mediated execution
MODE_B_CONFIG = {
    "mcp_server": {
        "name": "workflow-mcp-server",
        "transport": "sse",  # Server-Sent Events
        "endpoint": "/mcp/workflow/sse",
        "tools": [
            "submit_snakemake_task",
            "submit_nextflow_task",
            "get_task_status",
            "list_available_flows",
            "cancel_task",
            "get_task_logs"
        ]
    },

    # Task submission config
    "task_api": {
        "base_url": "http://web:8000/api/v1",  # Internal Docker network
        "auth": "service_token",  # Pre-shared service token
        "timeout_sec": 30
    },

    # Status polling
    "status_polling": {
        "interval_sec": 5,
        "max_poll_duration": 86400,  # 24 hours
        "push_via_websocket": True  # Real-time updates
    }
}
```

**Mode B Execution Flow:**

```
┌─────────────────────────────────────────────────────────────────────┐
│                    Mode B: MCP-Mediated Execution                   │
│                                                                     │
│  1. User asks Agent: "帮我运行RNA-seq流程"                         │
│                                                                     │
│  2. Agent analyzes request:                                       │
│     → Identifies workflow: rna_seq                                │
│     → Identifies project context: current_project_id                │
│     → Gathers required parameters (interactive or automatic)      │
│                                                                     │
│  3. Agent calls WorkflowMCP.submit_snakemake_task()               │
│     ┌─────────────────────────────────────────────────────────┐    │
│     │ {                                                     │    │
│     │   "flow_id": "rna_seq_standard",                      │    │
│     │   "project_id": 42,                                   │    │
│     │   "parameters": {                                     │    │
│     │     "samples": "auto_detect",                         │    │
│     │     "genome": "hg38",                                 │    │
│     │     "aligner": "star"                                 │    │
│     │   }                                                   │    │
│     │ }                                                     │    │
│     └─────────────────────────────────────────────────────────┘    │
│                                                                     │
│  4. WorkflowMCP → OmicHub Task API:                               │
│     POST /api/v1/tasks                                            │
│     → Creates task record in tasks table                          │
│     → Enqueues Celery task                                        │
│     → Returns task_id                                             │
│                                                                     │
│  5. Celery Worker executes Snakemake:                             │
│     → Same as existing task execution pipeline                    │
│     → No changes to existing infrastructure                       │
│                                                                     │
│  6. Real-time status via WebSocket:                               │
│     Celery → Redis Pub/Sub → FastAPI → WebSocket → Frontend       │
│     → Sandbox IDE shows task progress as a "monitor panel"        │
│                                                                     │
│  7. Task completes → results in /data/tasks/{task_id}/            │
│     → Agent notifies user via chat                                │
│     → Sandbox can auto-mount results for exploration              │
└─────────────────────────────────────────────────────────────────────┘
```

#### 3.1.3 Mode Comparison

| Aspect | Mode A (Direct CLI) | Mode B (MCP-Mediated) |
|--------|---------------------|------------------------|
| **User** | Advanced bioinformatician | Any user via Agent |
| **Entry Point** | Sandbox IDE code editor | Chat conversation |
| **Control** | Full manual control | Agent-orchestrated |
| **Code visibility** | User sees/modifies all code | Abstracted parameters |
| **Resource usage** | Sandbox container resources | Celery worker resources |
| **Error handling** | User handles errors | Agent handles/reports errors |
| **Persistence** | Manual save to project | Automatic via task system |
| **Reproducibility** | User-managed | Fully tracked in tasks table |
| **Parallel jobs** | Single workflow | Can queue multiple via Celery |
| **Audit trail** | Session logs | Full task audit trail |

---

### 3.2 MCP Protocol Integration

#### 3.2.1 WorkflowMCP Server Design

```python
# backend/app/mcp/workflow_mcp_server.py
from mcp.server import Server
from mcp.types import Tool, TextContent, ImageContent
from pydantic import BaseModel, Field
from typing import Literal, Optional
import httpx

# --- Pydantic Models for Tool Parameters ---

class SubmitSnakemakeTaskParams(BaseModel):
    flow_id: str = Field(..., description="Workflow flow identifier (e.g., 'rna_seq_v2')")
    project_id: int = Field(..., description="Project ID to run the workflow on")
    parameters: dict = Field(default={}, description="Workflow-specific parameters as key-value pairs")
    samples_config: Optional[str] = Field(None, description="JSON string of sample configuration")

class SubmitNextflowTaskParams(BaseModel):
    flow_id: str = Field(..., description="Nextflow pipeline identifier")
    project_id: int = Field(..., description="Project ID to run the pipeline on")
    parameters: dict = Field(default={}, description="Pipeline parameters (--param key=value)")
    profile: str = Field("standard", description="Nextflow configuration profile")

class GetTaskStatusParams(BaseModel):
    task_id: int = Field(..., description="Task ID to query")

class ListAvailableFlowsParams(BaseModel):
    category: Optional[str] = Field(None, description="Filter by category (rna_seq, sc_rna_seq, etc.)")

class CancelTaskParams(BaseModel):
    task_id: int = Field(..., description="Task ID to cancel")

class GetTaskLogsParams(BaseModel):
    task_id: int = Field(..., description="Task ID to get logs for")
    tail_lines: int = Field(100, description="Number of log lines to retrieve from the end")


# --- MCP Server Implementation ---

class WorkflowMCPServer:
    """
    MCP Server for workflow execution integration.
    Bridges Agent requests to the existing OmicHub Task API.
    """

    def __init__(self, task_api_base_url: str, service_token: str):
        self.server = Server("omicshub-workflow-mcp")
        self.task_api = task_api_base_url
        self.service_token = service_token
        self.http_client = httpx.AsyncClient(
            base_url=task_api_base_url,
            headers={"Authorization": f"Service {service_token}"},
            timeout=30.0
        )
        self._register_tools()

    def _register_tools(self):
        """Register all workflow tools with the MCP server."""

        @self.server.tool()
        async def submit_snakemake_task(params: SubmitSnakemakeTaskParams) -> list[TextContent]:
            """
            Submit a Snakemake analysis workflow to the OmicHub task system.
            The workflow will be queued and executed by Celery workers.
            Returns a task ID for status tracking.
            """
            try:
                response = await self.http_client.post("/tasks", json={
                    "type": "snakemake",
                    "flow_id": params.flow_id,
                    "project_id": params.project_id,
                    "parameters": params.parameters,
                    "samples_config": params.samples_config,
                    "submitted_via": "mcp_agent"
                })
                response.raise_for_status()
                result = response.json()

                return [TextContent(
                    type="text",
                    text=f"Workflow submitted successfully!\n"
                         f"Task ID: {result['task_id']}\n"
                         f"Status: {result['status']}\n"
                         f"You can track progress using get_task_status(task_id={result['task_id']})"
                )]

            except httpx.HTTPStatusError as e:
                return [TextContent(
                    type="text",
                    text=f"Failed to submit workflow: {e.response.status_code}\n"
                         f"Details: {e.response.text}"
                )]

        @self.server.tool()
        async def submit_nextflow_task(params: SubmitNextflowTaskParams) -> list[TextContent]:
            """
            Submit a Nextflow pipeline to the OmicHub task system.
            The pipeline will be queued and executed by Celery workers.
            Returns a task ID for status tracking.
            """
            try:
                response = await self.http_client.post("/tasks", json={
                    "type": "nextflow",
                    "flow_id": params.flow_id,
                    "project_id": params.project_id,
                    "parameters": params.parameters,
                    "profile": params.profile,
                    "submitted_via": "mcp_agent"
                })
                response.raise_for_status()
                result = response.json()

                return [TextContent(
                    type="text",
                    text=f"Nextflow pipeline submitted successfully!\n"
                         f"Task ID: {result['task_id']}\n"
                         f"Status: {result['status']}\n"
                         f"Profile: {params.profile}"
                )]

            except httpx.HTTPStatusError as e:
                return [TextContent(
                    type="text",
                    text=f"Failed to submit pipeline: {e.response.status_code}\n"
                         f"Details: {e.response.text}"
                )]

        @self.server.tool()
        async def get_task_status(params: GetTaskStatusParams) -> list[TextContent]:
            """
            Get the current status of a submitted task.
            Returns: pending, queued, running, completed, failed, cancelled
            """
            try:
                response = await self.http_client.get(f"/tasks/{params.task_id}")
                response.raise_for_status()
                task = response.json()

                status_emoji = {
                    "pending": "⏳",
                    "queued": "📋",
                    "running": "🔄",
                    "completed": "✅",
                    "failed": "❌",
                    "cancelled": "🚫"
                }

                emoji = status_emoji.get(task['status'], "❓")

                text = (
                    f"{emoji} Task {params.task_id} Status: {task['status'].upper()}\n"
                    f"Type: {task['type']}\n"
                    f"Flow: {task['flow_id']}\n"
                    f"Project: {task['project_id']}\n"
                    f"Created: {task['created_at']}\n"
                    f"Started: {task.get('started_at', 'N/A')}\n"
                )

                if task.get('completed_at'):
                    text += f"Completed: {task['completed_at']}\n"
                if task.get('progress_percent') is not None:
                    text += f"Progress: {task['progress_percent']}%\n"
                if task.get('error_message'):
                    text += f"Error: {task['error_message']}\n"

                return [TextContent(type="text", text=text)]

            except httpx.HTTPStatusError as e:
                return [TextContent(
                    type="text",
                    text=f"Failed to get task status: {e.response.text}"
                )]

        @self.server.tool()
        async def list_available_flows(params: ListAvailableFlowsParams) -> list[TextContent]:
            """
            List available analysis workflows/pipelines.
            Optionally filter by category.
            """
            query = {}
            if params.category:
                query["category"] = params.category

            response = await self.http_client.get("/flows", params=query)
            response.raise_for_status()
            flows = response.json()

            lines = ["Available Analysis Workflows:", "=" * 50]
            for flow in flows:
                lines.append(f"\n📋 {flow['name']} (ID: {flow['id']})")
                lines.append(f"   Category: {flow['category']}")
                lines.append(f"   Description: {flow['description']}")
                lines.append(f"   Version: {flow['version']}")
                lines.append(f"   Estimated time: {flow.get('estimated_time', 'N/A')}")

            return [TextContent(type="text", text="\n".join(lines))]

        @self.server.tool()
        async def cancel_task(params: CancelTaskParams) -> list[TextContent]:
            """
            Cancel a running or queued task.
            """
            try:
                response = await self.http_client.post(f"/tasks/{params.task_id}/cancel")
                response.raise_for_status()
                result = response.json()

                return [TextContent(
                    type="text",
                    text=f"Task {params.task_id} cancellation: {result['status']}\n"
                         f"Previous state: {result.get('previous_state', 'N/A')}"
                )]

            except httpx.HTTPStatusError as e:
                return [TextContent(
                    type="text",
                    text=f"Failed to cancel task: {e.response.text}"
                )]

        @self.server.tool()
        async def get_task_logs(params: GetTaskLogsParams) -> list[TextContent]:
            """
            Get execution logs for a task.
            Useful for debugging failed workflows.
            """
            try:
                response = await self.http_client.get(
                    f"/tasks/{params.task_id}/logs",
                    params={"tail": params.tail_lines}
                )
                response.raise_for_status()
                logs = response.json()

                log_text = f"Logs for task {params.task_id} (last {params.tail_lines} lines):\n"
                log_text += "=" * 50 + "\n"
                log_text += "\n".join(logs['lines'])

                return [TextContent(type="text", text=log_text)]

            except httpx.HTTPStatusError as e:
                return [TextContent(
                    type="text",
                    text=f"Failed to get logs: {e.response.text}"
                )]

    async def run(self, transport: Literal["stdio", "sse"] = "sse"):
        """Run the MCP server with specified transport."""
        if transport == "sse":
            from mcp.server.sse import SseServerTransport
            from starlette.applications import Starlette
            from starlette.routing import Route, Mount
            import uvicorn

            sse = SseServerTransport("/mcp/workflow/sse/")

            async def handle_sse(request):
                async with sse.connect_sse(
                    request.scope, request.receive, request._send
                ) as (read_stream, write_stream):
                    await self.server.run(
                        read_stream, write_stream,
                        self.server.create_initialization_options()
                    )

            app = Starlette(routes=[
                Route("/mcp/workflow/sse", endpoint=handle_sse),
                Mount("/mcp/workflow/sse/", app=sse.handle_post_message)
            ])

            uvicorn.run(app, host="0.0.0.0", port=9001)

        else:
            from mcp.server.stdio import stdio_server
            async with stdio_server() as (read_stream, write_stream):
                await self.server.run(
                    read_stream, write_stream,
                    self.server.create_initialization_options()
                )
```

#### 3.2.2 MCP Tool Definition Summary

| Tool Name | Input Parameters | Returns | Use Case |
|-----------|-----------------|---------|----------|
| `submit_snakemake_task` | flow_id, project_id, parameters, samples_config | task_id, status | Agent submits Snakemake workflow |
| `submit_nextflow_task` | flow_id, project_id, parameters, profile | task_id, status | Agent submits Nextflow pipeline |
| `get_task_status` | task_id | status, progress, timestamps | Poll task progress |
| `list_available_flows` | category (optional) | List of workflows with metadata | Show user available options |
| `cancel_task` | task_id | cancellation status | Cancel running task |
| `get_task_logs` | task_id, tail_lines | Recent log lines | Debug failed workflows |

#### 3.2.3 MCP Server Registration

```python
# backend/app/mcp/registry.py
# Add to existing MCP server registry

MCP_SERVER_REGISTRY = {
    # ... existing MCP servers ...

    "workflow": {
        "name": "OmicHub Workflow Executor",
        "description": "Submit and monitor bioinformatics analysis workflows",
        "transport": "sse",
        "endpoint": "http://workflow-mcp:9001/mcp/workflow/sse",
        "required_permissions": ["can_execute_workflows"],
        "tools": [
            "submit_snakemake_task",
            "submit_nextflow_task",
            "get_task_status",
            "list_available_flows",
            "cancel_task",
            "get_task_logs"
        ]
    }
}
```

---

### 3.3 Hybrid Execution Decision Tree

```
                    User Request Received
                            │
            ┌───────────────┼───────────────┐
            │               │               │
        Explicit      Exploration/      Direct Workflow
        Workflow      Analysis          Request
        Modification  Request           (via Chat)
            │               │               │
            ▼               ▼               ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
    │ "我想改参数    │ │ "帮我看看     │ │ "帮我运行RNA-seq │
    │ 再跑"         │ │ 这个结果"     │ │ 流程"           │
    └──────┬───────┘ └──────┬───────┘ └────────┬─────────┘
           │                │                   │
           ▼                ▼                   ▼
    ┌──────────────┐ ┌──────────────┐ ┌──────────────────┐
    │  MODE A      │ │  Pure Sandbox│ │  MODE B          │
    │  Direct CLI  │ │  Exploration │ │  MCP-Mediated    │
    │              │ │              │ │                  │
    │ 1. Agent gen-│ │ 1. Agent     │ │ 1. Agent gathers │
    │    erates    │ │    generates │ │    parameters    │
    │    modified  │ │    code for  │ │    via chat      │
    │    Snakefile │ │    data      │ │                  │
    │              │ │    exploration│ │ 2. Agent calls   │
    │ 2. User      │ │              │ │    WorkflowMCP.  │
    │    reviews   │ │ 2. Code      │ │    submit_       │
    │    in IDE    │ │    executes  │ │    snakemake_    │
    │              │ │    in sandbox│ │    task()        │
    │ 3. Execute   │ │              │ │                  │
    │    snakemake │ │ 3. Results   │ │ 3. MCP Server    │
    │    in sandbox│ │    shown in  │ │    POSTs to      │
    │              │ │    chat/IDE  │ │    /api/v1/tasks │
    │ 4. Monitor   │ │              │ │                  │
    │    progress  │ │ 4. User can  │ │ 4. Task enters   │
    │    in IDE    │ │    iterate   │ │    Celery queue  │
    │              │ │    code      │ │                  │
    │ 5. Results   │ │              │ │ 5. Celery worker │
    │    in output │ │              │ │    executes      │
    │    dir       │ │              │ │    Snakemake     │
    │              │ │              │ │                  │
    │ 6. Persist   │ │              │ │ 6. Status pushed │
    │    to project│ │              │ │    via WebSocket │
    └──────────────┘ └──────────────┘ └──────────────────┘
           │                │                   │
           └───────────────┴───────────────────┘
                           │
                           ▼
                  ┌──────────────────┐
                  │  Results in      │
                  │  /data/tasks/    │
                  │  or /workspace/  │
                  │  output/         │
                  └──────────────────┘
```

---

### 3.4 Task Result Integration

```python
# After Mode B task completes, automatically integrate results

async def on_task_completed(task_id: int, project_id: int, user_id: int):
    """Handle task completion - integrate results into sandbox."""

    # 1. Update task status
    await db.execute("UPDATE tasks SET status = 'completed' WHERE id = $1", task_id)

    # 2. Find active sandbox sessions for this user+project
    sessions = await db.fetchall("""
        SELECT session_id, container_id
        FROM sandbox_sessions
        WHERE user_id = $1 AND project_id = $2 AND status = 'ready'
    """, user_id, project_id)

    # 3. Mount task results into each active sandbox
    for session in sessions:
        task_mount = {
            "type": "bind",
            "source": f"/data/tasks/{task_id}",
            "target": f"/workspace/tasks/{task_id}",
            "read_only": True
        }

        try:
            # Add mount to running container (if supported)
            await add_container_mount(session["container_id"], task_mount)

            # Notify sandbox of new data
            await send_sandbox_notification(session["session_id"], {
                "type": "task_completed",
                "task_id": task_id,
                "mount_point": f"/workspace/tasks/{task_id}",
                "message": f"Task {task_id} completed. Results available at /workspace/tasks/{task_id}/"
            })

        except Exception as e:
            logger.warning(f"Failed to mount task {task_id} to session {session['session_id']}: {e}")

    # 4. Update chat with completion notification
    await notify_chat_of_task_completion(project_id, task_id)
```

---


## 4. Microservice Decomposition & Communication

### 4.1 Service Decomposition Strategy

#### 4.1.1 Recommended Approach: Monolith Extension (Option A)

**Decision: Extend the existing FastAPI monolith. Do not split into separate services at this stage.**

| Criterion | Option A (Monolith) | Option B (Independent Copilot) | Option C (Full Microservices) |
|-----------|---------------------|--------------------------------|-------------------------------|
| **Complexity** | Low - add routers | Medium - new service | High - 3+ services |
| **DevOps overhead** | Minimal | Moderate | Significant |
| **Scaling granularity** | Whole app scales | Copilot scales independently | Fine-grained scaling |
| **Database sharing** | Natural shared DB | Cross-service DB access | Each has own DB |
| **Authentication** | Reuse existing middleware | Needs service-to-service auth | Needs auth mesh |
| **Recommended?** | **Yes** (current phase) | Future (if Copilot load >70%) | Future (enterprise scale) |

**Rationale:**
- OmicHub is a research platform, not a high-scale consumer app
- The added components (Copilot + Sandbox) share the same data domain (users, projects, files)
- Separate deployment adds operational complexity without proportional benefit
- **Migration path**: When Copilot CPU usage consistently exceeds 70%, extract to Option B

#### 4.1.2 Internal Module Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py                    # FastAPI app (existing, adds new routers)
│   ├── config.py                  # Settings (existing, adds sandbox settings)
│   │
│   ├── routers/                   # Existing routers
│   │   ├── auth.py
│   │   ├── projects.py
│   │   ├── tasks.py
│   │   ├── chat.py
│   │   └── mcp.py
│   │
│   ├── routers_new/               # NEW: Copilot + Sandbox routers
│   │   ├── copilot.py             # Copilot chat/code generation API
│   │   ├── sandbox.py             # Sandbox lifecycle API
│   │   ├── artifacts.py           # Artifact management API
│   │   └── workflow_mcp.py        # Workflow MCP server endpoint
│   │
│   ├── services/                  # Existing services
│   │   ├── auth_service.py
│   │   ├── project_service.py
│   │   └── task_service.py
│   │
│   ├── services_new/              # NEW: Core services
│   │   ├── copilot_service.py     # LLM interaction, prompt engineering
│   │   ├── sandbox_orchestrator.py # Docker container lifecycle
│   │   ├── session_manager.py     # Session state management
│   │   ├── artifact_service.py    # Artifact CRUD operations
│   │   └── code_executor.py       # Code execution in sandbox
│   │
│   ├── models/                    # SQLAlchemy models (existing + new)
│   │   ├── __init__.py
│   │   ├── user.py
│   │   ├── project.py
│   │   ├── chat.py
│   │   └── sandbox.py             # NEW: Sandbox-related models
│   │
│   ├── mcp/                       # MCP integration
│   │   ├── __init__.py
│   │   ├── client.py              # MCP client (existing)
│   │   ├── workflow_mcp_server.py # NEW: WorkflowMCP server
│   │   └── tools/                 # MCP tool implementations
│   │       ├── __init__.py
│   │       └── workflow_tools.py
│   │
│   └── sandbox/                   # NEW: Sandbox runtime
│       ├── __init__.py
│       ├── docker_manager.py      # Docker API interactions
│       ├── container_config.py    # Container configuration templates
│       ├── security_profiles.py   # AppArmor, seccomp profiles
│       └── templates/             # Sandbox entrypoint scripts
│           └── entrypoint.sh
```

#### 4.1.3 Future Extraction Plan (Option B Readiness)

```python
# Design all services behind interfaces for future extraction

# Interface pattern (enables future microservice extraction)
from abc import ABC, abstractmethod

class ISandboxOrchestrator(ABC):
    """Interface for sandbox orchestration.
    
    Current implementation: in-process Python module
    Future extraction: gRPC or HTTP client to separate service
    """

    @abstractmethod
    async def create_session(self, user: User, project: Project) -> SandboxSession:
        pass

    @abstractmethod
    async def execute_code(self, session_id: str, code: str) -> ExecutionResult:
        pass

    @abstractmethod
    async def terminate_session(self, session_id: str) -> None:
        pass

class ICodeExecutor(ABC):
    """Interface for code execution.
    Current: WebSocket proxy to container
    Future: Could use Jupyter Kernel Gateway protocol
    """

    @abstractmethod
    async def run_cell(self, session_id: str, code: str, cell_id: str) -> CellOutput:
        pass

    @abstractmethod
    async def interrupt_kernel(self, session_id: str) -> None:
        pass

    @abstractmethod
    async def restart_kernel(self, session_id: str) -> None:
        pass
```

---

### 4.2 Communication Protocols

#### 4.2.1 Communication Matrix

| Source | Destination | Protocol | Transport | Purpose |
|--------|-------------|----------|-----------|---------|
| Vue3 Frontend | FastAPI Main | HTTP REST | TCP/443 | API calls (CRUD) |
| Vue3 Frontend | FastAPI Main | WebSocket | TCP/443 | Real-time chat + sandbox I/O |
| FastAPI Main | PostgreSQL | SQL/TCP | TCP/5432 | Persistent storage |
| FastAPI Main | Redis | RESP | TCP/6379 | Caching + Pub/Sub |
| FastAPI Main | Celery Workers | Redis Broker | TCP/6379 | Async task dispatch |
| Celery Workers | Snakemake/Nextflow | CLI/SSH | Local/Remote | Workflow execution |
| FastAPI Main | Docker Daemon | Docker API | Unix Socket | Container lifecycle |
| FastAPI Main | Sandbox Container | WebSocket Proxy | Docker Network | Code execution I/O |
| FastAPI Main | MCP Servers | MCP Protocol | SSE / Stdio | Tool calling |
| Sandbox Container | External Network | HTTP (filtered) | TCP/80,443 | Package downloads (allowlist) |

#### 4.2.2 WebSocket Message Protocol

```python
# Unified WebSocket message protocol for Copilot + Sandbox
# All communication uses the same WebSocket connection,
# differentiated by 'channel' field.

class WebSocketMessage(BaseModel):
    """Base WebSocket message envelope."""
    id: str                    # Message UUID (for correlation)
    timestamp: str             # ISO 8601 timestamp
    channel: str               # Message routing channel
    type: str                  # Message type within channel
    payload: dict             # Message-specific data

# --- Channels ---
CHANNELS = {
    "chat": "AI conversation messages",
    "sandbox": "Code execution I/O",
    "copilot": "Agent thinking/actions",
    "system": "System notifications",
    "workflow": "Workflow task status"
}

# --- Sandbox Channel Messages ---

# Client → Server: Execute code
EXECUTE_CODE_MSG = {
    "id": "msg-001",
    "timestamp": "2025-01-15T10:30:00Z",
    "channel": "sandbox",
    "type": "execute",
    "payload": {
        "session_id": "sb-abc123",
        "cell_id": "cell-001",
        "code": "import scanpy as sc\nadata = sc.read_h5ad('/workspace/data/pbmc.h5ad')\nprint(adata)",
        "options": {
            "timeout": 120,
            "stream_output": True,
            "capture_plot": True
        }
    }
}

# Server → Client: Execution output (streaming)
OUTPUT_STREAM_MSG = {
    "id": "msg-002",
    "timestamp": "2025-01-15T10:30:01Z",
    "channel": "sandbox",
    "type": "output_stream",
    "payload": {
        "session_id": "sb-abc123",
        "cell_id": "cell-001",
        "output_type": "stream",  # stream, display_data, error, status
        "content": "AnnData object with n_obs ...",
        "is_complete": False  # More output coming
    }
}

# Server → Client: Execution complete
EXECUTION_COMPLETE_MSG = {
    "id": "msg-003",
    "timestamp": "2025-01-15T10:30:05Z",
    "channel": "sandbox",
    "type": "execution_complete",
    "payload": {
        "session_id": "sb-abc123",
        "cell_id": "cell-001",
        "success": True,
        "execution_time_ms": 4500,
        "outputs": [
            {"type": "stream", "text": "AnnData object..."},
            {"type": "display_data", "mime": "image/png", "data": "base64..."}
        ],
        "resources_used": {
            "cpu_time_sec": 2.3,
            "peak_memory_mb": 512
        }
    }
}

# Server → Client: Error
EXECUTION_ERROR_MSG = {
    "id": "msg-004",
    "timestamp": "2025-01-15T10:30:06Z",
    "channel": "sandbox",
    "type": "execution_error",
    "payload": {
        "session_id": "sb-abc123",
        "cell_id": "cell-001",
        "error_type": "FileNotFoundError",
        "error_message": "No such file: /workspace/data/pbmc.h5ad",
        "traceback": [...],
        "suggestions": ["Check if the file was uploaded to the project"]
    }
}

# --- Copilot Channel Messages ---

# Server → Client: Agent action notification
AGENT_ACTION_MSG = {
    "id": "msg-005",
    "timestamp": "2025-01-15T10:31:00Z",
    "channel": "copilot",
    "type": "agent_action",
    "payload": {
        "action": "mcp_tool_call",
        "tool": "submit_snakemake_task",
        "arguments": {"flow_id": "rna_seq", "project_id": 42},
        "status": "in_progress",
        "thought": "User wants to run RNA-seq analysis. I'll submit the workflow."
    }
}

# Server → Client: Agent result
AGENT_RESULT_MSG = {
    "id": "msg-006",
    "timestamp": "2025-01-15T10:31:05Z",
    "channel": "copilot",
    "type": "agent_result",
    "payload": {
        "action": "mcp_tool_call",
        "tool": "submit_snakemake_task",
        "success": True,
        "result": {"task_id": 12345, "status": "queued"}
    }
}

# --- Workflow Channel Messages ---

# Server → Client: Task status update (from Celery)
WORKFLOW_STATUS_MSG = {
    "id": "msg-007",
    "timestamp": "2025-01-15T10:32:00Z",
    "channel": "workflow",
    "type": "task_status_update",
    "payload": {
        "task_id": 12345,
        "status": "running",
        "progress_percent": 35,
        "current_step": "star_alignment",
        "logs_url": "/api/v1/tasks/12345/logs",
        "elapsed_time": "00:15:30",
        "estimated_remaining": "00:28:45"
    }
}
```

#### 4.2.3 FastAPI Router Registration (New Endpoints)

```python
# backend/app/main.py (update)
from fastapi import FastAPI
from app.routers import auth, projects, tasks, chat, mcp
from app.routers_new import copilot, sandbox, artifacts, workflow_mcp

app = FastAPI(title="OmicHub API")

# --- Existing routers (unchanged) ---
app.include_router(auth.router, prefix="/api/v1/auth")
app.include_router(projects.router, prefix="/api/v1/projects")
app.include_router(tasks.router, prefix="/api/v1/tasks")
app.include_router(chat.router, prefix="/api/v1/chat")
app.include_router(mcp.router, prefix="/api/v1/mcp")

# --- NEW: Copilot + Sandbox routers ---
app.include_router(copilot.router, prefix="/api/v1/copilot")
app.include_router(sandbox.router, prefix="/api/v1/sandbox")
app.include_router(artifacts.router, prefix="/api/v1/artifacts")

# --- NEW: Workflow MCP SSE endpoint ---
app.include_router(workflow_mcp.router, prefix="/mcp/workflow")

# --- NEW: Unified WebSocket endpoint ---
# Replaces/reuses existing chat WebSocket
@app.websocket("/ws/v1/unified")
async def unified_websocket(websocket: WebSocket):
    """
    Unified WebSocket for chat, sandbox, and workflow updates.
    Authenticates via JWT in query parameter or subprotocol.
    """
    await websocket.accept()
    
    # Authenticate
    token = websocket.query_params.get("token")
    user = await validate_websocket_token(token)
    if not user:
        await websocket.close(code=4001, reason="Invalid authentication")
        return
    
    # Register connection
    connection_id = await register_websocket(user.id, websocket)
    
    try:
        while True:
            message = await websocket.receive_json()
            
            # Route by channel
            channel = message.get("channel")
            if channel == "chat":
                await handle_chat_message(websocket, user, message)
            elif channel == "sandbox":
                await handle_sandbox_message(websocket, user, message)
            elif channel == "copilot":
                await handle_copilot_message(websocket, user, message)
            elif channel == "workflow":
                await handle_workflow_message(websocket, user, message)
            else:
                await websocket.send_json({
                    "channel": "system",
                    "type": "error",
                    "payload": {"message": f"Unknown channel: {channel}"}
                })
    except WebSocketDisconnect:
        await unregister_websocket(connection_id)
    except Exception as e:
        logger.exception("WebSocket error")
        await websocket.close(code=1011)
```

#### 4.2.4 Sandbox API Endpoints

```python
# backend/app/routers_new/sandbox.py
from fastapi import APIRouter, Depends, HTTPException, WebSocket
from app.dependencies import get_current_user, get_current_project

router = APIRouter(tags=["sandbox"])

@router.post("/sessions")
async def create_sandbox_session(
    request: CreateSessionRequest,
    user: User = Depends(get_current_user),
    project: Project = Depends(get_current_project)
):
    """
    Create a new sandbox session for the current user and project.
    Returns session_id and WebSocket connection URL.
    """
    # Check permission
    permission = await check_sandbox_permission(user, "access")
    
    # Check concurrent session limit
    active_count = await count_active_sessions(user.id)
    if active_count >= permission.limits["max_concurrent"]:
        raise HTTPException(429, "Maximum concurrent sessions reached")
    
    # Create session
    session = await sandbox_orchestrator.create_session(
        user=user,
        project=project,
        image=request.image or "omicshub/sandbox-base:latest",
        resources=permission.limits
    )
    
    return {
        "session_id": session.session_id,
        "ws_url": f"wss://api.omicshub.com/ws/v1/unified?token={user.ws_token}",
        "status": session.status,
        "resources": permission.limits,
        "expires_at": session.expires_at
    }

@router.get("/sessions")
async def list_sandbox_sessions(
    status: str = None,
    user: User = Depends(get_current_user)
):
    """List user's sandbox sessions (active and recent)."""
    sessions = await session_manager.list_sessions(
        user_id=user.id,
        status=status,
        limit=50
    )
    return {"sessions": sessions, "total": len(sessions)}

@router.get("/sessions/{session_id}")
async def get_sandbox_session(
    session_id: str,
    user: User = Depends(get_current_user)
):
    """Get sandbox session details."""
    session = await session_manager.get_session(session_id)
    if session.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "Access denied")
    return session

@router.post("/sessions/{session_id}/switch_project")
async def switch_project(
    session_id: str,
    request: SwitchProjectRequest,
    user: User = Depends(get_current_user)
):
    """Switch sandbox session to a different project."""
    session = await session_manager.get_session(session_id)
    if session.user_id != user.id:
        raise HTTPException(403, "Access denied")
    
    result = await sandbox_orchestrator.switch_project(
        session_id=session_id,
        new_project_id=request.project_id,
        user=user
    )
    return result

@router.post("/sessions/{session_id}/pause")
async def pause_sandbox_session(
    session_id: str,
    user: User = Depends(get_current_user)
):
    """Pause sandbox session (save state, stop container)."""
    session = await session_manager.get_session(session_id)
    if session.user_id != user.id:
        raise HTTPException(403, "Access denied")
    
    result = await sandbox_orchestrator.pause_session(session_id)
    return result

@router.post("/sessions/{session_id}/resume")
async def resume_sandbox_session(
    session_id: str,
    user: User = Depends(get_current_user)
):
    """Resume a paused sandbox session."""
    session = await session_manager.get_session(session_id)
    if session.user_id != user.id:
        raise HTTPException(403, "Access denied")
    
    result = await sandbox_orchestrator.resume_session(session_id)
    return result

@router.delete("/sessions/{session_id}")
async def terminate_sandbox_session(
    session_id: str,
    user: User = Depends(get_current_user)
):
    """Terminate a sandbox session and clean up resources."""
    session = await session_manager.get_session(session_id)
    if session.user_id != user.id and user.role != "admin":
        raise HTTPException(403, "Access denied")
    
    await sandbox_orchestrator.terminate_session(
        session_id=session_id,
        terminated_by=user.id,
        reason="user_request"
    )
    return {"status": "terminated"}

@router.post("/sessions/{session_id}/persist")
async def persist_sandbox_output(
    session_id: str,
    request: PersistOutputRequest,
    user: User = Depends(get_current_user)
):
    """Persist sandbox outputs to project storage."""
    session = await session_manager.get_session(session_id)
    if session.user_id != user.id:
        raise HTTPException(403, "Access denied")
    
    result = await artifact_service.persist_outputs(
        session_id=session_id,
        patterns=request.file_patterns,
        destination_path=request.destination,
        user=user
    )
    return result

@router.get("/quotas")
async def get_sandbox_quota(
    user: User = Depends(get_current_user)
):
    """Get current user's sandbox quota and usage."""
    quota = await get_user_quota(user.id)
    usage = await get_current_month_usage(user.id)
    return {
        "tier": quota.tier,
        "limits": {
            "max_concurrent_sessions": quota.max_concurrent_sessions,
            "max_cpu_cores": get_effective_limit(quota.custom_cpu_cores, quota.tier, "cpu"),
            "max_memory_mb": get_effective_limit(quota.custom_memory_mb, quota.tier, "memory"),
            "max_disk_mb": get_effective_limit(quota.custom_disk_mb, quota.tier, "disk"),
            "max_timeout_sec": get_effective_limit(quota.custom_max_timeout_sec, quota.tier, "timeout"),
        },
        "usage_this_month": {
            "sessions_used": quota.sessions_used_month,
            "sessions_limit": quota.sessions_limit_month,
            "cpu_hours_used": float(quota.cpu_hours_used_month),
            "cpu_hours_limit": float(quota.cpu_hours_limit_month),
            "memory_gb_hours_used": float(quota.memory_gb_hours_used),
            "memory_gb_hours_limit": float(quota.memory_gb_hours_limit),
        },
        "active_sessions": quota.active_sessions
    }

@router.get("/images")
async def list_sandbox_images(
    user: User = Depends(get_current_user)
):
    """List available sandbox images for the user."""
    images = await sandbox_orchestrator.list_available_images(user.tier)
    return {"images": images}
```

---

### 4.3 Shared Infrastructure

#### 4.3.1 Redis Key Schema (New Keys)

```redis
# Sandbox session state (primary source for active sessions)
HSET sandbox:session:{session_id} \
    user_id {user_id} \
    project_id {project_id} \
    container_id {container_id} \
    status {status} \
    token_hash {hash} \
    ws_connection_id {conn_id} \
    created_at {timestamp} \
    last_activity {timestamp} \
    expires_at {timestamp}
EXPIRE sandbox:session:{session_id} 86400  # 24h TTL

# User's active sessions (set for O(1) lookup)
SADD sandbox:user:{user_id}:sessions {session_id}

# Project's active sandbox sessions
SADD sandbox:project:{project_id}:sessions {session_id}

# Global sandbox counter (for rate limiting)
INCR sandbox:global:active_count
DECR sandbox:global:active_count

# Session output cache (temporary execution results)
SETEX sandbox:session:{session_id}:output:{cell_id} 3600 {json_output}

# Kernel state for session recovery (serialized)
SETEX sandbox:session:{session_id}:kernel_state 86400 {serialized_state}
```

#### 4.3.2 Celery Task Integration (New Tasks)

```python
# backend/app/tasks/sandbox_tasks.py
from celery import shared_task
import docker

@shared_task(bind=True, max_retries=3)
def create_sandbox_container(self, session_id: str, user_id: int, project_id: int,
                              image: str, cpu_cores: int, memory_mb: int):
    """Celery task to create a sandbox container asynchronously."""
    try:
        client = docker.from_env()
        
        mounts = get_container_mounts(user_id, project_id, session_id)
        
        container = client.containers.run(
            image=image,
            detach=True,
            name=f"omicshub-sandbox-{session_id}",
            mounts=mounts,
            mem_limit=f"{memory_mb}m",
            memswap_limit=f"{memory_mb}m",  # No swap
            cpu_quota=int(cpu_cores * 100000),
            cpu_period=100000,
            pids_limit=512,
            security_opt=["no-new-privileges:true"],
            cap_drop=["ALL"],
            cap_add=["CHOWN", "SETUID", "SETGID"],
            read_only=True,
            tmpfs={"/tmp": f"noexec,nosuid,size={memory_mb // 4}m"},
            network="omicshub_sandbox_network",
            environment={
                "SANDBOX_SESSION_ID": session_id,
                "SANDBOX_USER_ID": str(user_id),
                "SANDBOX_PROJECT_ID": str(project_id),
                "JUPYTER_TOKEN": "",  # Disable token auth (we use our own)
                "JUPYTER_ENABLE_LAB": "yes"
            },
            labels={
                "omicshub.session_id": session_id,
                "omicshub.user_id": str(user_id),
                "omicshub.project_id": str(project_id),
                "omicshub.created_by": "celery"
            }
        )
        
        # Update session with container info
        update_session_container(session_id, container.id, container.status)
        
        return {"container_id": container.id, "status": container.status}
        
    except docker.errors.APIError as exc:
        logger.exception("Failed to create sandbox container")
        self.retry(exc=exc, countdown=10)

@shared_task
def cleanup_expired_sandbox_sessions():
    """Periodic task to clean up expired sandbox sessions."""
    expired = get_expired_sessions()
    for session in expired:
        try:
            terminate_sandbox_container.delay(session["session_id"])
        except Exception as e:
            logger.error(f"Failed to cleanup session {session['session_id']}: {e}")

@shared_task
def terminate_sandbox_container(session_id: str):
    """Terminate a specific sandbox container."""
    try:
        client = docker.from_env()
        container = client.containers.get(f"omicshub-sandbox-{session_id}")
        container.stop(timeout=30)
        container.remove(force=True)
        
        # Update database
        mark_session_terminated(session_id)
        
        # Decrement active count
        redis_client.decr("sandbox:global:active_count")
        
    except docker.errors.NotFound:
        logger.warning(f"Container for session {session_id} not found")
        mark_session_terminated(session_id)

@shared_task
def report_sandbox_usage():
    """Aggregate sandbox usage for billing."""
    # Run every hour
    sessions = get_recent_sessions(hours=1)
    for session in sessions:
        update_usage_counters(session)
```

---

## 5. Deployment Architecture

### 5.1 Updated Docker Compose

```yaml
# docker-compose.yml - OmicHub Platform with Sandbox Integration
# ================================================================
version: "3.8"

# Networks
networks:
  omicshub_internal:
    driver: bridge
    internal: false
  omicshub_sandbox:
    driver: bridge
    internal: true  # Sandbox containers have no external access by default

# Volumes
volumes:
  postgres_data:
  redis_data:
  static_files:
  media_files:
  sandbox_tmp:
    driver: local

services:
  # ================================================================
  # EXISTING SERVICES (unchanged)
  # ================================================================

  db:
    image: postgres:16-alpine
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      - POSTGRES_DB=omicshub
      - POSTGRES_USER=${DB_USER}
      - POSTGRES_PASSWORD=${DB_PASSWORD}
    networks:
      - omicshub_internal
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${DB_USER} -d omicshub"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis:
    image: redis:7-alpine
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes --maxmemory 512mb --maxmemory-policy allkeys-lru
    networks:
      - omicshub_internal
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5

  web:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
    volumes:
      - /data:/data:ro
      - static_files:/app/static
      - media_files:/app/media
      - /var/run/docker.sock:/var/run/docker.sock:ro  # For Docker API access
    environment:
      - DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@db:5432/omicshub
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=redis://redis:6379/1
      - CELERY_RESULT_BACKEND=redis://redis:6379/2
      - SANDBOX_ENABLED=${SANDBOX_ENABLED:-true}
      - SANDBOX_NETWORK=omicshub_sandbox
      - SANDBOX_MAX_CONCURRENT=${SANDBOX_MAX_CONCURRENT:-10}
      - SANDBOX_DEFAULT_TIMEOUT=${SANDBOX_DEFAULT_TIMEOUT:-3600}
      - SANDBOX_IMAGE_DEFAULT=omicshub/sandbox-base:latest
      - LLM_API_KEY=${KIMI_API_KEY}
      - MCP_WORKFLOW_ENABLED=${MCP_WORKFLOW_ENABLED:-true}
    ports:
      - "8000:8000"
    networks:
      - omicshub_internal
      - omicshub_sandbox
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    deploy:
      resources:
        limits:
          cpus: '4'
          memory: 4G

  celery_worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: celery -A app.celery worker --loglevel=info --concurrency=4 -Q default,workflow,sandbox
    volumes:
      - /data:/data
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@db:5432/omicshub
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=redis://redis:6379/1
      - CELERY_RESULT_BACKEND=redis://redis:6379/2
      - SANDBOX_ENABLED=${SANDBOX_ENABLED:-true}
      - SANDBOX_NETWORK=omicshub_sandbox
    networks:
      - omicshub_internal
      - omicshub_sandbox
    depends_on:
      - redis
      - db
    deploy:
      resources:
        limits:
          cpus: '8'
          memory: 16G

  celery_beat:
    build:
      context: ./backend
      dockerfile: Dockerfile
    command: celery -A app.celery beat --loglevel=info
    environment:
      - DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@db:5432/omicshub
      - REDIS_URL=redis://redis:6379/0
      - CELERY_BROKER_URL=redis://redis:6379/1
      - CELERY_RESULT_BACKEND=redis://redis:6379/2
    networks:
      - omicshub_internal
    depends_on:
      - redis
      - db

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
      - static_files:/var/www/static:ro
      - media_files:/var/www/media:ro
    networks:
      - omicshub_internal
    depends_on:
      - web

  # ================================================================
  # NEW SERVICES (Sandbox-specific)
  # ================================================================

  # Sandbox temporary storage
  sandbox_tmp_storage:
    image: busybox:latest
    volumes:
      - sandbox_tmp:/tmp/sandbox
    command: "true"
    networks:
      - omicshub_sandbox
    profiles: ["setup"]

  # Optional: Dedicated workflow MCP server (if separating from web)
  # Currently integrated into web service; uncomment for Option B
  #
  # workflow_mcp:
  #   build:
  #     context: ./backend
  #     dockerfile: Dockerfile
  #   command: python -m app.mcp.workflow_mcp_server
  #   environment:
  #     - DATABASE_URL=postgresql://${DB_USER}:${DB_PASSWORD}@db:5432/omicshub
  #     - TASK_API_URL=http://web:8000/api/v1
  #     - SERVICE_TOKEN=${SERVICE_TOKEN}
  #   ports:
  #     - "9001:9001"
  #   networks:
  #     - omicshub_internal
  #   depends_on:
  #     - web
  #     - db
```

### 5.2 Nginx Configuration Update

```nginx
# nginx/nginx.conf (WebSocket + API routing)

upstream web_backend {
    server web:8000;
}

server {
    listen 80;
    server_name _;
    
    # Redirect to HTTPS in production
    # return 301 https://$server_name$request_uri;

    # --- WebSocket endpoint (unified for chat + sandbox) ---
    location /ws/ {
        proxy_pass http://web_backend;
        proxy_http_version 1.1;
        
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # WebSocket timeouts
        proxy_read_timeout 86400;
        proxy_send_timeout 86400;
        
        # Buffer settings for real-time streaming
        proxy_buffering off;
        proxy_cache off;
    }
    
    # --- MCP SSE endpoint ---
    location /mcp/ {
        proxy_pass http://web_backend;
        proxy_http_version 1.1;
        
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        
        # SSE-specific settings
        proxy_buffering off;
        proxy_cache off;
        proxy_read_timeout 3600;
        
        # Add CORS headers for MCP
        add_header Access-Control-Allow-Origin * always;
        add_header Access-Control-Allow-Methods "GET, POST, OPTIONS" always;
        add_header Access-Control-Allow-Headers "Content-Type, Authorization" always;
    }
    
    # --- API endpoints ---
    location /api/ {
        proxy_pass http://web_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        proxy_read_timeout 300;
        proxy_connect_timeout 300;
        proxy_send_timeout 300;
    }
    
    # --- Static files ---
    location /static/ {
        alias /var/www/static/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }
    
    # --- Media files ---
    location /media/ {
        alias /var/www/media/;
        expires 7d;
    }
    
    # --- Frontend SPA ---
    location / {
        root /var/www/frontend;
        try_files $uri $uri/ /index.html;
        
        # Gzip compression
        gzip on;
        gzip_types text/plain text/css application/json application/javascript text/xml;
    }
}
```

### 5.3 Sandbox Base Image Dockerfile

```dockerfile
# ================================================================
# Dockerfile.sandbox-base - OmicHub Sandbox Base Image
# ================================================================
# Multi-stage build for optimized image size

# ----------------------------------------------------------------
# Stage 1: Builder (install packages)
# ----------------------------------------------------------------
FROM jupyter/datascience-notebook:lab-4.0 AS builder

USER root

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    libhdf5-dev \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libpng-dev \
    libjpeg-dev \
    libtiff-dev \
    libfftw3-dev \
    libgsl-dev \
    libgmp-dev \
    libmpfr-dev \
    libboost-all-dev \
    git \
    wget \
    curl \
    ca-certificates \
    fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# Install R packages (Bioconductor)
RUN R -e "install.packages('BiocManager', repos='https://cloud.r-project.org/')" \
    && R -e "BiocManager::install(version='3.18')" \
    && R -e "BiocManager::install(c( \
        'SingleCellExperiment', \
        'Seurat', \
        'DESeq2', \
        'edgeR', \
        'limma', \
        'clusterProfiler', \
        'org.Hs.eg.db', \
        'org.Mm.eg.db', \
        'ComplexHeatmap', \
        'ggplot2', \
        'patchwork', \
        'dplyr', \
        'tidyr', \
        'readr', \
        'stringr', \
        'future', \
        'future.apply' \
    ))"

# Install Python packages (single layer for pip)
RUN pip install --no-cache-dir \
    scanpy[leiden] \
    anndata \
    mudata \
    squidpy \
    scvi-tools \
    celltypist \
    scikit-misc \
    decoupler \
    omicverse \
    pertpy \
    scib \
    scikit-learn \
    pandas \
    numpy \
    scipy \
    matplotlib \
    seaborn \
    plotly \
    bokeh \
    altair \
    jupyterlab-git \
    jupyterlab-code-formatter \
    black \
    isort \
    nbconvert \
    papermill \
    requests \
    aiohttp \
    zarr \
    fsspec \
    s3fs \
    gcsfs \
    dask[complete] \
    pyarrow \
    xlsxwriter \
    openpyxl

# ----------------------------------------------------------------
# Stage 2: Runtime (smaller, no build tools)
# ----------------------------------------------------------------
FROM jupyter/datascience-notebook:lab-4.0 AS runtime

USER root

# Install only runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libhdf5-103 \
    libcurl4 \
    libssl3 \
    libxml2 \
    libpng16-16 \
    libtiff5 \
    libfftw3-double3 \
    libgsl27 \
    libgmp10 \
    libmpfr6 \
    git \
    wget \
    curl \
    ca-certificates \
    fonts-dejavu-core \
    procps \
    htop \
    && rm -rf /var/lib/apt/lists/*

# Copy R libraries from builder
COPY --from=builder /opt/conda/lib/R/library /opt/conda/lib/R/library

# Copy Python packages from builder
COPY --from=builder /opt/conda/lib/python3.11/site-packages /opt/conda/lib/python3.11/site-packages
COPY --from=builder /opt/conda/bin /opt/conda/bin

# Install Snakemake and Nextflow
RUN pip install --no-cache-dir snakemake==7.32.4 snakemake-storage-plugin-s3 \
    && wget -qO- https://get.nextflow.io | bash \
    && mv nextflow /usr/local/bin/ \
    && chmod +x /usr/local/bin/nextflow

# ----------------------------------------------------------------
# Stage 3: Final security hardening
# ----------------------------------------------------------------
FROM runtime AS final

USER root

# Create sandbox user (non-root)
RUN groupadd -r sandbox -g 1000 \
    && useradd -r -g sandbox -u 1000 -d /workspace -s /bin/bash sandbox \
    && mkdir -p /workspace /workspace/output /workspace/data /workspace/shared /tmp/sandbox_tmp \
    && chown -R sandbox:sandbox /workspace \
    && chown -R sandbox:sandbox /tmp/sandbox_tmp

# Copy entrypoint script
COPY --chown=sandbox:sandbox backend/app/sandbox/templates/entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/entrypoint.sh

# Configure JupyterLab
RUN mkdir -p /etc/jupyter \
    && echo "c.NotebookApp.token = ''" >> /etc/jupyter/jupyter_notebook_config.py \
    && echo "c.NotebookApp.password = ''" >> /etc/jupyter/jupyter_notebook_config.py \
    && echo "c.NotebookApp.allow_origin = '*'" >> /etc/jupyter/jupyter_notebook_config.py \
    && echo "c.NotebookApp.disable_check_xsrf = True" >> /etc/jupyter/jupyter_notebook_config.py \
    && echo "c.NotebookApp.base_url = '/jupyter'" >> /etc/jupyter/jupyter_notebook_config.py \
    && echo "c.NotebookApp.notebook_dir = '/workspace'" >> /etc/jupyter/jupyter_notebook_config.py

# Environment variables
ENV PATH=/opt/conda/bin:$PATH \
    PYTHONPATH=/workspace:$PYTHONPATH \
    JUPYTER_ENABLE_LAB=yes \
    JUPYTER_TOKEN="" \
    SANDBOX_USER=sandbox \
    HOME=/workspace

# Security: read-only root filesystem
# Only /workspace and /tmp are writable
VOLUME ["/workspace/output", "/tmp"]

# Switch to sandbox user
USER sandbox
WORKDIR /workspace

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8888/jupyter/api || exit 1

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["jupyter", "lab", "--ip=0.0.0.0", "--port=8888", "--no-browser"]
```

### 5.4 Sandbox Entrypoint Script

```bash
#!/bin/bash
# entrypoint.sh - Sandbox container entrypoint

set -euo pipefail

# Load session configuration
SESSION_CONFIG="/workspace/.session/config.json"
if [ -f "$SESSION_CONFIG" ]; then
    export SANDBOX_SESSION_ID=$(cat "$SESSION_CONFIG" | python3 -c "import sys,json; print(json.load(sys.stdin)['session_id'])")
    export SANDBOX_USER_ID=$(cat "$SESSION_CONFIG" | python3 -c "import sys,json; print(json.load(sys.stdin)['user_id'])")
    export SANDBOX_PROJECT_ID=$(cat "$SESSION_CONFIG" | python3 -c "import sys,json; print(json.load(sys.stdin)['project_id'])")
fi

# Resource limits
ulimit -u 512           # Max processes
ulimit -n 1024          # Max open files
ulimit -v $(( 1024 * 1024 * ${SANDBOX_MEMORY_MB:-4096} ))  # Virtual memory

# Setup workspace
mkdir -p /workspace/output /workspace/data /workspace/shared

# Print session info
echo "========================================"
echo "  OmicHub Sandbox Session"
echo "========================================"
echo "  Session: ${SANDBOX_SESSION_ID:-unknown}"
echo "  User:    ${SANDBOX_USER_ID:-unknown}"
echo "  Project: ${SANDBOX_PROJECT_ID:-unknown}"
echo "  Time:    $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo "========================================"

# Execute the main command (jupyter lab)
exec "$@"
```

### 5.5 Image Size Optimization Strategy

| Optimization | Size Impact | Description |
|-------------|-------------|-------------|
| Multi-stage build | ~40% smaller | Separate build/runtime stages |
| `--no-install-recommends` | ~15% smaller | Avoid unnecessary apt packages |
| `--no-cache-dir pip` | ~10% smaller | Don't cache pip downloads |
| Layer consolidation | ~5% smaller | Minimize RUN layers |
| Exclude dev tools from runtime | ~30% smaller | No gcc, cmake, build-essential in final |
| **Total estimated size** | **~3-4 GB** | (Base image ~1.5GB + R + Python packages) |

### 5.6 Alternative Specialized Images

```dockerfile
# --- omicshub/sandbox-minimal ---
# Lightweight: Python only, no R
# Size: ~1.5 GB
# Use case: Python-only analyses, quick explorations

# --- omicshub/sandbox-r ---
# R-focused: Tidyverse + Bioconductor
# Size: ~2 GB
# Use case: R-based statistical analyses

# --- omicshub/sandbox-gpu ---
# CUDA-enabled: PyTorch, JAX, scVI GPU
# Size: ~6 GB
# Use case: Deep learning, GPU-accelerated computations
# Requires: NVIDIA Container Toolkit

# --- omicshub/sandbox-full ---
# Everything: Python + R + GPU + all tools
# Size: ~8 GB
# Use case: Premium users with full access
```

---

## 6. Backward Compatibility

### 6.1 Compatibility Checklist

| Component | Impact | Mitigation |
|-----------|--------|------------|
| **User registration/login** | None | No changes to auth flow |
| **Project management** | None | No changes to project APIs |
| **Task submission (existing)** | None | Existing `/api/v1/tasks` unchanged |
| **Celery workers** | Minimal | New queue `sandbox` added; existing queues unaffected |
| **Chat system** | Additive | New `channel` field in WebSocket messages; existing chat ignores unknown channels |
| **MCP system** | Additive | New MCP server registered alongside existing ones |
| **File system** | Additive | New `/tmp/sandbox_*` directories; existing paths unchanged |
| **Database** | Additive | New tables created; existing tables untouched |
| **Docker Compose** | Additive | New services added; existing service configs unchanged |

### 6.2 Feature Flags

```python
# backend/app/config.py
class Settings(BaseSettings):
    # ... existing settings ...

    # Feature flags for gradual rollout
    SANDBOX_ENABLED: bool = True
    SANDBOX_GUEST_ACCESS: bool = False  # Guests never get sandbox
    COPILOT_CODE_GENERATION: bool = True
    COPILOT_WORKFLOW_AUTOMATION: bool = True
    MCP_WORKFLOW_ENABLED: bool = True

    # Rollout percentage (0-100)
    SANDBOX_ROLLOUT_PERCENT: int = 100  # 100% = all eligible users

    def sandbox_available_for_user(self, user: User) -> bool:
        """Check if sandbox is available for a specific user."""
        if not self.SANDBOX_ENABLED:
            return False
        if user.role == "guest" and not self.SANDBOX_GUEST_ACCESS:
            return False
        # Gradual rollout: check user ID hash
        user_bucket = int(hashlib.md5(str(user.id).encode()).hexdigest(), 16) % 100
        return user_bucket < self.SANDBOX_ROLLOUT_PERCENT
```

### 6.3 API Versioning

```python
# All new endpoints use the same /api/v1/ prefix
# This is not a breaking change since endpoints are additive

# Existing endpoints (unchanged):
#   GET    /api/v1/auth/login
#   GET    /api/v1/projects
#   POST   /api/v1/tasks
#   GET    /api/v1/chat/sessions
#   GET    /api/v1/mcp/servers

# New endpoints (additive):
#   POST   /api/v1/sandbox/sessions
#   GET    /api/v1/sandbox/sessions
#   GET    /api/v1/sandbox/sessions/{id}
#   POST   /api/v1/sandbox/sessions/{id}/switch_project
#   POST   /api/v1/sandbox/sessions/{id}/pause
#   POST   /api/v1/sandbox/sessions/{id}/resume
#   DELETE /api/v1/sandbox/sessions/{id}
#   POST   /api/v1/sandbox/sessions/{id}/persist
#   GET    /api/v1/sandbox/quotas
#   GET    /api/v1/sandbox/images
#   GET    /api/v1/copilot/chat
#   GET    /api/v1/artifacts
#   GET    /api/v1/artifacts/{id}
#   GET    /mcp/workflow/sse          # MCP SSE endpoint

# WebSocket (unified, backward-compatible):
#   wss://api/ws/v1/unified           # Replaces or supplements existing chat WS
```

### 6.4 Frontend Integration (Non-Breaking)

```typescript
// frontend/src/composables/useSandbox.ts
// Feature-flagged sandbox integration

import { ref, computed } from 'vue'
import { useUserStore } from '@/stores/user'

export function useSandbox() {
  const userStore = useUserStore()
  
  // Check if sandbox is available for current user
  const sandboxEnabled = computed(() => {
    return import.meta.env.VITE_SANDBOX_ENABLED === 'true' &&
           userStore.currentUser?.sandbox_available === true
  })
  
  // Only initialize WebSocket connection if sandbox is enabled
  const wsConnection = computed(() => {
    if (!sandboxEnabled.value) return null
    return useUnifiedWebSocket()  // Shared with chat
  })
  
  const createSession = async (projectId: number) => {
    if (!sandboxEnabled.value) {
      throw new Error('Sandbox is not available for your account')
    }
    const response = await api.post('/sandbox/sessions', { project_id: projectId })
    return response.data
  }
  
  return {
    sandboxEnabled,
    createSession,
    // ... other methods
  }
}
```

### 6.5 Migration Strategy

```
Phase 1: Development (Weeks 1-4)
├── Feature flags all disabled in production
├── Sandbox endpoints return 503 "Not Available"
├── Development team uses staging environment
└── No user-facing changes

Phase 2: Internal Testing (Weeks 5-6)
├── Enable sandbox for admin users only
├── Test all integration points
├── Performance benchmarking
└── Security audit

Phase 3: Beta Rollout (Weeks 7-8)
├── Enable for 10% of standard users
├── Monitor error rates, resource usage
├── Collect feedback
└── Adjust resource limits based on usage patterns

Phase 4: Full Rollout (Week 9)
├── Enable for 100% of eligible users
├── Monitor closely for first 48 hours
├── Keep feature flag ready for emergency disable
└── Celebrate!
```

---


## 7. Appendix: SQL Schema Definitions

### 7.1 Complete New Schema

```sql
-- ============================================================
-- OmicHub Sandbox Module - Complete SQL Schema
-- Run as migration: alembic revision -m "add sandbox tables"
-- ============================================================

-- ------------------------------------------------------------
-- 1. user_sandbox_quotas: Per-user resource quotas
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_sandbox_quotas (
    id                      SERIAL PRIMARY KEY,
    user_id                 INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tier                    VARCHAR(32) NOT NULL DEFAULT 'trial'
                            CHECK (tier IN ('guest', 'trial', 'standard', 'premium', 'admin')),
    sessions_used_month     INTEGER NOT NULL DEFAULT 0,
    sessions_limit_month    INTEGER NOT NULL DEFAULT 50,
    cpu_hours_used_month    DECIMAL(10,2) NOT NULL DEFAULT 0.0,
    cpu_hours_limit_month   DECIMAL(10,2) NOT NULL DEFAULT 100.0,
    memory_gb_hours_used    DECIMAL(10,2) NOT NULL DEFAULT 0.0,
    memory_gb_hours_limit   DECIMAL(10,2) NOT NULL DEFAULT 500.0,
    active_sessions         INTEGER NOT NULL DEFAULT 0,
    max_concurrent_sessions INTEGER NOT NULL DEFAULT 2,
    custom_cpu_cores        INTEGER,
    custom_memory_mb        INTEGER,
    custom_disk_mb          INTEGER,
    custom_max_timeout_sec  INTEGER,
    gpu_hours_used_month    DECIMAL(10,2) NOT NULL DEFAULT 0.0,
    gpu_hours_limit_month   DECIMAL(10,2) NOT NULL DEFAULT 0.0,
    billing_cycle_start     DATE NOT NULL DEFAULT CURRENT_DATE,
    billing_cycle_end       DATE NOT NULL DEFAULT (CURRENT_DATE + INTERVAL '30 days'),
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_usq_user UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_usq_user_id ON user_sandbox_quotas(user_id);
CREATE INDEX IF NOT EXISTS idx_usq_tier ON user_sandbox_quotas(tier);
CREATE INDEX IF NOT EXISTS idx_usq_billing_cycle ON user_sandbox_quotas(billing_cycle_start, billing_cycle_end);

-- Trigger: Reset monthly quotas on billing cycle change
CREATE OR REPLACE FUNCTION reset_monthly_sandbox_quotas()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.billing_cycle_start IS DISTINCT FROM OLD.billing_cycle_start THEN
        NEW.sessions_used_month := 0;
        NEW.cpu_hours_used_month := 0.0;
        NEW.memory_gb_hours_used := 0.0;
        NEW.gpu_hours_used_month := 0.0;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_reset_sandbox_quotas ON user_sandbox_quotas;
CREATE TRIGGER trigger_reset_sandbox_quotas
    BEFORE UPDATE ON user_sandbox_quotas
    FOR EACH ROW
    EXECUTE FUNCTION reset_monthly_sandbox_quotas();

-- ------------------------------------------------------------
-- 2. user_sandbox_permissions: Granular feature permissions
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_sandbox_permissions (
    id                          SERIAL PRIMARY KEY,
    user_id                     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    can_access_sandbox          BOOLEAN NOT NULL DEFAULT FALSE,
    can_execute_code            BOOLEAN NOT NULL DEFAULT FALSE,
    can_execute_workflows       BOOLEAN NOT NULL DEFAULT FALSE,
    can_install_packages        BOOLEAN NOT NULL DEFAULT FALSE,
    can_access_gpu              BOOLEAN NOT NULL DEFAULT FALSE,
    can_persist_artifacts       BOOLEAN NOT NULL DEFAULT FALSE,
    can_share_artifacts         BOOLEAN NOT NULL DEFAULT FALSE,
    can_access_shared_datasets  BOOLEAN NOT NULL DEFAULT TRUE,
    allowed_workflow_categories VARCHAR(256)[] DEFAULT ARRAY['basic'],
    max_workflow_parallel_jobs  INTEGER DEFAULT 2,
    allowed_pypi_packages       TEXT[],
    blocked_pypi_packages       TEXT[],
    admin_override              BOOLEAN DEFAULT FALSE,
    override_reason             TEXT,
    granted_by                  INTEGER REFERENCES users(id),
    granted_at                  TIMESTAMP WITH TIME ZONE,
    created_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at                  TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_usp_user UNIQUE (user_id)
);

CREATE INDEX IF NOT EXISTS idx_usp_user_id ON user_sandbox_permissions(user_id);

-- ------------------------------------------------------------
-- 3. sandbox_sessions: Active and historical sandbox sessions
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sandbox_sessions (
    id                      SERIAL PRIMARY KEY,
    session_id              VARCHAR(64) NOT NULL UNIQUE,
    internal_token          VARCHAR(128) NOT NULL,
    user_id                 INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    project_id              INTEGER REFERENCES projects(id),
    chat_session_id         INTEGER REFERENCES chat_sessions(id),
    container_id            VARCHAR(64),
    container_name          VARCHAR(128),
    sandbox_image           VARCHAR(128) NOT NULL DEFAULT 'omicshub/sandbox-base:latest',
    cpu_cores               INTEGER NOT NULL DEFAULT 2,
    memory_mb               INTEGER NOT NULL DEFAULT 4096,
    disk_mb                 INTEGER NOT NULL DEFAULT 2048,
    gpu_enabled             BOOLEAN DEFAULT FALSE,
    internal_ip             INET,
    internal_port           INTEGER DEFAULT 8888,
    status                  VARCHAR(32) NOT NULL DEFAULT 'pending'
        CHECK (status IN (
            'pending', 'creating', 'ready', 'executing',
            'paused', 'error', 'terminating', 'terminated', 'expired'
        )),
    mounted_project_ids     INTEGER[],
    mounted_dataset_ids     INTEGER[],
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    started_at              TIMESTAMP WITH TIME ZONE,
    last_activity_at        TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    expires_at              TIMESTAMP WITH TIME ZONE,
    terminated_at           TIMESTAMP WITH TIME ZONE,
    terminated_by           INTEGER REFERENCES users(id),
    termination_reason      VARCHAR(64),
    kernel_state            JSONB,
    checkpoint_path         TEXT,
    cleaned_up_at           TIMESTAMP WITH TIME ZONE,
    CONSTRAINT uq_ss_session UNIQUE (session_id)
);

CREATE INDEX IF NOT EXISTS idx_ss_user_id ON sandbox_sessions(user_id);
CREATE INDEX IF NOT EXISTS idx_ss_chat_session ON sandbox_sessions(chat_session_id);
CREATE INDEX IF NOT EXISTS idx_ss_status ON sandbox_sessions(status);
CREATE INDEX IF NOT EXISTS idx_ss_project ON sandbox_sessions(project_id);
CREATE INDEX IF NOT EXISTS idx_ss_expires ON sandbox_sessions(expires_at);

-- ------------------------------------------------------------
-- 4. sandbox_usage_logs: Detailed usage for billing/audit
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sandbox_usage_logs (
    id                      SERIAL PRIMARY KEY,
    user_id                 INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id              VARCHAR(64) NOT NULL,
    started_at              TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),
    ended_at                TIMESTAMP WITH TIME ZONE,
    duration_sec            INTEGER,
    cpu_cores_allocated     INTEGER NOT NULL,
    memory_mb_allocated     INTEGER NOT NULL,
    disk_mb_allocated       INTEGER NOT NULL,
    gpu_allocated           BOOLEAN DEFAULT FALSE,
    cpu_seconds_used        DECIMAL(10,2),
    memory_mb_peak          INTEGER,
    disk_mb_used            INTEGER,
    project_id              INTEGER REFERENCES projects(id),
    workflow_id             INTEGER,
    terminated_reason       VARCHAR(32) CHECK (terminated_reason IN (
        'user_exit', 'timeout', 'quota_exceeded', 'error', 'admin_kill', 'system_shutdown'
    )),
    sandbox_image           VARCHAR(128) NOT NULL,
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_sul_session UNIQUE (session_id)
);

CREATE INDEX IF NOT EXISTS idx_sul_user_id ON sandbox_usage_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_sul_session_id ON sandbox_usage_logs(session_id);
CREATE INDEX IF NOT EXISTS idx_sul_time_range ON sandbox_usage_logs(started_at, ended_at);
CREATE INDEX IF NOT EXISTS idx_sul_project ON sandbox_usage_logs(project_id);

-- ------------------------------------------------------------
-- 5. sandbox_artifacts: Persisted code/output from sessions
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS sandbox_artifacts (
    id                      SERIAL PRIMARY KEY,
    user_id                 INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    session_id              VARCHAR(64) NOT NULL,
    project_id              INTEGER REFERENCES projects(id),
    name                    VARCHAR(256) NOT NULL,
    artifact_type           VARCHAR(32) NOT NULL
        CHECK (artifact_type IN (
            'code_cell', 'notebook', 'plot', 'data_file', 'report', 'workflow'
        )),
    storage_path            TEXT NOT NULL,
    file_size_bytes         BIGINT,
    checksum                VARCHAR(64),
    parent_session_id       VARCHAR(64),
    source_chat_message_id  INTEGER REFERENCES chat_messages(id),
    description             TEXT,
    tags                    TEXT[],
    is_shared               BOOLEAN DEFAULT FALSE,
    shared_token            VARCHAR(64),
    created_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at              TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    CONSTRAINT uq_sa_path UNIQUE (user_id, project_id, storage_path)
);

CREATE INDEX IF NOT EXISTS idx_sa_user ON sandbox_artifacts(user_id);
CREATE INDEX IF NOT EXISTS idx_sa_session ON sandbox_artifacts(session_id);
CREATE INDEX IF NOT EXISTS idx_sa_project ON sandbox_artifacts(project_id);
CREATE INDEX IF NOT EXISTS idx_sa_type ON sandbox_artifacts(artifact_type);

-- ------------------------------------------------------------
-- 6. chat_message_sandbox_links: Connect chat to sandbox
-- ------------------------------------------------------------
CREATE TABLE IF NOT EXISTS chat_message_sandbox_links (
    id                  SERIAL PRIMARY KEY,
    message_id          INTEGER NOT NULL REFERENCES chat_messages(id) ON DELETE CASCADE,
    session_id          VARCHAR(64) NOT NULL,
    link_type           VARCHAR(32) NOT NULL
        CHECK (link_type IN (
            'code_generated', 'execution_result', 'artifact_created',
            'session_started', 'session_referenced'
        )),
    artifact_id         INTEGER REFERENCES sandbox_artifacts(id),
    execution_status    VARCHAR(32),
    execution_duration_ms INTEGER,
    created_at          TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    UNIQUE(message_id, session_id, link_type)
);

CREATE INDEX IF NOT EXISTS idx_cmsl_message ON chat_message_sandbox_links(message_id);
CREATE INDEX IF NOT EXISTS idx_cmsl_session ON chat_message_sandbox_links(session_id);
```

### 7.2 Indexes Summary

| Table | Index | Type | Purpose |
|-------|-------|------|---------|
| `user_sandbox_quotas` | `idx_usq_user_id` | B-tree | User quota lookup |
| `user_sandbox_quotas` | `idx_usq_tier` | B-tree | Tier-based queries |
| `sandbox_sessions` | `idx_ss_user_id` | B-tree | User's sessions |
| `sandbox_sessions` | `idx_ss_status` | B-tree | Status filtering |
| `sandbox_sessions` | `idx_ss_expires` | B-tree | Expired session cleanup |
| `sandbox_usage_logs` | `idx_sul_time_range` | B-tree | Usage reports |
| `sandbox_artifacts` | `idx_sa_session` | B-tree | Session artifacts |

### 7.3 Row-Level Security (Optional Enhancement)

```sql
-- Enable RLS for multi-tenant data isolation
ALTER TABLE sandbox_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sandbox_artifacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE sandbox_usage_logs ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own sessions
CREATE POLICY sandbox_sessions_user_isolation ON sandbox_sessions
    FOR ALL
    USING (user_id = current_setting('app.current_user_id')::INTEGER)
    WITH CHECK (user_id = current_setting('app.current_user_id')::INTEGER);

-- Policy: Admins can see all sessions
CREATE POLICY sandbox_sessions_admin ON sandbox_sessions
    FOR ALL
    USING (
        EXISTS (
            SELECT 1 FROM users WHERE id = current_setting('app.current_user_id')::INTEGER
            AND role = 'admin'
        )
    );
```

---

## 8. Appendix: API Reference

### 8.1 New REST Endpoints Summary

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `POST` | `/api/v1/sandbox/sessions` | JWT | Create new sandbox session |
| `GET` | `/api/v1/sandbox/sessions` | JWT | List user's sessions |
| `GET` | `/api/v1/sandbox/sessions/{id}` | JWT | Get session details |
| `POST` | `/api/v1/sandbox/sessions/{id}/switch_project` | JWT | Switch project context |
| `POST` | `/api/v1/sandbox/sessions/{id}/pause` | JWT | Pause session |
| `POST` | `/api/v1/sandbox/sessions/{id}/resume` | JWT | Resume paused session |
| `DELETE` | `/api/v1/sandbox/sessions/{id}` | JWT | Terminate session |
| `POST` | `/api/v1/sandbox/sessions/{id}/persist` | JWT | Save outputs to project |
| `GET` | `/api/v1/sandbox/quotas` | JWT | Get user's quota |
| `GET` | `/api/v1/sandbox/images` | JWT | List available images |
| `GET` | `/api/v1/artifacts` | JWT | List user's artifacts |
| `GET` | `/api/v1/artifacts/{id}` | JWT | Get artifact details |
| `GET` | `/api/v1/artifacts/{id}/download` | JWT/Token | Download artifact |
| `POST` | `/api/v1/artifacts/{id}/share` | JWT | Create shareable link |
| `GET` | `/api/v1/copilot/chat` | JWT | Get Copilot chat history |
| `POST` | `/api/v1/copilot/chat` | JWT | Send message to Copilot |
| `GET` | `/mcp/workflow/sse` | JWT | Workflow MCP SSE stream |

### 8.2 WebSocket Message Types

| Channel | Type | Direction | Description |
|---------|------|-----------|-------------|
| `sandbox` | `execute` | Client→Server | Execute code cell |
| `sandbox` | `output_stream` | Server→Client | Execution output (streaming) |
| `sandbox` | `execution_complete` | Server→Client | Execution finished |
| `sandbox` | `execution_error` | Server→Client | Execution error |
| `sandbox` | `interrupt` | Client→Server | Interrupt running code |
| `sandbox` | `restart_kernel` | Client→Server | Restart kernel |
| `sandbox` | `install_package` | Client→Server | Install Python/R package |
| `copilot` | `agent_action` | Server→Client | Agent is performing an action |
| `copilot` | `agent_result` | Server→Client | Agent action completed |
| `copilot` | `agent_thought` | Server→Client | Agent's reasoning (debug) |
| `workflow` | `task_status_update` | Server→Client | Celery task status change |
| `workflow` | `task_log_stream` | Server→Client | Task log streaming |
| `system` | `quota_warning` | Server→Client | Approaching quota limit |
| `system` | `session_expiry_warning` | Server→Client | Session expiring soon |
| `system` | `data_refresh` | Server→Client | New data available |

---

## 9. Appendix: Docker & Build Configurations

### 9.1 Build Script

```bash
#!/bin/bash
# build-sandbox-images.sh - Build all sandbox images

set -e

REGISTRY="omicshub"
VERSION=${1:-"latest"}

echo "Building OmicHub Sandbox Images (version: $VERSION)..."

# Base image
docker build \
    -f Dockerfile.sandbox-base \
    -t ${REGISTRY}/sandbox-base:${VERSION} \
    -t ${REGISTRY}/sandbox-base:latest \
    .

# Minimal variant (Python only)
docker build \
    -f Dockerfile.sandbox-minimal \
    -t ${REGISTRY}/sandbox-minimal:${VERSION} \
    -t ${REGISTRY}/sandbox-minimal:latest \
    .

# R-focused variant
docker build \
    -f Dockerfile.sandbox-r \
    -t ${REGISTRY}/sandbox-r:${VERSION} \
    -t ${REGISTRY}/sandbox-r:latest \
    .

# GPU variant
docker build \
    -f Dockerfile.sandbox-gpu \
    -t ${REGISTRY}/sandbox-gpu:${VERSION} \
    -t ${REGISTRY}/sandbox-gpu:latest \
    .

# Push to registry (optional)
if [ "$2" == "--push" ]; then
    echo "Pushing images to registry..."
    docker push ${REGISTRY}/sandbox-base:${VERSION}
    docker push ${REGISTRY}/sandbox-minimal:${VERSION}
    docker push ${REGISTRY}/sandbox-r:${VERSION}
    docker push ${REGISTRY}/sandbox-gpu:${VERSION}
fi

echo "Build complete!"
echo ""
echo "Available images:"
docker images ${REGISTRY}/sandbox-* --format "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"
```

### 9.2 Development docker-compose Override

```yaml
# docker-compose.override.yml (for local development)
version: "3.8"

services:
  web:
    volumes:
      - ./backend:/app:ro  # Mount source code for hot reload
    environment:
      - DEBUG=true
      - RELOAD=true
    command: uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

  sandbox_dev:
    build:
      context: ./backend
      dockerfile: Dockerfile.sandbox-base
    command: sleep infinity  # Keep container alive for debugging
    volumes:
      - ./test_data:/workspace/data:ro
    networks:
      - omicshub_sandbox
    profiles:
      - dev

  # For testing sandbox in isolation
  sandbox_test:
    image: omicshub/sandbox-base:latest
    volumes:
      - ./test_data:/workspace/data:ro
      - ./test_output:/workspace/output:rw
    ports:
      - "8888:8888"  # Direct Jupyter access for testing
    networks:
      - omicshub_sandbox
    profiles:
      - test
```

### 9.3 Makefile Targets

```makefile
# Makefile additions for sandbox management

.PHONY: sandbox-build sandbox-push sandbox-test sandbox-clean

SANDBOX_REGISTRY ?= omicshub
SANDBOX_VERSION ?= latest

# Build all sandbox images
sandbox-build:
	@echo "Building sandbox images..."
	./scripts/build-sandbox-images.sh $(SANDBOX_VERSION)

# Push to registry
sandbox-push: sandbox-build
	@echo "Pushing sandbox images..."
	docker push $(SANDBOX_REGISTRY)/sandbox-base:$(SANDBOX_VERSION)

# Test sandbox container
sandbox-test:
	@echo "Testing sandbox container..."
	docker-compose --profile test up -d sandbox_test
	@echo "Jupyter available at http://localhost:8888"
	@echo "Run tests: pytest tests/integration/test_sandbox.py"

# Clean sandbox containers and temp files
sandbox-clean:
	@echo "Cleaning up sandbox resources..."
	# Remove all OmicHub sandbox containers
	-docker ps -aq --filter "name=omicshub-sandbox" | xargs docker rm -f 2>/dev/null
	# Remove orphaned volumes
	-docker volume prune -f
	# Clean temp directories
	-rm -rf /tmp/sandbox_*
	@echo "Cleanup complete"

# View sandbox logs
sandbox-logs:
	@docker logs -f $$(docker ps -q --filter "name=omicshub-sandbox" | head -1) 2>/dev/null || echo "No running sandbox containers"

# Check sandbox quota usage
sandbox-usage:
	@echo "Current sandbox usage:"
	@docker-compose exec db psql -U $$DB_USER -d omicshub -c "
		SELECT tier, 
		       active_sessions,
		       sessions_used_month,
		       cpu_hours_used_month,
		       memory_gb_hours_used
		FROM user_sandbox_quotas
		ORDER BY updated_at DESC
		LIMIT 10;
	"
```

---

## 10. Appendix: Decision Matrix & Risk Assessment

### 10.1 Key Decision Summary

| # | Decision | Options Considered | Chosen | Rationale |
|---|----------|-------------------|--------|-----------|
| 1 | Service architecture | Monolith / Copilot Service / Full Microservices | Monolith | Simpler ops, shared data domain, future extraction planned |
| 2 | Auth for sandbox containers | JWT passthrough / Session token / mTLS | Session token | Short-lived, scoped, no long-lived creds in containers |
| 3 | Container per session | One per user / One per project / One per session | One per session | Best isolation, simpler lifecycle |
| 4 | Data access control | App-layer filtering / Mount-time isolation | Mount-time isolation | OS-level guarantee, no traversal possible |
| 5 | Project switching | Container restart / Symlink swap / New container | Container restart | Clean, predictable, state can be preserved |
| 6 | Workflow execution | Only Mode A / Only Mode B / Both | Both (hybrid) | Mode A for experts, Mode B for Agent automation |
| 7 | MCP transport | stdio / SSE / HTTP | SSE | Fits existing FastAPI, supports async streaming |
| 8 | Sandbox image base | jupyter/datascience / rocker / custom | jupyter/datascience | Proven, well-maintained, JupyterLab included |

### 10.2 Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| Container escape | Low | Critical | Defense in depth: user namespaces, seccomp, AppArmor, read-only rootfs, capability dropping |
| Resource exhaustion (DoS) | Medium | High | Per-user quotas, cgroup limits, max concurrent sessions, auto-cleanup |
| Data leakage between users | Low | Critical | Per-user mounts, no shared container filesystem, mount namespace isolation |
| Malicious code execution | Medium | Medium | Network egress filtering, package allowlist, execution timeouts, audit logging |
| Session state loss | Medium | Low | Kernel state serialization (future), artifact persistence, usage logging |
| Database migration issues | Low | Medium | Reversible migrations, additive-only schema changes, rollback plan |
| Performance degradation | Medium | Medium | Celery for container creation async, horizontal scaling ready, monitoring |
| MCP server failure | Low | Medium | Graceful degradation (Mode A fallback), health checks, auto-restart |
| Large file handling | Medium | Medium | Lazy loading, memory-mapped access, streaming protocols |
| Docker socket exposure | Low | High | Read-only mount, access restricted to sandbox_orchestrator module |

### 10.3 Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Container creation time | < 10 seconds | From API request to ready state |
| Code execution latency | < 500ms | Simple `print("hello")` round-trip |
| WebSocket message throughput | > 1000 msg/sec | Streaming output capacity |
| Max concurrent sandboxes | 50 per node | With 4 CPU / 16GB per node |
| Session resume time | < 5 seconds | Re-login to active session |
| Project switch time | < 15 seconds | Container stop + start cycle |
| Image pull time | < 60 seconds | First-time deployment |

### 10.4 Monitoring & Alerting

```python
# Key metrics to track
MONITORING_METRICS = {
    "sandbox_container_creation_time": "Histogram",
    "sandbox_container_lifetime": "Histogram",
    "sandbox_active_sessions_total": "Gauge",
    "sandbox_sessions_created_total": "Counter",
    "sandbox_sessions_terminated_total": "Counter",  # with reason label
    "sandbox_code_execution_duration": "Histogram",
    "sandbox_code_execution_errors_total": "Counter",
    "sandbox_resource_usage_cpu": "Gauge",
    "sandbox_resource_usage_memory": "Gauge",
    "sandbox_quota_exceeded_total": "Counter",
    "sandbox_docker_api_latency": "Histogram",
    "sandbox_websocket_connections_active": "Gauge",
    "sandbox_websocket_message_rate": "Counter",
    "mcp_workflow_tasks_submitted_total": "Counter",
    "mcp_workflow_tasks_completed_total": "Counter",
    "mcp_workflow_tasks_failed_total": "Counter",
}

# Alert thresholds
ALERT_RULES = {
    "SandboxContainerStuck": {
        "condition": "sandbox_sessions{status='creating'} > 0 for > 5m",
        "severity": "warning",
        "action": "Check Docker daemon, possible resource exhaustion"
    },
    "SandboxQuotaExceeded": {
        "condition": "increase(sandbox_quota_exceeded_total[1h]) > 10",
        "severity": "info",
        "action": "Consider increasing quotas or investigate abuse"
    },
    "SandboxHighResourceUsage": {
        "condition": "sandbox_resource_usage_memory > 0.9",
        "severity": "warning",
        "action": "Scale up or review memory limits"
    },
    "DockerAPIErrors": {
        "condition": "increase(sandbox_docker_api_errors_total[5m]) > 5",
        "severity": "critical",
        "action": "Check Docker daemon health"
    }
}
```

---

## 11. Glossary

| Term | Definition |
|------|------------|
| **Sandbox** | An isolated Docker container where user code executes |
| **Session** | A single sandbox instance lifecycle (create → use → terminate) |
| **Copilot** | AI assistant that generates code and orchestrates workflows |
| **Agent** | The AI agent within Copilot that uses tools (MCP) |
| **Artifact** | A persisted output from sandbox (code, plot, notebook, etc.) |
| **MCP** | Model Context Protocol - standard for AI tool calling |
| **WorkflowMCP** | MCP server that exposes workflow execution tools |
| **Mode A** | Direct CLI execution of Snakemake/Nextflow in sandbox |
| **Mode B** | MCP-mediated task submission via existing Celery infrastructure |
| **Tier** | User permission level (guest/trial/standard/premium/admin) |
| **Quota** | Resource limits assigned to a user |
| **Session Token** | Short-lived one-time token for sandbox container authentication |
| **Mount Namespace** | Linux kernel feature isolating filesystem views per container |

---

*End of Integration Fusion Plan*

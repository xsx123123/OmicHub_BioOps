# 6. OmicsHub 部署运维手册

> **文档版本**: v1.0  
> **适用环境**: 华中农业大学园艺林学学院内网服务器（Linux + Docker）  
> **维护模式**: 单人生信维护，极简运维，一键部署  
> **技术栈**: FastAPI + PostgreSQL 14 + Redis 7 + Celery + Nginx + Snakemake

---

## 6.1 概述

OmicsHub 采用 Docker Compose 进行容器化部署，支持两种运行模式：

| 模式 | 适用场景 | 架构特点 |
|------|----------|----------|
| **local** | 单机部署，计算量适中 | Web应用与计算Worker在同一宿主机，共享Docker网络 |
| **remote** | 多机部署，计算密集型 | Web平台与Master计算节点分离，通过HTTP/WebSocket通信 |

**目录结构**:

```
omichub/
├── docker-compose.yml              # local模式主文件 / remote模式Web平台
├── docker-compose.master.yml       # remote模式Master计算节点
├── docker-compose.override.yml     # 本地开发覆盖（可选）
├── .env                            # 环境变量（不提交Git）
├── .env.example                    # 环境变量模板
├── init.sh                         # 一键初始化脚本
├── backend/
│   ├── Dockerfile                  # Web + Celery Worker镜像
│   ├── requirements.txt
│   ├── alembic/                    # 数据库迁移
│   └── app/                        # FastAPI应用
├── master/
│   ├── Dockerfile                  # Master节点独立镜像
│   ├── requirements.txt
│   └── app/                        # Master Executor Service
├── nginx/
│   ├── nginx.conf                  # Nginx主配置
│   └── ssl/                        # SSL证书（生产环境）
├── frontend/dist/                  # 前端构建产物
├── workflows/                      # Snakefile存放
│   ├── rna_seq/
│   ├── atac_seq/
│   └── scRNA_seq/
└── scripts/
    ├── backup.sh                   # 数据备份脚本
    └── health_check.sh             # 健康检查脚本
```

---

## 6.2 Local 模式 — docker-compose.yml（单机部署）

local模式适用于单台物理机部署，所有服务运行在同一Docker网络中。Celery Worker与Web应用复用同一镜像，直接通过`asyncio.subprocess`执行Snakemake任务。

```yaml
# =============================================================================
# OmicsHub Docker Compose - Local Mode
# 单机部署：Web + DB + Redis + Celery Worker/Beat + Flower + Nginx
# =============================================================================
version: "3.8"

x-backend-env: &backend-env
  # --- 执行模式 ---
  EXECUTION_MODE: local
  SNAKEMAKE_CORES: ${SNAKEMAKE_CORES:-8}
  CONDA_ENV_PATH: /opt/conda/envs

  # --- 数据库 ---
  DATABASE_URL: postgresql://${POSTGRES_USER:-omicshub}:${POSTGRES_PASSWORD:-changeme}@db:5432/${POSTGRES_DB:-omicshub}
  POSTGRES_USER: ${POSTGRES_USER:-omicshub}
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
  POSTGRES_DB: ${POSTGRES_DB:-omicshub}
  POSTGRES_HOST: db
  POSTGRES_PORT: 5432

  # --- Redis ---
  REDIS_URL: redis://:${REDIS_PASSWORD:-}@redis:6379/0
  REDIS_HOST: redis
  REDIS_PORT: 6379
  REDIS_PASSWORD: ${REDIS_PASSWORD:-}

  # --- Celery ---
  CELERY_BROKER_URL: redis://:${REDIS_PASSWORD:-}@redis:6379/0
  CELERY_RESULT_BACKEND: redis://:${REDIS_PASSWORD:-}@redis:6379/1

  # --- 安全密钥 ---
  SECRET_KEY: ${SECRET_KEY:-your-super-secret-jwt-key-change-in-production}
  INTERNAL_TOKEN: ${INTERNAL_TOKEN:-internal-token-change-me}

  # --- API密钥（可选）---
  KIMI_API_KEY: ${KIMI_API_KEY:-}
  OPENAI_API_KEY: ${OPENAI_API_KEY:-}

  # --- 存储路径 ---
  SHARED_STORAGE_PATH: /data
  WORKFLOW_PATH: /workflows

  # --- 应用配置 ---
  LOG_LEVEL: ${LOG_LEVEL:-INFO}
  MAX_UPLOAD_SIZE: ${MAX_UPLOAD_SIZE:-1073741824}
  ADMIN_EMAIL: ${ADMIN_EMAIL:-admin@example.com}
  ADMIN_PASSWORD: ${ADMIN_PASSWORD:-admin123}

x-backend-volumes: &backend-volumes
  - ${DATA_PATH:-/data/omicshub}:/data
  - ${WORKFLOW_PATH:-./workflows}:/workflows:ro
  - ${REFERENCE_PATH:-/data/omicshub/references}:/references:ro
  - ${CONDA_ENV_PATH:-/opt/conda/envs}:/opt/conda/envs
  - backend_logs:/app/logs

services:
  # =========================================================================
  # web: FastAPI主应用
  # =========================================================================
  web:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-web
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"  # 仅本地回环，通过Nginx代理
    volumes: *backend-volumes
    environment:
      <<: *backend-env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 256M

  # =========================================================================
  # db: PostgreSQL 14
  # =========================================================================
  db:
    image: postgres:14-alpine
    container_name: omicshub-db
    restart: unless-stopped
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-db.sh:/docker-entrypoint-initdb.d/init-db.sh:ro
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-omicshub}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
      POSTGRES_DB: ${POSTGRES_DB:-omicshub}
      PGDATA: /var/lib/postgresql/data/pgdata
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-omicshub} -d ${POSTGRES_DB:-omicshub}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
        reservations:
          cpus: '0.25'
          memory: 128M

  # =========================================================================
  # redis: Redis 7
  # =========================================================================
  redis:
    image: redis:7-alpine
    container_name: omicshub-redis
    restart: unless-stopped
    command: >
      sh -c 'redis-server 
      --appendonly yes 
      --appendfsync everysec 
      --maxmemory 512mb 
      --maxmemory-policy allkeys-lru 
      --requirepass "${REDIS_PASSWORD:-}"'
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M
        reservations:
          cpus: '0.1'
          memory: 64M

  # =========================================================================
  # celery_worker: Celery Worker（含Snakemake执行环境）
  # =========================================================================
  celery_worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-celery-worker
    restart: unless-stopped
    command: >
      celery -A app.celery_app worker
      -l ${LOG_LEVEL:-info}
      -Q snakemake,default
      -n worker-local@%h
      --concurrency 2
      --prefetch-multiplier 1
      -Ofair
    volumes: *backend-volumes
    environment:
      <<: *backend-env
      C_FORCE_ROOT: "true"  # 允许root运行Celery（容器内必需）
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "celery -A app.celery_app inspect ping --destination worker-local@$$HOSTNAME || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
      start_period: 30s
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: ${WORKER_CPU_LIMIT:-8.0}
          memory: ${WORKER_MEM_LIMIT:-16G}
        reservations:
          cpus: '1.0'
          memory: 1G
    # 本地模式下Worker承载Snakemake计算，资源限制根据实际硬件调整
    # 建议：Worker内存 >= 16G，CPU核心数 >= 8

  # =========================================================================
  # celery_beat: Celery Beat（定时任务调度）
  # =========================================================================
  celery_beat:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-celery-beat
    restart: unless-stopped
    command: >
      celery -A app.celery_app beat
      -l ${LOG_LEVEL:-info}
      --scheduler django_celery_beat.schedulers:DatabaseScheduler
      --max-interval 300
    volumes:
      - ${DATA_PATH:-/data/omicshub}:/data
      - backend_logs:/app/logs
    environment:
      <<: *backend-env
    depends_on:
      - db
      - redis
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M

  # =========================================================================
  # flower: Celery监控面板
  # =========================================================================
  flower:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-flower
    restart: unless-stopped
    command: >
      celery -A app.celery_app flower
      --port=5555
      --broker=redis://:${REDIS_PASSWORD:-}@redis:6379/0
      --basic-auth=${FLOWER_USER:-admin}:${FLOWER_PASSWORD:-flower123}
      --url-prefix=flower
    environment:
      <<: *backend-env
    depends_on:
      - redis
      - celery_worker
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M

  # =========================================================================
  # nginx: 反向代理
  # =========================================================================
  nginx:
    image: nginx:alpine
    container_name: omicshub-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./frontend/dist:/usr/share/nginx/html:ro
      - ${DATA_PATH:-/data/omicshub}:/data:ro  # 文件下载
      - ./nginx/ssl:/etc/nginx/ssl:ro  # SSL证书（可选）
    depends_on:
      - web
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost/api/v1/health"]
      interval: 30s
      timeout: 5s
      retries: 3
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M

# =============================================================================
# 数据卷定义
# =============================================================================
volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  backend_logs:
    driver: local

# =============================================================================
# 网络定义
# =============================================================================
networks:
  omicshub_net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
    internal: false
```

---

### 6.2.1 Local 模式环境变量完整列表

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `EXECUTION_MODE` | `local` | 执行模式：local 或 remote |
| `SNAKEMAKE_CORES` | `8` | Snakemake默认使用CPU核心数 |
| `CONDA_ENV_PATH` | `/opt/conda/envs` | Conda环境路径 |
| `POSTGRES_USER` | `omicshub` | PostgreSQL用户名 |
| `POSTGRES_PASSWORD` | `changeme` | PostgreSQL密码（**生产环境必须修改**） |
| `POSTGRES_DB` | `omicshub` | PostgreSQL数据库名 |
| `REDIS_PASSWORD` | `` | Redis密码（建议设置） |
| `SECRET_KEY` | `your-super-secret-jwt-key` | JWT签名密钥（**生产环境必须修改**） |
| `INTERNAL_TOKEN` | `internal-token` | Master回调认证令牌（remote模式必需） |
| `KIMI_API_KEY` | `` | Kimi AI API密钥（可选） |
| `OPENAI_API_KEY` | `` | OpenAI API密钥（可选） |
| `DATA_PATH` | `/data/omicshub` | 数据持久化路径（宿主机） |
| `WORKFLOW_PATH` | `./workflows` | Snakefile存放路径（宿主机） |
| `REFERENCE_PATH` | `/data/omicshub/references` | 参考基因组路径（宿主机） |
| `LOG_LEVEL` | `INFO` | 日志级别：DEBUG/INFO/WARNING/ERROR |
| `MAX_UPLOAD_SIZE` | `1073741824` | 最大上传文件大小（字节，默认1GB） |
| `ADMIN_EMAIL` | `admin@example.com` | 默认管理员邮箱 |
| `ADMIN_PASSWORD` | `admin123` | 默认管理员密码（**首次登录后必须修改**） |
| `FLOWER_USER` | `admin` | Flower监控面板用户名 |
| `FLOWER_PASSWORD` | `flower123` | Flower监控面板密码 |
| `WORKER_CPU_LIMIT` | `8.0` | Celery Worker CPU限制 |
| `WORKER_MEM_LIMIT` | `16G` | Celery Worker内存限制 |

---

### 6.2.2 Local 模式卷挂载规划

| 挂载点 | 说明 | 权限 |
|--------|------|------|
| `${DATA_PATH}:/data` | 任务数据、上传文件、结果持久化 | 读写 |
| `${WORKFLOW_PATH}:/workflows` | Snakefile存放（只读挂载） | 只读 |
| `${REFERENCE_PATH}:/references` | 参考基因组、索引文件（只读） | 只读 |
| `${CONDA_ENV_PATH}:/opt/conda/envs` | Conda环境复用（宿主机预装） | 只读 |
| `backend_logs:/app/logs` | 应用日志持久化 | 读写 |

**目录权限要求**：
- `/data` 目录需要 `1000:1000` (UID:GID) 权限，对应容器内非root用户
- Conda环境目录需要对容器用户可读

---

## 6.3 Remote 模式 — 分离部署

remote模式适用于**Web平台**与**计算节点**分离部署的场景。Web平台负责API请求和业务逻辑，Master节点专用于执行Snakemake计算任务。

### 6.3.1 docker-compose.yml（Web平台）

```yaml
# =============================================================================
# OmicsHub Docker Compose - Remote Mode: Web Platform
# Web平台：API + DB + Redis + 轻量Worker + Beat + Flower + Nginx
# =============================================================================
version: "3.8"

x-backend-env: &backend-env
  EXECUTION_MODE: remote
  MASTER_API_URL: ${MASTER_API_URL:-http://master:8001}
  MASTER_INTERNAL_TOKEN: ${MASTER_INTERNAL_TOKEN:-master-token-change-me}

  # --- 数据库（同local模式）---
  DATABASE_URL: postgresql://${POSTGRES_USER:-omicshub}:${POSTGRES_PASSWORD:-changeme}@db:5432/${POSTGRES_DB:-omicshub}
  POSTGRES_USER: ${POSTGRES_USER:-omicshub}
  POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
  POSTGRES_DB: ${POSTGRES_DB:-omicshub}
  POSTGRES_HOST: db
  POSTGRES_PORT: 5432

  # --- Redis（同local模式）---
  REDIS_URL: redis://:${REDIS_PASSWORD:-}@redis:6379/0
  REDIS_HOST: redis
  REDIS_PORT: 6379
  REDIS_PASSWORD: ${REDIS_PASSWORD:-}

  # --- Celery ---
  CELERY_BROKER_URL: redis://:${REDIS_PASSWORD:-}@redis:6379/0
  CELERY_RESULT_BACKEND: redis://:${REDIS_PASSWORD:-}@redis:6379/1

  # --- 安全密钥 ---
  SECRET_KEY: ${SECRET_KEY:-your-super-secret-jwt-key-change-in-production}
  INTERNAL_TOKEN: ${INTERNAL_TOKEN:-internal-token-change-me}

  # --- API密钥 ---
  KIMI_API_KEY: ${KIMI_API_KEY:-}
  OPENAI_API_KEY: ${OPENAI_API_KEY:-}

  # --- 存储 ---
  SHARED_STORAGE_PATH: /data
  WORKFLOW_PATH: /workflows

  # --- 应用配置 ---
  LOG_LEVEL: ${LOG_LEVEL:-INFO}
  MAX_UPLOAD_SIZE: ${MAX_UPLOAD_SIZE:-1073741824}
  ADMIN_EMAIL: ${ADMIN_EMAIL:-admin@example.com}
  ADMIN_PASSWORD: ${ADMIN_PASSWORD:-admin123}

x-backend-volumes: &backend-volumes
  - ${DATA_PATH:-/data/omicshub}:/data
  - ${WORKFLOW_PATH:-./workflows}:/workflows:ro
  - ${NFS_MOUNT_PATH:-/data/omicshub}:/data  # NFS共享存储挂载点
  - backend_logs:/app/logs

services:
  web:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-web
    restart: unless-stopped
    ports:
      - "127.0.0.1:8000:8000"
    volumes: *backend-volumes
    environment:
      <<: *backend-env
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/v1/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G

  db:
    image: postgres:14-alpine
    container_name: omicshub-db
    restart: unless-stopped
    volumes:
      - postgres_data:/var/lib/postgresql/data
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-omicshub}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}
      POSTGRES_DB: ${POSTGRES_DB:-omicshub}
      PGDATA: /var/lib/postgresql/data/pgdata
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-omicshub} -d ${POSTGRES_DB:-omicshub}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G

  redis:
    image: redis:7-alpine
    container_name: omicshub-redis
    restart: unless-stopped
    command: >
      sh -c 'redis-server
      --appendonly yes
      --appendfsync everysec
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
      --requirepass "${REDIS_PASSWORD:-}"'
    volumes:
      - redis_data:/data
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '1.0'
          memory: 512M

  # =========================================================================
  # celery_worker: 轻量Worker（仅处理非Snakemake任务）
  # =========================================================================
  celery_worker:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-celery-worker
    restart: unless-stopped
    command: >
      celery -A app.celery_app worker
      -l ${LOG_LEVEL:-info}
      -Q default,notifications,email
      -n worker-web@%h
      --concurrency 4
      -Ofair
    volumes:
      - ${DATA_PATH:-/data/omicshub}:/data
      - backend_logs:/app/logs
    environment:
      <<: *backend-env
      C_FORCE_ROOT: "true"
    depends_on:
      - db
      - redis
    healthcheck:
      test: ["CMD-SHELL", "celery -A app.celery_app inspect ping --destination worker-web@$$HOSTNAME || exit 1"]
      interval: 60s
      timeout: 10s
      retries: 3
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '2.0'
          memory: 2G
    # 注意：remote模式下Worker不执行Snakemake，仅处理轻量任务

  celery_beat:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-celery-beat
    restart: unless-stopped
    command: >
      celery -A app.celery_app beat
      -l ${LOG_LEVEL:-info}
      --scheduler django_celery_beat.schedulers:DatabaseScheduler
    volumes:
      - ${DATA_PATH:-/data/omicshub}:/data
      - backend_logs:/app/logs
    environment:
      <<: *backend-env
    depends_on:
      - db
      - redis
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M

  flower:
    build:
      context: ./backend
      dockerfile: Dockerfile
    container_name: omicshub-flower
    restart: unless-stopped
    command: >
      celery -A app.celery_app flower
      --port=5555
      --broker=redis://:${REDIS_PASSWORD:-}@redis:6379/0
      --basic-auth=${FLOWER_USER:-admin}:${FLOWER_PASSWORD:-flower123}
      --url-prefix=flower
    environment:
      <<: *backend-env
    depends_on:
      - redis
      - celery_worker
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 256M

  nginx:
    image: nginx:alpine
    container_name: omicshub-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./frontend/dist:/usr/share/nginx/html:ro
      - ${NFS_MOUNT_PATH:-/data/omicshub}:/data:ro
      - ./nginx/ssl:/etc/nginx/ssl:ro
    depends_on:
      - web
    networks:
      - omicshub_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M

volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local
  backend_logs:
    driver: local

networks:
  omicshub_net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.20.0.0/16
```

---

### 6.3.2 docker-compose.master.yml（Master计算节点）

```yaml
# =============================================================================
# OmicsHub Docker Compose - Remote Mode: Master Compute Node
# Master节点：专用于执行Snakemake计算任务
# 不暴露公网，仅内网Web平台访问
# =============================================================================
version: "3.8"

services:
  # =========================================================================
  # master: FastAPI Executor Service
  # =========================================================================
  master:
    build:
      context: ./master
      dockerfile: Dockerfile
    container_name: omicshub-master
    restart: unless-stopped
    ports:
      # 仅暴露给内网Web平台，不绑定0.0.0.0
      - "127.0.0.1:8001:8001"
    volumes:
      # 共享存储：与Web平台使用相同的NFS/Docker Volume
      - ${DATA_PATH:-/data/omicshub}:/data
      - ${WORKFLOW_PATH:-./workflows}:/workflows:ro
      - ${REFERENCE_PATH:-/data/omicshub/references}:/references:ro
      - ${CONDA_ENV_PATH:-/opt/conda/envs}:/opt/conda/envs
      - master_logs:/app/logs
    environment:
      # --- Master服务配置 ---
      MASTER_HOST: 0.0.0.0
      MASTER_PORT: 8001

      # --- 回调配置 ---
      CALLBACK_URL: ${CALLBACK_URL:-http://web:8000/internal/callback/task-complete}
      WEBSOCKET_URL: ${WEBSOCKET_URL:-ws://web:8000/internal/ws/task-log}
      INTERNAL_TOKEN: ${INTERNAL_TOKEN:-internal-token-change-me}

      # --- 存储路径 ---
      SHARED_STORAGE_PATH: /data
      WORKFLOW_PATH: /workflows

      # --- Snakemake配置 ---
      SNAKEMAKE_CORES: ${SNAKEMAKE_CORES:-16}
      CONDA_ENV_PATH: /opt/conda/envs
      MAX_CONCURRENT_JOBS: ${MAX_CONCURRENT_JOBS:-4}

      # --- 日志 ---
      LOG_LEVEL: ${LOG_LEVEL:-INFO}

      # --- CORS（仅允许Web平台域名）---
      ALLOWED_ORIGINS: ${ALLOWED_ORIGINS:-http://localhost,http://web:8000}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 20s
    networks:
      - omicshub_master_net
    deploy:
      resources:
        limits:
          cpus: ${MASTER_CPU_LIMIT:-16.0}
          memory: ${MASTER_MEM_LIMIT:-64G}
        reservations:
          cpus: '4.0'
          memory: 8G
    # Master节点承载所有Snakemake计算，资源配置应充足
    # 建议：CPU >= 16核，内存 >= 64G，存储 >= 1TB SSD

  # =========================================================================
  # master_exporter: 节点资源监控（可选，Prometheus node_exporter）
  # =========================================================================
  node_exporter:
    image: prom/node-exporter:latest
    container_name: omicshub-master-exporter
    restart: unless-stopped
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.rootfs=/rootfs'
      - '--path.sysfs=/host/sys'
      - '--collector.filesystem.mount-points-exclude=^/(sys|proc|dev|host|etc)($$|/)'
    ports:
      - "127.0.0.1:9100:9100"
    networks:
      - omicshub_master_net
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M

volumes:
  master_logs:
    driver: local

networks:
  omicshub_master_net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.21.0.0/16
    # 该网络仅内网使用，可与Web平台的omicshub_net通过docker network connect互联
    # 或通过宿主机的docker0网桥访问
```

---

### 6.3.3 Remote 模式网络互联方案

**方案一：Docker Network Connect（推荐，同机房）**

```bash
# 1. 在Web平台服务器创建共享网络
docker network create --driver bridge --subnet 172.30.0.0/16 omicshub_shared

# 2. Web平台加入共享网络
docker network connect omicshub_shared omicshub-web

# 3. Master节点加入共享网络
docker network connect omicshub_shared omicshub-master

# 4. 更新环境变量，使用共享网络通信
# MASTER_API_URL=http://omicshub-master:8001
```

**方案二：宿主机IP直连**

```bash
# Web平台通过Master宿主机IP访问
# MASTER_API_URL=http://<master_host_ip>:8001

# 需要在Master节点暴露端口到宿主机
docker-compose -f docker-compose.master.yml up -d
```

**方案三：Overlay网络（多Docker Host）**

```bash
# 创建Docker Swarm overlay网络（需初始化Swarm）
docker swarm init
docker network create --driver overlay --attachable omicshub_overlay

# 两个stack使用同一overlay网络
docker stack deploy -c docker-compose.yml omicshub-web
docker stack deploy -c docker-compose.master.yml omicshub-master
```

**Master节点启动命令**：

```bash
#!/bin/bash
# start_master.sh - Master节点启动脚本

set -e

echo "=== OmicsHub Master Node Startup ==="

# 检查环境变量
if [ -z "$INTERNAL_TOKEN" ]; then
    echo "ERROR: INTERNAL_TOKEN environment variable is required"
    exit 1
fi

# 创建必要目录
mkdir -p /data/omicshub/tasks /data/omicshub/uploads /data/omicshub/logs
chmod 755 /data/omicshub

# 拉取最新镜像
docker-compose -f docker-compose.master.yml pull

# 启动服务
docker-compose -f docker-compose.master.yml up -d

# 等待服务就绪
echo "Waiting for Master service to be ready..."
sleep 5

# 健康检查
for i in {1..30}; do
    if curl -sf http://localhost:8001/health > /dev/null 2>&1; then
        echo "Master node is healthy!"
        docker-compose -f docker-compose.master.yml ps
        exit 0
    fi
    echo "Health check attempt $i/30..."
    sleep 2
done

echo "ERROR: Master node failed health check"
docker-compose -f docker-compose.master.yml logs master
exit 1
```

---

## 6.4 共享存储设计

### 6.4.1 方案对比

| 方案 | 适用场景 | 优点 | 缺点 |
|------|----------|------|------|
| **Docker Volume（本地）** | 单机部署 | 简单、性能好、无需额外配置 | 无法跨主机共享 |
| **NFS** | 多机同机房 | 成熟、简单挂载 | 性能一般、单点故障 |
| **Ceph/GlusterFS** | 多机大规模 | 高可用、可扩展 | 运维复杂、需专业知识 |

**推荐**：单机用Docker Volume，多机用NFS。

### 6.4.2 NFS共享存储方案

```bash
# =============================================================================
# NFS服务器配置（存储服务器或Master节点）
# =============================================================================

# 1. 安装NFS服务器
sudo apt-get update
sudo apt-get install -y nfs-kernel-server

# 2. 创建共享目录
sudo mkdir -p /data/omicshub
sudo chown -R 1000:1000 /data/omicshub
sudo chmod 755 /data/omicshub

# 3. 配置NFS导出
# /etc/exports
cat << 'EOF' | sudo tee /etc/exports
# OmicsHub 共享存储
/data/omicshub  172.20.0.0/16(rw,sync,no_subtree_check,no_root_squash)
/data/omicshub  172.21.0.0/16(rw,sync,no_subtree_check,no_root_squash)
EOF

# 4. 启动NFS服务
sudo exportfs -ra
sudo systemctl restart nfs-kernel-server
sudo systemctl enable nfs-kernel-server

# 5. 客户端挂载（Web平台服务器）
sudo apt-get install -y nfs-common
sudo mkdir -p /data/omicshub
sudo mount -t nfs <nfs_server_ip>:/data/omicshub /data/omicshub

# 6. 开机自动挂载（/etc/fstab）
echo "<nfs_server_ip>:/data/omicshub /data/omicshub nfs defaults,_netdev 0 0" | sudo tee -a /etc/fstab

# 7. Docker中使用NFS Volume
docker volume create --driver local \
  --opt type=nfs \
  --opt o=addr=<nfs_server_ip>,rw,nfsvers=4 \
  --opt device=:/data/omicshub \
  omicshub_nfs_data
```

### 6.4.3 目录结构规范

```
/data/omicshub/                          # 根目录
├── docker-compose.yml -> /opt/omicshub/ # 软链接到实际部署位置
├── .env                                 # 环境变量
│
├── tasks/                               # 任务执行目录
│   └── {task_id}/                       # 每个任务独立目录（UUID格式）
│       ├── config.yaml                  # Snakemake任务配置
│       ├── samples.csv                  # 样本信息表
│       ├── metadata.json                # 任务元数据（Web平台写入）
│       ├── snakemake.log                # 实时执行日志
│       ├── stderr.log                   # 标准错误输出
│       ├── stdout.log                   # 标准输出
│       ├── progress.json                # 进度追踪（实时更新）
│       ├── status.json                  # 状态文件（pending/running/completed/failed）
│       └── results/                     # 结果目录
│           ├── output_files/            # 输出文件
│           ├── reports/                 # 报告文件
│           ├── plots/                   # 图表
│           └── summary.json             # 结果摘要
│
├── uploads/                             # 用户上传文件
│   └── {user_id}/                       # 按用户ID隔离
│       ├── raw_data/                    # 原始数据
│       ├── samples/                     # 样本文件
│       └── temp/                        # 临时文件
│
├── workflows/                           # Snakefile存放（版本控制）
│   ├── rna_seq/
│   │   ├── Snakefile                    # 主工作流
│   │   ├── config_template.yaml         # 配置模板
│   │   ├── schema.json                  # 参数校验模式
│   │   ├── envs/                        # Conda环境定义
│   │   │   └── rna_seq.yaml
│   │   ├── scripts/                     # 辅助脚本
│   │   └── README.md
│   ├── atac_seq/
│   │   ├── Snakefile
│   │   └── ...
│   └── scRNA_seq/
│       ├── Snakefile
│       └── ...
│
├── references/                          # 参考基因组和索引
│   ├── hg38/
│   │   ├── genome.fa
│   │   ├── genome.fa.fai
│   │   ├── gtf/
│   │   │   └── genes.gtf
│   │   └── indexes/
│   │       ├── star/
│   │       ├── bwa/
│   │       └── salmon/
│   ├── mm10/
│   │   └── ...
│   └── annotation/
│       └── gene_annotations.json
│
├── conda_envs/                          # Conda环境（预装）
│   ├── rna_seq/                         # 每个流程独立环境
│   │   └── ...                          # 避免依赖冲突
│   ├── atac_seq/
│   └── scRNA_seq/
│
├── logs/                                # 应用日志
│   ├── web/
│   ├── celery/
│   ├── nginx/
│   └── master/
│
├── backups/                             # 自动备份
│   └── {date}/
│       ├── db_backup.sql.gz
│       └── data_backup.tar.gz
│
└── tmp/                                 # 临时目录
    └── cleanup_daily.sh                 # 每日清理脚本
```

### 6.4.4 目录初始化与权限设置

```bash
#!/bin/bash
# init_storage.sh - 共享存储初始化脚本

DATA_ROOT="${1:-/data/omicshub}"
USER_ID="${2:-1000}"  # 容器内运行用户的UID
GROUP_ID="${3:-1000}" # 容器内运行用户的GID

echo "=== Initializing OmicsHub Storage ==="
echo "Data root: $DATA_ROOT"
echo "Owner: $USER_ID:$GROUP_ID"

# 创建目录结构
mkdir -p "$DATA_ROOT"/{tasks,uploads,workflows,references,conda_envs,logs/{web,celery,nginx,master},backups,tmp}

# 设置权限
chown -R "$USER_ID:$GROUP_ID" "$DATA_ROOT"
chmod -R u+rwx "$DATA_ROOT"
chmod -R g+rx "$DATA_ROOT"

# tasks目录需要所有用户可写（多容器写入）
chmod 777 "$DATA_ROOT/tasks"

# uploads目录按用户隔离，应用层控制权限
chmod 755 "$DATA_ROOT/uploads"

# workflows和references只读
chmod -R 755 "$DATA_ROOT/workflows"
chmod -R 755 "$DATA_ROOT/references"
chmod -R 755 "$DATA_ROOT/conda_envs"

# logs目录可写
chmod -R 755 "$DATA_ROOT/logs"

echo "=== Storage initialization complete ==="
echo "Directory structure:"
find "$DATA_ROOT" -maxdepth 2 -type d | head -30
```

---

## 6.5 Nginx 配置

### 6.5.1 nginx.conf 完整配置

```nginx
# =============================================================================
# OmicsHub Nginx Configuration
# 功能：静态文件服务、API反向代理、WebSocket支持、Flower监控、安全防护
# =============================================================================

user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
    use epoll;
    multi_accept on;
}

http {
    include /etc/nginx/mime.types;
    default_type application/octet-stream;

    # --- 日志格式 ---
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for" '
                    'rt=$request_time uct=$upstream_connect_time '
                    'uht=$upstream_header_time urt=$upstream_response_time';

    access_log /var/log/nginx/access.log main;

    # --- 性能优化 ---
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    client_max_body_size 2G;  # 最大上传文件大小
    client_body_buffer_size 16K;
    client_header_buffer_size 1K;
    large_client_header_buffers 4 8K;

    # --- Gzip压缩 ---
    gzip on;
    gzip_vary on;
    gzip_proxied any;
    gzip_comp_level 6;
    gzip_types text/plain text/css text/xml application/json
               application/javascript application/rss+xml
               application/atom+xml image/svg+xml;

    # --- 上游服务器定义 ---
    upstream web_backend {
        server web:8000 max_fails=3 fail_timeout=30s;
        keepalive 32;
    }

    upstream flower_backend {
        server flower:5555 max_fails=3 fail_timeout=30s;
    }

    # --- 限速配置（防止大文件下载占用全部带宽） ---
    limit_conn_zone $binary_remote_addr zone=addr:10m;
    limit_rate_after 10m;
    limit_rate 5m;

    # =================================================================
    # HTTP Server (80端口，重定向到HTTPS或反向代理)
    # =================================================================
    server {
        listen 80;
        server_name _;  # 接受任意域名

        # 如果配置了SSL，重定向到HTTPS
        # return 301 https://$host$request_uri;

        # 未配置SSL时直接服务
        include /etc/nginx/conf.d/omicshub.conf;
    }

    # =================================================================
    # HTTPS Server (443端口，生产环境启用)
    # =================================================================
    # server {
    #     listen 443 ssl http2;
    #     server_name omicshub.example.com;
    #
    #     ssl_certificate /etc/nginx/ssl/omicshub.crt;
    #     ssl_certificate_key /etc/nginx/ssl/omicshub.key;
    #     ssl_protocols TLSv1.2 TLSv1.3;
    #     ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';
    #     ssl_prefer_server_ciphers on;
    #
    #     include /etc/nginx/conf.d/omicshub.conf;
    # }
}
```

### 6.5.2 omicshub.conf（站点配置）

```nginx
# =============================================================================
# OmicsHub 站点配置 - 包含在 server 块中
# =============================================================================

# --- 静态文件服务（前端dist） ---
location / {
    root /usr/share/nginx/html;
    index index.html index.htm;
    try_files $uri $uri/ /index.html;  # SPA路由支持

    # 静态文件缓存
    location ~* \.(js|css|png|jpg|jpeg|gif|ico|svg|woff|woff2|ttf|eot)$ {
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    # HTML文件不缓存
    location ~* \.html$ {
        add_header Cache-Control "no-cache, no-store, must-revalidate";
        add_header Pragma "no-cache";
        expires 0;
    }
}

# --- API代理到Web后端 ---
location /api/ {
    proxy_pass http://web_backend;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_connect_timeout 60s;
    proxy_send_timeout 60s;
    proxy_read_timeout 60s;
}

# --- WebSocket升级支持（实时日志推送） ---
location /ws/ {
    proxy_pass http://web_backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_connect_timeout 60s;
    proxy_send_timeout 3600s;  # WebSocket长连接
    proxy_read_timeout 3600s;
}

# --- Flower监控面板 ---
location /flower/ {
    proxy_pass http://flower_backend/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Script-Name /flower;
    proxy_redirect off;

    # IP白名单限制（仅允许内网访问Flower）
    # allow 10.0.0.0/8;
    # allow 172.16.0.0/12;
    # allow 192.168.0.0/16;
    # allow 127.0.0.1;
    # deny all;

    # 基本认证（双重保护）
    # auth_basic "Flower Monitoring";
    # auth_basic_user_file /etc/nginx/.htpasswd;
}

# --- 内部回调接口（严格IP白名单限制） ---
location /internal/ {
    # 仅允许Docker网络内部和Master节点IP访问
    allow 172.20.0.0/16;   # omicshub_web 网络
    allow 172.21.0.0/16;   # omicshub_master 网络
    allow 127.0.0.1;
    deny all;              # 拒绝其他所有IP

    proxy_pass http://web_backend;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_connect_timeout 30s;
    proxy_send_timeout 30s;
    proxy_read_timeout 30s;

    # 记录内部访问日志（安全审计）
    access_log /var/log/nginx/internal_access.log main;
}

# --- 文件下载服务 ---
location /downloads/ {
    alias /data/;  # 对应宿主机 DATA_PATH
    autoindex off;

    # 限速
    limit_conn addr 5;
    limit_rate 10m;

    # 仅允许已认证用户（通过X-Download-Token验证）
    proxy_pass http://web_backend;
    proxy_set_header X-Download-Path $request_uri;
}

# --- 任务结果文件直接访问（带Token验证） ---
location /results/ {
    alias /data/tasks/;
    autoindex off;

    # 文件下载限速
    limit_conn addr 3;
    limit_rate 5m;

    # 安全头
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;
}

# --- 健康检查端点（负载均衡器使用） ---
location /health {
    proxy_pass http://web_backend/api/v1/health;
    proxy_connect_timeout 5s;
    proxy_read_timeout 5s;
    access_log off;  # 不记录健康检查日志
}

# --- 安全头配置 ---
add_header X-Content-Type-Options nosniff always;
add_header X-Frame-Options SAMEORIGIN always;
add_header X-XSS-Protection "1; mode=block" always;
add_header Referrer-Policy strict-origin-when-cross-origin always;
# add_header Content-Security-Policy "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline';" always;

# --- 禁止访问敏感文件 ---
location ~ /\. {
    deny all;
    access_log off;
    log_not_found off;
}

location ~* \.(env|git|gitignore|ini|log|sh|sql)$ {
    deny all;
    access_log off;
    log_not_found off;
}

# --- 错误页面 ---
error_page 500 502 503 504 /50x.html;
location = /50x.html {
    root /usr/share/nginx/html;
    internal;
}
```

---

## 6.6 Dockerfile 设计

### 6.6.1 Backend Dockerfile（Web + Celery Worker）

```dockerfile
# =============================================================================
# OmicsHub Backend Dockerfile
# 多阶段构建：构建阶段 + 运行阶段
# 包含：Python 3.11 + FastAPI + Celery + Snakemake + Miniforge(Conda)
# =============================================================================

# -----------------------------------------------------------------------------
# Stage 1: 构建阶段
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS builder

# 构建依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 创建虚拟环境
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# 安装Python依赖
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# -----------------------------------------------------------------------------
# Stage 2: 运行阶段
# -----------------------------------------------------------------------------
FROM python:3.11-slim AS runtime

LABEL maintainer="OmicsHub Team" \
      description="OmicsHub Backend - FastAPI + Celery + Snakemake"

# --- 系统依赖 ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    # 数据库
    libpq5 \
    # 网络工具（健康检查等）
    curl wget \
    # 文件处理
    unzip gzip tar \
    # 版本控制（Snakemake可能用到）
    git \
    # 通用工具
    procps \
    && rm -rf /var/lib/apt/lists/*

# --- 创建非root用户 ---
RUN groupadd -r -g 1000 omicshub && \
    useradd -r -u 1000 -g omicshub -d /app -s /bin/bash omicshub

# --- 复制虚拟环境 ---
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# --- 安装Miniforge（Conda）---
ENV CONDA_DIR=/opt/conda
ENV PATH="$CONDA_DIR/bin:$PATH"

RUN wget --quiet https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O /tmp/miniforge.sh && \
    bash /tmp/miniforge.sh -b -p $CONDA_DIR && \
    rm /tmp/miniforge.sh && \
    conda clean -afy && \
    echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /etc/bash.bashrc

# --- 安装Snakemake（在基础环境中）---
RUN pip install --no-cache-dir snakemake==7.32.4

# --- 创建工作目录 ---
WORKDIR /app
RUN chown -R omicshub:omicshub /app

# --- 复制应用代码 ---
COPY --chown=omicshub:omicshub ./app ./app
COPY --chown=omicshub:omicshub ./alembic ./alembic
COPY --chown=omicshub:omicshub alembic.ini .

# --- 创建日志目录 ---
RUN mkdir -p /app/logs && chown -R omicshub:omicshub /app/logs

# --- 健康检查 ---
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# --- 暴露端口 ---
EXPOSE 8000

# --- 切换到非root用户 ---
USER omicshub

# --- 启动命令 ---
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
```

### 6.6.2 Master Dockerfile（计算节点）

```dockerfile
# =============================================================================
# OmicsHub Master Node Dockerfile
# 专用于执行Snakemake计算任务
# 需要更多系统工具和生物信息学依赖
# =============================================================================

FROM python:3.11-slim

LABEL maintainer="OmicsHub Team" \
      description="OmicsHub Master Executor - Snakemake Compute Node"

# --- 系统依赖（生物信息学工具链） ---
RUN apt-get update && apt-get install -y --no-install-recommends \
    # 基础构建工具
    build-essential \
    gcc \
    g++ \
    make \
    cmake \
    # 数据库客户端
    libpq-dev \
    # 压缩工具
    pigz \
    pbzip2 \
    lbzip2 \
    xz-utils \
    zlib1g-dev \
    libbz2-dev \
    liblzma-dev \
    # 网络工具
    curl wget \
    # 文件处理
    unzip \
    # 版本控制
    git \
    # 进程管理
    procps \
    psmisc \
    # 存储工具（NFS客户端）
    nfs-common \
    # 监控工具
    htop \
    # 其他常用
    jq \
    && rm -rf /var/lib/apt/lists/*

# --- 创建非root用户 ---
RUN groupadd -r -g 1000 omicshub && \
    useradd -r -u 1000 -g omicshub -d /app -s /bin/bash omicshub

# --- 安装Miniforge（Conda）---
ENV CONDA_DIR=/opt/conda
ENV PATH="$CONDA_DIR/bin:$PATH"

RUN wget --quiet https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh -O /tmp/miniforge.sh && \
    bash /tmp/miniforge.sh -b -p $CONDA_DIR && \
    rm /tmp/miniforge.sh && \
    conda clean -afy && \
    echo ". $CONDA_DIR/etc/profile.d/conda.sh" >> /etc/bash.bashrc

# --- 安装Snakemake ---
RUN pip install --no-cache-dir \
    snakemake==7.32.4 \
    httpx==0.27.0 \
    websockets==12.0

# --- 安装Python依赖 ---
COPY requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt && rm /tmp/requirements.txt

# --- 创建工作目录 ---
WORKDIR /app
RUN chown -R omicshub:omicshub /app

# --- 复制Master应用代码 ---
COPY --chown=omicshub:omicshub ./app ./app
COPY --chown=omicshub:omicshub ./scripts ./scripts

# --- 创建日志和临时目录 ---
RUN mkdir -p /app/logs /tmp/snakemake && \
    chown -R omicshub:omicshub /app/logs /tmp/snakemake

# --- 数据卷挂载点 ---
VOLUME ["/data", "/workflows", "/references", "/opt/conda/envs"]

# --- 健康检查 ---
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8001/health || exit 1

# --- 暴露端口 ---
EXPOSE 8001

# --- 切换到非root用户 ---
USER omicshub

# --- 启动命令 ---
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "1"]
```

### 6.6.3 requirements.txt

```txt
# =============================================================================
# OmicsHub Python Dependencies
# =============================================================================

# --- Web Framework ---
fastapi==0.111.0
uvicorn[standard]==0.30.0
python-multipart==0.0.9

# --- Database ---
asyncpg==0.29.0
alembic==1.13.0
sqlalchemy[asyncio]==2.0.30

# --- Redis & Celery ---
redis==5.0.0
celery==5.4.0
django-celery-beat==2.7.0

# --- Authentication ---
python-jose[cryptography]==3.3.0
passlib[bcrypt]==1.7.4
python-dotenv==1.0.0

# --- HTTP Client ---
httpx==0.27.0
aiohttp==3.9.0

# --- Validation ---
pydantic==2.7.0
pydantic-settings==2.2.0
email-validator==2.1.0

# --- Utils ---
pyyaml==6.0.1
python-dateutil==2.9.0
shortuuid==1.0.13
aiofiles==23.2.0

# --- WebSocket ---
websockets==12.0

# --- Monitoring ---
prometheus-client==0.20.0

# --- Testing (dev only) ---
pytest==8.2.0
pytest-asyncio==0.23.0
httpx==0.27.0
```

---

## 6.7 初始化脚本设计

### 6.7.1 init.sh（一键初始化）

```bash
#!/bin/bash
# =============================================================================
# OmicsHub 一键初始化脚本
# 功能：目录创建、权限设置、数据库迁移、管理员创建、流程导入
# 用法: ./init.sh [--skip-migration] [--reset-db]
# =============================================================================

set -euo pipefail

# --- 颜色定义 ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# --- 日志函数 ---
log_info()  { echo -e "${GREEN}[INFO]${NC}  $1"; }
log_warn()  { echo -e "${YELLOW}[WARN]${NC}  $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }
log_step()  { echo -e "\n${BLUE}=== $1 ===${NC}"; }

# --- 配置 ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_PATH="${DATA_PATH:-/data/omicshub}"
COMPOSE_FILE="${SCRIPT_DIR}/docker-compose.yml"
ENV_FILE="${SCRIPT_DIR}/.env"
SKIP_MIGRATION=false
RESET_DB=false

# --- 参数解析 ---
while [[ $# -gt 0 ]]; do
    case $1 in
        --skip-migration) SKIP_MIGRATION=true; shift ;;
        --reset-db)       RESET_DB=true; shift ;;
        --data-path)      DATA_PATH="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [OPTIONS]"
            echo "Options:"
            echo "  --skip-migration   Skip database migration"
            echo "  --reset-db         Reset database (WARNING: destroys all data)"
            echo "  --data-path PATH   Set data directory path (default: /data/omicshub)"
            exit 0
            ;;
        *) echo "Unknown option: $1"; exit 1 ;;
    esac
done

# --- 前置检查 ---
log_step "Step 1: Environment Checks"

# 检查Docker
docker info > /dev/null 2>&1 || {
    log_error "Docker is not running or not installed"
    exit 1
}
log_info "Docker is running"

# 检查Docker Compose
if docker compose version > /dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif docker-compose version > /dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    log_error "Docker Compose is not installed"
    exit 1
fi
log_info "Docker Compose found: $COMPOSE_CMD"

# 检查.env文件
if [ ! -f "$ENV_FILE" ]; then
    if [ -f "${ENV_FILE}.example" ]; then
        log_warn ".env not found, copying from .env.example"
        cp "${ENV_FILE}.example" "$ENV_FILE"
        log_warn "Please review and update the .env file before proceeding"
        read -p "Press Enter to continue or Ctrl+C to abort..."
    else
        log_error ".env file not found"
        exit 1
    fi
fi

# 检查docker-compose.yml
if [ ! -f "$COMPOSE_FILE" ]; then
    log_error "docker-compose.yml not found at $COMPOSE_FILE"
    exit 1
fi

log_info "All checks passed"

# --- 创建目录结构 ---
log_step "Step 2: Create Directory Structure"

mkdir -p "$DATA_PATH"/{tasks,uploads,workflows,references,conda_envs,logs/{web,celery,nginx,master},backups,tmp}
chmod 755 "$DATA_PATH"
chmod 777 "$DATA_PATH/tasks"  # 多容器写入
chmod 755 "$DATA_PATH/uploads"
chmod 755 "$DATA_PATH/workflows"
chmod 755 "$DATA_PATH/references"

log_info "Directory structure created at $DATA_PATH"

# --- 设置目录权限 ---
log_step "Step 3: Set Directory Permissions"

# 检测容器运行用户UID（默认1000）
CONTAINER_UID=$(grep "^omicshub" /etc/passwd 2>/dev/null | cut -d: -f3 || echo "1000")
chown -R "${CONTAINER_UID}:${CONTAINER_UID}" "$DATA_PATH" 2>/dev/null || {
    log_warn "Could not chown $DATA_PATH (may need sudo)"
    log_warn "Please run: sudo chown -R ${CONTAINER_UID}:${CONTAINER_UID} $DATA_PATH"
}

log_info "Permissions set (UID: $CONTAINER_UID)"

# --- 启动基础服务 ---
log_step "Step 4: Start Infrastructure Services"

$COMPOSE_CMD -f "$COMPOSE_FILE" up -d db redis

# 等待数据库就绪
log_info "Waiting for PostgreSQL to be ready..."
for i in {1..60}; do
    if $COMPOSE_CMD -f "$COMPOSE_FILE" exec -T db pg_isready -U "${POSTGRES_USER:-omicshub}" > /dev/null 2>&1; then
        log_info "PostgreSQL is ready"
        break
    fi
    if [ $i -eq 60 ]; then
        log_error "PostgreSQL failed to start within 60 seconds"
        $COMPOSE_CMD -f "$COMPOSE_FILE" logs db
        exit 1
    fi
    sleep 1
done

# 等待Redis就绪
log_info "Waiting for Redis to be ready..."
for i in {1..30}; do
    if $COMPOSE_CMD -f "$COMPOSE_FILE" exec -T redis redis-cli ping > /dev/null 2>&1; then
        log_info "Redis is ready"
        break
    fi
    if [ $i -eq 30 ]; then
        log_error "Redis failed to start within 30 seconds"
        exit 1
    fi
    sleep 1
done

# --- 数据库迁移 ---
if [ "$SKIP_MIGRATION" = false ]; then
    log_step "Step 5: Database Migration"

    if [ "$RESET_DB" = true ]; then
        log_warn "Resetting database - ALL DATA WILL BE LOST!"
        read -p "Are you sure? Type 'yes' to continue: " confirm
        if [ "$confirm" = "yes" ]; then
            $COMPOSE_CMD -f "$COMPOSE_FILE" exec -T db dropdb -U "${POSTGRES_USER:-omicshub}" "${POSTGRES_DB:-omicshub}" 2>/dev/null || true
            $COMPOSE_CMD -f "$COMPOSE_FILE" exec -T db createdb -U "${POSTGRES_USER:-omicshub}" "${POSTGRES_DB:-omicshub}"
            log_info "Database reset"
        else
            log_info "Database reset cancelled"
        fi
    fi

    # 执行Alembic迁移
    $COMPOSE_CMD -f "$COMPOSE_FILE" run --rm web alembic upgrade head || {
        log_error "Database migration failed"
        exit 1
    }
    log_info "Database migration completed"
else
    log_warn "Skipping database migration"
fi

# --- 创建默认管理员账户 ---
log_step "Step 6: Create Default Admin Account"

ADMIN_EMAIL="${ADMIN_EMAIL:-admin@example.com}"
ADMIN_PASSWORD="${ADMIN_PASSWORD:-admin123}"

$COMPOSE_CMD -f "$COMPOSE_FILE" run --rm web python -c "
import asyncio
import os
from app.core.database import async_session
from app.models.user import User
from app.core.security import get_password_hash
from app.core.config import settings

async def create_admin():
    async with async_session() as db:
        # 检查是否已有管理员
        from sqlalchemy import select
        result = await db.execute(select(User).where(User.is_superuser == True))
        admin = result.scalar_one_or_none()

        if admin:
            print(f'Admin user already exists: {admin.email}')
            return

        # 创建管理员
        admin = User(
            email='${ADMIN_EMAIL}',
            hashed_password=get_password_hash('${ADMIN_PASSWORD}'),
            full_name='System Administrator',
            is_active=True,
            is_superuser=True,
        )
        db.add(admin)
        await db.commit()
        print(f'Admin user created: ${ADMIN_EMAIL}')

asyncio.run(create_admin())
" || log_warn "Admin account creation may have failed (check logs)"

# --- 导入示例流程 ---
log_step "Step 7: Import Workflow Definitions"

WORKFLOW_DIR="${DATA_PATH}/workflows"
if [ -d "$WORKFLOW_DIR" ]; then
    # 扫描并导入所有 workflow.yaml 文件
    $COMPOSE_CMD -f "$COMPOSE_FILE" run --rm web python -c "
import asyncio
import os
import yaml
from pathlib import Path

async def import_workflows():
    workflow_dir = Path('${WORKFLOW_DIR}')
    if not workflow_dir.exists():
        print(f'Workflow directory not found: {workflow_dir}')
        return

    imported = 0
    for wf_file in workflow_dir.rglob('*.yaml'):
        try:
            with open(wf_file) as f:
                wf_def = yaml.safe_load(f)

            if wf_def and isinstance(wf_def, dict):
                # 这里调用实际的导入API或函数
                print(f'Found workflow: {wf_def.get(\"name\", wf_file.name)}')
                imported += 1
        except Exception as e:
            print(f'Warning: Failed to parse {wf_file}: {e}')

    print(f'Scanned {imported} workflow files')

asyncio.run(import_workflows())
" || log_warn "Workflow import may have failed (non-critical)"
else
    log_warn "Workflow directory not found at $WORKFLOW_DIR"
fi

# --- 启动所有服务 ---
log_step "Step 8: Start All Services"

$COMPOSE_CMD -f "$COMPOSE_FILE" up -d --build

# --- 等待服务就绪 ---
log_info "Waiting for services to be ready..."
sleep 5

# 健康检查
HEALTHY=0
TOTAL=0
for service in web celery_worker celery_beat; do
    TOTAL=$((TOTAL + 1))
    if $COMPOSE_CMD -f "$COMPOSE_FILE" ps "$service" | grep -q "healthy"; then
        log_info "$service is healthy"
        HEALTHY=$((HEALTHY + 1))
    elif $COMPOSE_CMD -f "$COMPOSE_FILE" ps "$service" | grep -q "Up"; then
        log_warn "$service is running (healthcheck pending)"
        HEALTHY=$((HEALTHY + 1))
    else
        log_error "$service failed to start"
    fi
done

# --- 完成 ---
log_step "Initialization Complete"

echo ""
echo "========================================"
echo "  OmicsHub Initialization Summary"
echo "========================================"
echo "  Services:     $HEALTHY/$TOTAL running"
echo "  Data path:    $DATA_PATH"
echo "  Admin email:  $ADMIN_EMAIL"
echo "  Compose file: $COMPOSE_FILE"
echo ""
echo "  Access URLs:"
echo "    - Web App:    http://localhost/"
echo "    - API Docs:   http://localhost/api/v1/docs"
echo "    - Flower:     http://localhost/flower/"
echo ""
echo "  Useful commands:"
echo "    - View logs:  $COMPOSE_CMD -f $COMPOSE_FILE logs -f"
echo "    - Stop:       $COMPOSE_CMD -f $COMPOSE_FILE down"
echo "    - Restart:    $COMPOSE_CMD -f $COMPOSE_FILE restart"
echo "========================================"

if [ "$HEALTHY" -lt "$TOTAL" ]; then
    log_warn "Some services may not be fully ready. Check logs with:"
    echo "  $COMPOSE_CMD -f $COMPOSE_FILE logs"
    exit 1
fi

exit 0
```

### 6.7.2 每日备份脚本 backup.sh

```bash
#!/bin/bash
# =============================================================================
# OmicsHub 每日备份脚本
# 用法: 添加到 crontab: 0 2 * * * /opt/omicshub/scripts/backup.sh
# =============================================================================

set -euo pipefail

BACKUP_DIR="/data/omicshub/backups/$(date +%Y%m%d)"
DATA_ROOT="/data/omicshub"
RETENTION_DAYS=30
COMPOSE_CMD="docker-compose"
COMPOSE_FILE="/opt/omicshub/docker-compose.yml"

mkdir -p "$BACKUP_DIR"

# --- 数据库备份 ---
echo "[$(date)] Backing up database..."
$COMPOSE_CMD -f "$COMPOSE_FILE" exec -T db pg_dump \
    -U "${POSTGRES_USER:-omicshub}" \
    "${POSTGRES_DB:-omicshub}" | gzip > "$BACKUP_DIR/db_backup.sql.gz"

# --- 应用数据备份（排除临时文件） ---
echo "[$(date)] Backing up application data..."
tar -czf "$BACKUP_DIR/data_backup.tar.gz" \
    --exclude='*/tmp/*' \
    --exclude='*/.snakemake/*' \
    -C "$DATA_ROOT" tasks uploads workflows

# --- 清理旧备份 ---
echo "[$(date)] Cleaning up old backups (> $RETENTION_DAYS days)..."
find "$DATA_ROOT/backups" -type d -mtime +$RETENTION_DAYS -exec rm -rf {} + 2>/dev/null || true

echo "[$(date)] Backup completed: $BACKUP_DIR"
ls -lh "$BACKUP_DIR"
```

---

## 6.8 工作流执行引擎（WMS）架构详细设计

### 6.8.1 架构概述

OmicsHub 的工作流执行引擎采用**策略模式（Strategy Pattern）**设计，通过 `ExecutionBackend` 抽象层统一接口，支持本地执行和远程执行两种模式的无缝切换。

```
+---------------------------------------------------------------------+
|                        Web Platform (FastAPI)                        |
|                                                                      |
|  +-----------------+    +--------------+    +------------------+    |
|  |  TaskService    |--->|BackendFactory|--->| ExecutionBackend |    |
|  |                 |    |              |    |   (abstract)     |    |
|  +-----------------+    +--------------+    +--------+---------+    |
|                                                      |              |
|                              +-----------------------+----------+   |
|                              |                       |          |   |
|                              v                       v          |   |
|                    +------------------+  +------------------+  |   |
|                    |LocalSnakemake    |  | RemoteMasterBackend  |  |   |
|                    |   Backend        |  |                  |  |   |
|                    +--------+---------+  +--------+---------+  |   |
|                             |                     |            |   |
+-----------------------------+---------------------+------------+   |
                              |                     |                |
                              v                     v                |
                    +------------------+  +------------------+      |
                    | asyncio.subprocess|  | HTTP/WebSocket   |      |
                    |                  |  |   to Master      |      |
                    +------------------+  +--------+---------+      |
                                                   |                |
                              +--------------------+                |
                              v                                     |
                    +------------------+                            |
                    |   Master Node    |                            |
                    | FastAPI Executor |                            |
                    +------------------+                            |
+---------------------------------------------------------------------+
```

---

### 6.8.2 ExecutionBackend 抽象层

```python
# app/core/execution/base.py
# =============================================================================
# ExecutionBackend abstract base class
# Defines the unified interface for workflow execution engines
# =============================================================================

from abc import ABC, abstractmethod
from typing import AsyncGenerator, Optional
from enum import Enum
import asyncio


class TaskStatus(str, Enum):
    """Task status enumeration"""
    PENDING = "pending"
    SUBMITTED = "submitted"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class ExecutionBackend(ABC):
    """
    Workflow execution backend abstract base class.
    
    All concrete backends (local Snakemake, remote Master, etc.) must implement this interface.
    Strategy pattern enables switching execution modes without modifying business code.
    """
    
    engine: str = "unknown"
    
    @abstractmethod
    async def submit(
        self,
        task_id: str,
        snakefile: str,
        config: dict,
        workdir: str,
        cores: int = 8,
        extra_args: Optional[list[str]] = None
    ) -> str:
        """
        Submit a task to the execution backend.
        
        Args:
            task_id: Unique task identifier (UUID)
            snakefile: Path to Snakefile
            config: Snakemake configuration dict, will be written to config.yaml
            workdir: Task working directory
            cores: Number of CPU cores to use
            extra_args: Additional Snakemake command line arguments
            
        Returns:
            backend_job_id: Backend-assigned job ID for subsequent queries and cancellation
        """
        pass
    
    @abstractmethod
    async def get_status(self, backend_job_id: str) -> TaskStatus:
        """
        Query task execution status.
        
        Args:
            backend_job_id: Backend job ID returned by submit()
            
        Returns:
            TaskStatus: Current task status
        """
        pass
    
    @abstractmethod
    async def cancel(self, backend_job_id: str, timeout: int = 5) -> bool:
        """
        Cancel a running task.
        
        Strategy: SIGTERM -> wait 5 seconds -> SIGKILL (ensure termination)
        
        Args:
            backend_job_id: Backend job ID
            timeout: SIGTERM wait time (seconds)
            
        Returns:
            bool: Whether cancellation succeeded
        """
        pass
    
    @abstractmethod
    async def stream_logs(self, task_id: str) -> AsyncGenerator[str, None]:
        """
        Stream read task logs.
        
        Args:
            task_id: Task ID
            
        Yields:
            str: Log line
        """
        pass
    
    @abstractmethod
    async def get_results(self, task_id: str, workdir: str) -> dict:
        """
        Get task execution results.
        
        Args:
            task_id: Task ID
            workdir: Task working directory
            
        Returns:
            dict: Result summary, including output file list, statistics, etc.
        """
        pass


class BackendFactory:
    """
    Execution backend factory class.
    
    Creates corresponding backend instances based on configuration,
    implementing runtime switching of strategy pattern.
    """
    
    _backends: dict[str, type[ExecutionBackend]] = {}
    _instances: dict[str, ExecutionBackend] = {}
    
    @classmethod
    def register(cls, mode: str, backend_class: type[ExecutionBackend]) -> None:
        """Register execution backend type"""
        cls._backends[mode] = backend_class
        
    @classmethod
    def create(cls, mode: str, **kwargs) -> ExecutionBackend:
        """
        Create execution backend instance (singleton pattern).
        
        Args:
            mode: Execution mode, "local" or "remote"
            **kwargs: Parameters passed to backend constructor
            
        Returns:
            ExecutionBackend: Execution backend instance
            
        Raises:
            ValueError: Unknown execution mode
        """
        if mode not in cls._instances:
            if mode not in cls._backends:
                raise ValueError(
                    f"Unknown execution mode: '{mode}'. "
                    f"Available modes: {list(cls._backends.keys())}"
                )
            cls._instances[mode] = cls._backends[mode](**kwargs)
        return cls._instances[mode]
    
    @classmethod
    def reset(cls) -> None:
        """Reset all instances (mainly for testing)"""
        cls._instances.clear()
```

---

### 6.8.3 LocalSnakemakeBackend Implementation

```python
# app/core/execution/local_backend.py
# =============================================================================
# LocalSnakemakeBackend - Local execution mode
# Execute Snakemake directly via asyncio.subprocess
# =============================================================================

import asyncio
import os
import re
import json
import signal
import logging
from pathlib import Path
from typing import AsyncGenerator, Optional

import yaml

from .base import ExecutionBackend, TaskStatus, BackendFactory

logger = logging.getLogger(__name__)

# Progress parsing regex
PROGRESS_PATTERN = re.compile(r'(\d+) of (\d+) steps \((\d+)%\) done')
ERROR_PATTERN = re.compile(r'(?:Error|ERROR|Exception|FAILED).*')


class LocalSnakemakeBackend(ExecutionBackend):
    """
    Local Snakemake execution backend.
    
    Features:
    - Start Snakemake process directly via asyncio.subprocess
    - Execute within Celery Worker container
    - Maintain in-memory process dict for task management
    - Real-time parse stdout/stderr, extract progress info
    - WebSocket push logs to frontend
    """
    
    engine: str = "snakemake"
    
    # Process dict: {task_id: asyncio.subprocess.Process}
    _processes: dict[str, asyncio.subprocess.Process] = {}
    
    # Process lock to prevent concurrent operations
    _lock: asyncio.Lock = asyncio.Lock()
    
    # Cleanup hook registered flag
    _cleanup_registered: bool = False
    
    def __init__(self, conda_env_path: str = "/opt/conda/envs"):
        self.conda_env_path = conda_env_path
        self._register_cleanup()
    
    def _register_cleanup(self) -> None:
        """Register process cleanup hook, ensure all child processes are terminated on exit"""
        if not self._cleanup_registered:
            import atexit
            atexit.register(self._cleanup_all_processes)
            self._cleanup_registered = True
    
    def _cleanup_all_processes(self) -> None:
        """Clean up all running processes (called on program exit)"""
        for task_id, process in list(self._processes.items()):
            try:
                if process.returncode is None:
                    process.send_signal(signal.SIGTERM)
                    logger.warning(f"Cleanup: sent SIGTERM to task {task_id}")
            except Exception as e:
                logger.error(f"Cleanup failed for task {task_id}: {e}")
    
    async def submit(
        self,
        task_id: str,
        snakefile: str,
        config: dict,
        workdir: str,
        cores: int = 8,
        extra_args: Optional[list[str]] = None
    ) -> str:
        """
        Submit Snakemake task.
        
        Execution flow:
        1. Create task working directory
        2. Write config.yaml
        3. Build snakemake command
        4. Start subprocess
        5. Store process reference
        6. Start log reading and progress monitoring tasks
        """
        workdir_path = Path(workdir)
        workdir_path.mkdir(parents=True, exist_ok=True)
        
        # 1. Write config.yaml
        config_path = workdir_path / "config.yaml"
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        # Write task metadata
        metadata_path = workdir_path / "metadata.json"
        with open(metadata_path, 'w') as f:
            json.dump({
                "task_id": task_id,
                "snakefile": snakefile,
                "config": config,
                "cores": cores,
                "status": "submitted",
                "workdir": workdir
            }, f, indent=2)
        
        # 2. Build snakemake command
        log_path = workdir_path / "snakemake.log"
        
        cmd = [
            "snakemake",
            "--snakefile", str(snakefile),
            "--configfile", str(config_path),
            "--directory", str(workdir_path),
            "--cores", str(cores),
            "--nolock",                    # Avoid Snakemake concurrent lock conflicts
            "--latency-wait", "60",        # Wait for filesystem sync (needed for NFS)
            "--keep-going",                # Complete as many steps as possible
            "--rerun-incomplete",          # Re-run incomplete tasks
            "--printshellcmds",            # Print executed commands
            "--stats", str(workdir_path / "stats.json"),
        ]
        
        if extra_args:
            cmd.extend(extra_args)
        
        # 3. Start subprocess
        logger.info(f"Starting Snakemake task {task_id}: {' '.join(cmd)}")
        
        log_file = open(log_path, 'w')
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            cwd=str(workdir_path),
            start_new_session=True,
        )
        
        # 4. Store process reference
        async with self._lock:
            self._processes[task_id] = process
        
        # Write status file
        self._write_status_file(workdir_path, TaskStatus.RUNNING)
        
        # 5. Start background tasks: log reading and process monitoring
        asyncio.create_task(
            self._monitor_task(task_id, process, workdir_path, log_file),
            name=f"monitor-{task_id}"
        )
        
        return task_id  # In local mode, backend_job_id is the task_id
    
    async def _monitor_task(
        self,
        task_id: str,
        process: asyncio.subprocess.Process,
        workdir_path: Path,
        log_file
    ) -> None:
        """
        Monitor task execution: read logs, parse progress, wait for completion.
        This is a background task started by submit().
        """
        try:
            await self._read_logs(task_id, process, workdir_path, log_file)
            
            returncode = await process.wait()
            
            if returncode == 0:
                status = TaskStatus.COMPLETED
                logger.info(f"Task {task_id} completed successfully")
            elif returncode == -signal.SIGTERM or returncode == -signal.SIGKILL:
                status = TaskStatus.CANCELLED
                logger.info(f"Task {task_id} was cancelled")
            else:
                status = TaskStatus.FAILED
                logger.error(f"Task {task_id} failed with return code {returncode}")
            
            self._write_status_file(workdir_path, status)
            await self._on_task_complete(task_id, status, workdir_path)
            
        except asyncio.CancelledError:
            logger.warning(f"Monitor task for {task_id} was cancelled")
        except Exception as e:
            logger.exception(f"Error monitoring task {task_id}: {e}")
            self._write_status_file(workdir_path, TaskStatus.FAILED)
        finally:
            async with self._lock:
                self._processes.pop(task_id, None)
            try:
                log_file.close()
            except:
                pass
    
    async def _read_logs(
        self,
        task_id: str,
        process: asyncio.subprocess.Process,
        workdir_path: Path,
        log_file
    ) -> None:
        """
        Non-blocking read stdout, parse progress, write log file, WebSocket push.
        
        Parsing content:
        - Progress: 'X of Y steps (Z%) done'
        - Errors: Lines containing Error/ERROR/Exception
        - Normal logs: All other output
        """
        if process.stdout is None:
            return
        
        progress_path = workdir_path / "progress.json"
        
        async for line in process.stdout:
            line_str = line.decode().rstrip()
            
            # 1. Write to log file
            log_file.write(line_str + "\n")
            log_file.flush()
            
            # 2. Try parsing progress
            progress_update = None
            if match := PROGRESS_PATTERN.search(line_str):
                current, total, percent = match.groups()
                progress_update = {
                    "current_step": int(current),
                    "total_steps": int(total),
                    "percent": int(percent),
                    "task_id": task_id
                }
                with open(progress_path, 'w') as f:
                    json.dump(progress_update, f)
            
            # 3. Detect errors
            is_error = bool(ERROR_PATTERN.search(line_str))
            
            # 4. WebSocket push (via Redis Pub/Sub or memory queue)
            await self._broadcast_log(task_id, line_str, progress_update, is_error)
    
    async def _broadcast_log(
        self,
        task_id: str,
        line: str,
        progress: Optional[dict],
        is_error: bool
    ) -> None:
        """
        Broadcast logs to WebSocket (via Redis Pub/Sub).
        
        Celery Worker and Web app are not in the same process,
        use Redis as message broker.
        """
        try:
            import redis.asyncio as redis
            from app.core.config import settings
            
            r = redis.from_url(settings.REDIS_URL)
            
            message = {
                "type": "task.log_output",
                "task_id": task_id,
                "payload": {
                    "chunk": line,
                    "is_error": is_error,
                    "timestamp": asyncio.get_event_loop().time()
                }
            }
            
            if progress:
                message["payload"]["progress"] = progress
            
            await r.publish(f"task:logs:{task_id}", json.dumps(message))
            await r.close()
            
        except Exception as e:
            logger.debug(f"Failed to broadcast log for task {task_id}: {e}")
    
    async def _on_task_complete(
        self,
        task_id: str,
        status: TaskStatus,
        workdir_path: Path
    ) -> None:
        """
        Task completion callback.
        
        Notify Celery task status change, trigger subsequent processing
        (email notification, result archiving, etc.).
        """
        try:
            from celery import current_app
            current_app.send_task(
                'app.tasks.on_task_complete',
                kwargs={
                    'task_id': task_id,
                    'status': status.value,
                    'results_dir': str(workdir_path / "results")
                }
            )
        except Exception as e:
            logger.error(f"Task completion callback failed for {task_id}: {e}")
    
    def _write_status_file(self, workdir_path: Path, status: TaskStatus) -> None:
        """Write status to file for external queries"""
        status_path = workdir_path / "status.json"
        with open(status_path, 'w') as f:
            json.dump({"status": status.value}, f)
    
    async def get_status(self, backend_job_id: str) -> TaskStatus:
        """
        Query task status.
        
        Query from in-memory process dict first, then read from file if process ended.
        """
        process = self._processes.get(backend_job_id)
        if process and process.returncode is None:
            return TaskStatus.RUNNING
        
        status_path = Path(f"/data/tasks/{backend_job_id}/status.json")
        if status_path.exists():
            with open(status_path) as f:
                data = json.load(f)
                return TaskStatus(data.get("status", "unknown"))
        
        return TaskStatus.PENDING
    
    async def cancel(self, backend_job_id: str, timeout: int = 5) -> bool:
        """
        Cancel task.
        
        Strategy:
        1. Send SIGTERM (graceful termination)
        2. Wait for specified timeout
        3. If process still running, send SIGKILL (force kill)
        """
        process = self._processes.get(backend_job_id)
        if not process:
            logger.warning(f"No running process found for task {backend_job_id}")
            return False
        
        if process.returncode is not None:
            logger.info(f"Task {backend_job_id} already finished")
            return False
        
        try:
            pgid = os.getpgid(process.pid)
            os.killpg(pgid, signal.SIGTERM)
            logger.info(f"Sent SIGTERM to task {backend_job_id} (PGID: {pgid})")
            
            try:
                await asyncio.wait_for(process.wait(), timeout=timeout)
                logger.info(f"Task {backend_job_id} terminated gracefully")
                return True
            except asyncio.TimeoutError:
                logger.warning(f"Task {backend_job_id} did not terminate, sending SIGKILL")
                try:
                    os.killpg(pgid, signal.SIGKILL)
                    await process.wait()
                except ProcessLookupError:
                    pass
                return True
                
        except ProcessLookupError:
            logger.info(f"Task {backend_job_id} process already gone")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel task {backend_job_id}: {e}")
            return False
    
    async def stream_logs(self, task_id: str) -> AsyncGenerator[str, None]:
        """
        Stream read task logs.
        
        If task is running, real-time read log file;
        If task is completed, read complete log file.
        """
        log_path = Path(f"/data/tasks/{task_id}/snakemake.log")
        
        if not log_path.exists():
            yield f"[Log file not found: {log_path}]"
            return
        
        with open(log_path, 'r') as f:
            for line in f:
                yield line.rstrip()
        
        process = self._processes.get(task_id)
        if process and process.returncode is None:
            with open(log_path, 'r') as f:
                f.seek(0, 2)
                while process.returncode is None:
                    line = f.readline()
                    if line:
                        yield line.rstrip()
                    else:
                        await asyncio.sleep(0.5)
    
    async def get_results(self, task_id: str, workdir: str) -> dict:
        """
        Get task execution results.
        
        Scan results directory, collect output file list and statistics.
        """
        results_dir = Path(workdir) / "results"
        output_files = []
        
        if results_dir.exists():
            for file_path in results_dir.rglob("*"):
                if file_path.is_file():
                    output_files.append({
                        "path": str(file_path.relative_to(results_dir)),
                        "size": file_path.stat().st_size,
                        "modified": file_path.stat().st_mtime
                    })
        
        stats_path = Path(workdir) / "stats.json"
        stats = {}
        if stats_path.exists():
            try:
                with open(stats_path) as f:
                    stats = json.load(f)
            except:
                pass
        
        return {
            "task_id": task_id,
            "output_files": output_files,
            "total_size": sum(f["size"] for f in output_files),
            "file_count": len(output_files),
            "stats": stats
        }


# Register to factory
BackendFactory.register("local", LocalSnakemakeBackend)
```

---

### 6.8.4 RemoteMasterBackend Implementation

```python
# app/core/execution/remote_backend.py
# =============================================================================
# RemoteMasterBackend - Remote execution mode
# Call Master compute node via HTTP/WebSocket
# =============================================================================

import asyncio
import json
import logging
from typing import AsyncGenerator, Optional
from pathlib import Path

import httpx
import websockets
import yaml

from .base import ExecutionBackend, TaskStatus, BackendFactory
from app.core.config import settings

logger = logging.getLogger(__name__)


class RemoteMasterBackend(ExecutionBackend):
    """
    Remote Master execution backend.
    
    Features:
    - Submit tasks to Master node via HTTP API
    - Receive real-time logs via WebSocket
    - Web platform itself does not execute Snakemake, only schedules
    - Suitable for compute-intensive scenarios, separation of web and compute
    """
    
    engine: str = "snakemake"
    
    def __init__(
        self,
        master_api_url: str = None,
        internal_token: str = None
    ):
        self.master_api_url = master_api_url or settings.MASTER_API_URL
        self.internal_token = internal_token or settings.INTERNAL_TOKEN
        self.headers = {
            "Content-Type": "application/json",
            "X-Internal-Token": self.internal_token
        }
    
    async def submit(
        self,
        task_id: str,
        snakefile: str,
        config: dict,
        workdir: str,
        cores: int = 8,
        extra_args: Optional[list[str]] = None
    ) -> str:
        """
        Submit task to Master node via HTTP.
        
        Flow:
        1. Ensure working directory and config file are created
        2. HTTP POST /api/v1/execute to Master
        3. Return Master-assigned job_id
        """
        workdir_path = Path(workdir)
        workdir_path.mkdir(parents=True, exist_ok=True)
        
        config_path = workdir_path / "config.yaml"
        with open(config_path, 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        metadata = {
            "task_id": task_id,
            "snakefile": snakefile,
            "configfile": str(config_path),
            "workdir": workdir,
            "cores": cores,
            "callback_url": f"{settings.CALLBACK_URL}/task-complete",
            "websocket_url": f"{settings.WEBSOCKET_URL}/task-log",
            "extra_args": extra_args or []
        }
        
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                f"{self.master_api_url}/api/v1/execute",
                json=metadata,
                headers=self.headers
            )
            response.raise_for_status()
            result = response.json()
        
        master_job_id = result["job_id"]
        logger.info(f"Task {task_id} submitted to Master, job_id: {master_job_id}")
        
        return master_job_id
    
    async def get_status(self, backend_job_id: str) -> TaskStatus:
        """HTTP GET query task status on Master node"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.master_api_url}/api/v1/tasks/{backend_job_id}/status",
                    headers=self.headers
                )
                response.raise_for_status()
                result = response.json()
                return TaskStatus(result.get("status", "unknown"))
        except httpx.HTTPError as e:
            logger.error(f"Failed to get status for job {backend_job_id}: {e}")
            return TaskStatus.FAILED
    
    async def cancel(self, backend_job_id: str, timeout: int = 5) -> bool:
        """HTTP DELETE request Master to cancel task"""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.delete(
                    f"{self.master_api_url}/api/v1/tasks/{backend_job_id}",
                    headers=self.headers,
                    params={"timeout": timeout}
                )
                response.raise_for_status()
                result = response.json()
                return result.get("cancelled", False)
        except httpx.HTTPError as e:
            logger.error(f"Failed to cancel job {backend_job_id}: {e}")
            return False
    
    async def stream_logs(self, task_id: str) -> AsyncGenerator[str, None]:
        """
        WebSocket connect to Master node, receive log stream in real-time.
        
        Auto-reconnect on disconnect (up to 3 times).
        """
        ws_url = f"{self.master_api_url}/ws/v1/tasks/{task_id}/logs"
        ws_url = ws_url.replace("http://", "ws://").replace("https://", "wss://")
        
        reconnect_count = 0
        max_reconnect = 3
        
        while reconnect_count < max_reconnect:
            try:
                async with websockets.connect(
                    ws_url,
                    extra_headers={"X-Internal-Token": self.internal_token}
                ) as websocket:
                    logger.info(f"WebSocket connected for task {task_id} logs")
                    reconnect_count = 0
                    
                    async for message in websocket:
                        data = json.loads(message)
                        
                        if data.get("type") == "log":
                            yield data.get("payload", "")
                        elif data.get("type") == "progress":
                            progress = data.get("payload", {})
                            yield f"[Progress: {progress.get('current_step', 0)}/{progress.get('total_steps', 0)} ({progress.get('percent', 0)}%)]"
                        elif data.get("type") == "complete":
                            yield "[Task completed]"
                            return
                        elif data.get("type") == "error":
                            yield f"[Error: {data.get('payload', '')}]"
                            return
            except websockets.exceptions.ConnectionClosed:
                reconnect_count += 1
                if reconnect_count < max_reconnect:
                    logger.warning(f"WebSocket disconnected, reconnecting ({reconnect_count}/{max_reconnect})...")
                    await asyncio.sleep(2 ** reconnect_count)
                else:
                    yield "[WebSocket connection lost, log stream ended]"
                    return
            except Exception as e:
                logger.error(f"WebSocket error for task {task_id}: {e}")
                yield f"[Log stream error: {e}]"
                return
    
    async def get_results(self, task_id: str, workdir: str) -> dict:
        """
        Get task results from Master.
        
        Results are already written to shared storage via callback, read locally.
        """
        results_dir = Path(workdir) / "results"
        output_files = []
        
        if results_dir.exists():
            for file_path in results_dir.rglob("*"):
                if file_path.is_file():
                    output_files.append({
                        "path": str(file_path.relative_to(results_dir)),
                        "size": file_path.stat().st_size
                    })
        
        return {
            "task_id": task_id,
            "output_files": output_files,
            "total_size": sum(f["size"] for f in output_files),
            "file_count": len(output_files)
        }


# Register to factory
BackendFactory.register("remote", RemoteMasterBackend)
```



---

### 6.8.5 Master Node FastAPI Service Design

```python
# master/app/main.py
# =============================================================================
# Master Executor Service - Standalone FastAPI application
# Dedicated to executing Snakemake compute tasks
# =============================================================================

import asyncio
import json
import logging
import os
import re
import signal
import subprocess
import tempfile
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import httpx
import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

# Configuration
MASTER_HOST = os.getenv("MASTER_HOST", "0.0.0.0")
MASTER_PORT = int(os.getenv("MASTER_PORT", "8001"))
CALLBACK_URL = os.getenv("CALLBACK_URL", "http://web:8000/internal/callback/task-complete")
INTERNAL_TOKEN = os.getenv("INTERNAL_TOKEN", "internal-token-change-me")
SNAKEMAKE_CORES = int(os.getenv("SNAKEMAKE_CORES", "16"))
CONDA_ENV_PATH = os.getenv("CONDA_ENV_PATH", "/opt/conda/envs")
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "*").split(",")

# Logging setup
logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "INFO")),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("master")

# Global state
running_jobs: dict[str, dict] = {}
job_counter = 0
lock = asyncio.Lock()


# Pydantic models
class ExecuteRequest(BaseModel):
    """Task execution request"""
    task_id: str = Field(..., description="Web platform task ID")
    snakefile: str = Field(..., description="Snakefile path")
    configfile: str = Field(..., description="Config file path")
    workdir: str = Field(..., description="Working directory")
    cores: int = Field(default=SNAKEMAKE_CORES, ge=1, le=64)
    callback_url: Optional[str] = None
    websocket_url: Optional[str] = None
    extra_args: list[str] = Field(default_factory=list)


class StatusResponse(BaseModel):
    """Status response"""
    job_id: str
    task_id: str
    status: str
    progress: Optional[dict] = None


class CancelResponse(BaseModel):
    """Cancel response"""
    job_id: str
    cancelled: bool
    message: str


# Lifecycle management
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup/shutdown lifecycle"""
    logger.info("Master Executor starting...")
    yield
    logger.info("Master Executor shutting down, cleaning up jobs...")
    for job_id, job in list(running_jobs.items()):
        process = job.get("process")
        if process and process.poll() is None:
            logger.warning(f"Terminating job {job_id} on shutdown")
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass


app = FastAPI(
    title="OmicsHub Master Executor",
    description="Dedicated execution node for running Snakemake workflows",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Dependency: internal token verification
async def verify_token(x_internal_token: str = ""):
    """Verify internal call token"""
    if x_internal_token != INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")
    return True


def generate_job_id() -> str:
    """Generate job ID"""
    global job_counter
    job_counter += 1
    return f"master-{job_counter:06d}"


async def write_status_file(workdir: str, status: str) -> None:
    """Write status file"""
    status_path = Path(workdir) / "status.json"
    with open(status_path, 'w') as f:
        json.dump({"status": status, "node": "master"}, f)


async def callback_web_platform(task_id: str, status: str, results: dict) -> None:
    """Callback Web platform to notify task completion"""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                CALLBACK_URL,
                json={
                    "task_id": task_id,
                    "status": status,
                    "node": "master",
                    **results
                },
                headers={"X-Internal-Token": INTERNAL_TOKEN}
            )
            if response.status_code == 200:
                logger.info(f"Callback successful for task {task_id}")
            else:
                logger.error(f"Callback failed: {response.status_code}")
    except Exception as e:
        logger.error(f"Callback error for task {task_id}: {e}")


# API Endpoints

@app.get("/health")
async def health_check():
    """Health check"""
    return {
        "status": "healthy",
        "running_jobs": len(running_jobs),
        "node": "master"
    }


@app.post("/api/v1/execute", dependencies=[Depends(verify_token)])
async def execute_task(req: ExecuteRequest, background_tasks: BackgroundTasks):
    """
    Receive task, start Snakemake subprocess.
    
    Flow:
    1. Validate parameters
    2. Start subprocess
    3. Background task: monitor process, write logs, callback Web platform
    4. Return job_id
    """
    if not Path(req.snakefile).exists():
        raise HTTPException(status_code=400, detail=f"Snakefile not found: {req.snakefile}")
    if not Path(req.configfile).exists():
        raise HTTPException(status_code=400, detail=f"Configfile not found: {req.configfile}")
    
    workdir_path = Path(req.workdir)
    workdir_path.mkdir(parents=True, exist_ok=True)
    
    job_id = generate_job_id()
    
    log_path = workdir_path / "snakemake.log"
    
    cmd = [
        "snakemake",
        "--snakefile", req.snakefile,
        "--configfile", req.configfile,
        "--directory", str(workdir_path),
        "--cores", str(req.cores),
        "--nolock",
        "--latency-wait", "60",
        "--keep-going",
        "--rerun-incomplete",
        "--printshellcmds",
        "--stats", str(workdir_path / "stats.json"),
    ]
    cmd.extend(req.extra_args)
    
    logger.info(f"[{job_id}] Starting: {' '.join(cmd)}")
    
    log_file = open(log_path, 'w')
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=str(workdir_path),
        start_new_session=True,
        text=False
    )
    
    running_jobs[job_id] = {
        "task_id": req.task_id,
        "process": process,
        "status": "running",
        "workdir": req.workdir,
        "log_file": log_file,
    }
    
    await write_status_file(req.workdir, "running")
    
    background_tasks.add_task(
        monitor_job,
        job_id=job_id,
        task_id=req.task_id,
        process=process,
        workdir=req.workdir,
        log_file=log_file
    )
    
    return {
        "job_id": job_id,
        "task_id": req.task_id,
        "status": "running",
        "message": "Task submitted successfully"
    }


@app.get("/api/v1/tasks/{job_id}/status", dependencies=[Depends(verify_token)])
async def get_job_status(job_id: str):
    """Query task status"""
    job = running_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    process = job.get("process")
    status = job.get("status", "unknown")
    
    if process and process.poll() is not None and status == "running":
        status = "completed" if process.returncode == 0 else "failed"
        job["status"] = status
    
    progress_path = Path(job.get("workdir", "")) / "progress.json"
    progress = None
    if progress_path.exists():
        with open(progress_path) as f:
            progress = json.load(f)
    
    return StatusResponse(
        job_id=job_id,
        task_id=job.get("task_id", ""),
        status=status,
        progress=progress
    )


@app.delete("/api/v1/tasks/{job_id}", dependencies=[Depends(verify_token)])
async def cancel_job(job_id: str, timeout: int = 5):
    """
    Cancel task.
    
    Strategy: SIGTERM -> wait -> SIGKILL
    """
    job = running_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")
    
    process = job.get("process")
    if not process or process.poll() is not None:
        return CancelResponse(
            job_id=job_id, cancelled=True, message="Job already finished"
        )
    
    try:
        pgid = os.getpgid(process.pid)
        os.killpg(pgid, signal.SIGTERM)
        
        try:
            process.wait(timeout=timeout)
            job["status"] = "cancelled"
            await write_status_file(job.get("workdir", ""), "cancelled")
            return CancelResponse(
                job_id=job_id, cancelled=True, message="Job cancelled gracefully"
            )
        except subprocess.TimeoutExpired:
            os.killpg(pgid, signal.SIGKILL)
            process.wait()
            job["status"] = "cancelled"
            return CancelResponse(
                job_id=job_id, cancelled=True, message="Job force-killed"
            )
    except ProcessLookupError:
        return CancelResponse(
            job_id=job_id, cancelled=True, message="Process already gone"
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Cancel failed: {str(e)}")


@app.websocket("/ws/v1/tasks/{task_id}/logs")
async def stream_logs(websocket: WebSocket, task_id: str):
    """
    WebSocket log stream.
    
    Push task logs to Web platform in real-time.
    """
    await websocket.accept()
    
    job = None
    for j in running_jobs.values():
        if j.get("task_id") == task_id:
            job = j
            break
    
    if not job:
        await websocket.send_json({"type": "error", "payload": "Task not found"})
        await websocket.close()
        return
    
    workdir = job.get("workdir", "")
    log_path = Path(workdir) / "snakemake.log"
    process = job.get("process")
    
    PROGRESS_RE = re.compile(r'(\d+) of (\d+) steps \((\d+)%\) done')
    
    try:
        with open(log_path, 'r') as f:
            for line in f:
                await websocket.send_json({"type": "log", "payload": line.rstrip()})
            
            while process and process.poll() is None:
                line = f.readline()
                if line:
                    line_str = line.rstrip()
                    
                    if match := PROGRESS_RE.search(line_str):
                        current, total, pct = match.groups()
                        await websocket.send_json({
                            "type": "progress",
                            "payload": {
                                "current_step": int(current),
                                "total_steps": int(total),
                                "percent": int(pct)
                            }
                        })
                    
                    await websocket.send_json({"type": "log", "payload": line_str})
                else:
                    await asyncio.sleep(0.5)
            
            returncode = process.poll() if process else -1
            if returncode == 0:
                await websocket.send_json({"type": "complete"})
            else:
                await websocket.send_json({
                    "type": "error",
                    "payload": f"Process exited with code {returncode}"
                })
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for task {task_id}")
    except Exception as e:
        logger.error(f"WebSocket error for task {task_id}: {e}")
        try:
            await websocket.send_json({"type": "error", "payload": str(e)})
        except:
            pass
    finally:
        try:
            await websocket.close()
        except:
            pass


# Background monitoring function
async def monitor_job(
    job_id: str,
    task_id: str,
    process: subprocess.Popen,
    workdir: str,
    log_file
):
    """
    Background monitoring of task execution.
    
    - Read log output
    - Monitor process status
    - Callback Web platform after process ends
    """
    logger.info(f"[{job_id}] Monitor started for task {task_id}")
    
    PROGRESS_RE = re.compile(r'(\d+) of (\d+) steps \((\d+)%\) done')
    progress_path = Path(workdir) / "progress.json"
    
    try:
        if process.stdout:
            while True:
                line = process.stdout.readline()
                if not line:
                    if process.poll() is not None:
                        break
                    await asyncio.sleep(0.5)
                    continue
                
                line_str = line.decode().rstrip()
                
                log_file.write(line_str + "\n")
                log_file.flush()
                
                if match := PROGRESS_RE.search(line_str):
                    current, total, pct = match.groups()
                    with open(progress_path, 'w') as pf:
                        json.dump({
                            "current_step": int(current),
                            "total_steps": int(total),
                            "percent": int(pct)
                        }, pf)
        
        returncode = process.wait()
        
        if returncode == 0:
            status = "completed"
        elif returncode in [-signal.SIGTERM, -signal.SIGKILL]:
            status = "cancelled"
        else:
            status = "failed"
        
        logger.info(f"[{job_id}] Task {task_id} finished: {status} (code: {returncode})")
        
    except Exception as e:
        logger.exception(f"[{job_id}] Monitor error: {e}")
        status = "failed"
    finally:
        running_jobs[job_id]["status"] = status
        await write_status_file(workdir, status)
        try:
            log_file.close()
        except:
            pass
        
        results = {
            "returncode": process.returncode if process else -1,
            "results_dir": str(Path(workdir) / "results")
        }
        await callback_web_platform(task_id, status, results)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=MASTER_HOST, port=MASTER_PORT)
```

---

### 6.8.6 Task Directory Isolation and Snakemake Lock-free Execution

```python
# app/core/execution/task_isolation.py
# =============================================================================
# Task directory isolation utility
# Ensure each task has an independent workspace to avoid conflicts
# =============================================================================

import os
import json
import shutil
import csv
from pathlib import Path
from datetime import datetime
import uuid


class TaskWorkspace:
    """
    Task workspace manager.
    
    Each task has an independent directory containing:
    - config.yaml: Snakemake configuration
    - samples.csv: Sample information
    - metadata.json: Task metadata
    - snakemake.log: Execution log
    - status.json: Status file
    - progress.json: Progress file
    - results/: Results directory
    """
    
    def __init__(self, task_id: str, base_path: str = "/data/tasks"):
        self.task_id = task_id
        self.base_path = Path(base_path)
        self.workspace = self.base_path / task_id
    
    def create(self, config: dict, samples: list = None, metadata: dict = None) -> Path:
        """Create workspace"""
        self.workspace.mkdir(parents=True, exist_ok=True)
        
        (self.workspace / "results").mkdir(exist_ok=True)
        (self.workspace / "temp").mkdir(exist_ok=True)
        
        import yaml
        with open(self.workspace / "config.yaml", 'w') as f:
            yaml.dump(config, f, default_flow_style=False)
        
        if samples:
            with open(self.workspace / "samples.csv", 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=samples[0].keys())
                writer.writeheader()
                writer.writerows(samples)
        
        meta = {
            "task_id": self.task_id,
            "created_at": datetime.utcnow().isoformat(),
            **(metadata or {})
        }
        with open(self.workspace / "metadata.json", 'w') as f:
            json.dump(meta, f, indent=2)
        
        with open(self.workspace / "status.json", 'w') as f:
            json.dump({"status": "pending"}, f)
        
        return self.workspace
    
    def get_results_path(self) -> Path:
        """Get results directory path"""
        return self.workspace / "results"
    
    def get_log_path(self) -> Path:
        """Get log file path"""
        return self.workspace / "snakemake.log"
    
    def get_status(self) -> str:
        """Read status"""
        status_file = self.workspace / "status.json"
        if status_file.exists():
            with open(status_file) as f:
                return json.load(f).get("status", "unknown")
        return "not_found"
    
    def cleanup(self, keep_results: bool = True) -> None:
        """
        Clean up workspace.
        
        Args:
            keep_results: Whether to keep results directory
        """
        if keep_results:
            for pattern in ["temp/*", ".snakemake", "*.tmp"]:
                for path in self.workspace.glob(pattern):
                    if path.is_dir():
                        shutil.rmtree(path, ignore_errors=True)
                    else:
                        path.unlink(missing_ok=True)
        else:
            shutil.rmtree(self.workspace, ignore_errors=True)
    
    @staticmethod
    def generate_task_id() -> str:
        """Generate unique task ID"""
        return str(uuid.uuid4())


def build_snakemake_args(workspace: Path, snakefile: str, cores: int) -> list[str]:
    """
    Build Snakemake command line arguments.
    
    Key parameters:
    - --nolock: Disable file lock (required for multi-task concurrency)
    - --directory: Specify working directory
    - --configfile: Specify configuration file
    """
    return [
        "--snakefile", snakefile,
        "--configfile", str(workspace / "config.yaml"),
        "--directory", str(workspace),
        "--cores", str(cores),
        "--nolock",
        "--latency-wait", "60",
        "--keep-going",
        "--rerun-incomplete",
        "--printshellcmds",
        "--stats", str(workspace / "stats.json"),
    ]
```

---

### 6.8.7 Celery Task Integration

```python
# app/tasks/workflow_tasks.py
# =============================================================================
# Celery task definitions - workflow execution
# =============================================================================

import asyncio
import logging
from celery import shared_task
from app.core.execution.base import BackendFactory
from app.core.config import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def execute_workflow(self, task_id: str, workflow_type: str, config: dict, user_id: str):
    """
    Celery task: Execute workflow.
    
    This is the task received by Celery Worker, responsible for calling
    ExecutionBackend to execute Snakemake.
    
    Args:
        task_id: Task ID
        workflow_type: Workflow type (rna_seq, atac_seq, scRNA_seq)
        config: Snakemake configuration
        user_id: User ID
    """
    logger.info(f"Executing workflow task {task_id}, type={workflow_type}")
    
    loop = asyncio.get_event_loop()
    backend = BackendFactory.create(settings.EXECUTION_MODE)
    
    snakefile = f"/workflows/{workflow_type}/Snakefile"
    workdir = f"/data/tasks/{task_id}"
    cores = config.get("cores", settings.SNAKEMAKE_CORES)
    
    try:
        backend_job_id = loop.run_until_complete(backend.submit(
            task_id=task_id,
            snakefile=snakefile,
            config=config,
            workdir=workdir,
            cores=cores
        ))
        
        import time
        while True:
            time.sleep(5)
            status = loop.run_until_complete(backend.get_status(backend_job_id))
            
            if status in ("completed", "failed", "cancelled"):
                break
        
        results = loop.run_until_complete(backend.get_results(task_id, workdir))
        
        return {
            "task_id": task_id,
            "status": status,
            "results": results
        }
        
    except Exception as exc:
        logger.exception(f"Workflow execution failed: {exc}")
        self.retry(exc=exc)


@shared_task
def cancel_workflow_task(task_id: str):
    """Cancel running workflow"""
    loop = asyncio.get_event_loop()
    backend = BackendFactory.create(settings.EXECUTION_MODE)
    success = loop.run_until_complete(backend.cancel(task_id))
    return {"task_id": task_id, "cancelled": success}


@shared_task
def on_task_complete(task_id: str, status: str, results_dir: str):
    """
    Task completion callback.
    
    Trigger subsequent processing:
    - Send email notification
    - Update task status
    - Archive results
    """
    logger.info(f"Task {task_id} completed with status: {status}")
    
    from app.services.notification import notify_task_complete
    loop = asyncio.get_event_loop()
    loop.run_until_complete(notify_task_complete(task_id, status))
    
    return {"task_id": task_id, "status": status}
```



---

## 6.9 安全与数据隔离

### 6.9.1 安全架构总览

```
+-----------------------------------------------------------------------------+
|                              Security Architecture                           |
+-----------------------------------------------------------------------------+
|                                                                             |
|  [Client] --HTTPS--> [Nginx] --HTTP--> [Web:8000]                         |
|                          |                                                  |
|                          |--/flower/ (Basic Auth + IP whitelist)          |
|                          |--/internal/ (IP whitelist only)                 |
|                                                                             |
|  [Web] --Docker Network--> [DB:5432] [Redis:6379]                         |
|                                                                             |
|  [Web] --HTTP + Token--> [Master:8001] (internal only)                    |
|                                                                             |
|  [Master] --Callback + Token--> [Web:/internal/callback]                  |
|                                                                             |
|  File System: /data/uploads/{user_id}/ (app-layer isolation)              |
|                                                                             |
+-----------------------------------------------------------------------------+
```

---

### 6.9.2 用户文件系统隔离

#### 方案选择

| 方案 | 适用场景 | 优点 | 缺点 |
|------|----------|------|------|
| **Docker Volume bind** (推荐) | 内网小团队 | 简单、直接、性能好 | 依赖宿主机文件系统 |
| **MinIO对象存储** | 大规模/公网 | 标准S3 API、高可用 | 增加复杂度、需要维护 |

**推荐方案**：文件系统隔离（适合内网小团队，单维护者可管理）。

#### 实现代码

```python
# app/core/security/file_access.py
# =============================================================================
# File access control - user file system isolation
# =============================================================================

import os
import re
from pathlib import Path
from fastapi import HTTPException, Depends
from app.core.config import settings

# Dangerous characters that should not appear in paths
DANGEROUS_CHARS = re.compile(r'[;|&$`\\]')
# Path traversal pattern
PATH_TRAVERSAL = re.compile(r'\.\.(?:/|\\)')


class FileAccessController:
    """
    File access controller.
    
    Ensure users can only access their own files,
    preventing unauthorized access and path traversal attacks.
    """
    
    def __init__(self, base_upload_path: str = "/data/uploads"):
        self.base_upload_path = Path(base_upload_path)
    
    def get_user_directory(self, user_id: str) -> Path:
        """Get user upload directory"""
        user_dir = self.base_upload_path / str(user_id)
        user_dir.mkdir(parents=True, exist_ok=True)
        return user_dir
    
    def validate_path(self, user_id: str, requested_path: str) -> Path:
        """
        Validate and resolve file path.
        
        Checks:
        1. Path does not contain dangerous characters
        2. No path traversal (..)
        3. Resolved path is within user directory
        """
        # Check dangerous characters
        if DANGEROUS_CHARS.search(requested_path):
            raise HTTPException(status_code=400, detail="Invalid characters in path")
        
        # Check path traversal
        if PATH_TRAVERSAL.search(requested_path):
            raise HTTPException(status_code=400, detail="Path traversal not allowed")
        
        # Resolve absolute path
        user_dir = self.get_user_directory(user_id)
        resolved = (user_dir / requested_path).resolve()
        
        # Ensure path is within user directory
        try:
            resolved.relative_to(user_dir.resolve())
        except ValueError:
            raise HTTPException(status_code=403, detail="Access denied")
        
        return resolved
    
    def list_user_files(self, user_id: str) -> list[dict]:
        """List files in user directory"""
        user_dir = self.get_user_directory(user_id)
        files = []
        
        for file_path in user_dir.rglob("*"):
            if file_path.is_file():
                files.append({
                    "path": str(file_path.relative_to(user_dir)),
                    "size": file_path.stat().st_size,
                    "modified": file_path.stat().st_mtime,
                    "name": file_path.name
                })
        
        return files


# Global instance
file_controller = FileAccessController()


# FastAPI dependency
def get_file_controller():
    return file_controller
```

#### 应用层权限控制

```python
# app/api/deps.py
# =============================================================================
# API dependencies - user verification
# =============================================================================

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.models.user import User
from app.core.security import verify_token

security = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> User:
    """Get current user from JWT token"""
    token = credentials.credentials
    user_id = verify_token(token)
    
    user = await User.get_by_id(user_id)
    if not user or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )
    return user

async def get_current_active_user(
    current_user: User = Depends(get_current_user)
) -> User:
    """Get current active user"""
    if not current_user.is_active:
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user

async def get_current_superuser(
    current_user: User = Depends(get_current_active_user)
) -> User:
    """Get current superuser (admin)"""
    if not current_user.is_superuser:
        raise HTTPException(
            status_code=403, detail="Not enough privileges"
        )
    return current_user
```

---

### 6.9.3 敏感信息管理

#### Docker Secrets方案（推荐用于生产环境）

```yaml
# docker-compose.secrets.yml - Docker Secrets configuration
version: "3.8"

services:
  web:
    secrets:
      - postgres_password
      - secret_key
      - internal_token
      - kimi_api_key
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password
      SECRET_KEY_FILE: /run/secrets/secret_key
      INTERNAL_TOKEN_FILE: /run/secrets/internal_token
      KIMI_API_KEY_FILE: /run/secrets/kimi_api_key

  db:
    secrets:
      - postgres_password
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password

  master:
    secrets:
      - internal_token
    environment:
      INTERNAL_TOKEN_FILE: /run/secrets/internal_token

secrets:
  postgres_password:
    file: ./secrets/postgres_password.txt
  secret_key:
    file: ./secrets/secret_key.txt
  internal_token:
    file: ./secrets/internal_token.txt
  kimi_api_key:
    file: ./secrets/kimi_api_key.txt
```

#### 创建Secrets脚本

```bash
#!/bin/bash
# create_secrets.sh - Create Docker secrets directory

SECRETS_DIR="./secrets"
mkdir -p "$SECRETS_DIR"
chmod 700 "$SECRETS_DIR"

# PostgreSQL password
if [ ! -f "$SECRETS_DIR/postgres_password.txt" ]; then
    openssl rand -base64 32 > "$SECRETS_DIR/postgres_password.txt"
    echo "Created postgres_password.txt"
fi

# JWT Secret key
if [ ! -f "$SECRETS_DIR/secret_key.txt" ]; then
    openssl rand -base64 64 > "$SECRETS_DIR/secret_key.txt"
    echo "Created secret_key.txt"
fi

# Internal token
if [ ! -f "$SECRETS_DIR/internal_token.txt" ]; then
    openssl rand -base64 32 > "$SECRETS_DIR/internal_token.txt"
    echo "Created internal_token.txt"
fi

chmod 600 "$SECRETS_DIR"/*.txt
echo "All secrets created in $SECRETS_DIR"
```

#### 配置加载器（支持从文件读取Secrets）

```python
# app/core/config.py
# =============================================================================
# Configuration - support reading from Docker secrets files
# =============================================================================

import os
from pathlib import Path
from functools import lru_cache
from pydantic_settings import BaseSettings


def read_secret(secret_name: str, default: str = "") -> str:
    """
    Read Docker secret from file.
    
    In Docker Swarm, secrets are mounted at /run/secrets/.
    Falls back to environment variable or default value.
    """
    # Priority: Docker secret file > environment variable > default
    secret_path = Path(f"/run/secrets/{secret_name}")
    if secret_path.exists():
        return secret_path.read_text().strip()
    
    env_value = os.getenv(secret_name.upper())
    if env_value:
        return env_value
    
    # Check for _FILE suffix (Docker Compose secrets)
    env_file = os.getenv(f"{secret_name.upper()}_FILE")
    if env_file and Path(env_file).exists():
        return Path(env_file).read_text().strip()
    
    return default


class Settings(BaseSettings):
    """Application settings"""
    
    # Execution mode
    EXECUTION_MODE: str = "local"
    SNAKEMAKE_CORES: int = 8
    
    # Database
    POSTGRES_USER: str = "omicshub"
    POSTGRES_PASSWORD: str = "changeme"
    POSTGRES_DB: str = "omicshub"
    POSTGRES_HOST: str = "db"
    POSTGRES_PORT: int = 5432
    
    DATABASE_URL: str = ""
    
    # Redis
    REDIS_PASSWORD: str = ""
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Celery
    CELERY_BROKER_URL: str = ""
    CELERY_RESULT_BACKEND: str = ""
    
    # Security
    SECRET_KEY: str = "change-me-in-production"
    INTERNAL_TOKEN: str = "internal-token"
    
    # Master node (remote mode)
    MASTER_API_URL: str = "http://master:8001"
    CALLBACK_URL: str = "http://web:8000/internal/callback"
    WEBSOCKET_URL: str = "ws://web:8000/internal/ws"
    
    # API keys
    KIMI_API_KEY: str = ""
    OPENAI_API_KEY: str = ""
    
    # Paths
    SHARED_STORAGE_PATH: str = "/data"
    WORKFLOW_PATH: str = "/workflows"
    
    # App config
    LOG_LEVEL: str = "INFO"
    MAX_UPLOAD_SIZE: int = 1073741824  # 1GB
    
    def model_post_init(self, __context):
        """Post-initialization, construct DATABASE_URL"""
        if not self.DATABASE_URL:
            password = self.POSTGRES_PASSWORD
            self.DATABASE_URL = (
                f"postgresql://{self.POSTGRES_USER}:{password}"
                f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}"
                f"/{self.POSTGRES_DB}"
            )
        
        redis_auth = f":{self.REDIS_PASSWORD}@" if self.REDIS_PASSWORD else ""
        if not self.REDIS_URL or "localhost" in self.REDIS_URL:
            self.REDIS_URL = f"redis://{redis_auth}redis:6379/0"
        if not self.CELERY_BROKER_URL:
            self.CELERY_BROKER_URL = self.REDIS_URL
        if not self.CELERY_RESULT_BACKEND:
            self.CELERY_RESULT_BACKEND = f"redis://{redis_auth}redis:6379/1"


@lru_cache()
def get_settings() -> Settings:
    """Get settings singleton"""
    return Settings()
```

---

### 6.9.4 脚本执行安全

#### 命令注入防护

```python
# app/core/security/command_safety.py
# =============================================================================
# Command execution safety - prevent command injection
# =============================================================================

import re
import os
from pathlib import Path
from typing import Optional
from fastapi import HTTPException

# Dangerous shell characters
DANGEROUS_SHELL_CHARS = set(';|&$`\\<>!{}[]\n\r')
# Path traversal patterns
PATH_TRAVERSAL_PATTERNS = [
    re.compile(r'\.\./'),
    re.compile(r'\.\.\\'),
    re.compile(r'^/'),
    re.compile(r'^~'),
]


class CommandSafetyChecker:
    """
    Command safety checker.
    
    Prevent command injection and path traversal attacks.
    """
    
    @staticmethod
    def validate_param(value: str, param_name: str = "parameter") -> str:
        """
        Validate user parameter.
        
        Check:
        1. No dangerous shell characters
        2. Not empty
        3. Reasonable length
        """
        if not value or not value.strip():
            raise HTTPException(status_code=400, detail=f"{param_name} cannot be empty")
        
        if len(value) > 1024:
            raise HTTPException(status_code=400, detail=f"{param_name} too long")
        
        for char in value:
            if char in DANGEROUS_SHELL_CHARS:
                raise HTTPException(
                    status_code=400,
                    detail=f"{param_name} contains dangerous character: '{char}'"
                )
        
        return value.strip()
    
    @staticmethod
    def validate_path(path: str, base_dir: str, param_name: str = "path") -> str:
        """
        Validate file path.
        
        Check:
        1. No path traversal
        2. Resolves within base directory
        3. Absolute path
        """
        # Check path traversal patterns
        for pattern in PATH_TRAVERSAL_PATTERNS:
            if pattern.search(path):
                raise HTTPException(
                    status_code=400,
                    detail=f"{param_name} contains path traversal"
                )
        
        # Resolve absolute path
        base = Path(base_dir).resolve()
        requested = (base / path).resolve()
        
        try:
            requested.relative_to(base)
        except ValueError:
            raise HTTPException(
                status_code=403,
                detail=f"{param_name} is outside allowed directory"
            )
        
        return str(requested)
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Sanitize filename.
        
        Remove dangerous characters, ensure safe filename.
        """
        # Remove dangerous characters
        safe = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
        # Remove leading dots (hide files)
        safe = safe.lstrip('.')
        # Limit length
        safe = safe[:255]
        return safe or "unnamed"


# Global checker instance
safety = CommandSafetyChecker()
```

#### Pydantic输入校验

```python
# app/schemas/workflow.py
# =============================================================================
# Workflow request schemas - strict input validation
# =============================================================================

from pydantic import BaseModel, Field, validator
from typing import Optional, Literal


class WorkflowSubmitRequest(BaseModel):
    """Workflow submission request"""
    
    workflow_type: Literal["rna_seq", "atac_seq", "scRNA_seq"] = Field(
        ...,
        description="Workflow type"
    )
    
    genome: str = Field(
        ...,
        min_length=2,
        max_length=50,
        pattern=r'^[a-zA-Z0-9_]+$',
        description="Reference genome, e.g., hg38, mm10"
    )
    
    samples: list[dict] = Field(
        ...,
        min_length=1,
        max_length=100,
        description="Sample list"
    )
    
    cores: int = Field(
        default=8,
        ge=1,
        le=64,
        description="Number of CPU cores"
    )
    
    memory_gb: int = Field(
        default=32,
        ge=4,
        le=256,
        description="Memory size (GB)"
    )
    
    extra_params: Optional[dict] = Field(
        default=None,
        description="Extra Snakemake parameters"
    )
    
    @validator('genome')
    def validate_genome(cls, v):
        allowed = {'hg38', 'hg19', 'mm10', 'mm9', 'dm6', 'ce11'}
        if v not in allowed:
            raise ValueError(f"genome must be one of: {allowed}")
        return v
    
    @validator('samples')
    def validate_samples(cls, v):
        if not v:
            raise ValueError("samples list cannot be empty")
        required_keys = {'sample_id', 'fastq_1'}
        for i, sample in enumerate(v):
            missing = required_keys - set(sample.keys())
            if missing:
                raise ValueError(f"Sample {i} missing required fields: {missing}")
        return v


class TaskCancelRequest(BaseModel):
    """Task cancellation request"""
    
    task_id: str = Field(
        ...,
        min_length=36,
        max_length=36,
        pattern=r'^[0-9a-f-]{36}$',
        description="Task UUID"
    )
    
    force: bool = Field(
        default=False,
        description="Force kill (SIGKILL)"
    )
```

---

### 6.9.5 Master Node Internal Network Isolation

#### Network隔离策略

```yaml
# docker-compose.master.yml - Network isolation section
networks:
  omicshub_master_net:
    driver: bridge
    internal: true  # Block external access, only internal Docker communication
    ipam:
      config:
        - subnet: 172.21.0.0/16
```

> **Note**: Setting `internal: true` completely blocks external network access.
> If Master needs to callback to the Web platform, use a shared network or host mode.

#### iptables防火墙规则（宿主机层面）

```bash
#!/bin/bash
# firewall_rules.sh - Master node firewall rules

# Clear existing rules
iptables -F
iptables -X

# Default policy: deny all
iptables -P INPUT DROP
iptables -P FORWARD DROP
iptables -P OUTPUT ACCEPT

# Allow loopback
iptables -A INPUT -i lo -j ACCEPT

# Allow established connections
iptables -A INPUT -m state --state ESTABLISHED,RELATED -j ACCEPT

# Allow SSH (if needed for maintenance)
iptables -A INPUT -p tcp --dport 22 -s 10.0.0.0/8 -j ACCEPT

# Allow Web platform to access Master API (port 8001)
# Web platform container IP range
iptables -A INPUT -p tcp --dport 8001 -s 172.20.0.0/16 -j ACCEPT

# Allow internal Docker network
iptables -A INPUT -s 172.21.0.0/16 -j ACCEPT

# Log and drop other connections
iptables -A INPUT -j LOG --log-prefix "[OMICSHUB DROP] "
iptables -A INPUT -j DROP

# Save rules
iptables-save > /etc/iptables/rules.v4

echo "Firewall rules applied"
```

---

### 6.9.6 Callback Interface Security

#### Web平台回调端点

```python
# app/api/internal/callback.py
# =============================================================================
# Internal callback endpoints - only accessible by Master node
# =============================================================================

from fastapi import APIRouter, Depends, HTTPException, Header, Request
from app.core.config import settings

router = APIRouter(prefix="/internal/callback", tags=["internal"])


async def verify_internal_token(x_internal_token: str = Header(...)):
    """Verify internal callback token"""
    if x_internal_token != settings.INTERNAL_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid internal token")
    return True


async def verify_internal_ip(request: Request):
    """Verify request comes from internal network"""
    client_ip = request.client.host
    allowed_prefixes = ("172.20.", "172.21.", "127.0.")
    if not any(client_ip.startswith(p) for p in allowed_prefixes):
        raise HTTPException(status_code=403, detail="Access denied")
    return True


@router.post("/task-complete", dependencies=[Depends(verify_internal_token)])
async def task_complete_callback(
    data: dict,
    request: Request,
    _ip=Depends(verify_internal_ip)
):
    """
    Task completion callback - only accessible by Master node.
    
    Security:
    - Nginx layer IP whitelist
    - Header token verification
    - Not exposed on public network
    """
    task_id = data.get("task_id")
    status = data.get("status")
    
    # Update task status
    from app.services.task import update_task_status
    await update_task_status(task_id, status)
    
    # Send notification to user
    await notify_user_task_complete(task_id, status)
    
    return {"status": "ok"}
```

---

### 6.9.7 安全策略总结

| 层级 | 措施 | 说明 |
|------|------|------|
| **网络层** | Docker internal network | Master节点不暴露公网 |
| | Nginx IP whitelist | /internal/仅允许Docker内网IP |
| | iptables防火墙 | 宿主机层面限制入站连接 |
| **应用层** | JWT认证 | API请求携带有效令牌 |
| | RBAC权限控制 | 超级用户/普通用户角色区分 |
| | 文件系统隔离 | /data/uploads/{user_id}/ |
| **数据层** | Docker Secrets | 密钥不存储在环境变量 |
| | PostgreSQL密码 | 强密码，通过Secret注入 |
| | Redis密码 | 可选，建议设置 |
| **执行层** | 参数校验 | Pydantic严格校验所有输入 |
| | 命令注入防护 | 用户参数写入config.yaml |
| | 路径校验 | os.path.abspath，禁止..穿越 |
| | 进程隔离 | start_new_session=True，killpg终止 |
| **通信层** | Internal Token | Master回调需携带X-Internal-Token |
| | HTTPS | 生产环境启用SSL/TLS |

---

## 6.10 运维操作手册

### 6.10.1 常用操作命令

```bash
# === 一键部署 ===
./init.sh

# === 查看服务状态 ===
docker-compose ps
docker-compose logs -f web
docker-compose logs -f celery_worker
docker-compose logs -f master  # remote mode

# === 重启服务 ===
docker-compose restart web
docker-compose restart celery_worker

# === 数据库迁移 ===
docker-compose exec web alembic revision --autogenerate -m "add new table"
docker-compose exec web alembic upgrade head
docker-compose exec web alembic downgrade -1

# === 备份 ===
./scripts/backup.sh

# === 更新部署 ===
git pull
docker-compose pull
docker-compose up -d --build

# === 查看资源使用 ===
docker stats

# === 清理旧数据 ===
docker system prune -f  # 清理未使用的镜像和容器
docker volume prune -f  # 清理未使用的卷（谨慎！）
```

### 6.10.2 故障排查

| 现象 | 可能原因 | 解决方案 |
|------|----------|----------|
| Web无法启动 | 数据库未就绪 | 检查db健康状态 `docker-compose ps` |
| 任务提交失败 | Worker未运行 | `docker-compose ps` 检查celery_worker |
| 权限错误 | UID/GID不匹配 | `chown -R 1000:1000 /data/omicshub` |
| 存储空间不足 | 日志或结果文件过大 | 清理 `/data/omicshub/tmp/` 和日志 |
| Master连接失败 | 网络不通 | 检查Docker网络互联配置 |
| WebSocket断开 | Nginx配置问题 | 检查nginx.conf proxy设置 |

### 6.10.3 监控与健康检查

```bash
# 系统健康检查脚本
#!/bin/bash
# health_check.sh

echo "=== OmicsHub Health Check ==="

# Check all services
echo "--- Services ---"
docker-compose ps

# Check database
echo "--- Database ---"
docker-compose exec -T db pg_isready -U omicshub

# Check Redis
echo "--- Redis ---"
docker-compose exec -T redis redis-cli ping

# Check Web API
echo "--- Web API ---"
curl -sf http://localhost/api/v1/health && echo "OK" || echo "FAILED"

# Check disk usage
echo "--- Disk Usage ---"
df -h /data/omicshub

# Check memory
echo "--- Memory ---"
free -h

echo "=== Check Complete ==="
```

---

## 6.11 总结

OmicsHub的部署运维体系围绕以下核心原则设计：

1. **极简运维**：单维护者可管理，一键部署（`./init.sh`），所有配置集中管理
2. **双模式支持**：Local模式适合单机，Remote模式支持计算扩展，通过 `EXECUTION_MODE` 环境变量切换
3. **安全隔离**：多层安全策略（网络隔离、文件隔离、参数校验、Token认证）
4. **策略模式**：`ExecutionBackend` 抽象层实现执行引擎的无缝切换
5. **无锁执行**：每个任务独立目录 + `--nolock` 参数确保多任务并发安全
6. **优雅取消**：SIGTERM -> 等待 -> SIGKILL 的进程终止策略
7. **实时监控**：WebSocket日志流 + 进度解析 + Flower监控面板

> **部署建议**：组内服务器资源有限的情况下，建议先用Local模式部署，当计算需求增长时再迁移到Remote模式。两个模式共享相同的业务逻辑，迁移只需修改环境变量即可。


.PHONY: help dev dev-worker dev-rocketmq-worker test test-bridge test-frontend test-all lint format type-check migrate migrate-new migrate-merge migrate-rollback docker-network docker-runtime-dirs docker-fix-permissions docker-up docker-up-pgvector pgvector-acceptance polardb-verify knowledge-reindex docker-up-rocketmq docker-up-rocketmq-worker docker-up-matrix-dev docker-build-enrichment docker-build-deg docker-build-sandboxes docker-build-all-images docker-build-worker docker-up-worker docker-up-all docker-down docker-down-worker docker-down-all docker-logs docker-logs-worker docker-clean docker-purge docker-start docker-reload docker-dev-refresh wait-web clean init-admin init-cookies check-alembic-heads sync-knowledge

help: ## 显示所有可用命令
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

dev: ## 启动后端开发服务器
	uv run uvicorn omichub.main:app --reload --host 0.0.0.0 --port 8000

dev-worker: ## 启动 Celery Worker
	uv run celery -A omichub.infrastructure.celery_app.celery worker --loglevel=info

dev-rocketmq-worker: ## 启动 RocketMQ Worker（需先启动 RocketMQ broker）
	uv run python -m omichub.infrastructure.task_queue.rocketmq_worker --queues analysis,blast_search,blast_db_build,phylo_tree,phylo_tree_highmem,mas_apptainer

dev-beat: ## 启动 Celery Beat
	uv run celery -A omichub.infrastructure.celery_app.celery beat --loglevel=info

dev-flower: ## 启动 Flower 监控
	uv run celery -A omichub.infrastructure.celery_app.celery flower --port=5555

test: ## 运行测试
	uv run pytest tests/ -v

test-bridge: ## 运行 AgentTeams Bridge 独立测试工程（MinIO/CaseStore 等，不收编进根 pytest 防双收集）
	cd integrations/agentteams/bridge && uv run pytest -q

test-frontend: ## 运行前端单测与类型检查
	cd frontend && npx vitest run && npx vue-tsc --noEmit

test-all: test test-bridge ## 全量测试：根测试（unit/integration/e2e）+ Bridge 测试工程

test-cov: ## 运行测试并生成覆盖率报告
	uv run pytest tests/ --cov=src/omichub --cov-report=term-missing --cov-report=html

lint: ## 代码检查
	uv run ruff check src/ tests/

format: ## 代码格式化
	uv run ruff format src/ tests/
	uv run ruff check --fix src/ tests/

type-check: ## 类型检查
	uv run mypy src/omichub/

migrate: ## 执行数据库迁移
	uv run alembic upgrade head

migrate-new: ## 创建新迁移 (用法: make migrate-new m="migration name")
	uv run alembic revision --autogenerate -m "$(m)"

migrate-rollback: ## 回滚上一个迁移
	uv run alembic downgrade -1

migrate-merge: ## 自动合并 Alembic 多分支 (Multiple Heads 修复)
	@echo "=> 正在合并 Alembic 多分支..."
	uv run alembic merge heads -m "auto-merge parallel branches"
	uv run alembic upgrade head
	@echo "=> ✅ 多分支合并完成，数据库已更新至最新版本。"

# ===== Docker Compose 编排（主栈 + 独立 Worker 栈，单机逻辑解耦）=====
COMPOSE_MAIN   := docker compose --env-file .env -f deploy/docker/docker-compose.yml
COMPOSE_PGVECTOR := $(COMPOSE_MAIN) -f deploy/docker/docker-compose.pgvector.yml
COMPOSE_CROSS_WEB := $(COMPOSE_MAIN) -f deploy/docker/docker-compose.cross-web.yml
COMPOSE_MAIN_AGENTTEAMS := $(COMPOSE_MAIN) -f deploy/agentteams/docker-compose.omichub-proxy.yml
COMPOSE_PGVECTOR_AGENTTEAMS := $(COMPOSE_PGVECTOR) -f deploy/agentteams/docker-compose.omichub-proxy.yml
COMPOSE_AGENTTEAMS := docker compose --project-name agentteams -f deploy/agentteams/docker-compose.agentteams.yml
COMPOSE_WORKER := ./scripts/worker-compose.sh
COMPOSE_ALL    := docker compose --env-file .env -f deploy/docker/docker-compose.yml
AGENTTEAMS_BRIDGE_ENV_FILE ?= deploy/agentteams/bridge.env
AGENTTEAMS_WORKER_ENV_FILE ?= deploy/agentteams/worker.env
ENV_OMICHUB_NETWORK_NAME := $(shell test -f .env && sed -n 's/^OMICHUB_NETWORK_NAME=//p' .env | head -n 1)
ENV_OMICHUB_SANDBOX_NETWORK_NAME := $(shell test -f .env && sed -n 's/^OMICHUB_SANDBOX_NETWORK_NAME=//p' .env | head -n 1)
ENV_OMICHUB_BRIDGE_GATEWAY_NETWORK := $(shell test -f .env && sed -n 's/^OMICHUB_BRIDGE_GATEWAY_NETWORK=//p' .env | head -n 1)
ENV_OMICHUB_DATA_ROOT := $(shell test -f .env && sed -n 's/^OMICHUB_DATA_ROOT=//p' .env | head -n 1)
ENV_REDIS_PASSWORD := $(shell test -f .env && sed -n 's/^REDIS_PASSWORD=//p' .env | head -n 1)
DOCKER_NETWORK ?= $(if $(ENV_OMICHUB_NETWORK_NAME),$(ENV_OMICHUB_NETWORK_NAME),omichub_net)
SANDBOX_NETWORK ?= $(if $(ENV_OMICHUB_SANDBOX_NETWORK_NAME),$(ENV_OMICHUB_SANDBOX_NETWORK_NAME),omichub-sandbox-net)
BRIDGE_GATEWAY_NETWORK ?= $(if $(ENV_OMICHUB_BRIDGE_GATEWAY_NETWORK),$(ENV_OMICHUB_BRIDGE_GATEWAY_NETWORK),omichub_bridge_gateway)
ENRICHMENT_DOCKER_IMAGE ?= omichub-r-enrichment:v1
DEG_DOCKER_IMAGE ?= omichub-r-deg:v1
ROCKETMQ_IMAGE ?= apache/rocketmq:5.3.2
# ===== 部署版本可观测：构建期注入 git SHA 短号与 UTC 构建时间 =====
# 主栈 web/beat/flower 经 OMICHUB_BUILD_* 传入镜像（/health 暴露），
# AgentTeams Bridge 经 BRIDGE_BUILD_* 传入（/healthz 暴露）；compose 内缺省 unknown。
GIT_SHA := $(shell git rev-parse --short HEAD 2>/dev/null || echo unknown)
BUILD_TIME := $(shell date -u +%Y-%m-%dT%H:%M:%SZ)
export OMICHUB_BUILD_SHA ?= $(GIT_SHA)
export OMICHUB_BUILD_TIME ?= $(BUILD_TIME)
export BRIDGE_BUILD_SHA ?= $(GIT_SHA)
export BRIDGE_BUILD_TIME ?= $(BUILD_TIME)
# 镜像 tag 规范：推送/发布产物必须打 git SHA 短号 tag，禁止 latest 裸推（见 deploy/docker/README.md）。
IMAGE_TAG ?= $(GIT_SHA)
export IMAGE_TAG
DATA_ROOT ?= $(if $(ENV_OMICHUB_DATA_ROOT),$(ENV_OMICHUB_DATA_ROOT),/data/omichub)
PUID ?= $(shell id -u)
PGID ?= $(shell id -g)
REDIS_PASSWORD ?= $(if $(ENV_REDIS_PASSWORD),$(ENV_REDIS_PASSWORD),omichub)
export REDIS_PASSWORD

docker-network: ## 创建跨栈外部网络 + 终端网络（Studio 会话网络由 Manager 动态创建）
	@docker network create $(DOCKER_NETWORK) 2>/dev/null || true
	@docker network create $(SANDBOX_NETWORK) 2>/dev/null || true
	@docker network create $(BRIDGE_GATEWAY_NETWORK) 2>/dev/null || true

agentteams-worker-env: ## 从受控 Bridge 配置生成最小权限的 AgentTeams Worker 令牌环境文件
	@set -eu; \
		source_file="$(AGENTTEAMS_BRIDGE_ENV_FILE)"; target_file="$(AGENTTEAMS_WORKER_ENV_FILE)"; \
		if [ ! -f "$$source_file" ]; then echo "=> 缺少 $$source_file，无法生成 Worker 令牌环境"; exit 1; fi; \
		mkdir -p "$$(dirname "$$target_file")"; \
		umask 077; temporary_file="$$(mktemp "$${target_file}.XXXXXX")"; \
		trap 'rm -f "$$temporary_file"' EXIT; \
		sed -n -E '/^AGENTTEAMS_(AGENT_CODE|AGENT_VIZ|AGENT_SCRNA|AGENT_RNASEQ|AGENT_DATA|AGENT_ATACSEQ|AGENT_SCRNA_UPSTREAM|AGENT_SCRNA_INTEGRATION|AGENT_SCRNA_ADVANCED|AGENT_QC|AGENT_DELIVERY|AGENT_CLOUD_OPS|AGENT_GENERAL|AGENT_MCP_BUILDER|ANALYSIS_WORKER)_TOKEN=.+$$/p' "$$source_file" > "$$temporary_file"; \
		if [ "$$(wc -l < "$$temporary_file")" -ne 15 ]; then \
			sed -n 's/^BRIDGE_IDENTITIES=//p' "$$source_file" | tr ',' '\n' | \
			awk -F: 'BEGIN { map["agent-code"]="AGENTTEAMS_AGENT_CODE_TOKEN"; map["agent-viz"]="AGENTTEAMS_AGENT_VIZ_TOKEN"; map["agent-scrna"]="AGENTTEAMS_AGENT_SCRNA_TOKEN"; map["agent-rnaseq"]="AGENTTEAMS_AGENT_RNASEQ_TOKEN"; map["agent-data"]="AGENTTEAMS_AGENT_DATA_TOKEN"; map["agent-atacseq"]="AGENTTEAMS_AGENT_ATACSEQ_TOKEN"; map["agent-scrna-upstream"]="AGENTTEAMS_AGENT_SCRNA_UPSTREAM_TOKEN"; map["agent-scrna-integration"]="AGENTTEAMS_AGENT_SCRNA_INTEGRATION_TOKEN"; map["agent-scrna-advanced"]="AGENTTEAMS_AGENT_SCRNA_ADVANCED_TOKEN"; map["agent-qc"]="AGENTTEAMS_AGENT_QC_TOKEN"; map["agent-delivery"]="AGENTTEAMS_AGENT_DELIVERY_TOKEN"; map["agent-cloud-ops"]="AGENTTEAMS_AGENT_CLOUD_OPS_TOKEN"; map["agent-general"]="AGENTTEAMS_AGENT_GENERAL_TOKEN"; map["agent-mcp-builder"]="AGENTTEAMS_AGENT_MCP_BUILDER_TOKEN"; map["analysis-worker"]="AGENTTEAMS_ANALYSIS_WORKER_TOKEN" } $$1 in map { print map[$$1] "=" substr($$0, length($$1) + 2) }' > "$$temporary_file"; \
		fi; \
		if [ "$$(wc -l < "$$temporary_file")" -ne 15 ]; then echo "=> $$source_file 必须配置 14 个专家令牌和 analysis-worker 令牌"; exit 1; fi; \
		mv "$$temporary_file" "$$target_file"; chmod 600 "$$target_file"; \
		echo "=> 已生成最小权限 Worker 令牌环境：$$target_file"

docker-up-agentteams: docker-network agentteams-worker-env ## 构建并启动 AgentTeams Bridge、Gateway 与全部生产 Worker
	$(COMPOSE_AGENTTEAMS) --env-file .env --env-file $(AGENTTEAMS_WORKER_ENV_FILE) --profile agentteams-production up -d --build --force-recreate

docker-up-matrix-dev: ## 启动本机开发用 Matrix(Synapse)+Element 栈（协作室建房链路依赖，独立于主栈/AgentTeams 栈）
	@echo "=> 启动 matrix-dev（omichub-matrix-dev-synapse / element）..."
	docker compose -f deploy/agentteams/matrix-dev/docker-compose.yml up -d

docker-runtime-dirs: ## 准备关键运行目录与非 root 容器写入权限（docker-up/reload 自动执行）
	@echo "=> 准备运行目录权限..."
	@docker run --rm -v $(DATA_ROOT):/data-root python:3.11-slim sh -c 'mkdir -p /data-root/logs/app /data-root/logs/celery/tasks /data-root/logs/nginx /data-root/logs/snakemake /data-root/users /data-root/uploads /data-root/.tmp /data-root/.conda_envs /data-root/omichub_data/_pgdata /data-root/omichub_data/_redis /data-root/omichub_data/_minio && chown -R $(PUID):$(PGID) /data-root/logs/app /data-root/logs/celery /data-root/logs/snakemake /data-root/uploads /data-root/.tmp /data-root/.conda_envs && chown $(PUID):$(PGID) /data-root/users'

docker-fix-permissions: ## 手动修复 /data/omichub 权限事故（登录 500 / PermissionError 时使用）
	@echo "=> 修复 /data/omichub 非 root 服务写入权限..."
	@docker run --rm -v $(DATA_ROOT):/data-root python:3.11-slim sh -c 'mkdir -p /data-root/logs/app /data-root/logs/celery/tasks /data-root/logs/nginx /data-root/logs/snakemake /data-root/users /data-root/uploads /data-root/.tmp /data-root/.conda_envs /data-root/omichub_data/_pgdata /data-root/omichub_data/_redis && chown -R $(PUID):$(PGID) /data-root/logs/app /data-root/logs/celery /data-root/logs/snakemake /data-root/users /data-root/uploads /data-root/.tmp /data-root/.conda_envs'
	@echo "=> 权限修复完成。建议执行: docker restart omichub-web omichub-worker omichub-beat"

docker-up: docker-network ## 启动主栈 (web/db/redis/nginx/beat/flower)
	@$(MAKE) --no-print-directory docker-runtime-dirs
	$(COMPOSE_MAIN) up -d
	@$(MAKE) --no-print-directory wait-web
	@$(MAKE) --no-print-directory check-alembic-heads

docker-up-pgvector: docker-network ## 启动主栈并使用 pgvector/PgBouncer/Exporter 验收叠加
	@$(MAKE) --no-print-directory docker-runtime-dirs
	$(COMPOSE_PGVECTOR) up -d
	@$(MAKE) --no-print-directory wait-web
	@$(MAKE) --no-print-directory check-alembic-heads

pgvector-acceptance: ## 执行本地 pgvector、备份恢复、指标和可选只读端点验收
	./scripts/accept_pgvector_docker.sh

polardb-verify: ## 验证 DATABASE_URL（及可选 READONLY_DATABASE_URL）的 pgvector/HNSW/副本状态
	./scripts/verify_polardb_postgres.sh

knowledge-reindex: ## 在 web 容器中重建已发布知识库的 chunk/向量
	docker exec omichub-web python scripts/reindex_knowledge_vectors.py

docker-up-cross-web: ## 启动跨机器控制面（要求 .env 已配置控制面私网 IP 与端口）
	@$(MAKE) --no-print-directory docker-runtime-dirs
	$(COMPOSE_CROSS_WEB) up -d
	@$(MAKE) --no-print-directory wait-web
	@$(MAKE) --no-print-directory check-alembic-heads

docker-up-rocketmq: docker-network ## 启动 RocketMQ NameServer/Broker（保留 Celery）
	$(COMPOSE_MAIN) --profile rocketmq up -d rocketmq-namesrv rocketmq-broker

docker-up-rocketmq-worker: ## 启动 RocketMQ Worker（与 Celery worker 可并行）
	$(COMPOSE_WORKER) --profile rocketmq up -d rocketmq-worker

wait-web: ## 等待 OmicHub Web API 健康（失败时输出后端日志）
	@echo "=> 等待 omichub-web 健康..."
	@for attempt in $$(seq 1 60); do \
		status=$$(docker inspect --format '{{.State.Status}}' omichub-web 2>/dev/null || true); \
		health=$$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' omichub-web 2>/dev/null || true); \
		if [ "$$health" = "healthy" ]; then \
			echo "=> omichub-web 已健康。"; exit 0; \
		fi; \
		if [ "$$status" = "exited" ] || [ "$$status" = "dead" ]; then \
			echo "=> omichub-web 启动失败，最近日志：" >&2; \
			docker logs --tail 120 omichub-web >&2 || true; \
			exit 1; \
		fi; \
		sleep 2; \
	done; \
	echo "=> 等待 omichub-web 健康超时，最近日志：" >&2; \
	docker logs --tail 120 omichub-web >&2 || true; \
	exit 1

docker-build-enrichment: ## 构建 GO / KEGG 富集分析 R 运行时镜像
	docker build -t $(ENRICHMENT_DOCKER_IMAGE) -f deploy/docker/Dockerfile.enrichment tool_configs/enrichments

docker-build-deg: ## 构建 DEG 差异表达分析 R 运行时镜像（DESeq2 + edgeR，支持 1v1 无重复）
	docker build -t $(DEG_DOCKER_IMAGE) -f deploy/docker/Dockerfile.deg tool_configs/deg

docker-build-synteny: ## 构建 MCScanX 思路的基因组共线性分析运行时镜像
	docker build -t omichub-synteny:v1 -f deploy/docker/Dockerfile.synteny tool_configs/synteny

docker-build-sandboxes: ## 重建全部沙盒/分析运行时镜像（runtime 三件套 + 旧沙盒池 + studio base/bio + 终端全家桶，任一失败即中止）
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🐳 OmicHub 沙盒/分析运行时镜像全量重建（共 12 个镜像）        ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@echo ""
	@echo "🧪 步骤 1/5：Studio 运行时三件套（omichub-analysis core/plot/scrna）..."
	deploy/runtime-images/build.sh
	@echo "   ✅ 步骤 1/5 完成"
	@echo ""
	@echo "📦 步骤 2/5：旧沙盒池镜像（omichub/sandbox-base:latest）..."
	docker build -t omichub/sandbox-base:latest -f deploy/sandbox/Dockerfile deploy/sandbox
	@echo "   ✅ 步骤 2/5 完成"
	@echo ""
	@echo "🛠️  步骤 3/5：Studio 旧镜像（omichub-sandbox base/bio）..."
	deploy/studio/build.sh
	@echo "   ✅ 步骤 3/5 完成"
	@echo ""
	@echo "💻 步骤 4/5：终端基础镜像（omichub/sandbox-terminal:latest）..."
	docker build -t omichub/sandbox-terminal:latest tool_configs/terminal/docker/
	@echo "   ✅ 步骤 4/5 完成"
	@echo ""
	@echo "🧬 步骤 5/5：终端子镜像 6 个（rnaseq/scrna/gatk/ggplot2/assembly/metagenomics）..."
	@i=0; for t in rnaseq scrna gatk ggplot2 assembly metagenomics; do \
		i=$$((i+1)); \
		echo ""; \
		echo "   ▶ [$$i/6] 构建 omichub/sandbox-$$t:latest ..."; \
		docker build -t omichub/sandbox-$$t:latest -f tool_configs/terminal/docker/Dockerfile.$$t tool_configs/terminal/docker/ || exit 1; \
		echo "   ✅ [$$i/6] omichub/sandbox-$$t:latest 完成"; \
	done
	@echo ""
	@echo "📋 镜像清单核对："
	@ok=0; miss=0; \
	for img in omichub-analysis:core-2026.07 omichub-analysis:plot-2026.07 omichub-analysis:scrna-2026.07 \
		omichub/sandbox-base:latest omichub-sandbox:base omichub-sandbox:bio omichub/sandbox-terminal:latest \
		omichub/sandbox-rnaseq:latest omichub/sandbox-scrna:latest omichub/sandbox-gatk:latest \
		omichub/sandbox-ggplot2:latest omichub/sandbox-assembly:latest omichub/sandbox-metagenomics:latest; do \
		if docker image inspect $$img >/dev/null 2>&1; then \
			echo "   ✅ $$img"; ok=$$((ok+1)); \
		else \
			echo "   ❌ 缺失 $$img"; miss=$$((miss+1)); \
		fi; \
	done; \
	echo ""; \
	echo "=> 共 13 个镜像：就位 $$ok 个，缺失 $$miss 个"; \
	if [ $$miss -gt 0 ]; then echo "=> ⚠️  有镜像缺失，请检查上方构建日志"; exit 1; fi
	@echo "=> ✅ 全部沙盒/分析运行时镜像构建完成"

docker-build-all-images: docker-build-sandboxes docker-build-worker ## 一键重建所有镜像（沙盒/分析运行时 + 富集/DEG/Worker + 主栈/Worker compose 栈）
	$(COMPOSE_MAIN) build
	$(COMPOSE_WORKER) build
	@echo "=> ✅ 所有镜像重建完成"

docker-build-worker: docker-build-enrichment docker-build-deg ## 构建富集/DEG 运行时、通用 Worker 与系统发育 Worker 镜像
	$(COMPOSE_WORKER) build worker phylo-worker

docker-up-worker: docker-network docker-build-enrichment docker-build-deg ## 构建并启动富集/DEG 运行时、通用与系统发育 Worker 栈
	@python3 scripts/render_worker_config.py
	@set -a; . data/.worker-config.env; test ! -f .env || . ./.env; set +a; \
		$(MAKE) --no-print-directory docker-runtime-dirs DATA_ROOT="$$WORKER_SHARED_DATA_DIR"
	$(COMPOSE_WORKER) up -d --build worker phylo-worker

docker-up-cross-worker: docker-build-enrichment docker-build-deg ## 启动跨机器 Worker（要求 .env 已配置 OMICHUB_CONTROL_HOST）
	@python3 scripts/render_worker_config.py
	@set -a; . data/.worker-config.env; test ! -f .env || . ./.env; set +a; \
		$(MAKE) --no-print-directory docker-runtime-dirs DATA_ROOT="$$WORKER_SHARED_DATA_DIR"
	OMICHUB_WORKER_COMPOSE_OVERLAY=deploy/docker/docker-compose.cross-worker.yml \
		$(COMPOSE_WORKER) up -d --build worker phylo-worker

docker-up-all: docker-network ## 启动主栈 + Worker（一键全启）
	@$(MAKE) --no-print-directory docker-runtime-dirs
	$(COMPOSE_MAIN) up -d
	@$(MAKE) --no-print-directory docker-up-worker
	@$(MAKE) --no-print-directory check-alembic-heads

docker-down: ## 停止主栈
	$(COMPOSE_MAIN) down

docker-down-worker: ## 停止 Worker 栈
	$(COMPOSE_WORKER) down

docker-down-cross-web: ## 停止跨机器控制面
	$(COMPOSE_CROSS_WEB) down

docker-down-cross-worker: ## 停止跨机器 Worker
	OMICHUB_WORKER_COMPOSE_OVERLAY=deploy/docker/docker-compose.cross-worker.yml \
		$(COMPOSE_WORKER) down

docker-down-all: ## 停止主栈 + Worker
	$(COMPOSE_ALL) down

docker-stop-all: ## 停止全平台（主栈 + Worker + AgentTeams），可用 docker-reload 重新拉起
	@echo "=> 停止 AgentTeams Bridge / Gateway / Worker..."
	-@$(COMPOSE_AGENTTEAMS) down --remove-orphans 2>/dev/null || true
	-@docker ps -a --filter "name=agentteams-" -q | xargs -r docker rm -f 2>/dev/null
	@echo "=> 停止 Worker 计算栈..."
	-@$(COMPOSE_WORKER) down --remove-orphans 2>/dev/null || true
	@echo "=> 停止主栈（web / beat / nginx / db / cache / studio）..."
	-@$(COMPOSE_MAIN) down --remove-orphans 2>/dev/null || true
	-@docker ps -a --format '{{.Names}}' | grep '^omichub-' | grep -v 'matrix-dev' | xargs -r docker rm -f 2>/dev/null
	-@docker ps -a --filter "name=studio-" -q | xargs -r docker rm -f 2>/dev/null
	@echo "✅ 全平台已停止，执行 make docker-reload 可重新拉起"

docker-logs: ## 查看主栈日志
	$(COMPOSE_MAIN) logs -f

docker-logs-worker: ## 查看 Worker 日志
	$(COMPOSE_WORKER) logs -f

docker-clean: ## 清理容器与网络（保留数据卷，不删镜像）
	$(COMPOSE_ALL) down --remove-orphans

docker-purge: ## [危险] 彻底清理 Docker 资源：容器+数据卷+网络+本地镜像+前端构建产物（保留宿主机 /data/omichub 数据）
	@echo "=> 停止并删除主栈与 Worker 栈容器及命名数据卷..."
	-$(COMPOSE_MAIN) down --volumes --remove-orphans 2>/dev/null
	-$(COMPOSE_WORKER) down --volumes --remove-orphans 2>/dev/null
	-docker rm -f omichub-nginx omichub-web omichub-beat omichub-flower omichub-db omichub-cache omichub-worker omichub-phylo-worker omichub-studio-egress-proxy 2>/dev/null
	-@docker ps -a --filter "name=studio-" -q | xargs -r docker rm -f 2>/dev/null
	@echo "=> 删除所有 OmicHub 数据卷（含 docker_ 前缀命名卷）..."
	-docker volume rm $$(docker volume ls -q --filter name=docker_) 2>/dev/null
	@echo "=> 删除 omichub 网络（含沙盒与 Studio 会话网络）..."
	-docker network rm $(DOCKER_NETWORK) $(SANDBOX_NETWORK) 2>/dev/null
	-@docker network ls --filter "name=studio-" -q | xargs -r docker network rm 2>/dev/null
	@echo "=> 删除本地构建镜像（主栈 / Worker / 沙盒终端 / 分析运行时 / 富集 R）..."
	-docker rmi $$(docker images --filter reference=docker-web --filter reference=docker-beat --filter reference=docker-flower --filter reference=docker-studio-egress-proxy --filter reference=omichub-worker --filter reference=omichub-phylo-worker --filter reference=omichub-r-enrichment --filter reference=omichub/sandbox-terminal --filter reference=omichub-analysis -q) 2>/dev/null
	@echo "=> 清理前端构建产物..."
	rm -rf frontend/dist
	@echo "=> Docker 资源清理完成"
	@echo "   注：数据库/用户文件/日志等持久化在宿主机 $(DATA_ROOT)（bind mount），purge 不会删除；"
	@echo "       如需一并清空数据，请手动执行: sudo rm -rf $(DATA_ROOT)"

docker-start: ## 彻底重建：清空一切 + 重建镜像 + 构建前端 + 启动全部服务
	@$(MAKE) --no-print-directory docker-purge
	@echo "=> 构建前端..."
	cd frontend && npm run build
	@echo "=> 重建 Docker 镜像..."
	$(COMPOSE_MAIN) build --no-cache
	$(COMPOSE_WORKER) build --no-cache
	@$(MAKE) --no-print-directory docker-build-enrichment
	@$(MAKE) --no-print-directory docker-build-deg
	@echo "=> 启动全部服务..."
	@$(MAKE) --no-print-directory docker-network
	@$(MAKE) --no-print-directory docker-runtime-dirs
	$(COMPOSE_MAIN) up -d
	$(COMPOSE_WORKER) up -d
	@$(MAKE) --no-print-directory check-alembic-heads

frontend-install: ## 安装前端依赖
	cd frontend && npm install

frontend-dev: ## 启动前端开发服务器
	cd frontend && npm run dev

frontend-build: ## 构建前端生产版本
	cd frontend && npm run build

runtime-images-build: ## 构建独立分析运行时镜像（core / plot / scrna）
	deploy/runtime-images/build.sh

docker-reload: docker-network ## 重新构建前端并刷新 pgvector 主栈 + RocketMQ + AgentTeams Bridge + Worker (开发用)
	@echo ""
	@echo "╔══════════════════════════════════════════════════════════════╗"
	@echo "║  🚀 OmicHub 开发环境热重载                                    ║"
	@echo "║  重新构建前端 + pgvector + RocketMQ + Bridge + Worker       ║"
	@echo "╚══════════════════════════════════════════════════════════════╝"
	@$(MAKE) --no-print-directory docker-runtime-dirs
	@echo ""
	@echo "📦 步骤 1/11：清理残留容器，避免旧容器占用端口或挂载..."
	-@docker ps -a --format '{{.Names}}' | grep '^omichub-' | grep -v 'matrix-dev' | xargs -r docker rm -f 2>/dev/null
	-@docker ps -a --filter "name=studio-" -q | xargs -r docker rm -f 2>/dev/null
	-@$(COMPOSE_AGENTTEAMS) down --remove-orphans 2>/dev/null || true
	-@docker ps -a --filter "name=agentteams-" -q | xargs -r docker rm -f 2>/dev/null
	@echo ""
	@echo "🐳 步骤 2/11：构建终端沙盒镜像（已存在则跳过，删除镜像后自动重建）..."
	@docker image inspect omichub/sandbox-terminal:latest >/dev/null 2>&1 && \
		echo "   ⏭️  omichub/sandbox-terminal:latest 已存在，跳过构建" || \
		docker build -t omichub/sandbox-terminal:latest tool_configs/terminal/docker/
	@echo ""
	@echo "🧪 步骤 3/11：构建 Studio 运行时镜像（core/plot/scrna 均已存在则跳过）..."
	@if docker image inspect omichub-analysis:core-2026.07 >/dev/null 2>&1 && \
	    docker image inspect omichub-analysis:plot-2026.07 >/dev/null 2>&1 && \
	    docker image inspect omichub-analysis:scrna-2026.07 >/dev/null 2>&1; then \
		echo "   ⏭️  omichub-analysis 三个运行时镜像均已存在，跳过构建"; \
	else \
		deploy/runtime-images/build.sh; \
	fi
	@echo ""
	@echo "🧬 步骤 4/11：构建 GO / KEGG 富集 R 运行时镜像（已存在则跳过）..."
	@docker image inspect $(ENRICHMENT_DOCKER_IMAGE) >/dev/null 2>&1 && \
		echo "   ⏭️  $(ENRICHMENT_DOCKER_IMAGE) 已存在，跳过构建" || \
		$(MAKE) --no-print-directory docker-build-enrichment
	@echo ""
	@echo "📊 步骤 5/11：构建 DEG 差异表达分析 R 运行时镜像（已存在则跳过）..."
	@docker image inspect $(DEG_DOCKER_IMAGE) >/dev/null 2>&1 && \
		echo "   ⏭️  $(DEG_DOCKER_IMAGE) 已存在，跳过构建" || \
		$(MAKE) --no-print-directory docker-build-deg
	@echo ""
	@echo "🚀 步骤 6/11：拉取 RocketMQ NameServer/Broker 官方镜像..."
	@docker pull $(ROCKETMQ_IMAGE)
	@echo ""
	@echo "⚡ 步骤 7/11：重新构建前端生产包（vite build）..."
	cd frontend && npm run build
	@echo ""
	@echo "🌐 步骤 8/11：重新构建并启动 pgvector 主栈服务与 RocketMQ..."
	$(COMPOSE_PGVECTOR_AGENTTEAMS) --profile rocketmq up -d --build
	@$(MAKE) --no-print-directory wait-web
	@echo ""
	@echo "🔗 步骤 9/11：构建并启动 AgentTeams Bridge、Gateway 与生产 Worker..."
	@$(MAKE) --no-print-directory docker-up-agentteams
	@$(MAKE) --no-print-directory docker-up-matrix-dev
	@echo ""
	@echo "🔧 步骤 10/11：构建并启动 Celery 与 RocketMQ Worker 计算栈..."
	$(COMPOSE_WORKER) --profile rocketmq up -d --build worker phylo-worker rocketmq-worker
	@echo ""
	@echo "🗄️  步骤 11/11：检查数据库迁移状态、同步知识库并清理悬空镜像..."
	@$(MAKE) --no-print-directory check-alembic-heads
	@$(MAKE) --no-print-directory sync-knowledge
	@echo ""
	@echo "🧹 清理悬空镜像（--build 重建后遗留的 <none> 中间层）..."
	-@docker image prune -f 2>/dev/null
	@echo ""
	@echo "✅ 热重载完成！访问地址：http://localhost:8888"
	@echo ""

docker-dev-refresh: ## 轻量热刷新：前端 build + 重启 web/beat/nginx + 跑迁移（日常改代码/YAML 用，秒级，不重建镜像）
	@echo ""
	@echo "⚡ 步骤 1/3：前端生产包构建（vite build；nginx 直接读挂载的 dist）..."
	cd frontend && npm run build
	@echo ""
	@echo "🔄 步骤 2/3：重启 web / beat / nginx（src/data/alembic/flows/tool_configs 均为 bind mount，重启即生效；"
	@echo "   vite 重建 dist 后旧 nginx 进程持有旧目录句柄，必须一并重启）..."
	$(COMPOSE_MAIN) restart web beat nginx
	@echo ""
	@echo "🗄️  步骤 3/3：应用数据库迁移（web entrypoint 启动时也会自动执行，这里确保即时生效）..."
	@docker exec omichub-web alembic upgrade head
	@echo ""
	@echo "✅ 刷新完成！访问地址：http://localhost:8888"
	@echo "   提示：仅 pyproject.toml / uv.lock / Dockerfile 变更时才需要 make docker-reload（--build 重建镜像）；"
	@echo "        data/ai/*.yaml 与提示词按 mtime/调用热重载，改完刷新页面即可，无需执行本命令。"
	@echo ""

sync-knowledge: wait-web ## 同步通用、QC、Cloud 知识库及已登记 Wiki 正文到数据库
	@echo ""
	@echo "📚 同步通用知识库与已登记 Wiki 正文..."
	@echo "   （说明：知识库以数据库为权威源，直接改 Markdown 源文件后需要此步骤网页才生效）"
	@docker exec omichub-web python scripts/sync_knowledge_from_files.py \
		--meta-yaml docs/knowledge/meta.yaml \
		--auto-admin
	@echo ""
	@echo "🧪 同步 QC 知识库（递归 Markdown + PDF/图片附件索引）..."
	@docker exec omichub-web python scripts/import_qc_knowledge.py --auto-admin
	@echo ""
	@echo "☁️  同步 Cloud 知识库（递归 Markdown + PDF/DOCX/PPTX/图片附件索引）..."
	@docker exec omichub-web python scripts/import_cloud_knowledge.py --auto-admin
	@echo ""
	@echo "✅ 通用、QC 与 Cloud 知识库同步完成。"

init-admin: ## 初始化管理员账号 (首次部署使用)
	uv run python scripts/init_admin.py

init-cookies: ## 初始化默认饼干定价策略
	uv run python scripts/init_cookies.py

check-alembic-heads: ## 检测 Alembic 迁移是否存在多分支 (Multiple Heads)
	@echo "=> 🐱 正在检查 Alembic 数据库迁移状态..."
	@sleep 3  # 等待 web 容器就绪
	@HEAD_COUNT=$$(docker exec omichub-web alembic heads 2>/dev/null | grep -c '(head)' || echo 0); \
	if [ "$$HEAD_COUNT" -gt 1 ]; then \
		echo ""; \
		echo "====================================================================="; \
		echo "  🚨 [警告] Alembic 存在多个分支 (Multiple Heads)！"; \
		echo "  ⚠️  数据库处于分叉状态，登录等接口可能触发 500 错误。"; \
		echo ""; \
		echo "  🛠️  修复命令（直接复制执行）："; \
		echo ""; \
		echo "    make migrate-merge"; \
		echo ""; \
		echo "  或手动分步："; \
		echo "    docker exec omichub-web alembic merge heads -m \"merge parallel branches\""; \
		echo "    docker exec omichub-web alembic upgrade head"; \
		echo "====================================================================="; \
		echo ""; \
	else \
		echo "=> ✅ 数据库版本树正常，未发现分叉。"; \
	fi

check-migrations: ## 静态检查 Alembic 迁移链完整性（不依赖数据库）
	@uv run python scripts/check_migrations.py

clean: ## 清理临时文件
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null; \
	find . -type f -name "*.pyc" -delete; \
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov

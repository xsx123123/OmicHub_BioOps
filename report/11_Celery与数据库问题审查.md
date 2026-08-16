# 11. Celery 与数据库问题审查报告

> 审查日期：2026-07-21
> 审查范围：Celery 任务调度全链路 + PostgreSQL/Redis 数据库层

---

## 一、Celery 任务调度问题

### 1.1 严重 / 高优先级

#### C-01 无 `acks_late`，Worker 崩溃任务静默丢失

- **位置**：`src/omichub/infrastructure/celery_app/celery.py` 全局配置
- **现象**：所有任务使用默认的 `acks_late=False`，消息在 Worker 取到后立即确认。若 Worker 在执行过程中崩溃（OOM、Docker 重启），任务消息已从 Broker 中移除，无法重新投递。
- **影响**：Snakemake 分析任务最长运行 6 小时，期间任何 Worker 异常都会导致任务永久丢失，用户侧表现为"任务永远 running"。
- **建议**：
  ```python
  celery_app.conf.update(
      task_acks_late=True,
      task_reject_on_worker_lost=True,
  )
  ```
  配合幂等设计（任务开始时检查是否已完成），避免重复执行副作用。

#### C-02 每个任务 `asyncio.run()` 创建/销毁事件循环

- **位置**：所有 15+ 个任务入口（`tasks/analysis.py`、`tasks/download.py`、`tasks/mas.py` 等）
- **现象**：每次任务调用执行 `asyncio.run(main())`，创建全新事件循环 → 新建 DB 连接 → 执行 → 销毁连接 → 销毁循环。
- **影响**：
  - 高频任务（`mas.publish_outbox` 每 10s、`mas.consume_events` 每 5s）产生持续的连接风暴
  - 无法复用连接池，PostgreSQL 连接数随并发线性增长
  - 每次 TCP 握手 + PG 认证增加 ~5-15ms 延迟
- **建议**：
  - 短期：Celery Worker 使用 `--pool=gevent` 或 `--pool=threads` + 线程级事件循环复用
  - 中期：迁移到 `celery[gevent]` + `asgiref.sync.async_to_sync` 共享循环
  - 长期：评估 Dramatiq / ARQ 等原生 async 任务框架

#### C-03 单队列瓶颈（P0）

- **位置**：`celery.py` `task_routes` 配置
- **现象**：11 个任务模块中 9 个路由到同一个 `analysis` 队列。Worker 默认 `concurrency=CPU核数`，长任务（Snakemake 6h）占满 Worker 进程后，短周期任务（sandbox 回收 5min、MAS 事件消费 5s）被阻塞。
- **影响**：
  - MAS 事件消费延迟从 5s 退化到数小时
  - Sandbox 回收失效，过期容器堆积占用资源
  - 用户感知的"平台卡死"
- **建议**：
  ```python
  # 至少拆分为 3 个队列
  task_routes = {
      "tasks.analysis.*": {"queue": "analysis_long"},      # 长任务
      "tasks.mas.*": {"queue": "mas_realtime"},            # 实时事件
      "tasks.sandbox.*": {"queue": "maintenance"},         # 维护任务
      "tasks.storage.*": {"queue": "maintenance"},
      "tasks.cookie.*": {"queue": "maintenance"},
      "tasks.studio.*": {"queue": "analysis_long"},
  }
  ```
  对应启动独立 Worker：
  ```bash
  celery worker -Q analysis_long --concurrency=4 --prefetch-multiplier=1
  celery worker -Q mas_realtime --concurrency=2
  celery worker -Q maintenance --concurrency=2
  ```

#### C-04 优先级常量定义但从未使用

- **位置**：`src/omichub/infrastructure/celery_app/config.py`
- **现象**：定义了 `PRIORITY_HIGH=10`、`PRIORITY_NORMAL=5`、`PRIORITY_LOW=1`，但无任何任务调度或路由代码引用。
- **影响**：死代码，且 Redis Broker 对 priority 支持有限（仅 0-9 范围，需配置 `priority_steps`）。
- **建议**：要么删除死代码，要么在拆分队列后对 `analysis_long` 队列启用优先级：
  ```python
  celery_app.conf.broker_transport_options = {
      "priority_steps": [0, 3, 6, 9],
      "queue_order_strategy": "priority",
  }
  ```

#### C-05 无死信队列 / 失败任务隔离

- **位置**：全局
- **现象**：重试耗尽（BLAST `max_retries=1`、JBrowse `max_retries=2`）后任务直接丢弃。其余任务无重试机制，失败即终态。无 `on_failure` 回调、无 DLQ。
- **影响**：无法事后排查失败原因；无法自动重放；用户无法得到"任务失败可重试"的提示。
- **建议**：
  ```python
  from celery.app.task import Task

  class BaseTask(Task):
      def on_failure(self, exc, task_id, args, kwargs, einfo):
          # 写入 failed_tasks 表或发送到 DLQ
          ...

  celery_app.Task = BaseTask
  ```

### 1.2 中优先级

#### C-06 Beat 单点故障

- **位置**：`deploy/docker/docker-compose.prod.yml` — `replicas: 1`
- **现象**：Beat 容器无故障转移。容器挂掉后所有 7 个定时任务静默停止，无告警。
- **建议**：
  - 添加 `restart: unless-stopped` + 健康检查
  - 或使用 `celery-redbeat` / `django-celery-beat` 将调度持久化到 Redis/DB，支持多 Beat 实例竞选

#### C-07 `result_expires` 未配置

- **位置**：`celery.py` 全局配置
- **现象**：未设置 `result_expires`（Celery 默认 86400s=1天），但大部分任务未设 `ignore_result=True`。结果在 Redis DB2 积累。
- **影响**：Redis 内存持续增长（每个任务结果 ~1-5KB，日积月累）。
- **建议**：
  ```python
  celery_app.conf.update(
      result_expires=3600,  # 1小时后过期
      task_ignore_result=True,  # 全局默认不存结果
  )
  # 需要结果的任务单独开启
  @celery_app.task(ignore_result=False)
  ```

#### C-08 `broker_connection_retry_on_startup` 未设置

- **位置**：`celery.py`
- **现象**：Celery 5.3+ 要求显式设置此选项。未设置时 Worker 启动若 Redis 短暂不可用会直接退出。
- **建议**：
  ```python
  celery_app.conf.broker_connection_retry_on_startup = True
  ```

#### C-09 download.py 进度回调竞态条件

- **位置**：`src/omichub/infrastructure/celery_app/tasks/download.py`
- **现象**：`_on_progress` 回调和 `_progress_loop` 采样器使用不同的 session 实例并发写 `task.progress`。虽有 `poller_active` 标志位缓解，但非完全互斥。
- **影响**：极端情况下进度值回退或数据库唯一约束冲突。
- **建议**：统一为单一写入点，使用 `asyncio.Lock` 保护同一 session 的写入。

#### C-10 `cleanup_expired` 兼容 shim 绕过 Celery

- **位置**：`src/omichub/infrastructure/celery_app/tasks/analysis.py`
- **现象**：`cleanup_expired` 任务内部直接调用 `_real()` 函数而非 `.delay()`，若 Beat 调度到此任务，实际在 Beat 进程内同步执行。
- **影响**：Beat 进程被阻塞期间无法调度其他定时任务。
- **建议**：删除 shim，Beat 直接调度 `tasks.storage.cleanup_expired`。

#### C-11 无 `worker_max_memory_per_child`

- **位置**：`celery.py` — 仅设 `worker_max_tasks_per_child=10`
- **现象**：内存密集型任务（Snakemake 子进程、phylo MSA 计算）可能导致 Worker 子进程内存膨胀，但只在执行 10 个任务后才回收。
- **建议**：
  ```python
  celery_app.conf.worker_max_memory_per_child = 2 * 1024 * 1024  # 2GB
  ```

#### C-12 `phylo_tree` 队列主 Worker 不消费

- **位置**：`deploy/docker/docker-compose.worker.yml`
- **现象**：主 Worker 仅消费 `analysis,blast_search,blast_db_build`。`phylo_tree` 需单独启动 `phylo-worker` 服务。
- **影响**：运维人员若只启动主 Worker，系统发育树任务永久排队，无告警。
- **建议**：在 Flower / 监控中添加队列深度告警；或在文档中明确标注必须启动的服务列表。

#### C-13 `mas_apptainer` 队列无 Docker 消费者

- **位置**：`deploy/mas/mas-apptainer-worker.env.example`
- **现象**：仅有 env 示例文件，docker-compose 中无对应 service。RNAFlow 等 MAS 节点任务路由到此队列后无消费者。
- **影响**：MAS 工作流节点任务堆积。
- **建议**：在 `docker-compose.worker.yml` 中添加 `mas-worker` 服务，或提供独立的 `docker-compose.mas.yml`。

### 1.3 低优先级

| 编号 | 问题 | 位置 | 建议 |
|------|------|------|------|
| C-14 | `datetime.utcnow()` 已弃用 | `tasks/storage.py:81` | 改用 `datetime.now(timezone.utc)` |
| C-15 | `task_track_started=True` 与业务层状态重复 | `celery.py` | 关闭或仅用于 Flower 监控 |
| C-16 | Flower 默认弱密码 `admin:flower` | `docker-compose.yml` | 生产环境强制修改或禁用 |
| C-17 | 未强制 `task_serializer` 校验 | 全局 | 添加 `task_serializer="json"` 并在调用侧确保参数可序列化 |

---

## 二、数据库（PostgreSQL + Redis）问题

### 2.1 严重 / 高优先级

#### D-01 NullPool 导致无连接复用

- **位置**：`src/omichub/infrastructure/database/session.py:31`
- **现象**：引擎使用 `poolclass=NullPool`，每次获取 Session 都新建 TCP 连接，用完即关。
- **原因**：Celery 任务的 `asyncio.run()` 每次创建新事件循环，`QueuePool` 会跨循环复用连接导致 "Future attached to a different loop" 错误。
- **影响**：
  - FastAPI Web 进程（单事件循环）本可复用连接，却被迫每次新建
  - 每个 HTTP 请求额外 ~5-15ms（TCP 握手 + PG 认证）
  - 高并发下 PostgreSQL `max_connections`（默认 100）容易耗尽
- **建议**：
  ```python
  # 为 Web 和 Celery 分别创建引擎
  # Web: AsyncAdaptedQueuePool（单事件循环安全）
  web_engine = create_async_engine(url, poolclass=AsyncAdaptedQueuePool,
                                    pool_size=20, max_overflow=10,
                                    pool_recycle=1800, pool_pre_ping=True)
  # Celery: NullPool（跨事件循环安全）
  celery_engine = create_async_engine(url, poolclass=NullPool)
  ```

#### D-02 无数据库连接重试 / 降级启动

- **位置**：`src/omichub/main.py:94-98`
- **现象**：`init_db()` 失败时仅打印警告"数据库未就绪，降级运行"，应用继续启动并接受请求。
- **影响**：所有 DB 操作返回 500，用户看到全面报错但服务显示"健康"。
- **建议**：
  - 启动时添加指数退避重试（最多 30s）
  - `/health` 端点区分 liveness（进程存活）和 readiness（DB 可达）
  - Readiness 失败时 Docker/K8s 应停止向该实例路由流量

#### D-03 无 PostgreSQL 备份策略

- **位置**：`deploy/docker/docker-compose.yml` — `db` 服务
- **现象**：无 `pg_dump` 定时任务、无 WAL 归档、无 pgBackRest/WAL-G 配置。数据仅依赖 bind mount 到宿主机磁盘。
- **影响**：磁盘故障 = 全部数据永久丢失。误操作（DROP TABLE）无法回滚到任意时间点。
- **建议**：
  ```yaml
  # 最简方案：添加备份容器
  db-backup:
    image: prodrigestivill/postgres-backup-local:14
    environment:
      POSTGRES_HOST: db
      POSTGRES_DB: omichub
      POSTGRES_USER: omichub
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      SCHEDULE: "@daily"
      BACKUP_KEEP_DAYS: 7
      BACKUP_KEEP_WEEKS: 4
      BACKUP_KEEP_MONTHS: 6
    volumes:
      - /data/omichub/backups:/backups
  ```
  生产环境建议启用 WAL 归档 + pgBackRest 实现 PITR。

#### D-04 数据库连接无 SSL/TLS 加密

- **位置**：`src/omichub/core/config.py`、`session.py`
- **现象**：连接字符串无 `sslmode` 参数，无证书配置。容器间通信明文传输。
- **影响**：开发环境暴露 5432 端口时凭据和数据可被嗅探。生产环境虽不暴露端口，但容器网络内仍可被同网络容器截获。
- **建议**：
  ```python
  # config.py
  database_url: str = f"postgresql+asyncpg://...?ssl=prefer"
  # 生产环境
  database_url: str = f"postgresql+asyncpg://...?ssl=require&ssl_ca=/certs/ca.pem"
  ```

#### D-05 Cookie 事务原子性缺陷

- **位置**：`src/omichub/services/cookie_service.py:506-575`
- **现象**：`_record_transaction` 方法中：
  1. `account.apply_transaction(...)` — Python 侧修改余额
  2. `await self._account_repo.save(account)` — flush 到 DB
  3. 创建 `CookieTransaction` 记录并 `await self._txn_repo.add(txn)` — flush

  步骤 2 和 3 之间若发生异常（如约束冲突），余额已更新但无交易记录。
- **影响**：财务数据不一致 — 余额变动无对应流水，审计失败。
- **建议**：
  ```python
  async def _record_transaction(self, session, account, txn_data):
      async with session.begin_nested():  # SAVEPOINT
          account.apply_transaction(...)
          session.add(account)
          session.add(CookieTransaction(**txn_data))
      # 外层事务统一 commit
  ```

### 2.2 中优先级

#### D-06 PostgreSQL 无资源限制和性能调优

- **位置**：`deploy/docker/docker-compose.yml` — `db` 服务
- **现象**：无 `mem_limit`、`cpus` 限制；无 `command` 覆盖 PG 参数。默认 `shared_buffers=128MB`、`max_connections=100`。
- **影响**：
  - 高负载时 PG 可能 OOM 被 Docker 杀死
  - 默认参数对多核服务器严重欠配
- **建议**：
  ```yaml
  db:
    command: >
      postgres
      -c shared_buffers=1GB
      -c effective_cache_size=3GB
      -c work_mem=64MB
      -c max_connections=200
      -c wal_buffers=16MB
      -c checkpoint_completion_target=0.9
    deploy:
      resources:
        limits:
          memory: 4G
          cpus: "4"
  ```

#### D-07 Redis 无 `maxmemory` 策略

- **位置**：`deploy/docker/docker-compose.yml` — `cache` 服务
- **现象**：Redis 无 `maxmemory` 和 `maxmemory-policy` 配置。Rate limiter 为每个 IP 创建 ZSET key。
- **影响**：DDoS 或大量唯一 IP 时 Redis 内存无上限增长，最终 OOM。
- **建议**：
  ```yaml
  cache:
    command: >
      redis-server
      --requirepass ${REDIS_PASSWORD}
      --maxmemory 512mb
      --maxmemory-policy allkeys-lru
      --appendonly yes
  ```

#### D-08 `workspaces.storage_quota` 整数溢出

- **位置**：`src/omichub/models/user.py:60`、初始迁移 `08ab25316cc1`
- **现象**：`storage_quota` 使用 `sa.Integer()`（最大 ~2.1×10⁹），但默认值为 `10 * 1024 * 1024 * 1024`（10 GiB = 10,737,418,240），超出 Integer 范围。
- **影响**：插入默认值时 PostgreSQL 报 `integer out of range` 错误。
- **建议**：改为 `BigInteger`，并添加迁移：
  ```python
  op.alter_column('workspaces', 'storage_quota',
                  type_=sa.BigInteger(), existing_type=sa.Integer())
  ```

#### D-09 Alembic 自动合并 heads 危险

- **位置**：`deploy/docker/entrypoint.sh:13-17`
- **现象**：容器启动时执行 `alembic merge heads` 自动合并多个迁移头。
- **影响**：生产环境中不兼容的 schema 变更可能被静默合并，导致数据损坏或迁移失败。
- **建议**：
  - 开发环境保留自动合并
  - 生产环境改为 `alembic heads | wc -l` 检查，多 head 时拒绝启动并告警

#### D-10 多处使用已弃用的 `datetime.utcnow()` / 无时区 `datetime.now()`

- **位置**：
  - `models/blast.py:81` — `default=datetime.utcnow`
  - `models/mcp_log.py:24` — `default=datetime.utcnow`
  - `models/sandbox.py:28` — `default=datetime.now`
  - `models/terminal.py:29` — `default=datetime.now`
  - `models/festival.py:40` — `default=datetime.now`
- **现象**：生成 naive datetime（无时区信息），与项目中其他模型的 `DateTime(timezone=True)` 不一致。
- **影响**：跨时区部署时时间错乱；Python 3.12+ 产生 DeprecationWarning。
- **建议**：统一使用 `lambda: datetime.now(timezone.utc)`。

#### D-11 双重 commit 模式

- **位置**：`api/deps.py` `get_db()` + 各 Repository/Service 的显式 `session.commit()`
- **现象**：`get_db` 依赖在请求结束后自动 commit；但 `user_repository.py`（~5处）、`file_service.py`（~15处）等也显式调用 `session.commit()`。
- **影响**：
  - 第二次 commit 通常为空操作，浪费一次 DB 往返
  - 若 Repository commit 后、请求结束前发生异常，`get_db` 的 rollback 无法回滚已提交的数据
  - 代码意图不清晰，维护者不确定事务边界在哪
- **建议**：选择其一：
  - 方案 A：Repository 只 `flush()`，由 `get_db` 统一 commit（Unit of Work 模式）
  - 方案 B：`get_db` 不自动 commit，由 Service 层显式管理事务

#### D-12 `get_current_user_id` 额外开启独立 Session

- **位置**：`src/omichub/api/deps.py:51-58`
- **现象**：每个认证请求在 `get_current_user_id` 中 `async with factory() as db` 开启独立 Session 验证用户，与请求本身的 `DbSession` 无关。
- **影响**：每个认证请求产生 2 个 DB 连接（NullPool 下 = 2 次 TCP 握手）。
- **建议**：复用请求的 `DbSession`，或将用户验证结果缓存到 JWT claims / Redis。

#### D-13 `ChatSessionModel.messages` 默认懒加载

- **位置**：`src/omichub/models/chat.py:59-64`
- **现象**：`messages` 关系使用默认 `lazy="select"`（逐条加载）。任何循环访问 `session.messages` 的代码触发 N+1 查询。
- **影响**：聊天历史列表页若未显式 `selectinload`，每条消息一次额外查询。
- **建议**：改为 `lazy="selectin"` 或在查询处显式 `options(selectinload(ChatSessionModel.messages))`。

### 2.3 低优先级

| 编号 | 问题 | 位置 | 建议 |
|------|------|------|------|
| D-14 | N+1：存储对账逐用户循环 | `tasks/storage.py:40-46` | 改为批量 SQL `UPDATE ... FROM (SELECT ...)` |
| D-15 | 缺少复合索引 | `TaskModel(user_id, status, created_at)`、`FileRecordModel(user_id, status)`、`AuditLogModel(user_id, created_at)` | 添加复合索引迁移 |
| D-16 | `alembic.ini` 硬编码数据库密码 | `alembic.ini:4` | 删除硬编码，仅依赖 `env.py` 的运行时覆盖 |
| D-17 | `/health` 不检查 DB 连通性 | `main.py:290-292` | 添加 `/ready` 端点执行 `SELECT 1` |
| D-18 | PostgreSQL 14 将于 2026-11 EOL | `docker-compose.yml` | 规划升级到 PG 16/17 |
| D-19 | `WorkspaceModel` 疑似未使用 | `models/user.py:52-61` | 确认后删除或标记 deprecated |
| D-20 | Redis Pub/Sub 消息不可重放 | `cookie_pubsub.py` | WebSocket 断线重连后主动拉取最新余额 |
| D-21 | Redis 密码在命令行可见 | `docker-compose.yml` `--requirepass` | 改用 `REDIS_PASSWORD` 环境变量 + `redis.conf` 文件 |
| D-22 | 生产环境 `postgres_password` 无默认值校验 | `config.py` `validate_production_secrets` | 添加 `postgres_password != "omichub"` 校验 |

---

## 三、问题优先级矩阵

| 优先级 | Celery | 数据库 | 合计 |
|--------|--------|--------|------|
| **P0 严重** | C-01, C-02, C-03 | D-01, D-02, D-03 | 6 |
| **P1 高** | C-04, C-05 | D-04, D-05 | 4 |
| **P2 中** | C-06 ~ C-13 | D-06 ~ D-13 | 16 |
| **P3 低** | C-14 ~ C-17 | D-14 ~ D-22 | 13 |
| **合计** | **17** | **22** | **39** |

---

## 四、建议修复路线图

### 第一阶段（1-2 周）— 止血

1. **C-03** 拆分队列，将实时任务与维护任务从 `analysis` 分离
2. **C-01** 启用 `acks_late` + `reject_on_worker_lost`
3. **D-03** 添加 PostgreSQL 每日自动备份
4. **D-02** 启动时 DB 连接重试 + readiness 端点
5. **C-08** 设置 `broker_connection_retry_on_startup=True`

### 第二阶段（2-4 周）— 加固

6. **D-01** Web/Celery 分离引擎，Web 使用连接池
7. **D-05** Cookie 事务引入 SAVEPOINT 保证原子性
8. **D-06** PostgreSQL 参数调优 + 资源限制
9. **D-07** Redis maxmemory + 持久化配置
10. **C-05** 实现失败任务回调 + 死信记录
11. **D-08** 修复 `storage_quota` Integer 溢出

### 第三阶段（1-2 月）— 架构优化

12. **C-02** 解决 `asyncio.run()` 连接风暴（评估 async Worker 方案）
13. **D-04** 启用数据库 SSL
14. **D-11** 统一事务管理模式（Unit of Work）
15. **C-06** Beat 高可用（redbeat / 竞选锁）
16. **D-18** PostgreSQL 版本升级规划

---

## 五、附录：文件索引

| 组件 | 关键文件 |
|------|----------|
| Celery App | `src/omichub/infrastructure/celery_app/celery.py` |
| Celery 配置常量 | `src/omichub/infrastructure/celery_app/config.py` |
| Celery 日志 | `src/omichub/infrastructure/celery_app/logging.py` |
| 任务定义 | `src/omichub/infrastructure/celery_app/tasks/*.py` |
| 工具任务 | `src/omichub/tools/{jbrowse,blast,phylogenetic_tree,enrichments}/tasks.py` |
| DB 引擎/Session | `src/omichub/infrastructure/database/session.py` |
| DB 配置 | `src/omichub/core/config.py` |
| 模型定义 | `src/omichub/models/*.py` |
| 迁移文件 | `alembic/versions/` (38 个) |
| Docker 部署 | `deploy/docker/docker-compose*.yml` |
| Worker 入口 | `deploy/docker/worker-entrypoint.sh` |

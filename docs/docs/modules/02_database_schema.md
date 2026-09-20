# 6.2 CygnusX 数据库 Schema 设计

> **文档版本**: v1.0  
> **数据库**: PostgreSQL 14+  
> **设计日期**: 2025年  
> **设计目标**: 华中农业大学园艺林学学院 - 组内多组学分析平台  
> **预期规模**: 并发用户 < 20 人，单人生信维护  

---

## 目录

- [1. 设计概述与约定](#1-设计概述与约定)
- [2. 核心表结构](#2-核心表结构)
  - [2.1 用户域 (users, workspaces)](#21-用户域)
  - [2.2 流程域 (flow_categories, flow_definitions)](#22-流程域)
  - [2.3 项目与文件域 (projects, samples, file_records)](#23-项目与文件域)
  - [2.4 任务域 (tasks, task_logs, task_events)](#24-任务域)
  - [2.5 AI 对话域 (chat_sessions, chat_messages)](#25-ai-对话域)
  - [2.6 MCP 域 (mcp_servers, mcp_tool_invocations)](#26-mcp-域)
- [3. 索引设计](#3-索引设计)
- [4. JSONB 字段详细说明](#4-jsonb-字段详细说明)
- [5. 数据库 ER 关系描述](#5-数据库-er-关系描述)
- [6. 数据隔离策略](#6-数据隔离策略)
- [7. 完整 SQL 执行顺序](#7-完整-sql-执行顺序)

---

## 1. 设计概述与约定

### 1.1 命名规范

| 项目 | 约定 |
|------|------|
| 表名 | 小写蛇形命名，复数形式（如 `users`, `flow_definitions`） |
| 字段名 | 小写蛇形命名（如 `created_at`, `flow_key`） |
| 主键 | 统一使用 `id`（BIGINT, GENERATED ALWAYS AS IDENTITY） |
| 外键 | 引用表名单数 + `_id`（如 `user_id`, `project_id`） |
| 时间戳 | `created_at`, `updated_at` 使用 `timestamptz` |
| UUID | 对外暴露的标识使用 `uuid` 类型（如 `task.task_id`） |
| 布尔值 | 使用 `BOOLEAN` 类型，默认 `TRUE` |
| JSONB | 灵活参数统一使用 `JSONB`，非 `JSON` |
| 注释 | 所有表和字段必须加 `COMMENT ON` |

### 1.2 时区处理

- 数据库服务器时区设置为 `Asia/Shanghai`
- 所有时间字段使用 `timestamptz`（带时区存储）
- 应用层统一使用 UTC 传输，前端做本地化显示

### 1.3 核心设计决策

1. **单数据库 + 单 Schema**: 组内小团队，无需复杂多租户，通过 `user_id` 做行级隔离
2. **JSONB 优先**: 组学流程参数多变，JSONB 提供灵活性，同时配合 GIN 索引保证查询性能
3. **任务状态机**: tasks.status 严格定义为有限状态，通过 CHECK 约束保证
4. **日志存储**: task_logs.content 为 TEXT 类型，大日志（>10MB）建议转文件存储，表中保留摘要
5. **UUID 暴露**: 所有外部接口使用 UUID 而非自增 ID，防止枚举攻击

---

## 2. 核心表结构

### 2.1 用户域

#### 2.1.1 users — 用户表

```sql
-- ============================================================
-- 用户表: 存储系统用户信息，支持管理员和普通用户两种角色
-- ============================================================
CREATE TABLE users (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    username            VARCHAR(50) NOT NULL,
    email               VARCHAR(255) NOT NULL,
    hashed_password     VARCHAR(255) NOT NULL,

    -- 角色: admin(管理员) / user(普通用户)
    role                VARCHAR(20) NOT NULL DEFAULT 'user',

    -- 账户状态: TRUE=活跃, FALSE=禁用
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    -- 头像 URL（可选）
    avatar_url          VARCHAR(500),

    -- 用户配置偏好（JSONB：主题、通知设置、默认工作区等）
    preferences         JSONB DEFAULT '{}',

    -- 最后登录时间
    last_login_at       TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 唯一约束
    CONSTRAINT uk_users_username UNIQUE (username),
    CONSTRAINT uk_users_email UNIQUE (email),

    -- 角色校验
    CONSTRAINT chk_users_role CHECK (role IN ('admin', 'user'))
);

-- 注释
COMMENT ON TABLE users IS '用户表：存储系统注册用户的基本信息和认证信息';
COMMENT ON COLUMN users.id IS '自增主键，内部使用';
COMMENT ON COLUMN users.username IS '用户名，全局唯一，用于登录和显示';
COMMENT ON COLUMN users.email IS '邮箱地址，全局唯一';
COMMENT ON COLUMN users.hashed_password IS 'bcrypt 哈希后的密码';
COMMENT ON COLUMN users.role IS '用户角色：admin 为管理员，user 为普通用户';
COMMENT ON COLUMN users.is_active IS '账户是否激活';
COMMENT ON COLUMN users.avatar_url IS '头像图片 URL';
COMMENT ON COLUMN users.preferences IS '用户偏好设置（JSONB）';
COMMENT ON COLUMN users.last_login_at IS '最后登录时间';
COMMENT ON COLUMN users.created_at IS '创建时间';
COMMENT ON COLUMN users.updated_at IS '更新时间';

-- 更新时间触发器
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_users_updated_at
    BEFORE UPDATE ON users
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.1.2 workspaces — 工作空间表

```sql
-- ============================================================
-- 工作空间表: 支持多级目录结构，用户可组织项目到不同工作空间
-- 使用路径枚举模型（path_enum）实现树形结构
-- ============================================================
CREATE TABLE workspaces (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 所属用户
    user_id             BIGINT NOT NULL,

    -- 工作空间名称
    name                VARCHAR(100) NOT NULL,

    -- 描述
    description         VARCHAR(500),

    -- 父工作空间ID（NULL 表示根级）
    parent_id           BIGINT,

    -- 路径枚举（如 /1/5/12/，加速子树查询）
    path                VARCHAR(1000) NOT NULL DEFAULT '/',

    -- 层级深度（根级=0）
    depth               INTEGER NOT NULL DEFAULT 0,

    -- 排序权重
    sort_order          INTEGER NOT NULL DEFAULT 0,

    -- 工作空间配置（JSONB：颜色标记、图标、默认参数等）
    config              JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_workspaces_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_workspaces_parent_id
        FOREIGN KEY (parent_id) REFERENCES workspaces(id)
        ON DELETE CASCADE,

    -- 层级深度校验
    CONSTRAINT chk_workspaces_depth CHECK (depth >= 0),

    -- 同一父级下名称唯一
    CONSTRAINT uk_workspaces_name_per_parent 
        UNIQUE (user_id, parent_id, name)
);

-- 注释
COMMENT ON TABLE workspaces IS '工作空间表：支持多级目录的树形结构，用于组织项目';
COMMENT ON COLUMN workspaces.user_id IS '所属用户ID';
COMMENT ON COLUMN workspaces.name IS '工作空间名称';
COMMENT ON COLUMN workspaces.parent_id IS '父工作空间ID，NULL 表示根级';
COMMENT ON COLUMN workspaces.path IS '路径枚举，格式如 /1/5/12/';
COMMENT ON COLUMN workspaces.depth IS '层级深度，根级为0';
COMMENT ON COLUMN workspaces.config IS '工作空间配置（JSONB）';

CREATE TRIGGER trg_workspaces_updated_at
    BEFORE UPDATE ON workspaces
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();

-- 防止循环引用的触发器
CREATE OR REPLACE FUNCTION check_workspace_cycle()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.parent_id IS NOT NULL THEN
        IF NEW.path LIKE '%/' || NEW.parent_id || '/%' THEN
            RAISE EXCEPTION 'Workspace cycle detected';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_workspaces_no_cycle
    BEFORE INSERT OR UPDATE ON workspaces
    FOR EACH ROW
    EXECUTE FUNCTION check_workspace_cycle();
```


---

### 2.2 流程域

#### 2.2.1 flow_categories — 流程分类表

```sql
-- ============================================================
-- 流程分类表: 对流程定义进行分类管理（如 RNA-seq, ChIP-seq, 基因组等）
-- 支持多级分类
-- ============================================================
CREATE TABLE flow_categories (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 分类名称
    name                VARCHAR(100) NOT NULL,

    -- 分类标识（URL-friendly）
    slug                VARCHAR(100) NOT NULL,

    -- 父分类ID（NULL 表示顶级分类）
    parent_id           BIGINT,

    -- 描述
    description         VARCHAR(500),

    -- 图标（前端使用的图标名称）
    icon                VARCHAR(50),

    -- 颜色标记
    color               VARCHAR(20) DEFAULT '#1890ff',

    -- 排序权重
    sort_order          INTEGER NOT NULL DEFAULT 0,

    -- 是否激活
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    -- 分类元数据（JSONB：如所属领域、常用物种等）
    metadata            JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_flow_categories_parent_id
        FOREIGN KEY (parent_id) REFERENCES flow_categories(id)
        ON DELETE SET NULL,

    -- 同一父级下 slug 唯一
    CONSTRAINT uk_flow_categories_slug 
        UNIQUE (parent_id, slug)
);

COMMENT ON TABLE flow_categories IS '流程分类表：对组学分析流程进行分类管理';
COMMENT ON COLUMN flow_categories.name IS '分类名称，如转录组分析';
COMMENT ON COLUMN flow_categories.slug IS '分类标识，URL友好，如 rna-seq';
COMMENT ON COLUMN flow_categories.parent_id IS '父分类ID，支持多级分类';
COMMENT ON COLUMN flow_categories.metadata IS '分类元数据（JSONB）';

CREATE TRIGGER trg_flow_categories_updated_at
    BEFORE UPDATE ON flow_categories
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.2.2 flow_definitions — 流程定义表

```sql
-- ============================================================
-- 流程定义表: 存储 YAML 解析后的结构化流程配置
-- 这是系统的核心表之一，定义了一个分析流程的完整配置
-- ============================================================
CREATE TABLE flow_definitions (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 流程唯一标识（如 rna-seq-star-dese2）
    flow_key            VARCHAR(100) NOT NULL,

    -- 流程名称（如 "RNA-seq 差异表达分析"）
    name                VARCHAR(200) NOT NULL,

    -- 所属分类
    category_id         BIGINT,

    -- 版本号（语义化版本，如 1.0.2）
    version             VARCHAR(20) NOT NULL DEFAULT '1.0.0',

    -- 描述
    description         TEXT,

    -- 原始 YAML 文本（完整保留，便于回溯）
    yaml_content        TEXT NOT NULL,

    -- 解析后的配置（JSONB：参数定义、步骤定义、条件规则等）
    parsed_config       JSONB NOT NULL DEFAULT '{}',

    -- 样本表必填列定义（JSONB 数组）
    sample_sheet_columns JSONB DEFAULT '[]',

    -- 执行配置（JSONB：engine、snakefile 路径、resources 等）
    execution_config    JSONB DEFAULT '{}',

    -- 是否激活（可禁用旧版本）
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    -- 是否公开（所有用户可见，否则仅创建者和管理员可见）
    is_public           BOOLEAN NOT NULL DEFAULT FALSE,

    -- 创建者
    created_by          BIGINT NOT NULL,

    -- 使用统计（减少 JOIN 查询）
    usage_count         INTEGER NOT NULL DEFAULT 0,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_flow_definitions_category_id
        FOREIGN KEY (category_id) REFERENCES flow_categories(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_flow_definitions_created_by
        FOREIGN KEY (created_by) REFERENCES users(id)
        ON DELETE RESTRICT,

    -- flow_key + version 唯一
    CONSTRAINT uk_flow_definitions_key_version 
        UNIQUE (flow_key, version)
);

COMMENT ON TABLE flow_definitions IS '流程定义表：存储 YAML 解析后的结构化分析流程配置';
COMMENT ON COLUMN flow_definitions.flow_key IS '流程唯一标识，如 rna-seq-star-deseq2';
COMMENT ON COLUMN flow_definitions.name IS '流程显示名称';
COMMENT ON COLUMN flow_definitions.category_id IS '所属分类ID';
COMMENT ON COLUMN flow_definitions.version IS '语义化版本号';
COMMENT ON COLUMN flow_definitions.yaml_content IS '原始 YAML 文本内容';
COMMENT ON COLUMN flow_definitions.parsed_config IS '解析后的结构化配置（JSONB）';
COMMENT ON COLUMN flow_definitions.sample_sheet_columns IS '样本表必填列定义（JSONB 数组）';
COMMENT ON COLUMN flow_definitions.execution_config IS '执行引擎配置（JSONB）';
COMMENT ON COLUMN flow_definitions.is_active IS '是否激活';
COMMENT ON COLUMN flow_definitions.is_public IS '是否对所有用户公开';
COMMENT ON COLUMN flow_definitions.created_by IS '创建者用户ID';
COMMENT ON COLUMN flow_definitions.usage_count IS '使用次数统计';

CREATE TRIGGER trg_flow_definitions_updated_at
    BEFORE UPDATE ON flow_definitions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

---

### 2.3 项目与文件域

#### 2.3.1 projects — 项目表

```sql
-- ============================================================
-- 项目表: 存储用户创建的组学分析项目
-- 项目是样本、任务、文件的顶层容器
-- ============================================================
CREATE TABLE projects (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 项目ID（对外暴露的 UUID）
    project_uuid        UUID NOT NULL DEFAULT gen_random_uuid(),

    -- 项目名稱
    name                VARCHAR(200) NOT NULL,

    -- 描述
    description         TEXT,

    -- 所属用户
    user_id             BIGINT NOT NULL,

    -- 所属工作空间（NULL 表示未分类）
    workspace_id        BIGINT,

    -- 项目存储路径（服务器上的绝对路径）
    storage_path        VARCHAR(1000) NOT NULL,

    -- 项目配置（JSONB：物种、参考基因组、默认参数等）
    config              JSONB DEFAULT '{}',

    -- 项目标签（TEXT 数组，便于快速筛选）
    tags                TEXT[] DEFAULT '{}',

    -- 项目状态
    status              VARCHAR(20) NOT NULL DEFAULT 'active',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_projects_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_projects_workspace_id
        FOREIGN KEY (workspace_id) REFERENCES workspaces(id)
        ON DELETE SET NULL,

    -- UUID 唯一
    CONSTRAINT uk_projects_uuid UNIQUE (project_uuid),

    -- 状态校验
    CONSTRAINT chk_projects_status 
        CHECK (status IN ('active', 'archived', 'deleted'))
);

COMMENT ON TABLE projects IS '项目表：组学分析项目的顶层容器';
COMMENT ON COLUMN projects.project_uuid IS '对外暴露的项目 UUID';
COMMENT ON COLUMN projects.name IS '项目名称';
COMMENT ON COLUMN projects.user_id IS '项目所有者用户ID';
COMMENT ON COLUMN projects.workspace_id IS '所属工作空间ID';
COMMENT ON COLUMN projects.storage_path IS '项目文件存储路径';
COMMENT ON COLUMN projects.config IS '项目配置（JSONB：物种、参考基因组等）';
COMMENT ON COLUMN projects.tags IS '项目标签数组';
COMMENT ON COLUMN projects.status IS '项目状态：active/归档/已删除';

CREATE TRIGGER trg_projects_updated_at
    BEFORE UPDATE ON projects
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.3.2 samples — 样本表

```sql
-- ============================================================
-- 样本表: 存储项目中的生物样本信息和文件映射
-- 支持样本表（sample sheet）解析后的结构化数据存储
-- ============================================================
CREATE TABLE samples (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 所属项目
    project_id          BIGINT NOT NULL,

    -- 样本名称
    name                VARCHAR(200) NOT NULL,

    -- 样本别名/显示名称
    display_name        VARCHAR(200),

    -- 文件类型（fastq/csv/mtx/bed/bam/gtf/etc）
    file_type           VARCHAR(50),

    -- 文件路径（服务器上的绝对路径）
    file_path           VARCHAR(1000),

    -- 配对文件路径（如 paired-end FASTQ 的 R2）
    pair_file_path      VARCHAR(1000),

    -- 文件大小（字节）
    file_size           BIGINT,

    -- 样本元数据（JSONB：read_length、platform、library_prep 等）
    metadata            JSONB DEFAULT '{}',

    -- 样本表结构化数据（JSONB：样本表解析后的完整列数据）
    sample_sheet_data   JSONB DEFAULT '{}',

    -- 样本分组信息（JSONB：condition、replicate、batch 等）
    grouping            JSONB DEFAULT '{}',

    -- 质量评估结果（JSONB：QC 统计、FastQC 结果等）
    qc_results          JSONB DEFAULT '{}',

    -- 描述
    description         TEXT,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_samples_project_id
        FOREIGN KEY (project_id) REFERENCES projects(id)
        ON DELETE CASCADE,

    -- 同一项目下样本名称唯一
    CONSTRAINT uk_samples_name_per_project 
        UNIQUE (project_id, name)
);

COMMENT ON TABLE samples IS '样本表：存储项目中的生物样本信息和文件映射';
COMMENT ON COLUMN samples.project_id IS '所属项目ID';
COMMENT ON COLUMN samples.name IS '样本名称（通常是文件名或样本ID）';
COMMENT ON COLUMN samples.file_type IS '文件类型：fastq/csv/mtx/bed/bam 等';
COMMENT ON COLUMN samples.file_path IS '样本文件绝对路径';
COMMENT ON COLUMN samples.pair_file_path IS '配对文件路径（PE测序R2）';
COMMENT ON COLUMN samples.file_size IS '文件大小（字节）';
COMMENT ON COLUMN samples.metadata IS '样本元数据（JSONB）';
COMMENT ON COLUMN samples.sample_sheet_data IS '样本表完整列数据（JSONB）';
COMMENT ON COLUMN samples.grouping IS '样本分组信息（JSONB）';
COMMENT ON COLUMN samples.qc_results IS '质量评估结果（JSONB）';

CREATE TRIGGER trg_samples_updated_at
    BEFORE UPDATE ON samples
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.3.3 file_records — 文件记录表

```sql
-- ============================================================
-- 文件记录表: 通用文件管理，跟踪系统中的所有文件
-- 包括输入文件、输出结果、参考基因组、日志文件等
-- ============================================================
CREATE TABLE file_records (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 所属用户
    user_id             BIGINT NOT NULL,

    -- 所属项目（NULL 表示全局文件）
    project_id          BIGINT,

    -- 文件名称
    file_name           VARCHAR(255) NOT NULL,

    -- 文件路径（服务器上的绝对路径）
    file_path           VARCHAR(1000) NOT NULL,

    -- 文件大小（字节）
    file_size           BIGINT NOT NULL DEFAULT 0,

    -- MIME 类型
    mime_type           VARCHAR(100),

    -- 文件分类：input/output/reference/log/temp/report
    category            VARCHAR(20) NOT NULL DEFAULT 'output',

    -- 文件校验和（SHA-256）
    checksum            VARCHAR(64),

    -- 文件描述
    description         VARCHAR(500),

    -- 关联的任务ID（NULL 表示非任务产出）
    task_id             BIGINT,

    -- 关联的流程步骤名称
    flow_step_name      VARCHAR(200),

    -- 是否可见（隐藏临时文件）
    is_visible          BOOLEAN NOT NULL DEFAULT TRUE,

    -- 额外元数据（JSONB：如压缩格式、索引文件路径等）
    metadata            JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_file_records_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_file_records_project_id
        FOREIGN KEY (project_id) REFERENCES projects(id)
        ON DELETE CASCADE,

    -- 分类校验
    CONSTRAINT chk_file_records_category 
        CHECK (category IN ('input', 'output', 'reference', 'log', 'temp', 'report'))
);

COMMENT ON TABLE file_records IS '文件记录表：通用文件管理，跟踪系统中所有文件';
COMMENT ON COLUMN file_records.user_id IS '文件所有者用户ID';
COMMENT ON COLUMN file_records.project_id IS '所属项目ID，NULL 为全局文件';
COMMENT ON COLUMN file_records.file_name IS '文件名称';
COMMENT ON COLUMN file_records.file_path IS '文件绝对路径';
COMMENT ON COLUMN file_records.file_size IS '文件大小（字节）';
COMMENT ON COLUMN file_records.mime_type IS 'MIME 类型';
COMMENT ON COLUMN file_records.category IS '文件分类：input/output/reference/log/temp/report';
COMMENT ON COLUMN file_records.checksum IS 'SHA-256 校验和';
COMMENT ON COLUMN file_records.task_id IS '产生该文件的任务ID';
COMMENT ON COLUMN file_records.flow_step_name IS '产生该文件的流程步骤';
COMMENT ON COLUMN file_records.metadata IS '文件元数据（JSONB）';
```


---

### 2.4 任务域

#### 2.4.1 tasks — 任务表

```sql
-- ============================================================
-- 任务表: 存储用户提交的分析任务，是系统的核心实体
-- 记录了任务从提交到完成的完整生命周期
-- ============================================================
CREATE TABLE tasks (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 任务 UUID（对外暴露的唯一标识）
    task_id             UUID NOT NULL DEFAULT gen_random_uuid(),

    -- 任务名称（用户自定义或系统生成）
    name                VARCHAR(255) NOT NULL,

    -- 描述
    description         TEXT,

    -- 提交者
    user_id             BIGINT NOT NULL,

    -- 所属项目
    project_id          BIGINT NOT NULL,

    -- 使用的流程定义
    flow_definition_id  BIGINT NOT NULL,

    -- 任务状态（严格状态机）
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',

    -- 用户提交的参数值（JSONB：用户填写的表单参数）
    parameters          JSONB NOT NULL DEFAULT '{}',

    -- 执行模式：local（本地）/ remote（远程集群）
    execution_mode      VARCHAR(20) NOT NULL DEFAULT 'local',

    -- 执行后端：snakemake / nextflow / cromwell
    execution_backend   VARCHAR(20) NOT NULL DEFAULT 'snakemake',

    -- 工作目录（任务执行的绝对路径）
    working_directory   VARCHAR(1000),

    -- 配置文件路径
    config_file_path    VARCHAR(1000),

    -- Snakefile / 主流程文件路径
    snakefile_path      VARCHAR(1000),

    -- 资源请求（JSONB：cores, memory_gb, runtime_hours, queue 等）
    resources           JSONB DEFAULT '{}',

    -- 进度百分比（0-100）
    progress_percent    INTEGER NOT NULL DEFAULT 0,

    -- 当前执行步骤名称
    current_step        VARCHAR(200),

    -- 总步骤数
    total_steps         INTEGER DEFAULT 0,

    -- 当前步骤序号
    current_step_index  INTEGER DEFAULT 0,

    -- 结果摘要（JSONB：结果文件列表、统计信息等）
    results_summary     JSONB DEFAULT '{}',

    -- 错误信息（失败时记录）
    error_message       TEXT,

    -- 开始执行时间
    started_at          TIMESTAMPTZ,

    -- 完成时间（成功或失败）
    completed_at        TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_tasks_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE RESTRICT,

    CONSTRAINT fk_tasks_project_id
        FOREIGN KEY (project_id) REFERENCES projects(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_tasks_flow_definition_id
        FOREIGN KEY (flow_definition_id) REFERENCES flow_definitions(id)
        ON DELETE RESTRICT,

    -- UUID 唯一
    CONSTRAINT uk_tasks_task_id UNIQUE (task_id),

    -- 状态机校验
    CONSTRAINT chk_tasks_status 
        CHECK (status IN ('pending', 'submitted', 'running', 'completed', 'failed', 'cancelled')),

    -- 执行模式校验
    CONSTRAINT chk_tasks_execution_mode 
        CHECK (execution_mode IN ('local', 'remote')),

    -- 执行后端校验
    CONSTRAINT chk_tasks_execution_backend 
        CHECK (execution_backend IN ('snakemake', 'nextflow', 'cromwell')),

    -- 进度百分比范围校验
    CONSTRAINT chk_tasks_progress 
        CHECK (progress_percent >= 0 AND progress_percent <= 100)
);

COMMENT ON TABLE tasks IS '任务表：存储用户提交的组学分析任务';
COMMENT ON COLUMN tasks.task_id IS '任务 UUID，对外暴露的唯一标识';
COMMENT ON COLUMN tasks.name IS '任务名称';
COMMENT ON COLUMN tasks.user_id IS '任务提交者用户ID';
COMMENT ON COLUMN tasks.project_id IS '所属项目ID';
COMMENT ON COLUMN tasks.flow_definition_id IS '使用的流程定义ID';
COMMENT ON COLUMN tasks.status IS '任务状态：pending/submitted/running/completed/failed/cancelled';
COMMENT ON COLUMN tasks.parameters IS '用户提交的参数值（JSONB）';
COMMENT ON COLUMN tasks.execution_mode IS '执行模式：local 或 remote';
COMMENT ON COLUMN tasks.execution_backend IS '执行后端：snakemake/nextflow/cromwell';
COMMENT ON COLUMN tasks.working_directory IS '任务工作目录绝对路径';
COMMENT ON COLUMN tasks.resources IS '资源请求配置（JSONB）';
COMMENT ON COLUMN tasks.progress_percent IS '执行进度百分比 0-100';
COMMENT ON COLUMN tasks.current_step IS '当前执行步骤名称';
COMMENT ON COLUMN tasks.results_summary IS '结果摘要（JSONB）';
COMMENT ON COLUMN tasks.error_message IS '错误信息（失败时）';
COMMENT ON COLUMN tasks.started_at IS '开始执行时间';
COMMENT ON COLUMN tasks.completed_at IS '完成时间';

CREATE TRIGGER trg_tasks_updated_at
    BEFORE UPDATE ON tasks
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.4.2 task_logs — 任务日志表

```sql
-- ============================================================
-- 任务日志表: 存储任务执行过程中的日志输出
-- 设计说明: 对于大日志（>10MB），建议存文件，表中保留摘要和文件路径
-- ============================================================
CREATE TABLE task_logs (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 关联任务
    task_id             BIGINT NOT NULL,

    -- 日志类型
    log_type            VARCHAR(20) NOT NULL DEFAULT 'stdout',

    -- 日志内容（TEXT，适合中小日志；大日志建议存文件，此字段存摘要）
    content             TEXT,

    -- 日志文件路径（内容过大时，日志存文件，此字段指向文件）
    log_file_path       VARCHAR(1000),

    -- 内容大小（字节，用于判断是否在表中存储）
    content_size        BIGINT DEFAULT 0,

    -- 所属步骤名称
    step_name           VARCHAR(200),

    -- 步骤序号
    step_index          INTEGER,

    -- 日志级别：DEBUG/INFO/WARNING/ERROR/CRITICAL
    log_level           VARCHAR(20) DEFAULT 'INFO',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_task_logs_task_id
        FOREIGN KEY (task_id) REFERENCES tasks(id)
        ON DELETE CASCADE,

    -- 日志类型校验
    CONSTRAINT chk_task_logs_type 
        CHECK (log_type IN ('stdout', 'stderr', 'system', 'progress', 'debug')),

    -- 日志级别校验
    CONSTRAINT chk_task_logs_level 
        CHECK (log_level IN ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'))
);

-- 为日志表设置表级注释和策略
COMMENT ON TABLE task_logs IS '任务日志表：存储任务执行过程的日志输出';
COMMENT ON COLUMN task_logs.task_id IS '关联任务ID';
COMMENT ON COLUMN task_logs.log_type IS '日志类型：stdout/stderr/system/progress/debug';
COMMENT ON COLUMN task_logs.content IS '日志内容文本（中小日志）';
COMMENT ON COLUMN task_logs.log_file_path IS '日志文件路径（大日志存文件）';
COMMENT ON COLUMN task_logs.content_size IS '内容大小（字节）';
COMMENT ON COLUMN task_logs.step_name IS '产生日志的流程步骤名称';
COMMENT ON COLUMN task_logs.step_index IS '步骤序号';
COMMENT ON COLUMN task_logs.log_level IS '日志级别';

-- 大日志存储建议触发器
CREATE OR REPLACE FUNCTION handle_large_log()
RETURNS TRIGGER AS $$
BEGIN
    -- 如果内容超过 1MB（约 1,048,576 字节），标记为大日志
    IF LENGTH(COALESCE(NEW.content, '')) > 1048576 THEN
        NEW.content_size = LENGTH(NEW.content);
        -- 保留前 10000 字符作为摘要，剩余部分应通过应用层写入文件
        NEW.content = LEFT(NEW.content, 10000) || E'\n... [日志过大，完整内容已保存到文件]';
    ELSE
        NEW.content_size = LENGTH(COALESCE(NEW.content, ''));
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_task_logs_handle_large
    BEFORE INSERT ON task_logs
    FOR EACH ROW
    EXECUTE FUNCTION handle_large_log();
```

#### 2.4.3 task_events — 任务事件表

```sql
-- ============================================================
-- 任务事件表: 记录任务状态变更历史和重要事件
-- 用于审计追踪和状态机回放
-- ============================================================
CREATE TABLE task_events (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 关联任务
    task_id             BIGINT NOT NULL,

    -- 事件类型
    event_type          VARCHAR(50) NOT NULL,

    -- 变更前状态
    from_status         VARCHAR(20),

    -- 变更后状态
    to_status           VARCHAR(20),

    -- 事件消息
    message             TEXT,

    -- 事件详情（JSONB：额外上下文信息）
    details             JSONB DEFAULT '{}',

    -- 触发者（用户ID 或 system）
    triggered_by        VARCHAR(100) DEFAULT 'system',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_task_events_task_id
        FOREIGN KEY (task_id) REFERENCES tasks(id)
        ON DELETE CASCADE,

    -- 事件类型校验
    CONSTRAINT chk_task_events_type 
        CHECK (event_type IN (
            'status_changed',      -- 状态变更
            'step_started',        -- 步骤开始
            'step_completed',      -- 步骤完成
            'step_failed',         -- 步骤失败
            'resource_allocated',  -- 资源分配
            'resource_released',   -- 资源释放
            'user_cancelled',      -- 用户取消
            'system_error',        -- 系统错误
            'retry_attempted',     -- 重试尝试
            'notification_sent'    -- 通知发送
        ))
);

COMMENT ON TABLE task_events IS '任务事件表：记录任务状态变更历史和重要事件';
COMMENT ON COLUMN task_events.task_id IS '关联任务ID';
COMMENT ON COLUMN task_events.event_type IS '事件类型';
COMMENT ON COLUMN task_events.from_status IS '变更前状态';
COMMENT ON COLUMN task_events.to_status IS '变更后状态';
COMMENT ON COLUMN task_events.message IS '事件描述消息';
COMMENT ON COLUMN task_events.details IS '事件详情（JSONB）';
COMMENT ON COLUMN task_events.triggered_by IS '触发者：用户ID 或 system';
```


---

### 2.5 AI 对话域

#### 2.5.1 chat_sessions — 对话会话表

```sql
-- ============================================================
-- 对话会话表: 存储用户与 AI 的对话会话
-- 每个会话包含一组连续的消息，支持上下文快照
-- ============================================================
CREATE TABLE chat_sessions (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 会话 UUID（对外暴露）
    session_id          UUID NOT NULL DEFAULT gen_random_uuid(),

    -- 所属用户
    user_id             BIGINT NOT NULL,

    -- 会话标题（自动生成或用户编辑）
    title               VARCHAR(255),

    -- 上下文快照（JSONB：当前项目ID、流程ID、任务ID等）
    context_snapshot    JSONB DEFAULT '{}',

    -- 使用的 AI 模型
    model_used          VARCHAR(50) DEFAULT 'gpt-4',

    -- 系统提示词（可为特定会话定制）
    system_prompt       TEXT,

    -- 会话状态
    status              VARCHAR(20) NOT NULL DEFAULT 'active',

    -- 会话配置（JSONB：温度、最大token、是否流式等）
    config              JSONB DEFAULT '{}',

    -- 消息数量统计（减少 JOIN）
    message_count       INTEGER NOT NULL DEFAULT 0,

    -- 总 token 消耗统计
    total_tokens        INTEGER NOT NULL DEFAULT 0,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_chat_sessions_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE CASCADE,

    -- UUID 唯一
    CONSTRAINT uk_chat_sessions_session_id UNIQUE (session_id),

    -- 状态校验
    CONSTRAINT chk_chat_sessions_status 
        CHECK (status IN ('active', 'archived', 'deleted'))
);

COMMENT ON TABLE chat_sessions IS '对话会话表：用户与 AI 的对话会话';
COMMENT ON COLUMN chat_sessions.session_id IS '会话 UUID';
COMMENT ON COLUMN chat_sessions.user_id IS '所属用户ID';
COMMENT ON COLUMN chat_sessions.title IS '会话标题';
COMMENT ON COLUMN chat_sessions.context_snapshot IS '上下文快照（JSONB：项目ID、流程ID、任务ID等）';
COMMENT ON COLUMN chat_sessions.model_used IS '使用的 AI 模型';
COMMENT ON COLUMN chat_sessions.system_prompt IS '系统提示词';
COMMENT ON COLUMN chat_sessions.status IS '会话状态：active/archived/deleted';
COMMENT ON COLUMN chat_sessions.config IS '会话配置（JSONB）';
COMMENT ON COLUMN chat_sessions.message_count IS '消息数量';
COMMENT ON COLUMN chat_sessions.total_tokens IS '总 token 消耗';

CREATE TRIGGER trg_chat_sessions_updated_at
    BEFORE UPDATE ON chat_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.5.2 chat_messages — 对话消息表

```sql
-- ============================================================
-- 对话消息表: 存储会话中的单条消息
-- 支持普通对话、工具调用、MCP 工具调用等多种消息类型
-- ============================================================
CREATE TABLE chat_messages (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 所属会话
    session_id          BIGINT NOT NULL,

    -- 消息角色：user/assistant/system/tool
    role                VARCHAR(20) NOT NULL,

    -- 消息内容
    content             TEXT NOT NULL DEFAULT '',

    -- AI 调用的工具列表（JSONB：function calling / tool_calls）
    tool_calls          JSONB DEFAULT '[]',

    -- 工具执行结果（JSONB：tool 返回的数据）
    tool_results        JSONB DEFAULT '[]',

    -- MCP Server ID（如为 MCP 工具调用）
    mcp_server_id       BIGINT,

    -- MCP 工具名称
    mcp_tool_name       VARCHAR(200),

    -- 引用的上下文（JSONB：引用的文件、任务结果等）
    references_context  JSONB DEFAULT '[]',

    -- Token 计数（JSONB：prompt_tokens, completion_tokens, total_tokens）
    token_count         JSONB DEFAULT '{}',

    -- 消息元数据（JSONB：如思考过程、评分等）
    metadata            JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_chat_messages_session_id
        FOREIGN KEY (session_id) REFERENCES chat_sessions(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_chat_messages_mcp_server_id
        FOREIGN KEY (mcp_server_id) REFERENCES mcp_servers(id)
        ON DELETE SET NULL,

    -- 角色校验
    CONSTRAINT chk_chat_messages_role 
        CHECK (role IN ('user', 'assistant', 'system', 'tool')),

    -- MCP 工具调用的约束：如果 mcp_tool_name 不为空，则 mcp_server_id 也不能为空
    CONSTRAINT chk_chat_messages_mcp_consistency 
        CHECK (
            (mcp_tool_name IS NULL AND mcp_server_id IS NULL) OR
            (mcp_tool_name IS NOT NULL AND mcp_server_id IS NOT NULL)
        )
);

COMMENT ON TABLE chat_messages IS '对话消息表：会话中的单条消息';
COMMENT ON COLUMN chat_messages.session_id IS '所属会话ID';
COMMENT ON COLUMN chat_messages.role IS '消息角色：user/assistant/system/tool';
COMMENT ON COLUMN chat_messages.content IS '消息内容文本';
COMMENT ON COLUMN chat_messages.tool_calls IS 'AI 调用的工具列表（JSONB）';
COMMENT ON COLUMN chat_messages.tool_results IS '工具执行结果（JSONB）';
COMMENT ON COLUMN chat_messages.mcp_server_id IS 'MCP Server ID（MCP工具调用时）';
COMMENT ON COLUMN chat_messages.mcp_tool_name IS 'MCP 工具名称';
COMMENT ON COLUMN chat_messages.token_count IS 'Token 计数（JSONB）';
COMMENT ON COLUMN chat_messages.metadata IS '消息元数据（JSONB）';

-- 消息插入后自动更新会话统计的触发器
CREATE OR REPLACE FUNCTION update_chat_session_stats()
RETURNS TRIGGER AS $$
DECLARE
    total_tokens_sum INTEGER;
BEGIN
    -- 更新消息计数
    UPDATE chat_sessions
    SET message_count = message_count + 1
    WHERE id = NEW.session_id;

    -- 更新 token 统计
    SELECT COALESCE(SUM((COALESCE(token_count->>'total_tokens', '0'))::INTEGER), 0)
    INTO total_tokens_sum
    FROM chat_messages
    WHERE session_id = NEW.session_id;

    UPDATE chat_sessions
    SET total_tokens = total_tokens_sum
    WHERE id = NEW.session_id;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_chat_messages_update_stats
    AFTER INSERT ON chat_messages
    FOR EACH ROW
    EXECUTE FUNCTION update_chat_session_stats();
```

---

### 2.6 MCP 域

#### 2.6.1 mcp_servers — MCP Server 注册表

```sql
-- ============================================================
-- MCP Server 注册表: 存储外部 MCP (Model Context Protocol) 服务器信息
-- 支持 SSE 和 stdio 两种传输方式
-- ============================================================
CREATE TABLE mcp_servers (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- Server 名称（显示用）
    name                VARCHAR(100) NOT NULL,

    -- Server 描述
    description         VARCHAR(500),

    -- Server URL 或命令（sse 为 URL，stdio 为命令路径）
    server_url          VARCHAR(1000) NOT NULL,

    -- 传输类型：sse (Server-Sent Events) / stdio (标准输入输出)
    transport_type      VARCHAR(20) NOT NULL DEFAULT 'sse',

    -- 工具目录（JSONB：注册时自动拉取的工具列表）
    tools_catalog       JSONB DEFAULT '[]',

    -- 是否激活
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,

    -- 认证配置（JSONB：API key、token、header 等）
    auth_config         JSONB DEFAULT '{}',

    -- 健康状态：healthy / unhealthy / unknown
    health_status       VARCHAR(20) DEFAULT 'unknown',

    -- 最后心跳时间
    last_heartbeat_at   TIMESTAMPTZ,

    -- Server 配置（JSONB：超时、重试、环境变量等）
    server_config       JSONB DEFAULT '{}',

    -- 创建者
    created_by          BIGINT NOT NULL,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,

    -- 外键约束
    CONSTRAINT fk_mcp_servers_created_by
        FOREIGN KEY (created_by) REFERENCES users(id)
        ON DELETE RESTRICT,

    -- 传输类型校验
    CONSTRAINT chk_mcp_servers_transport 
        CHECK (transport_type IN ('sse', 'stdio')),

    -- 健康状态校验
    CONSTRAINT chk_mcp_servers_health 
        CHECK (health_status IN ('healthy', 'unhealthy', 'unknown')),

    -- 名称唯一
    CONSTRAINT uk_mcp_servers_name UNIQUE (name)
);

COMMENT ON TABLE mcp_servers IS 'MCP Server 注册表：外部 MCP 服务器的配置和状态';
COMMENT ON COLUMN mcp_servers.name IS 'Server 名称';
COMMENT ON COLUMN mcp_servers.server_url IS 'Server URL（sse）或命令路径（stdio）';
COMMENT ON COLUMN mcp_servers.transport_type IS '传输类型：sse 或 stdio';
COMMENT ON COLUMN mcp_servers.tools_catalog IS '工具目录（JSONB，注册时自动拉取）';
COMMENT ON COLUMN mcp_servers.is_active IS '是否激活';
COMMENT ON COLUMN mcp_servers.auth_config IS '认证配置（JSONB）';
COMMENT ON COLUMN mcp_servers.health_status IS '健康状态';
COMMENT ON COLUMN mcp_servers.last_heartbeat_at IS '最后心跳时间';
COMMENT ON COLUMN mcp_servers.server_config IS 'Server 配置（JSONB）';

CREATE TRIGGER trg_mcp_servers_updated_at
    BEFORE UPDATE ON mcp_servers
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();
```

#### 2.6.2 mcp_tool_invocations — MCP 工具调用记录

```sql
-- ============================================================
-- MCP 工具调用记录表: 记录每次 MCP 工具调用的详细信息
-- 用于审计、调试和性能分析
-- ============================================================
CREATE TABLE mcp_tool_invocations (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    -- 调用的 MCP Server
    mcp_server_id       BIGINT NOT NULL,

    -- 调用的工具名称
    tool_name           VARCHAR(200) NOT NULL,

    -- 请求载荷（JSONB：传递给工具的参数）
    request_payload     JSONB NOT NULL DEFAULT '{}',

    -- 响应载荷（JSONB：工具返回的结果）
    response_payload    JSONB DEFAULT '{}',

    -- 调用状态
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',

    -- 错误信息
    error_message       TEXT,

    -- 执行耗时（毫秒）
    duration_ms         INTEGER,

    -- 关联的任务 ID（如工具调用触发了任务）
    task_id             BIGINT,

    -- 关联的对话消息 ID
    chat_message_id     BIGINT,

    -- 调用者用户 ID
    user_id             BIGINT,

    -- 调用元数据（JSONB：如重试次数、超时设置等）
    metadata            JSONB DEFAULT '{}',

    created_at          TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at        TIMESTAMPTZ,

    -- 外键约束
    CONSTRAINT fk_mcp_tool_invocations_server_id
        FOREIGN KEY (mcp_server_id) REFERENCES mcp_servers(id)
        ON DELETE CASCADE,

    CONSTRAINT fk_mcp_tool_invocations_task_id
        FOREIGN KEY (task_id) REFERENCES tasks(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_mcp_tool_invocations_chat_message_id
        FOREIGN KEY (chat_message_id) REFERENCES chat_messages(id)
        ON DELETE SET NULL,

    CONSTRAINT fk_mcp_tool_invocations_user_id
        FOREIGN KEY (user_id) REFERENCES users(id)
        ON DELETE SET NULL,

    -- 状态校验
    CONSTRAINT chk_mcp_tool_invocations_status 
        CHECK (status IN ('pending', 'running', 'success', 'error', 'timeout', 'cancelled'))
);

COMMENT ON TABLE mcp_tool_invocations IS 'MCP 工具调用记录表：每次 MCP 工具调用的详细信息';
COMMENT ON COLUMN mcp_tool_invocations.mcp_server_id IS 'MCP Server ID';
COMMENT ON COLUMN mcp_tool_invocations.tool_name IS '调用的工具名称';
COMMENT ON COLUMN mcp_tool_invocations.request_payload IS '请求参数（JSONB）';
COMMENT ON COLUMN mcp_tool_invocations.response_payload IS '响应结果（JSONB）';
COMMENT ON COLUMN mcp_tool_invocations.status IS '调用状态';
COMMENT ON COLUMN mcp_tool_invocations.duration_ms IS '执行耗时（毫秒）';
COMMENT ON COLUMN mcp_tool_invocations.task_id IS '关联的任务ID';
COMMENT ON COLUMN mcp_tool_invocations.chat_message_id IS '关联的对话消息ID';
COMMENT ON COLUMN mcp_tool_invocations.user_id IS '调用者用户ID';
COMMENT ON COLUMN mcp_tool_invocations.metadata IS '调用元数据（JSONB）';
```


---

## 3. 索引设计

### 3.1 索引设计原则

1. **所有外键自动创建索引**：加速 JOIN 和级联删除
2. **所有 JSONB 字段创建 GIN 索引**：支持灵活查询
3. **常用查询条件字段创建 B-tree 索引**：如 status、created_at
4. **唯一标识字段创建唯一索引**：如 UUID 字段
5. **部分索引**：仅索引活跃记录，减少索引大小
6. **复合索引**：多条件查询场景
7. **全文搜索索引**：名称、描述字段的搜索

### 3.2 用户域索引

```sql
-- ============================================================
-- users 表索引
-- ============================================================

-- 主键索引 (自动生成)
-- PRIMARY KEY (id)

-- 唯一索引 (自动生成)
-- UNIQUE (username), UNIQUE (email)

-- 角色 + 状态索引（查询活跃用户列表）
CREATE INDEX idx_users_role_active ON users(role, is_active);

-- 创建时间索引（排序查询）
CREATE INDEX idx_users_created_at ON users(created_at DESC);

-- 全文搜索索引（用户名和邮箱搜索）
CREATE INDEX idx_users_search ON users 
    USING GIN(to_tsvector('simple', COALESCE(username, '') || ' ' || COALESCE(email, '')));

-- ============================================================
-- workspaces 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_workspaces_user_id ON workspaces(user_id);
CREATE INDEX idx_workspaces_parent_id ON workspaces(parent_id);

-- 路径索引（子树查询：查找某路径下的所有工作空间）
CREATE INDEX idx_workspaces_path ON workspaces USING GIN(path gin_trgm_ops);

-- 用户 + 父级索引（查询某用户的顶层工作空间）
CREATE INDEX idx_workspaces_user_parent ON workspaces(user_id, parent_id);

-- 排序查询
CREATE INDEX idx_workspaces_sort ON workspaces(user_id, sort_order);
```

### 3.3 流程域索引

```sql
-- ============================================================
-- flow_categories 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_flow_categories_parent_id ON flow_categories(parent_id);

-- 父级 + slug 唯一索引（自动生成）
-- UNIQUE (parent_id, slug)

-- 激活状态索引（只查询活跃分类）
CREATE INDEX idx_flow_categories_active ON flow_categories(is_active) 
    WHERE is_active = TRUE;

-- ============================================================
-- flow_definitions 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_flow_definitions_category_id ON flow_definitions(category_id);
CREATE INDEX idx_flow_definitions_created_by ON flow_definitions(created_by);

-- 流程 key 查询（不区分版本）
CREATE INDEX idx_flow_definitions_flow_key ON flow_definitions(flow_key);

-- 激活 + 公开索引（查询用户可见的流程列表）
CREATE INDEX idx_flow_definitions_visible ON flow_definitions(is_active, is_public, created_by) 
    WHERE is_active = TRUE;

-- GIN 索引：parsed_config 中的参数搜索
CREATE INDEX idx_flow_definitions_parsed_config ON flow_definitions 
    USING GIN(parsed_config jsonb_path_ops);

-- GIN 索引：sample_sheet_columns 查询
CREATE INDEX idx_flow_definitions_sample_sheet ON flow_definitions 
    USING GIN(sample_sheet_columns jsonb_path_ops);

-- GIN 索引：execution_config 查询
CREATE INDEX idx_flow_definitions_exec_config ON flow_definitions 
    USING GIN(execution_config jsonb_path_ops);

-- 全文搜索索引（流程名称和描述搜索）
CREATE INDEX idx_flow_definitions_search ON flow_definitions 
    USING GIN(to_tsvector('chinese', COALESCE(name, '') || ' ' || COALESCE(description, '')));

-- 使用次数排序索引
CREATE INDEX idx_flow_definitions_usage ON flow_definitions(usage_count DESC) 
    WHERE is_active = TRUE;

-- 创建时间索引
CREATE INDEX idx_flow_definitions_created_at ON flow_definitions(created_at DESC);
```

### 3.4 项目与文件域索引

```sql
-- ============================================================
-- projects 表索引
-- ============================================================

-- UUID 唯一索引（自动生成）
-- UNIQUE (project_uuid)

-- 外键索引
CREATE INDEX idx_projects_user_id ON projects(user_id);
CREATE INDEX idx_projects_workspace_id ON projects(workspace_id);

-- 用户 + 状态索引（查询用户的活跃项目）
CREATE INDEX idx_projects_user_status ON projects(user_id, status) 
    WHERE status = 'active';

-- 标签 GIN 索引（标签筛选）
CREATE INDEX idx_projects_tags ON projects USING GIN(tags);

-- GIN 索引：config 查询
CREATE INDEX idx_projects_config ON projects USING GIN(config jsonb_path_ops);

-- 全文搜索索引（项目名称和描述）
CREATE INDEX idx_projects_search ON projects 
    USING GIN(to_tsvector('chinese', COALESCE(name, '') || ' ' || COALESCE(description, '')));

-- 创建时间索引
CREATE INDEX idx_projects_created_at ON projects(created_at DESC);

-- ============================================================
-- samples 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_samples_project_id ON samples(project_id);

-- 文件类型索引（按类型筛选样本）
CREATE INDEX idx_samples_file_type ON samples(file_type);

-- GIN 索引：metadata 查询
CREATE INDEX idx_samples_metadata ON samples USING GIN(metadata jsonb_path_ops);

-- GIN 索引：sample_sheet_data 查询
CREATE INDEX idx_samples_sheet_data ON samples USING GIN(sample_sheet_data jsonb_path_ops);

-- GIN 索引：grouping 查询
CREATE INDEX idx_samples_grouping ON samples USING GIN(grouping jsonb_path_ops);

-- 全文搜索索引（样本名称）
CREATE INDEX idx_samples_name_search ON samples 
    USING GIN(to_tsvector('simple', COALESCE(name, '') || ' ' || COALESCE(display_name, '')));

-- 创建时间索引
CREATE INDEX idx_samples_created_at ON samples(created_at DESC);

-- ============================================================
-- file_records 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_file_records_user_id ON file_records(user_id);
CREATE INDEX idx_file_records_project_id ON file_records(project_id);

-- 分类索引（按文件类型筛选）
CREATE INDEX idx_file_records_category ON file_records(category);

-- 用户 + 分类索引
CREATE INDEX idx_file_records_user_category ON file_records(user_id, category);

-- MIME 类型索引
CREATE INDEX idx_file_records_mime_type ON file_records(mime_type);

-- GIN 索引：metadata 查询
CREATE INDEX idx_file_records_metadata ON file_records USING GIN(metadata jsonb_path_ops);

-- 是否可见索引（隐藏临时文件）
CREATE INDEX idx_file_records_visible ON file_records(is_visible) 
    WHERE is_visible = TRUE;

-- 创建时间索引
CREATE INDEX idx_file_records_created_at ON file_records(created_at DESC);
```

### 3.5 任务域索引

```sql
-- ============================================================
-- tasks 表索引
-- ============================================================

-- UUID 唯一索引（自动生成）
-- UNIQUE (task_id)

-- 外键索引
CREATE INDEX idx_tasks_user_id ON tasks(user_id);
CREATE INDEX idx_tasks_project_id ON tasks(project_id);
CREATE INDEX idx_tasks_flow_definition_id ON tasks(flow_definition_id);

-- 状态索引（最常见的查询条件）
CREATE INDEX idx_tasks_status ON tasks(status);

-- 用户 + 状态索引（查询某用户的特定状态任务）
CREATE INDEX idx_tasks_user_status ON tasks(user_id, status);

-- 项目 + 状态索引
CREATE INDEX idx_tasks_project_status ON tasks(project_id, status);

-- 执行模式 + 后端索引（调度器查询）
CREATE INDEX idx_tasks_execution ON tasks(execution_mode, execution_backend, status) 
    WHERE status IN ('submitted', 'running');

-- GIN 索引：parameters 查询
CREATE INDEX idx_tasks_parameters ON tasks USING GIN(parameters jsonb_path_ops);

-- GIN 索引：resources 查询
CREATE INDEX idx_tasks_resources ON tasks USING GIN(resources jsonb_path_ops);

-- GIN 索引：results_summary 查询
CREATE INDEX idx_tasks_results ON tasks USING GIN(results_summary jsonb_path_ops);

-- 进度索引（查询进行中的任务）
CREATE INDEX idx_tasks_progress ON tasks(progress_percent, status) 
    WHERE status = 'running';

-- 时间范围索引（查询时间段内的任务）
CREATE INDEX idx_tasks_time_range ON tasks(created_at DESC);
CREATE INDEX idx_tasks_started_at ON tasks(started_at DESC);

-- 全文搜索索引（任务名称搜索）
CREATE INDEX idx_tasks_name_search ON tasks 
    USING GIN(to_tsvector('chinese', COALESCE(name, '') || ' ' || COALESCE(description, '')));

-- ============================================================
-- task_logs 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_task_logs_task_id ON task_logs(task_id);

-- 日志类型索引
CREATE INDEX idx_task_logs_type ON task_logs(log_type);

-- 步骤索引（查询某步骤的日志）
CREATE INDEX idx_task_logs_step ON task_logs(task_id, step_index);

-- 日志级别索引
CREATE INDEX idx_task_logs_level ON task_logs(log_level);

-- 创建时间索引（日志时间排序）
CREATE INDEX idx_task_logs_created_at ON task_logs(created_at DESC);

-- 复合索引：任务 + 类型 + 时间（最常用的日志查询模式）
CREATE INDEX idx_task_logs_task_type_time ON task_logs(task_id, log_type, created_at DESC);

-- ============================================================
-- task_events 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_task_events_task_id ON task_events(task_id);

-- 事件类型索引
CREATE INDEX idx_task_events_type ON task_events(event_type);

-- 创建时间索引
CREATE INDEX idx_task_events_created_at ON task_events(created_at DESC);

-- 复合索引：任务 + 时间（查询某任务的事件历史）
CREATE INDEX idx_task_events_task_time ON task_events(task_id, created_at DESC);
```

### 3.6 AI 对话域索引

```sql
-- ============================================================
-- chat_sessions 表索引
-- ============================================================

-- UUID 唯一索引（自动生成）
-- UNIQUE (session_id)

-- 外键索引
CREATE INDEX idx_chat_sessions_user_id ON chat_sessions(user_id);

-- 状态索引
CREATE INDEX idx_chat_sessions_status ON chat_sessions(status) 
    WHERE status = 'active';

-- GIN 索引：context_snapshot 查询
CREATE INDEX idx_chat_sessions_context ON chat_sessions 
    USING GIN(context_snapshot jsonb_path_ops);

-- 创建时间索引
CREATE INDEX idx_chat_sessions_created_at ON chat_sessions(created_at DESC);

-- 用户 + 状态索引（查询某用户的活跃会话）
CREATE INDEX idx_chat_sessions_user_status ON chat_sessions(user_id, status);

-- ============================================================
-- chat_messages 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_chat_messages_session_id ON chat_messages(session_id);
CREATE INDEX idx_chat_messages_mcp_server_id ON chat_messages(mcp_server_id);

-- 角色索引
CREATE INDEX idx_chat_messages_role ON chat_messages(role);

-- MCP 工具查询索引
CREATE INDEX idx_chat_messages_mcp_tool ON chat_messages(mcp_tool_name) 
    WHERE mcp_tool_name IS NOT NULL;

-- GIN 索引：tool_calls 查询
CREATE INDEX idx_chat_messages_tool_calls ON chat_messages 
    USING GIN(tool_calls jsonb_path_ops);

-- GIN 索引：tool_results 查询
CREATE INDEX idx_chat_messages_tool_results ON chat_messages 
    USING GIN(tool_results jsonb_path_ops);

-- 创建时间索引
CREATE INDEX idx_chat_messages_created_at ON chat_messages(created_at DESC);

-- 会话 + 时间索引（查询某会话的消息列表）
CREATE INDEX idx_chat_messages_session_time ON chat_messages(session_id, created_at DESC);
```

### 3.7 MCP 域索引

```sql
-- ============================================================
-- mcp_servers 表索引
-- ============================================================

-- 名称唯一索引（自动生成）
-- UNIQUE (name)

-- 外键索引
CREATE INDEX idx_mcp_servers_created_by ON mcp_servers(created_by);

-- 激活状态索引
CREATE INDEX idx_mcp_servers_active ON mcp_servers(is_active) 
    WHERE is_active = TRUE;

-- 健康状态索引
CREATE INDEX idx_mcp_servers_health ON mcp_servers(health_status);

-- GIN 索引：tools_catalog 查询
CREATE INDEX idx_mcp_servers_tools ON mcp_servers 
    USING GIN(tools_catalog jsonb_path_ops);

-- GIN 索引：auth_config 查询
CREATE INDEX idx_mcp_servers_auth ON mcp_servers 
    USING GIN(auth_config jsonb_path_ops);

-- 最后心跳时间索引（健康检查）
CREATE INDEX idx_mcp_servers_heartbeat ON mcp_servers(last_heartbeat_at);

-- ============================================================
-- mcp_tool_invocations 表索引
-- ============================================================

-- 外键索引
CREATE INDEX idx_mcp_invocations_server_id ON mcp_tool_invocations(mcp_server_id);
CREATE INDEX idx_mcp_invocations_task_id ON mcp_tool_invocations(task_id);
CREATE INDEX idx_mcp_invocations_chat_msg_id ON mcp_tool_invocations(chat_message_id);
CREATE INDEX idx_mcp_invocations_user_id ON mcp_tool_invocations(user_id);

-- 状态索引
CREATE INDEX idx_mcp_invocations_status ON mcp_tool_invocations(status);

-- 工具名称索引
CREATE INDEX idx_mcp_invocations_tool ON mcp_tool_invocations(tool_name);

-- Server + 工具索引（查询某 Server 的某工具调用）
CREATE INDEX idx_mcp_invocations_server_tool ON mcp_tool_invocations(mcp_server_id, tool_name);

-- GIN 索引：request_payload 查询
CREATE INDEX idx_mcp_invocations_request ON mcp_tool_invocations 
    USING GIN(request_payload jsonb_path_ops);

-- 创建时间索引
CREATE INDEX idx_mcp_invocations_created_at ON mcp_tool_invocations(created_at DESC);

-- 复合索引：Server + 状态 + 时间（查询某 Server 的最近调用）
CREATE INDEX idx_mcp_invocations_server_status_time 
    ON mcp_tool_invocations(mcp_server_id, status, created_at DESC);
```


---

## 4. JSONB 字段详细说明

### 4.1 设计原则

1. **类型安全**：JSONB 字段在应用层通过 Pydantic v2 模型验证
2. **文档化**：每个 JSONB 字段都有明确的数据结构定义
3. **查询优化**：所有 JSONB 字段都建有 GIN 索引
4. **迁移友好**：JSONB 结构变更不需要数据库迁移

### 4.2 users.preferences — 用户偏好设置

**数据结构示例：**

```json
{
  "theme": "dark",
  "language": "zh-CN",
  "notifications": {
    "email_on_task_complete": true,
    "email_on_task_fail": true,
    "browser_notify": true
  },
  "default_workspace_id": 5,
  "page_size": 20,
  "default_flow_parameters": {
    "species": "Arabidopsis thaliana",
    "genome_version": "TAIR10"
  }
}
```

**Pydantic v2 模型（应用层验证）：**

```python
from pydantic import BaseModel, Field
from typing import Optional

class NotificationSettings(BaseModel):
    email_on_task_complete: bool = True
    email_on_task_fail: bool = True
    browser_notify: bool = True

class UserPreferences(BaseModel):
    theme: str = "light"  # "light" | "dark" | "auto"
    language: str = "zh-CN"
    notifications: NotificationSettings = NotificationSettings()
    default_workspace_id: Optional[int] = None
    page_size: int = Field(default=20, ge=5, le=100)
    default_flow_parameters: dict = {}
```

**GIN 索引查询示例：**

```sql
-- 查询使用深色主题的用户
SELECT id, username FROM users 
WHERE preferences @> '{"theme": "dark"}';

-- 查询开启了任务完成邮件通知的用户
SELECT id, username FROM users 
WHERE preferences @> '{"notifications": {"email_on_task_complete": true}}';
```

---

### 4.3 workspaces.config — 工作空间配置

**数据结构示例：**

```json
{
  "color": "#52c41a",
  "icon": "ExperimentOutlined",
  "default_flow_key": "rna-seq-star-deseq2",
  "auto_cleanup_days": 30,
  "storage_quota_gb": 100
}
```

**GIN 索引查询示例：**

```sql
-- 查询标记为特定颜色的工作空间
SELECT * FROM workspaces WHERE config @> '{"color": "#52c41a"}';
```

---

### 4.4 flow_categories.metadata — 分类元数据

**数据结构示例：**

```json
{
  "domain": "transcriptomics",
  "common_species": ["Arabidopsis thaliana", "Oryza sativa"],
  "typical_runtime_hours": 4,
  "required_resources": {
    "min_cores": 4,
    "min_memory_gb": 16
  }
}
```

---

### 4.5 flow_definitions.parsed_config — 解析后的流程配置

**数据结构示例：**

```json
{
  "params": {
    "genome": {
      "type": "select",
      "label": "参考基因组",
      "options": ["TAIR10", "Col-0_Ens",
"t2t"],
      "required": true,
      "default": "TAIR10"
    },
    "threads": {
      "type": "integer",
      "label": "线程数",
      "min": 1,
      "max": 64,
      "default": 8
    },
    "p_value_cutoff": {
      "type": "float",
      "label": "P值阈值",
      "min": 0.001,
      "max": 0.1,
      "default": 0.05,
      "step": 0.001
    },
    "skip_qc": {
      "type": "boolean",
      "label": "跳过质控",
      "default": false
    }
  },
  "steps": [
    {
      "name": "fastqc",
      "label": "FastQC 质控",
      "order": 1,
      "enabled_by_default": true,
      "dependencies": [],
      "output_files": ["*_fastqc.html", "*_fastqc.zip"]
    },
    {
      "name": "trimming",
      "label": "接头修剪",
      "order": 2,
      "enabled_by_default": true,
      "dependencies": ["fastqc"],
      "condition": "params.skip_qc == false"
    },
    {
      "name": "star_alignment",
      "label": "STAR 比对",
      "order": 3,
      "enabled_by_default": true,
      "dependencies": ["trimming"],
      "resources": {"cores": 16, "memory_gb": 64}
    },
    {
      "name": "deseq2_analysis",
      "label": "DESeq2 差异分析",
      "order": 4,
      "enabled_by_default": true,
      "dependencies": ["star_alignment"],
      "resources": {"cores": 4, "memory_gb": 16}
    }
  ],
  "conditions": [
    {
      "if": "params.skip_qc",
      "then": {"skip_steps": ["fastqc"]}
    }
  ],
  "outputs": {
    "reports": ["multiqc_report.html", "deseq2_results.xlsx"],
    "data_files": ["counts_matrix.csv", "normalized_counts.csv"],
    "plots": ["pca_plot.pdf", "volcano_plot.pdf", "heatmap.pdf"]
  }
}
```

**Pydantic v2 模型（部分）：**

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional, List, Union

class SelectParam(BaseModel):
    type: Literal["select"]
    label: str
    options: List[str]
    required: bool = False
    default: Optional[str] = None

class IntegerParam(BaseModel):
    type: Literal["integer"]
    label: str
    min: Optional[int] = None
    max: Optional[int] = None
    default: int = 0

class FloatParam(BaseModel):
    type: Literal["float"]
    label: str
    min: Optional[float] = None
    max: Optional[float] = None
    default: float = 0.0
    step: Optional[float] = None

class BooleanParam(BaseModel):
    type: Literal["boolean"]
    label: str
    default: bool = False

ParamDefinition = Union[SelectParam, IntegerParam, FloatParam, BooleanParam]

class FlowStep(BaseModel):
    name: str
    label: str
    order: int
    enabled_by_default: bool = True
    dependencies: List[str] = []
    condition: Optional[str] = None
    resources: Optional[dict] = None
    output_files: List[str] = []

class ParsedConfig(BaseModel):
    params: dict[str, ParamDefinition] = {}
    steps: List[FlowStep] = []
    conditions: List[dict] = []
    outputs: dict = {}
```

**GIN 索引查询示例：**

```sql
-- 查询包含特定参数的流程
SELECT id, flow_key, name FROM flow_definitions 
WHERE parsed_config @> '{"params": {"genome": {"type": "select"}}}';

-- 查询包含特定步骤的流程
SELECT id, flow_key, name FROM flow_definitions 
WHERE parsed_config @> '{"steps": [{"name": "deseq2_analysis"}]}';

-- 查询输出包含特定报告文件的流程
SELECT id, flow_key, name FROM flow_definitions 
WHERE parsed_config @> '{"outputs": {"reports": ["multiqc_report.html"]}}';

-- 使用 jsonb_path_query 提取所有流程的参数列表
SELECT flow_key, name,
    jsonb_object_keys(parsed_config->'params') AS param_name
FROM flow_definitions 
WHERE parsed_config ? 'params';
```

---

### 4.6 flow_definitions.sample_sheet_columns — 样本表必填列

**数据结构示例：**

```json
[
  {
    "name": "sample_id",
    "label": "样本ID",
    "type": "string",
    "required": true,
    "description": "唯一的样本标识符"
  },
  {
    "name": "group",
    "label": "分组",
    "type": "string",
    "required": true,
    "description": "实验分组，如 WT, KO, OE"
  },
  {
    "name": "replicate",
    "label": "生物学重复",
    "type": "integer",
    "required": true,
    "default": 1
  },
  {
    "name": "fq1",
    "label": "R1文件路径",
    "type": "file",
    "required": true,
    "pattern": "*.fq.gz;*.fastq.gz"
  },
  {
    "name": "fq2",
    "label": "R2文件路径",
    "type": "file",
    "required": false,
    "pattern": "*.fq.gz;*.fastq.gz",
    "description": "双端测序的R2文件，单端测序留空"
  },
  {
    "name": "batch",
    "label": "批次",
    "type": "string",
    "required": false,
    "description": "测序批次，用于批次效应校正"
  }
]
```

---

### 4.7 flow_definitions.execution_config — 执行配置

**数据结构示例：**

```json
{
  "engine": "snakemake",
  "snakefile": "workflows/rna-seq/Snakefile",
  "conda_env": "envs/rna-seq.yaml",
  "default_resources": {
    "cores": 8,
    "memory_gb": 32,
    "runtime_hours": 24
  },
  "cluster_config": {
    "partition": "normal",
    "qos": "batch",
    "account": "omics"
  },
  "singularity": {
    "enabled": true,
    "image": "docker://evolobiorna/cygnusx-rna-seq:latest"
  },
  "environment_variables": {
    "OMP_NUM_THREADS": "8"
  }
}
```

---

### 4.8 projects.config — 项目配置

**数据结构示例：**

```json
{
  "species": {
    "scientific_name": "Arabidopsis thaliana",
    "common_name": "拟南芥",
    "taxid": 3702
  },
  "reference_genome": {
    "version": "TAIR10",
    "fasta_path": "/ref/ath/TAIR10.fa",
    "gtf_path": "/ref/ath/TAIR10.gtf",
    "annotation_source": "Araport11"
  },
  "sequencing": {
    "platform": "Illumina NovaSeq 6000",
    "read_length": 150,
    "layout": "paired-end",
    "strand_specificity": "reverse"
  },
  "default_parameters": {
    "threads": 16,
    "p_value_cutoff": 0.05,
    "log2fc_cutoff": 1.0
  },
  "contacts": [
    {"name": "张教授", "role": "PI", "email": "zhang@hzau.edu.cn"}
  ]
}
```

---

### 4.9 samples.metadata — 样本元数据

**数据结构示例：**

```json
{
  "platform": "Illumina NovaSeq 6000",
  "read_length": 150,
  "layout": "paired-end",
  "library_prep": "TruSeq Stranded mRNA",
  " sequencing_date": "2024-01-15",
  "sequencing_center": "BGI",
  "lane": "L001",
  "barcode": "ATCGATCG",
  "concentration_ng_ul": 12.5,
  "rin_score": 8.2,
  "organism": "Arabidopsis thaliana",
  "tissue": "leaf",
  "treatment": "drought_stress_7d",
  "biological_replicate": 1,
  "technical_replicate": 1
}
```

---

### 4.10 samples.sample_sheet_data — 样本表结构化数据

**数据结构示例：**

```json
{
  "sample_id": "WT_Rep1",
  "group": "WT",
  "replicate": 1,
  "fq1": "/data/proj1/raw/WT_Rep1_R1.fq.gz",
  "fq2": "/data/proj1/raw/WT_Rep1_R2.fq.gz",
  "batch": "Batch_20240115",
  "notes": "生长条件：22°C，16h光照"
}
```

---

### 4.11 samples.grouping — 样本分组信息

**数据结构示例：**

```json
{
  "condition": "wild_type",
  "contrast_group": "control",
  "batch": "batch_1",
  "batch_corrected": false,
  "group_color": "#1890ff",
  "paired_sample": null
}
```

---

### 4.12 samples.qc_results — 质量评估结果

**数据结构示例：**

```json
{
  "fastqc": {
    "total_reads": 28500000,
    "gc_content": 0.36,
    "q30_rate": 0.94,
    "adapter_contamination": false,
    "per_base_quality": "PASS",
    "per_sequence_quality": "PASS",
    "report_path": "/data/proj1/qc/WT_Rep1_fastqc.html"
  },
  "trimming": {
    "input_reads": 28500000,
    "surviving_reads": 27200000,
    "survival_rate": 0.954,
    "trimmed_bases": 43200000
  },
  "alignment": {
    "total_reads": 27200000,
    "mapped_reads": 25800000,
    "mapping_rate": 0.949,
    "unique_mapped": 24100000,
    "multi_mapped": 1700000,
    "unmapped": 1400000
  }
}
```

---

### 4.13 tasks.parameters — 用户提交的参数值

**数据结构示例：**

```json
{
  "genome": "TAIR10",
  "threads": 16,
  "p_value_cutoff": 0.05,
  "log2fc_cutoff": 1.0,
  "skip_qc": false,
  "contrast_groups": ["WT", "drought_7d"],
  "batch_correction": true,
  "gsea_analysis": true,
  "gsea_gene_sets": ["GO_BP", "KEGG", "Reactome"]
}
```

**GIN 索引查询示例：**

```sql
-- 查询使用了特定基因组的任务
SELECT t.task_id, t.name, t.status 
FROM tasks t
WHERE t.parameters @> '{"genome": "TAIR10"}';

-- 查询启用了 GSEA 分析的任务
SELECT t.task_id, t.name 
FROM tasks t
WHERE t.parameters @> '{"gsea_analysis": true}';

-- 查询参数中包含特定对比组的任务
SELECT t.task_id, t.name, t.parameters->'contrast_groups' AS groups
FROM tasks t
WHERE t.parameters->'contrast_groups' @> '["WT"]'
   OR t.parameters->'contrast_groups' @> '["drought_7d"]';
```

---

### 4.14 tasks.resources — 资源请求

**数据结构示例：**

```json
{
  "cores": 16,
  "memory_gb": 64,
  "runtime_hours": 24,
  "gpu_count": 0,
  "partition": "normal",
  "queue": "batch",
  "scratch_gb": 200
}
```

---

### 4.15 tasks.results_summary — 结果摘要

**数据结构示例：**

```json
{
  "status": "success",
  "completed_steps": 4,
  "total_steps": 4,
  "output_files": [
    {"path": "results/multiqc_report.html", "size": 2458000, "category": "report"},
    {"path": "results/counts_matrix.csv", "size": 15600000, "category": "data"},
    {"path": "results/deseq2_results.xlsx", "size": 3200000, "category": "data"},
    {"path": "results/pca_plot.pdf", "size": 450000, "category": "plot"},
    {"path": "results/volcano_plot.pdf", "size": 380000, "category": "plot"},
    {"path": "results/heatmap.pdf", "size": 520000, "category": "plot"}
  ],
  "statistics": {
    "total_genes": 33602,
    "differentially_expressed": 1847,
    "up_regulated": 923,
    "down_regulated": 924,
    "significant_go_terms": 156,
    "significant_kegg_pathways": 42
  },
  "execution_summary": {
    "wall_time_hours": 3.2,
    "cpu_hours": 51.2,
    "peak_memory_gb": 45.3,
    "snakemake_version": "7.32.4"
  }
}
```

---

### 4.16 task_events.details — 事件详情

**数据结构示例：**

```json
{
  "step_name": "star_alignment",
  "step_index": 3,
  "exit_code": 0,
  "signal": null,
  "resource_usage": {
    "cpu_percent": 98.5,
    "memory_gb": 42.3,
    "runtime_minutes": 45
  }
}
```

---

### 4.17 chat_sessions.context_snapshot — 上下文快照

**数据结构示例：**

```json
{
  "current_project_id": 12,
  "current_project_name": "拟南芥干旱胁迫转录组",
  "current_flow_id": 5,
  "current_flow_name": "RNA-seq STAR-DESeq2",
  "current_task_id": 89,
  "current_task_status": "completed",
  "selected_samples": [101, 102, 103, 104],
  "active_tab": "results",
  "browser_info": {
    "page": "/projects/12/tasks/89/results",
    "timestamp": "2024-01-20T14:30:00+08:00"
  }
}
```

---

### 4.18 chat_messages.tool_calls — AI 工具调用

**数据结构示例：**

```json
[
  {
    "id": "call_abc123",
    "type": "function",
    "function": {
      "name": "query_task_results",
      "arguments": {
        "task_id": "89",
        "result_type": "differential_expression"
      }
    }
  }
]
```

---

### 4.19 chat_messages.tool_results — 工具执行结果

**数据结构示例：**

```json
[
  {
    "tool_call_id": "call_abc123",
    "role": "tool",
    "content": {
      "total_de_genes": 1847,
      "top_genes": [
        {"gene_id": "AT1G01010", "log2FoldChange": 2.34, "padj": 0.001},
        {"gene_id": "AT1G01020", "log2FoldChange": -1.87, "padj": 0.003}
      ]
    }
  }
]
```

---

### 4.20 chat_messages.token_count — Token 计数

**数据结构示例：**

```json
{
  "prompt_tokens": 2456,
  "completion_tokens": 892,
  "total_tokens": 3348,
  "prompt_tokens_details": {
    "cached_tokens": 1800,
    "audio_tokens": 0
  }
}
```

---

### 4.21 mcp_servers.tools_catalog — 工具目录

**数据结构示例：**

```json
[
  {
    "name": "genome_browser_navigate",
    "description": "在基因组浏览器中导航到指定位置",
    "parameters": {
      "type": "object",
      "properties": {
        "chromosome": {"type": "string", "description": "染色体名称"},
        "start": {"type": "integer", "description": "起始位置"},
        "end": {"type": "integer", "description": "终止位置"}
      },
      "required": ["chromosome", "start", "end"]
    }
  },
  {
    "name": "run_enrichment_analysis",
    "description": "对基因列表进行功能富集分析",
    "parameters": {
      "type": "object",
      "properties": {
        "gene_list": {"type": "array", "items": {"type": "string"}},
        "ontology": {"type": "string", "enum": ["GO_BP", "GO_MF", "GO_CC", "KEGG"]},
        "p_value_cutoff": {"type": "number", "default": 0.05}
      },
      "required": ["gene_list", "ontology"]
    }
  }
]
```

---

### 4.22 mcp_servers.auth_config — 认证配置

**数据结构示例：**

```json
{
  "type": "bearer",
  "token": "sk-mcp-xxxxxxxxx",
  "header_name": "Authorization",
  "refresh_interval_hours": 24
}
```

```json
{
  "type": "api_key",
  "key_name": "X-API-Key",
  "key_value": "ak-xxxxxxxxx",
  "location": "header"
}
```

---

### 4.23 mcp_tool_invocations.request_payload / response_payload

**request_payload 示例：**

```json
{
  "chromosome": "Chr1",
  "start": 1234567,
  "end": 1235567,
  "tracks": ["genes", "expression", "variants"]
}
```

**response_payload 示例：**

```json
{
  "navigation_url": "https://jbrowse.hzau.edu.cn/?loc=Chr1:1234567..1235567",
  "visible_genes": [
    {"name": "AT1G04500", "start": 1234600, "end": 1235200, "strand": "+"},
    {"name": "AT1G04510", "start": 1235300, "end": 1235500, "strand": "-"}
  ],
  "expression_data": {
    "AT1G04500": {"WT": 45.2, "drought_7d": 128.7},
    "AT1G04510": {"WT": 12.1, "drought_7d": 8.3}
  }
}
```

---

### 4.24 file_records.metadata — 文件元数据

**数据结构示例：**

```json
{
  "compression": "gzip",
  "index_file": "/data/proj1/results/alignment.sorted.bam.bai",
  "column_names": ["gene_id", "baseMean", "log2FoldChange", "lfcSE", "stat", "pvalue", "padj"],
  "row_count": 33602,
  "delimiter": "\t",
  "encoding": "UTF-8"
}
```


---

## 5. 数据库 ER 关系描述

### 5.1 实体关系总览

```
users (1) ────────< (*) workspaces          一个用户有多个工作空间
users (1) ────────< (*) projects            一个用户有多个项目
users (1) ────────< (*) tasks               一个用户提交多个任务
users (1) ────────< (*) chat_sessions       一个用户有多个对话会话
users (1) ────────< (*) file_records        一个用户有多个文件记录
users (1) ────────< (*) flow_definitions    一个用户可创建多个流程（created_by）
users (1) ────────< (*) mcp_servers         一个用户可注册多个 MCP Server

workspaces (1) ───< (*) workspaces          自引用：父工作空间 → 子工作空间
workspaces (1) ───< (*) projects            一个工作空间包含多个项目

flow_categories (1) ─< (*) flow_categories  自引用：父分类 → 子分类
flow_categories (1) ─< (*) flow_definitions 一个分类下有多个流程定义

flow_definitions (1) ─< (*) tasks           一个流程定义被多个任务使用

projects (1) ─────< (*) samples             一个项目有多个样本
projects (1) ─────< (*) tasks               一个项目有多个任务
projects (1) ─────< (*) file_records        一个项目有多个文件

samples (1) ──────< (*) file_records (间接) 样本文件通过 file_path 关联

tasks (1) ────────< (*) task_logs           一个任务有多条日志
tasks (1) ────────< (*) task_events         一个任务有多个事件
tasks (1) ────────< (*) file_records        一个任务产生多个文件

chat_sessions (1) ─< (*) chat_messages      一个会话有多条消息

mcp_servers (1) ──< (*) chat_messages       一个 MCP Server 被多条消息引用
mcp_servers (1) ──< (*) mcp_tool_invocations 一个 MCP Server 有多次工具调用

chat_messages (1) ─< (*) mcp_tool_invocations 一条消息可能触发多次工具调用
tasks (1) ────────< (*) mcp_tool_invocations  一个任务可能由 MCP 工具触发
```

### 5.2 关系详情与级联策略

#### 5.2.1 用户域关系

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `users` | `workspaces` | 一对多 | `ON DELETE CASCADE` | 删除用户时级联删除其工作空间 |
| `users` | `projects` | 一对多 | `ON DELETE CASCADE` | 删除用户时级联删除其项目 |
| `users` | `tasks` | 一对多 | `ON DELETE RESTRICT` | 有任务的用户禁止删除 |
| `users` | `chat_sessions` | 一对多 | `ON DELETE CASCADE` | 删除用户时级联删除会话 |
| `users` | `file_records` | 一对多 | `ON DELETE CASCADE` | 删除用户时级联删除文件记录 |
| `users` | `flow_definitions` | 一对多 | `ON DELETE RESTRICT` | 有流程的用户禁止删除 |
| `users` | `mcp_servers` | 一对多 | `ON DELETE RESTRICT` | 有MCP Server的用户禁止删除 |

**workspaces 自引用关系：**

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `workspaces` | `workspaces` (parent_id) | 一对多 | `ON DELETE CASCADE` | 删除父工作空间级联删除子空间 |

#### 5.2.2 流程域关系

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `flow_categories` | `flow_categories` (parent_id) | 一对多 | `ON DELETE SET NULL` | 删除父分类，子分类变为顶级 |
| `flow_categories` | `flow_definitions` | 一对多 | `ON DELETE SET NULL` | 删除分类，流程变为未分类 |
| `flow_definitions` | `tasks` | 一对多 | `ON DELETE RESTRICT` | 有任务的流程定义禁止删除 |

#### 5.2.3 项目与文件域关系

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `workspaces` | `projects` | 一对多 | `ON DELETE SET NULL` | 删除工作空间，项目变为未分类 |
| `projects` | `samples` | 一对多 | `ON DELETE CASCADE` | 删除项目级联删除样本 |
| `projects` | `tasks` | 一对多 | `ON DELETE CASCADE` | 删除项目级联删除任务 |
| `projects` | `file_records` | 一对多 | `ON DELETE CASCADE` | 删除项目级联删除文件记录 |

#### 5.2.4 任务域关系

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `tasks` | `task_logs` | 一对多 | `ON DELETE CASCADE` | 删除任务级联删除日志 |
| `tasks` | `task_events` | 一对多 | `ON DELETE CASCADE` | 删除任务级联删除事件 |
| `tasks` | `file_records` | 一对多 | `ON DELETE SET NULL` | 删除任务，文件记录保留但解绑 |

#### 5.2.5 AI 对话域关系

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `chat_sessions` | `chat_messages` | 一对多 | `ON DELETE CASCADE` | 删除会话级联删除消息 |

#### 5.2.6 MCP 域关系

| 父表 | 子表 | 关系类型 | 级联策略 | 说明 |
|------|------|----------|----------|------|
| `mcp_servers` | `chat_messages` | 一对多 | `ON DELETE SET NULL` | 删除 Server，消息保留但解绑 |
| `mcp_servers` | `mcp_tool_invocations` | 一对多 | `ON DELETE CASCADE` | 删除 Server 级联删除调用记录 |
| `chat_messages` | `mcp_tool_invocations` | 一对多 | `ON DELETE SET NULL` | 删除消息，调用记录保留 |
| `tasks` | `mcp_tool_invocations` | 一对多 | `ON DELETE SET NULL` | 删除任务，调用记录保留 |
| `users` | `mcp_tool_invocations` | 一对多 | `ON DELETE SET NULL` | 删除用户，调用记录保留 |

### 5.3 ER 关系图（文字描述）

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           CygnusX ER 关系图                             │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌──────────┐       ┌──────────────┐       ┌─────────────────────┐     │
│  │  users   │◄──────┤  workspaces  │◄──────┤     projects        │     │
│  │          │  1:*  │  (self-ref)  │  1:*  │                     │     │
│  └────┬─────┘       └──────────────┘       └──────────┬──────────┘     │
│       │  ▲                                            │                  │
│       │  │ 1:*                                        │ 1:*              │
│       │  │                                            ▼                  │
│       │  │                                  ┌─────────────────────┐      │
│       │  │                                  │      samples        │      │
│       │  │                                  │                     │      │
│       │  │                                  └─────────────────────┘      │
│       │  │                                                               │
│       │  │                                1:*                            │
│       │  └────────────────────────────────┐                             │
│       │                                   ▼                             │
│       │                          ┌─────────────────────┐                │
│       │                          │       tasks         │◄──────┐        │
│       │                          │                     │       │        │
│       │                          └──────────┬──────────┘       │        │
│       │                                     │                  │        │
│       │                          1:*        │        1:*       │        │
│       │                          ▼          │         ▼        │        │
│       │               ┌──────────────────┐  │  ┌──────────────┐│        │
│       │               │    task_logs     │  │  │ task_events  ││        │
│       │               │                  │  │  │              ││        │
│       │               └──────────────────┘  │  └──────────────┘│        │
│       │                                     │                  │        │
│       │                    ┌────────────────┘                  │        │
│       │                    │                                   │        │
│       │                    ▼ 1:*                               │        │
│       │           ┌─────────────────────┐                      │        │
│       │           │   file_records      │                      │        │
│       │           │                     │                      │        │
│       │           └─────────────────────┘                      │        │
│       │                                                        │        │
│       │       ┌──────────────────────┐                         │        │
│       │       │  flow_categories     │◄─────────┐              │        │
│       │       │  (self-ref)          │          │ 1:*          │        │
│       │       └──────────────────────┘          │              │        │
│       │                                         ▼              │        │
│       │                              ┌─────────────────────┐   │        │
│       │                              │  flow_definitions   │───┘        │
│       │                              │                     │            │
│       │                              └─────────────────────┘            │
│       │                                                                 │
│       │  ┌──────────────────────┐      ┌──────────────────────┐         │
│       └──┤   chat_sessions    │◄─────┤   chat_messages      │         │
│          │                    │ 1:*  │                      │         │
│          └────────────────────┘      └──────────┬───────────┘         │
│                                                 │                       │
│                                                 ▼                       │
│          ┌──────────────────────┐      ┌──────────────────────┐         │
│          │    mcp_servers       │◄─────┤ mcp_tool_invocations │         │
│          │                    │ 1:*  │                      │         │
│          └────────────────────┘      └──────────────────────┘         │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 5.4 级联删除决策矩阵

| 删除操作 | 级联影响 | 设计理由 |
|----------|----------|----------|
| 删除用户 | 工作空间、项目、会话、文件记录 级联删除；任务、流程、MCP Server 禁止删除 | 保留历史记录完整性 |
| 删除工作空间 | 子工作空间级联删除；项目变为未分类 | 保护项目数据 |
| 删除项目 | 样本、任务、文件记录 级联删除 | 项目为顶层容器 |
| 删除任务 | 日志、事件 级联删除；文件记录解绑 | 保留文件但解绑来源 |
| 删除流程定义 | 有任务时禁止删除 | 保护历史任务记录 |
| 删除会话 | 消息级联删除 | 消息为会话的子实体 |
| 删除 MCP Server | 调用记录级联删除；消息解绑 | 保留消息但解绑工具 |
| 删除样本 | 无直接级联（file_records 通过 path 软关联） | 样本删除不影响已产生的文件 |


---

## 6. 数据隔离策略

### 6.1 策略选择：应用层过滤 + 行级安全（RLS）双重保障

考虑到 CygnusX 的使用场景（组内平台，<20 并发用户，单人生信维护），我们采用以下策略：

| 层级 | 策略 | 说明 |
|------|------|------|
| **应用层** | 主要隔离手段 | FastAPI 在每个请求中注入当前用户 ID，所有查询自动附加 WHERE user_id = current_user_id |
| **数据库层（RLS）** | 安全兜底 | PostgreSQL RLS 策略作为第二道防线，防止应用层漏洞导致的数据泄露 |
| **数据库层（外键约束）** | 完整性保障 | 通过外键确保数据关联关系的有效性 |

### 6.2 为什么不采用完整的多租户方案

对于组内小团队（<20人），以下多租户方案不适用：

| 方案 | 适用场景 | 不适用理由 |
|------|----------|------------|
| 单数据库多 Schema | 中等规模 SaaS | 维护复杂，权限管理开销大 |
| 多数据库 | 大规模多租户 | 资源浪费，备份复杂 |
| 共享表 + 租户ID | 通用 SaaS | 索引膨胀，查询需带租户过滤 |

我们的方案：**单数据库 + 单 Schema + user_id 字段隔离 + RLS 兜底**

### 6.3 行级安全（RLS）策略实现

```sql
-- ============================================================
-- 启用行级安全（RLS）
-- ============================================================
ALTER TABLE workspaces ENABLE ROW LEVEL SECURITY;
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE samples ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE task_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE file_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE flow_definitions ENABLE ROW LEVEL SECURITY;
ALTER TABLE mcp_servers ENABLE ROW LEVEL SECURITY;
ALTER TABLE mcp_tool_invocations ENABLE ROW LEVEL SECURITY;

-- 创建当前用户 ID 配置函数
CREATE OR REPLACE FUNCTION set_current_user_id(user_id BIGINT)
RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.current_user_id', user_id::TEXT, FALSE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION get_current_user_id()
RETURNS BIGINT AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_user_id', TRUE), '')::BIGINT;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION is_current_user_admin()
RETURNS BOOLEAN AS $$
DECLARE
    user_role VARCHAR(20);
    current_uid BIGINT;
BEGIN
    current_uid := get_current_user_id();
    IF current_uid IS NULL THEN
        RETURN FALSE;
    END IF;
    SELECT role INTO user_role FROM users WHERE id = current_uid;
    RETURN user_role = 'admin';
END;
$$ LANGUAGE plpgsql STABLE;

-- users 表 RLS 策略
CREATE POLICY users_select_self ON users
    FOR SELECT USING (id = get_current_user_id() OR is_current_user_admin());

CREATE POLICY users_update_self ON users
    FOR UPDATE USING (id = get_current_user_id())
    WITH CHECK (id = get_current_user_id());

-- workspaces 表 RLS 策略
CREATE POLICY workspaces_isolation ON workspaces
    FOR ALL USING (user_id = get_current_user_id() OR is_current_user_admin());

-- projects 表 RLS 策略
CREATE POLICY projects_isolation ON projects
    FOR ALL USING (user_id = get_current_user_id() OR is_current_user_admin());

-- samples 表 RLS 策略
CREATE POLICY samples_isolation ON samples
    FOR ALL USING (
        project_id IN (
            SELECT id FROM projects 
            WHERE user_id = get_current_user_id() OR is_current_user_admin()
        )
    );

-- tasks 表 RLS 策略
CREATE POLICY tasks_isolation ON tasks
    FOR ALL USING (user_id = get_current_user_id() OR is_current_user_admin());

-- task_logs 表 RLS 策略
CREATE POLICY task_logs_isolation ON task_logs
    FOR ALL USING (
        task_id IN (
            SELECT id FROM tasks 
            WHERE user_id = get_current_user_id() OR is_current_user_admin()
        )
    );

-- task_events 表 RLS 策略
CREATE POLICY task_events_isolation ON task_events
    FOR ALL USING (
        task_id IN (
            SELECT id FROM tasks 
            WHERE user_id = get_current_user_id() OR is_current_user_admin()
        )
    );

-- file_records 表 RLS 策略
CREATE POLICY file_records_isolation ON file_records
    FOR ALL USING (user_id = get_current_user_id() OR is_current_user_admin());

-- chat_sessions 表 RLS 策略
CREATE POLICY chat_sessions_isolation ON chat_sessions
    FOR ALL USING (user_id = get_current_user_id() OR is_current_user_admin());

-- chat_messages 表 RLS 策略
CREATE POLICY chat_messages_isolation ON chat_messages
    FOR ALL USING (
        session_id IN (
            SELECT id FROM chat_sessions 
            WHERE user_id = get_current_user_id() OR is_current_user_admin()
        )
    );

-- flow_definitions 表 RLS 策略
CREATE POLICY flow_definitions_isolation ON flow_definitions
    FOR ALL USING (
        is_public = TRUE 
        OR created_by = get_current_user_id() 
        OR is_current_user_admin()
    );

-- mcp_servers 表 RLS 策略
CREATE POLICY mcp_servers_isolation ON mcp_servers
    FOR ALL USING (
        is_public = TRUE 
        OR created_by = get_current_user_id() 
        OR is_current_user_admin()
    );

-- mcp_tool_invocations 表 RLS 策略
CREATE POLICY mcp_invocations_isolation ON mcp_tool_invocations
    FOR ALL USING (
        user_id = get_current_user_id() 
        OR is_current_user_admin()
        OR mcp_server_id IN (
            SELECT id FROM mcp_servers 
            WHERE is_public = TRUE OR created_by = get_current_user_id()
        )
    );
```

### 6.4 应用层隔离实现

在 FastAPI 中，通过依赖注入自动附加用户过滤条件：

```python
from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import text

async def get_current_user(request, db):
    token = request.cookies.get("session_token")
    user = db.execute(
        text("SELECT * FROM users WHERE session_token = :token"),
        {"token": token}
    ).fetchone()
    if not user:
        raise HTTPException(status_code=401, detail="Unauthorized")
    return user

async def set_db_user_context(db, user_id):
    db.execute(text("SELECT set_current_user_id(:uid)"), {"uid": user_id})

class UserScopedService:
    def __init__(self, db, current_user):
        self.db = db
        self.current_user = current_user
        set_db_user_context(db, current_user.id)

    def query_projects(self, status=None):
        query = "SELECT * FROM projects"
        params = {}
        if status:
            query += " WHERE status = :status"
            params["status"] = status
        return self.db.execute(text(query), params).fetchall()

    def query_tasks(self, project_id=None, status=None):
        conditions = []
        params = {}
        if project_id:
            conditions.append("project_id = :pid")
            params["pid"] = project_id
        if status:
            conditions.append("status = :status")
            params["status"] = status
        query = "SELECT * FROM tasks"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY created_at DESC"
        return self.db.execute(text(query), params).fetchall()
```

### 6.5 文件系统隔离

```
/data/cygnusx/
├── users/
│   ├── {user_id_1}/
│   │   ├── projects/
│   │   │   ├── {project_uuid_1}/
│   │   │   │   ├── raw/
│   │   │   │   ├── processed/
│   │   │   │   ├── results/
│   │   │   │   ├── logs/
│   │   │   │   └── temp/
│   │   │   └── {project_uuid_2}/
│   │   └── uploads/
│   └── {user_id_2}/
├── shared/
│   ├── reference_genomes/
│   ├── conda_envs/
│   └── flow_templates/
└── system/
    ├── logs/
    └── backups/
```

| 存储位置 | 归属 | 说明 |
|----------|------|------|
| /data/cygnusx/users/{user_id}/ | 用户私有 | 用户只能访问自己的目录 |
| /data/cygnusx/shared/reference_genomes/ | 共享只读 | 管理员维护，所有用户可读 |
| /data/cygnusx/shared/conda_envs/ | 共享只读 | 管理员维护的 Conda 环境 |
| /data/cygnusx/system/ | 系统 | 仅系统进程可访问 |

### 6.6 管理员权限

```sql
-- 管理员专属视图
CREATE VIEW admin_all_tasks AS
SELECT 
    t.*,
    u.username AS owner_username,
    u.email AS owner_email,
    p.name AS project_name
FROM tasks t
JOIN users u ON t.user_id = u.id
JOIN projects p ON t.project_id = p.id
WHERE is_current_user_admin();

-- 管理员仪表盘统计
CREATE VIEW admin_dashboard_stats AS
SELECT 
    (SELECT COUNT(*) FROM users) AS total_users,
    (SELECT COUNT(*) FROM users WHERE is_active = TRUE) AS active_users,
    (SELECT COUNT(*) FROM projects) AS total_projects,
    (SELECT COUNT(*) FROM tasks) AS total_tasks,
    (SELECT COUNT(*) FROM tasks WHERE status = 'running') AS running_tasks,
    (SELECT COUNT(*) FROM tasks WHERE status = 'failed') AS failed_tasks,
    (SELECT COUNT(*) FROM tasks WHERE status = 'completed') AS completed_tasks,
    (SELECT COALESCE(SUM(file_size), 0) FROM file_records) AS total_storage_bytes
WHERE is_current_user_admin();
```

### 6.7 安全最佳实践

1. 数据库连接: 应用使用非超级用户连接数据库，仅授予必要的表权限
2. 参数化查询: 所有用户输入通过参数化查询传递，防止 SQL 注入
3. 审计日志: 所有数据修改操作记录到 task_events 和审计日志表
4. 敏感数据: users.hashed_password 和 mcp_servers.auth_config 需要额外保护
5. 定期备份: 使用 pg_dump 每日备份，保留 30 天

```sql
-- 创建应用数据库用户（最小权限原则）
CREATE ROLE cygnusx_app WITH LOGIN PASSWORD 'strong_password';
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO cygnusx_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO cygnusx_app;
REVOKE DELETE ON users, flow_definitions, mcp_servers FROM cygnusx_app;
```

---

## 7. 完整 SQL 执行顺序

```sql
-- ============================================================
-- Step 1: 1_extensions.sql
-- 扩展和基础设置
-- ============================================================
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
SET timezone = 'Asia/Shanghai';

-- ============================================================
-- Step 2: 2_functions.sql
-- 通用函数和触发器
-- ============================================================
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION set_current_user_id(user_id BIGINT)
RETURNS VOID AS $$
BEGIN
    PERFORM set_config('app.current_user_id', user_id::TEXT, FALSE);
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE OR REPLACE FUNCTION get_current_user_id()
RETURNS BIGINT AS $$
BEGIN
    RETURN NULLIF(current_setting('app.current_user_id', TRUE), '')::BIGINT;
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION is_current_user_admin()
RETURNS BOOLEAN AS $$
DECLARE
    user_role VARCHAR(20);
    current_uid BIGINT;
BEGIN
    current_uid := get_current_user_id();
    IF current_uid IS NULL THEN
        RETURN FALSE;
    END IF;
    SELECT role INTO user_role FROM users WHERE id = current_uid;
    RETURN user_role = 'admin';
END;
$$ LANGUAGE plpgsql STABLE;

CREATE OR REPLACE FUNCTION check_workspace_cycle()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.parent_id IS NOT NULL THEN
        IF NEW.path LIKE '%/' || NEW.parent_id || '/%' THEN
            RAISE EXCEPTION 'Workspace cycle detected';
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION handle_large_log()
RETURNS TRIGGER AS $$
BEGIN
    IF LENGTH(COALESCE(NEW.content, '')) > 1048576 THEN
        NEW.content_size = LENGTH(NEW.content);
        NEW.content = LEFT(NEW.content, 10000) 
            || E'
... [Log truncated, full content saved to file]';
    ELSE
        NEW.content_size = LENGTH(COALESCE(NEW.content, ''));
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION update_chat_session_stats()
RETURNS TRIGGER AS $$
DECLARE
    total_tokens_sum INTEGER;
BEGIN
    UPDATE chat_sessions
    SET message_count = message_count + 1
    WHERE id = NEW.session_id;

    SELECT COALESCE(SUM(
        (COALESCE(token_count->>'total_tokens', '0'))::INTEGER
    ), 0)
    INTO total_tokens_sum
    FROM chat_messages
    WHERE session_id = NEW.session_id;

    UPDATE chat_sessions
    SET total_tokens = total_tokens_sum
    WHERE id = NEW.session_id;

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- Step 3: 3_tables.sql
-- 建表语句（按依赖顺序）
-- ============================================================
-- 执行顺序:
-- 1. users (no dependencies)
-- 2. flow_categories (no deps, self-ref at INSERT)
-- 3. mcp_servers (depends on users)
-- 4. workspaces (depends on users, self-ref)
-- 5. projects (depends on users, workspaces)
-- 6. flow_definitions (depends on flow_categories, users)
-- 7. samples (depends on projects)
-- 8. tasks (depends on users, projects, flow_definitions)
-- 9. task_logs (depends on tasks)
-- 10. task_events (depends on tasks)
-- 11. file_records (depends on users, projects, tasks optional)
-- 12. chat_sessions (depends on users)
-- 13. chat_messages (depends on chat_sessions, mcp_servers optional)
-- 14. mcp_tool_invocations (depends on mcp_servers, tasks opt,
--                           chat_messages opt, users opt)

-- ============================================================
-- Step 4: 4_indexes.sql
-- 创建索引（所有表创建完成后）
-- ============================================================
-- All index statements (see Section 3)

-- ============================================================
-- Step 5: 5_triggers.sql
-- 创建触发器（所有表创建完成后）
-- ============================================================
-- All CREATE TRIGGER statements

-- ============================================================
-- Step 6: 6_rls_policies.sql
-- 启用 RLS 并创建策略
-- ============================================================
-- All RLS policy statements (see Section 6.3)
```

### 快速初始化脚本

```bash
#!/bin/bash
# init_db.sh - Database initialization script
DB_NAME="cygnusx"
DB_USER="cygnusx_admin"

psql -U $DB_USER -d $DB_NAME -f 1_extensions.sql
psql -U $DB_USER -d $DB_NAME -f 2_functions.sql
psql -U $DB_USER -d $DB_NAME -f 3_tables.sql
psql -U $DB_USER -d $DB_NAME -f 4_indexes.sql
psql -U $DB_USER -d $DB_NAME -f 5_triggers.sql
psql -U $DB_USER -d $DB_NAME -f 6_rls_policies.sql

echo "CygnusX database initialized successfully!"
```

---

## 附录 A: 表统计汇总

| 表名 | 核心字段数 | JSONB 字段数 | 外键数 | 索引数 | 说明 |
|------|-----------|-------------|--------|--------|------|
| `users` | 10 | 1 | 0 | 5 | 用户管理 |
| `workspaces` | 11 | 1 | 2 | 5 | 多级工作空间 |
| `flow_categories` | 11 | 1 | 1 | 3 | 流程分类 |
| `flow_definitions` | 16 | 3 | 2 | 9 | 流程定义（核心） |
| `projects` | 12 | 2 | 2 | 7 | 项目管理 |
| `samples` | 14 | 4 | 1 | 7 | 样本管理 |
| `file_records` | 14 | 1 | 3 | 7 | 文件管理 |
| `tasks` | 24 | 3 | 3 | 12 | 任务管理（核心） |
| `task_logs` | 10 | 0 | 1 | 5 | 任务日志 |
| `task_events` | 8 | 1 | 1 | 4 | 任务事件 |
| `chat_sessions` | 12 | 3 | 1 | 5 | 对话会话 |
| `chat_messages` | 11 | 5 | 2 | 6 | 对话消息 |
| `mcp_servers` | 14 | 4 | 1 | 6 | MCP Servers |
| `mcp_tool_invocations` | 12 | 3 | 4 | 7 | MCP 工具调用 |
| **合计** | **159** | **32** | **24** | **89** | |

## 附录 B: 字段类型统计

| 字段类型 | 数量 | 占比 |
|----------|------|------|
| BIGINT | 24 | 15.1% |
| INTEGER | 8 | 5.0% |
| VARCHAR | 35 | 22.0% |
| TEXT | 6 | 3.8% |
| BOOLEAN | 6 | 3.8% |
| JSONB | 32 | 20.1% |
| TIMESTAMPTZ | 12 | 7.5% |
| UUID | 2 | 1.3% |
| TEXT[] (数组) | 1 | 0.6% |
| 约束/其他 | 33 | 20.8% |

## 附录 C: Pydantic v2 集成建议

```python
from pydantic import BaseModel
from sqlalchemy import Column, BigInteger, JSON
from sqlalchemy.orm import declarative_base

Base = declarative_base()

class Task(Base):
    __tablename__ = "tasks"

    id = Column(BigInteger, primary_key=True)
    parameters = Column(JSON)
    resources = Column(JSON)
    results_summary = Column(JSON)

    class ParameterModel(BaseModel):
        genome: str
        threads: int = 8
        p_value_cutoff: float = 0.05

    class ResourceModel(BaseModel):
        cores: int = 4
        memory_gb: int = 16

    def get_parameters(self):
        return self.ParameterModel(**(self.parameters or {}))

    def set_parameters(self, params):
        self.parameters = params.model_dump()
```

---

*文档结束 - CygnusX 数据库 Schema 设计 v1.0*

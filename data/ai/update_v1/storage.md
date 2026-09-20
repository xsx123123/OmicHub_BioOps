# CygnusX 多 Agent 存储架构与云迁移设计

> 文档状态：现状说明与后续优化建议  
> 适用范围：OmicStudio、超频模式（Overdrive）、AgentTeams、生物信息分析任务、用户工作空间与云端存储迁移

## 1. 结论

CygnusX 当前不应在“现有工作区”和“AgentTeams/MinIO”之间二选一，更合理的总体架构是：

```text
用户权威数据存储
        │
        ├── 当前：用户目录 / 平台文件存储
        └── 上云：S3 兼容对象存储
        │
        ▼
Session 热执行工作区
        │
        ├── OmicStudio
        ├── Overdrive 多 Agent
        ├── Python / R / Shell / 生信软件
        └── 临时文件、脚本、中间结果、缓存
        │
        ▼
Artifact Registry
        │
        ├── 文件身份、生产者、消费者
        ├── local_path / object_uri
        ├── checksum / size / version
        └── 权限、状态、生命周期
        │
        ▼
对象存储制品层
        ├── AgentTeams 跨 Worker 交换
        ├── 最终报告与 QC 证据
        ├── 跨节点恢复与审计
        └── 长期保存与云端交付
```

核心原则：

1. **用户数据存储是权威数据源。**
2. **Session 工作区是低延迟、可执行的热工作区。**
3. **Agent 通过显式授权访问当前用户和当前 Session 的数据。**
4. **多 Agent 通过共享工作区交换运行中文件，通过 Artifact Registry 传递稳定引用。**
5. **对象存储负责跨节点、长期保存、制品交换和审计，不直接替代所有 POSIX 执行语义。**
6. **上云后可以把用户持久化数据全面迁移到对象存储，但计算时仍需要临时本地工作区、缓存或对象存储挂载层。**

## 2. 当前平台存储架构

### 2.1 用户数据空间

平台为每个用户维护独立的数据目录，原始数据、上传文件、分析结果和报告均受到用户身份边界保护。

Studio 沙盒只挂载当前用户的数据目录，不挂载整个系统存储根目录：

```text
宿主机：{storage_path}/users/{user_id}
容器内：/data/platform
挂载模式：read-only
```

这意味着沙盒内 Agent 可以读取当前用户经过授权的数据，但不能通过遍历平台存储访问其他用户的数据。

### 2.2 Session 工作区

每个聊天 Session 拥有独立工作区：

```text
{workspace_root}/{session_id}/
├── input/
├── ref/
├── scripts/
├── output/
│   ├── results/
│   ├── figures/
│   ├── logs/
│   ├── tmp/
│   └── overdrive/
├── .logs/
└── mcp-builds/
```

该目录以可写方式挂载到沙盒容器的 `/workspace`。当前用户的权威数据目录则以只读方式挂载到 `/data/platform`。

这种设计实现了：

- 原始数据只读保护；
- Agent 脚本和产物可写；
- 不复制大型生信输入文件；
- Session 之间默认隔离；
- 容器停止后，宿主机仍可访问工作区产物；
- 多个获得授权的 Agent 可以操作同一个 Session 工作区。

### 2.3 Overdrive 工作区

Overdrive 不是使用独立的全局共享目录，而是在当前 Session 工作区内创建运行目录：

```text
/workspace/output/overdrive/{session_id}/{run_id}/
├── plan.md
├── plan.vN.md
├── tasks/
│   ├── {task_id}/result.md
│   └── independent-qc/result.md
└── delivery/final-report.md
```

同一个 Overdrive Run 内的 Agent 可以共享：

- 冻结计划；
- 上游任务结果；
- 图表、表格和日志；
- Artifact Index；
- 最终交付报告。

文件共享的前提是子任务设置 `workspace_access=true`。获得该权限后，`workspace_read`、`workspace_list`、`workspace_write`、`workspace_edit` 和 `sandbox_execute` 会被路由到父 Session 工作区。

因此，超频模式目前已经具备多 Agent 文件共享能力。此前某些 QC Agent 无法读取上游结果，属于任务权限和工具路由配置问题，不代表当前框架缺少共享能力。

## 3. `@文件` 与 `@目录` 的实际行为

### 3.1 `@文件`

在聊天输入框通过 `@xxx` 选择一个文件时，前端会将该文件转换为受控文件引用：

```text
file://{file_uuid}
```

进入 Studio/超频执行链路后，平台会：

1. 校验文件属于当前用户；
2. 收集本轮附件和当前 Session 历史轮次中的文件引用；
3. 幂等地将文件引入 Session 的 `input/`；
4. 在沙盒中生成可读路径：

```text
/workspace/input/{filename}
```

5. 将该沙盒路径显式告诉 Agent，要求代码直接读取工作区路径，而不是读取 `file://` 引用。

对于平台用户目录中的文件，当前实现不是复制大文件，而是在 `input/` 创建指向 `/data/platform` 的软链接。真正的只读保护来自 `/data/platform` 的只读挂载，而不是软链接本身。

因此可以确认：

> 在 Studio/超频模式中，通过 `@` 正式选择的单个文件，会自动引入当前 Session 工作区，并能被获得工作区权限的 Agent 读取。

同一 Session 历史消息中已经引用过的文件也会在后续轮次重新收集并幂等引入，避免多轮分析丢失文件上下文。

### 3.2 `@目录`

当前实现中的目录项主要用于继续浏览目录。选择目录后，输入框会变成类似：

```text
@project/raw-data/
```

然后继续显示该目录下的文件供用户选择。

现阶段存在的能力缺口是：

- 把整个目录作为附件提交；
- 递归枚举并挂载目录内所有文件；
- 为当前 Session 创建受控的目录读取授权；
- 让普通工作台 AI 助手和 Overdrive Agent 使用同一个目录引用；
- 在后续轮次自动恢复已引用目录。

因此当前准确语义是：

| 操作 | 当前实现 |
|---|---|
| `@` 选择单个文件 | 自动引入 `/workspace/input/` |
| `@` 选择目录 | 进入目录并继续选择文件 |
| 在文本中手动输入 `@目录名` | 只是文本，不代表已授权或已挂载 |
| 引用历史轮次已选择文件 | 同一 Session 内自动恢复文件引用 |

该缺口需要在当前版本中补齐。目标不是只为超频模式增加一个特殊目录参数，而是建设一套供工作台 AI 助手、OmicStudio 和 Overdrive 共同使用的 Session Workspace Reference 能力。

### 3.3 目录引用的目标能力

#### 3.3.1 统一引用协议

目录必须使用受控引用，不允许把用户输入的路径字符串直接交给 Agent：

```text
directory://{directory_id}
```

引用中只携带不可猜测的目录 ID。服务端根据当前用户身份解析真实目录，并验证目录属于当前用户。

目录附件建议扩展为：

```json
{
  "type": "directory",
  "name": "project/raw-data",
  "file_id": "directory://directory_uuid",
  "recursive": true,
  "source": "workspace"
}
```

为兼容现有附件链路，可以继续使用 `file_id` 字段承载统一资源引用；后续再将其重命名为更通用的 `resource_ref`。

#### 3.3.2 前端交互

目录项需要提供两个明确动作：

1. **进入目录**：保持当前行为，继续浏览子目录和文件；
2. **引用整个目录**：将目录作为附件加入输入框。

不应让普通单击同时承担“进入”和“挂载”两种含义。推荐在目录行提供“进入”和“引用目录”两个按钮，或将主点击用于进入、右侧附件按钮用于引用。

引用成功后，输入框附件区显示：

```text
📁 project/raw-data/
```

并明确标识：

- 只读；
- 是否递归；
- 预计文件数量；
- 预计总容量；
- 当前 Session 有效。

用户手动输入未经过选择器确认的 `@project/raw-data/` 仍然只是普通文本，不得自动转换为目录授权。

#### 3.3.3 Session 级授权

目录选择成功后，服务端为当前 Session 创建只读授权：

```json
{
  "session_id": "...",
  "user_id": "...",
  "resource_ref": "directory://...",
  "permission": "read",
  "recursive": true,
  "status": "active",
  "expires_with_session": true
}
```

授权范围只能覆盖：

- 当前用户；
- 当前 Session；
- 被选择的目录；
- 明确声明的递归范围；
- 只读操作。

目录引用不能自动扩大为用户根目录权限，也不能被另一个 Session、Case 或用户复用。

#### 3.3.4 工作区引入方式

目录引用应幂等引入当前 Session：

```text
/workspace/input/{directory_name}/
```

本地部署下，不复制目录中的大型文件。推荐在 `input/` 下创建指向 `/data/platform/{user_relative_path}` 的目录软链接；真正的只读保证继续由 `/data/platform` 的只读 bind mount 提供。

必须验证：

- 目录记录属于当前用户；
- 目录真实路径位于当前用户根目录内；
- 不允许 `..` 和绝对路径逃逸；
- 不跟随指向用户目录外部的符号链接；
- 重名目录使用稳定且幂等的链接名；
- 删除 Session 引用不能删除用户原始目录；
- Agent 对 `input/` 引用目录的写入必须失败。

#### 3.3.5 工作台 AI 助手支持

目录挂载不能只在 Overdrive 启动后发生。普通工作台 AI 助手收到目录附件时也必须：

1. 在消息入库前校验 `directory://` 引用；
2. 将目录引入当前 Session 工作区；
3. 向模型注入确定的沙盒路径；
4. 提供受限的目录列举和文件读取工具；
5. 在后续轮次恢复当前 Session 已引用目录；
6. 在没有启动沙盒容器时，通过宿主机工作区读取回退链路访问同一目录；
7. 不把完整目录文件内容直接塞入 Prompt。

模型收到的上下文应类似：

```text
[目录：project/raw-data，已只读引入当前 Session：/workspace/input/raw-data/。
请先使用 workspace_list 检查目录结构，再按需使用 workspace_read 或 sandbox_execute 读取文件。
不要猜测目录之外的路径。]
```

普通工作台 AI 的目录权限默认为只读。只有用户选择允许分析或完整权限时，Agent 才能在 `/workspace/output/`、`/workspace/scripts/` 等可写目录产生结果；无论何种模式都不能修改引用目录中的原始文件。

#### 3.3.6 Overdrive 支持

Overdrive 创建 Run 时必须继承父 Session 已激活的文件和目录引用，并写入 Run Context：

```json
{
  "workspace_refs": [
    {
      "ref": "directory://...",
      "sandbox_path": "/workspace/input/raw-data",
      "permission": "read",
      "recursive": true
    }
  ]
}
```

规划器生成任务时，应根据 `accepts_inputs` 和用户引用自动判断哪些 Agent 需要读取目录。需要输入数据的任务应获得 `workspace_access=true`，纯总结或不需要数据的任务不应无条件扩大权限。

同一个 Run 中的所有授权 Agent 访问同一父 Session 路径，但仍写入各自独立的任务输出目录，禁止写入 `/workspace/input/`。

独立 QC 必须能够：

- 列举引用目录；
- 核对样本文件是否齐全；
- 检查上游 Agent 实际使用的输入清单；
- 对照目录 Manifest 和任务产物进行独立验证。

#### 3.3.7 目录 Manifest

目录可能包含数千到数百万文件，不能把完整列表直接注入模型上下文。平台应生成可分页或延迟构建的 Manifest：

```json
{
  "resource_ref": "directory://...",
  "sandbox_path": "/workspace/input/raw-data",
  "recursive": true,
  "file_count": 120,
  "total_size_bytes": 987654321,
  "snapshot_at": "...",
  "entries": [
    {
      "relative_path": "sample01_R1.fastq.gz",
      "size_bytes": 123,
      "mtime": "..."
    }
  ],
  "truncated": false
}
```

Manifest 的职责是让 Agent 和调度器获得稳定输入视图，而不是复制原始文件。对于超大目录，应只保存摘要和分页索引，Agent 通过工具按需列举。

#### 3.3.8 对象存储兼容

上云后，同一个 `directory://` 引用解析为对象存储 Prefix，而不是宿主机目录：

```text
directory://directory_uuid
        ↓
s3://user-data/users/{user_id}/projects/raw-data/
```

Session 启动时可根据任务特征选择：

- 生成对象 Prefix Manifest；
- 按需下载指定文件；
- 物化到临时 POSIX 工作区；
- 使用节点缓存；
- 使用 S3 CSI/FUSE 提供兼容路径；
- 对原生支持 S3 的工具直接返回受控对象引用。

因此 `directory://` 是本地目录和云对象 Prefix 之间的稳定业务抽象，也是后续无感迁移到云存储的关键。

#### 3.3.9 限额和安全策略

目录引用至少需要具备：

- 当前用户归属校验；
- 目录 ID 与路径解耦；
- 文件数量和总容量上限；
- 是否递归的明确选项；
- 文件类型过滤；
- 只读挂载；
- 快照或版本信息；
- 防止符号链接逃逸；
- 对象存储场景下的 Prefix Manifest；
- 向 Agent 注入确定的目录路径和清单。

建议增加默认限额并允许管理员配置：

```text
最大递归文件数
最大目录逻辑容量
最大单次 Manifest 条目数
最大目录扫描时间
允许的文件类型
是否允许隐藏文件
是否允许嵌套符号链接
Session 引用保留时间
```

超出限额时不能静默截断后继续分析，应返回明确错误并提示用户缩小目录范围、关闭递归或选择子目录。

#### 3.3.10 兼容性要求

目录能力必须同时覆盖：

| 使用入口 | 要求 |
|---|---|
| 普通工作台 AI 助手 | 能列举和读取用户明确引用的目录 |
| OmicStudio | 自动引入 `/workspace/input/` 并支持代码执行 |
| Overdrive | 父 Session 引用自动传递给需要数据的子 Agent |
| AgentTeams Workspace Execution | 可登记目录 Manifest，并按 Artifact/引用规则交接 |
| 历史会话恢复 | 恢复目录引用和授权状态，不依赖 Prompt 文本猜测 |
| 本地部署 | 只读 bind mount + 目录软链接，不复制大文件 |
| 云端部署 | 对象 Prefix + Manifest + 按需物化或挂载 |

## 4. 当前多 Agent 上下文传递方式

文件共享和模型上下文共享是两个不同问题。

### 4.1 文件级上下文

文件内容通过共享工作区传递：

```text
Agent A 生成文件
    → 写入 tasks/agent-a/
    → 登记 Artifact Index
    → Agent B 获得路径
    → Agent B 按需读取
```

大型矩阵、图表、日志和分析结果不应完整放入 Prompt，而应保存在文件中，由下游 Agent 按需读取。

### 4.2 语义级上下文

当前框架通过以下信息显式传递语义：

- `context_summary`；
- 当前任务指令；
- `depends_on`；
- `accepts_inputs`；
- `produces_outputs`；
- 冻结计划路径；
- 上游 `result.md` 路径；
- 已登记 Artifact Index；
- 用户目标和分析约束。

不同 Agent 不共享模型内部状态，也不应该默认共享完整历史对话。显式上下文包更容易控制 Token、避免污染并支持任务回放。

### 4.3 建议优化

1. 有 `depends_on` 或 `accepts_inputs` 的任务，根据任务类型自动推导 `workspace_access`。
2. 下游任务启动前验证输入 Artifact 已存在、校验成功并完成登记。
3. Prompt 只传递摘要、路径和 Manifest，不传递超长文件正文。
4. 每个任务使用独立输出目录，完成后原子登记，避免并发覆盖。
5. 独立 QC 必须读取当前 Run 的计划、结果和 Artifact，不得误用其他任务系统的查询接口。
6. 对关键生信结果记录工具版本、参数、参考基因组版本、样本清单和 checksum。

## 5. AgentTeams 与对象存储的当前定位

当前 AgentTeams 产物链路采用“本地登记 + 对象存储”的方式：

```text
AgentTeams Worker 工作目录
        │
        ├── 复制到用户 workspace/agentteams/{case_id}/{work_item_id}/
        ├── 创建 DataFile 数据库记录
        ├── 计算 SHA-256
        └── 上传到私有 S3 Bucket
                    │
                    ▼
        s3://agentteams-evidence/{case_id}/{work_item_id}/...
```

下游 Agent 不会把 MinIO Bucket 当作本地 POSIX 工作目录，而是通过 `artifact_fetch` 将对象下载到自己的执行目录。

该模式适合：

- AgentTeams 跨容器和跨节点协作；
- Case 级证据归档；
- 最终报告、QC 结果和交付 Manifest；
- Worker 销毁后的恢复；
- 文件 checksum 和审计；
- 预签名下载与生命周期管理。

它不适合直接承担全部实时计算工作区：

- Python/R/生信工具普遍依赖 POSIX 路径；
- FASTQ/BAM/CRAM/H5AD 等文件可能非常大；
- 分析过程中会产生大量小文件和临时文件；
- 随机读写对象存储需要额外适配；
- 每个中间文件都上传下载会增加延迟、流量和成本；
- 许多传统生信软件不原生支持 S3 URI。

## 6. 为什么当前架构更适合生物信息分析

当前架构不是通用 Agent 框架的简单复制，而是针对生物信息计算特征进行了优化。

### 6.1 生信数据体积大

常见输入包括：

- FASTQ；
- BAM/CRAM；
- VCF/BCF；
- H5AD；
- 单细胞表达矩阵；
- 参考基因组与索引；
- 大型注释数据库。

如果每个 Agent 都通过对象存储重复上传、下载和解压这些文件，会产生明显的网络、磁盘、等待时间和云流量成本。

当前“用户数据只读挂载 + Session 热工作区”允许多个 Agent 使用同一份数据，不需要反复复制原始输入。

### 6.2 生信工具依赖 POSIX 文件系统

STAR、RSEM、samtools、bcftools、Snakemake、Nextflow、R、Python 科学计算库等通常期望：

- 稳定的本地路径；
- 目录遍历；
- 随机读取；
- 临时文件；
- 文件锁；
- 管道和标准输入输出；
- 大量小文件；
- 索引文件与主文件位于相邻目录。

单纯使用 AgentTeams 官方对象存储交换模式，不能直接替代这些执行语义。

### 6.3 生信任务需要可复现和独立 QC

当前 Run 目录可以固定保存：

- 分析计划；
- 参数；
- 脚本；
- 软件日志；
- 中间统计；
- 最终结果；
- 独立 QC 结论。

这比只在聊天房间中交换消息或对象 URI 更适合追踪生信分析过程。

### 6.4 生信任务通常是 DAG

生信分析天然具有明确依赖关系，例如：

```text
FASTQ
  → QC
  → 比对
  → 定量
  → 差异分析
  → 富集分析
  → 可视化
  → 独立 QC
  → 报告
```

当前 Overdrive 的 `depends_on`、任务目录、上游结果路径和 Artifact Index 能够自然映射这种 DAG，而不是仅依赖 Agent 在消息房间中自行寻找上下文。

### 6.5 直接照搬官方架构可能出现的问题

如果完全按照通用 AgentTeams/MinIO 文件交换方式实现生信分析，可能出现：

1. 大文件在 Worker 之间重复传输；
2. 网络带宽成为计算瓶颈；
3. 对象下载完成前下游任务提前启动；
4. 临时文件大量进入对象存储；
5. 文件前缀被错误当成真实目录；
6. POSIX 工具无法直接消费 S3 URI；
7. 参考基因组和索引被重复复制；
8. QC Agent 只能看到摘要，无法直接检查完整产物；
9. 难以保证同一任务读取的是同一数据版本；
10. 对象存储调用次数和云流量成本快速增加；
11. Agent 错误覆盖或发布未完成产物；
12. 通用聊天协作状态与生信任务真实执行状态不一致。

因此 CygnusX 应保留面向生信优化的执行面，把 AgentTeams 作为协同控制面，而不是让 AgentTeams 的通用存储方式替代生信执行工作区。

## 7. 优化后的目标架构

### 7.1 Storage Adapter

所有持久化文件访问通过统一接口完成：

```text
UserStorage
├── LocalUserStorage
├── S3UserStorage
└── HybridUserStorage

ArtifactStore
├── LocalArtifactStore
├── S3ArtifactStore
└── CachedArtifactStore
```

业务代码不应直接依赖 MinIO SDK，也不应假定所有用户文件都存在于宿主机固定路径。

MinIO 应被视为一种 S3 兼容实现，而不是不可替换的业务依赖。

### 7.2 Artifact Registry

建议统一 Overdrive `artifact_index`、AgentTeams Artifact、`DataFile` 和报告中心文件记录。

推荐字段：

```json
{
  "artifact_id": "art_xxx",
  "owner_user_id": "user_uuid",
  "session_id": "session_uuid",
  "run_id": "run_uuid",
  "case_id": null,
  "work_item_id": null,
  "producer_task_id": "alignment",
  "kind": "bam",
  "local_path": "output/overdrive/.../aligned.bam",
  "object_uri": "s3://bucket/users/.../aligned.bam",
  "size_bytes": 123456789,
  "sha256": "...",
  "content_type": "application/octet-stream",
  "status": "validated",
  "version": 1,
  "created_at": "...",
  "retention_class": "result"
}
```

Artifact 状态建议采用：

```text
declared → writing → ready → validated → published → archived
                         └── rejected
```

只有 `ready` 或 `validated` 的产物才能被下游任务消费。

### 7.3 热数据与冷数据分层

| 数据类型 | 推荐位置 |
|---|---|
| 当前任务脚本 | Session 工作区 |
| 临时文件与缓存 | Session 工作区 |
| 高频随机访问中间文件 | 本地工作区或节点缓存 |
| 用户原始数据 | 当前用户存储；上云后对象存储为权威源 |
| 参考数据库 | 共享只读缓存或对象存储 + 节点缓存 |
| 最终报告 | 对象存储 |
| QC 证据 | 对象存储 |
| 关键结果表和图 | 对象存储 |
| 运行 Manifest | 数据库 + 对象存储 |
| 可重建的大型中间文件 | 按策略保留或清理 |

### 7.4 自动晋升策略

工作区文件不应全部自动上传。建议在以下条件触发 Artifact 晋升：

- 任务声明为正式输出；
- 独立 QC 通过；
- 最终报告引用；
- 需要跨节点消费；
- 用户主动保存；
- 工作区即将过期；
- Case 需要审计证据。

晋升流程：

```text
工作区文件完成写入
  → 关闭文件并计算 checksum
  → Artifact Registry 标记 ready
  → QC / Schema 校验
  → 上传对象存储
  → 校验对象大小与 checksum
  → 记录 object_uri
  → 标记 published/archived
```

## 8. 上云后的用户存储迁移

### 8.1 可以全面使用对象存储作为权威持久化层

上云后，用户持久化数据可以迁移到 S3 兼容对象存储，包括：

- 用户上传文件；
- 原始测序数据；
- 项目数据；
- 报告；
- AgentTeams Artifact；
- Overdrive 最终制品；
- 运行日志归档；
- 参考数据版本。

数据库保存对象身份、权限、版本、校验和和业务关系，对象存储保存文件实体。

这一方向与当前架构是兼容的，因为平台已经把以下概念分开：

- 用户权威数据；
- Session 工作区；
- Agent 运行目录；
- 数据库文件记录；
- MinIO/S3 Artifact；
- 报告中心长期产物。

因此，当前架构确实为未来云迁移保留了良好边界，不需要重写整个 Agent 和分析编排体系。

### 8.2 不能简单理解为“计算完全不需要文件系统”

对象存储可以完全替换用户数据的**持久化后端**，但通常不能直接替换生信程序需要的全部**运行时文件系统**。

上云后的推荐执行方式：

```text
S3 权威对象
   │
   ├── 按任务下载到临时工作盘
   ├── 通过节点级只读缓存复用
   ├── 使用 CSI/FUSE 挂载提供兼容路径
   └── 对支持 S3 的工具直接流式读取
   │
   ▼
Pod / VM 临时 POSIX 工作区
   │
   ▼
结果上传回 S3
```

工作区可以使用：

- Kubernetes `emptyDir`；
- 云硬盘临时卷；
- 高性能并行文件系统；
- 节点本地 NVMe；
- S3 CSI/FUSE；
- 对象下载缓存服务。

具体方式应根据文件大小、随机读取需求、任务生命周期和成本决定。

### 8.3 云迁移阶段

#### 阶段一：本地文件系统 + MinIO

- 保持当前用户目录；
- Overdrive 使用 Session 工作区；
- AgentTeams 和正式制品使用 MinIO；
- 建立 Storage Adapter 和 Artifact Registry。

#### 阶段二：对象存储成为权威副本

- 新上传数据直接写入对象存储；
- 本地用户目录变为缓存或兼容层；
- 数据库中的 `object_uri` 成为主要定位；
- Session 启动时按需物化输入。

#### 阶段三：云原生执行

- 每个任务运行在独立 Pod/Worker；
- 输入按 Artifact Manifest 拉取；
- 节点缓存复用参考基因组和公共数据库；
- 任务产物通过两阶段提交上传对象存储；
- 工作区在任务结束后自动清理；
- 所有正式结果可通过 Artifact Registry 重建和追踪。

#### 阶段四：可替换的多云存储

- 业务层仅依赖 S3 兼容接口；
- 可在 MinIO、云厂商对象存储和其他 S3 服务之间切换；
- Bucket、区域、存储类型和生命周期策略由配置决定；
- 不把 MinIO 内部地址和凭据暴露给 Agent 或浏览器。

## 9. 最终架构定位

CygnusX 的目标不是构建一个只会在聊天室中传文件的通用 Agent 系统，而是构建一个面向生物信息分析的多 Agent 科学计算平台。

因此各层职责应保持清晰：

| 层级 | 职责 |
|---|---|
| AgentTeams | 团队、角色、Case、房间、人工介入和跨 Worker 协同 |
| Overdrive | 生信任务拆解、DAG 调度、并行执行、独立 QC 和交付 |
| Session Workspace | 实时代码执行和多 Agent 热文件共享 |
| User Storage | 用户权威数据和权限边界 |
| Artifact Registry | 文件身份、版本、依赖、校验和与生命周期 |
| S3/Object Storage | 跨节点交换、持久化、归档、审计和云迁移 |
| Database | 任务状态、权限、元数据和业务关系的权威来源 |

最终推荐架构为：

```text
AgentTeams Coordination Plane
            +
Overdrive Bioinformatics Execution Plane
            +
Session POSIX Workspace
            +
Artifact Registry
            +
Replaceable S3-compatible Durable Storage
```

这既保留了 AgentTeams 的通用多 Agent 协作能力，也保留了 CygnusX 针对大型生信文件、POSIX 工具链、DAG、可复现执行和独立 QC 的优化，并为后续完整上云提供清晰迁移路径。

## 10. 近期实施优先级

### P0

1. 实现受控 `directory://` 引用和目录归属校验。
2. 工作台 AI、OmicStudio 和 Overdrive 共用 Session 目录引入服务。
3. 前端目录项明确提供“进入”和“引用整个目录”两个动作。
4. 实现目录 Manifest、分页列举、容量与文件数限额。
5. Overdrive 继承父 Session 目录引用，并根据输入依赖推导工作区读取权限。
6. 统一 Overdrive 和 AgentTeams Artifact 数据模型。
7. 下游任务启动前增加 Artifact Ready Barrier。
8. 保证独立 QC 能访问当前 Run 的输入 Manifest、冻结计划和全部声明产物。

### P1

1. 增加 S3 Storage Adapter，消除业务代码对 MinIO 的直接依赖。
2. 将 `directory://` 映射到对象存储 Prefix 和按需物化流程。
3. 增加工作区到对象存储的 Artifact 晋升流程。
4. 增加 checksum、版本、生产者和消费者关系。
5. 增加节点缓存和参考数据库缓存策略。

### P2

1. 用户权威数据迁移到云对象存储。
2. Session 工作区迁移到云端临时卷或高性能缓存层。
3. Worker/Pod 按 Artifact Manifest 自动拉取输入、上传输出。
4. 建立跨区域、多云和灾备复制策略。
5. 根据成本和访问频率自动切换热、温、冷存储层级。

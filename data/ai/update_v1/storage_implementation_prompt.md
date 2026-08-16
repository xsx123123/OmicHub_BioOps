# OmicHub Session 目录引用与多 Agent 存储优化实施提示词

> 使用方式：将本文件与 `data/ai/update_v1/storage.md` 一起提供给编码 Agent。  
> 本提示词是实施约束，`storage.md` 是架构与产品语义的权威说明。发生冲突时，先核对当前代码；不得通过缩减安全边界来规避实现问题。

## 角色

你是 OmicHub 的资深全栈与平台工程师，负责在现有代码库中实现“受控目录引用 + Session 工作区引入 + 工作台 AI/OmicStudio/Overdrive 共用”的完整能力。

这不是新建演示项目，也不是只修改 Prompt。必须基于当前仓库的真实架构完成前端、API Schema、服务层、工作区、权限、上下文传递、Overdrive 和测试闭环。

## 开始前必须阅读

1. 完整阅读 `data/ai/update_v1/storage.md`。
2. 阅读仓库内适用于修改目录的全部 `AGENTS.md`。
3. 检查当前 Git 状态，不得覆盖或回滚用户已有修改。
4. 阅读并理解以下现有实现：

```text
frontend/src/components/ai-chat/KimiChatInput.vue
frontend/src/components/ai-chat/types.ts
frontend/src/stores/agentHub.ts
src/omichub/application/schemas/chat.py
src/omichub/application/services/chat_service.py
src/omichub/application/services/studio_context_service.py
src/omichub/application/services/studio_tools.py
src/omichub/application/services/parallel_subagent_service.py
src/omichub/application/services/overdrive_run_service.py
src/omichub/infrastructure/celery_app/tasks/overdrive.py
src/omichub/infrastructure/studio/manager.py
src/omichub/infrastructure/studio/workspace.py
src/omichub/infrastructure/storage/path_factory.py
src/omichub/infrastructure/database/models/file.py
src/omichub/api/v1/files.py
```

5. 搜索现有文件搜索、目录树、附件入库、Session 恢复、工作区工具和 Artifact Index 测试，优先复用已有抽象。

## 当前问题

当前代码已经支持：

- 在聊天输入框通过 `@` 选择单个文件；
- 将文件转换为 `file://{uuid}`；
- Studio 模式下把当前轮次和历史轮次文件幂等引入 `/workspace/input/`；
- 将当前用户目录以只读方式挂载到 `/data/platform`；
- Overdrive Agent 在 `workspace_access=true` 时共享父 Session 工作区。

但目录能力存在断点：

1. 前端选择目录时只进入目录，不会把目录作为附件提交。
2. `FileAttachment` 和 `ChatAttachment` 仅围绕文件/图片设计。
3. 服务端没有 `directory://{directory_id}` 解析、归属验证和 Session 授权。
4. `_link_session_files_to_workspace` 只处理文件引用，并且当前主要在 Studio 分支触发。
5. 普通工作台 AI 助手无法稳定获得目录的受控路径和目录工具上下文。
6. Overdrive 没有统一继承父 Session 目录引用和目录 Manifest。
7. 用户手动输入 `@目录名` 与正式选择目录缺少明确安全区分。
8. 当前没有目录文件数、容量、扫描时间、符号链接和 Manifest 限制。

## 总体目标

实现统一的 Session Workspace Reference：

```text
file://{file_id}
directory://{directory_id}
```

要求同一个目录引用能够被以下入口共同使用：

- 普通工作台 AI 助手；
- OmicStudio；
- Overdrive 父 Session 和获得授权的子 Agent；
- AgentTeams Workspace Execution 的后续 Artifact/Manifest 交接。

不得为 Overdrive 单独复制一套目录挂载实现。目录解析、校验、引入、恢复和 Manifest 必须集中在共享服务中。

## 不可改变的架构原则

1. 只允许访问当前用户明确选择的目录。
2. 目录默认只读，任何模式都不能修改用户原始输入。
3. 不把整个平台存储根目录挂载到沙盒。
4. 本地部署不复制大型目录，优先复用 `/data/platform` 只读挂载和 `input/` 引用。
5. 不因为目录挂载把目录全部文件内容注入 Prompt。
6. 手动输入 `@path` 不产生授权，只有选择器返回的受控 ID 才有效。
7. Session 之间、用户之间、Case 之间不能复用未授权引用。
8. 不直接把业务逻辑绑定到 MinIO；保留本地目录和未来 S3 Prefix 的统一抽象。
9. 不破坏现有 `file://`、`upload://`、图片附件和历史附件行为。
10. 不允许路径逃逸、符号链接逃逸或通过重名覆盖现有工作区文件。

## 实施任务

### 任务一：定义统一资源引用模型

扩展前后端附件模型，使其至少支持：

```ts
type AttachmentKind = 'image' | 'file' | 'directory'
```

目录附件需要包含：

```json
{
  "type": "directory",
  "name": "project/raw-data",
  "file_id": "directory://uuid",
  "source": "workspace",
  "recursive": true
}
```

如果当前数据库附件 JSON 可以兼容扩展字段，优先保持兼容，不要为简单字段新增不必要的数据表。

内部实现允许引入更准确的 `resource_ref`、`WorkspaceResourceRef` 或类似类型，但外部 API 必须兼容现有 `file_id`。

必须集中实现引用解析，禁止在不同服务中分别手写字符串切割：

```text
parse_workspace_resource_ref(ref)
validate_workspace_resource_owner(user_id, ref)
```

### 任务二：扩展目录搜索和前端选择

在现有 `@` 搜索面板中保留目录导航，同时新增明确的“引用整个目录”动作。

交互要求：

- 点击目录名称或“进入”按钮：继续浏览；
- 点击“引用目录”按钮：添加目录附件；
- 已引用目录不能重复添加；
- 附件区使用目录图标和尾随 `/`；
- 显示只读和递归状态；
- 删除目录附件只移除本轮引用，不删除用户目录；
- 手动输入的 `@目录路径` 不得生成 `directory://`；
- 键盘操作和无障碍标签不能退化。

如果当前目录搜索 API 没有稳定目录 ID，补充服务端返回值。不要使用目录路径本身作为授权凭据。

### 任务三：实现目录归属和路径安全校验

基于当前文件/目录数据库模型实现：

- 目录存在；
- 目录属于当前用户；
- 目录对应路径位于当前用户根目录；
- 拒绝绝对路径和 `..`；
- 拒绝解析到用户根目录之外的符号链接；
- 拒绝其他用户、其他租户和失效目录 ID；
- 对根目录、系统目录和平台内部目录设置明确策略；
- 错误信息对用户可理解，但不能泄露真实宿主机路径。

归属和路径校验必须发生在服务端，前端检查只能作为体验优化。

### 任务四：统一 Session 引入服务

将仅面向文件的能力演进为统一资源能力，例如：

```text
link_session_workspace_refs(
    user_id,
    session_id,
    refs,
    db,
) -> paths, manifests, errors
```

要求：

- 同时处理 `upload://`、`file://` 和 `directory://`；
- 保持文件现有幂等行为；
- 目录重复引用必须复用同一工作区名称；
- 文件与目录重名时使用稳定且可预测的安全名称；
- 单个引用失败不能阻断其他合法引用；
- 返回模型可使用的 `/workspace/input/...` 路径；
- 返回结构化错误供日志和 UI 使用；
- 不在日志中输出凭据或不必要的用户绝对路径。

普通工作台 AI 助手、Studio 和 Overdrive 必须调用同一服务，不允许存在三个行为不同的实现。

### 任务五：实现本地只读目录引入

在当前本地部署中：

- 用户目录继续只读挂载到 `/data/platform`；
- 在 Session `input/` 下建立指向用户目录的受控目录引用；
- 容器内路径为 `/workspace/input/{safe_name}/`；
- 宿主机回退读取必须能解析该引用；
- `workspace_list` 可以分页列举；
- `workspace_read` 只能读取文件，读取目录时返回明确提示；
- `workspace_write`、`workspace_edit` 和代码执行不能修改引用目录；
- Session 工作区清理只能删除引用，不能删除原始目录。

不要通过把目录复制进 `input/` 来假装完成挂载。

如果当前 `/workspace` 整体可写导致 Agent 能删除 `input/` 下的软链接，只要原始数据仍由 `/data/platform` 只读保护，可以允许删除 Session 引用；但必须保证删除引用不影响原始数据，并在需要时能够根据 Session 授权恢复引用。

### 任务六：实现目录 Manifest

为每个目录引用生成轻量 Manifest，至少包含：

- `resource_ref`；
- `sandbox_path`；
- `recursive`；
- `file_count`；
- `total_size_bytes`；
- `snapshot_at`；
- `entries`；
- `truncated`；
- `next_cursor` 或等价分页信息。

要求：

- 小目录可以同步生成完整 Manifest；
- 大目录必须分页或截断；
- 不允许一次请求无上限递归扫描；
- 超时或超限返回明确状态；
- 不把完整 Manifest 自动拼进 Prompt；
- 模型只接收摘要、沙盒路径和按需列举说明；
- Manifest 可被 Overdrive 独立 QC 使用；
- Manifest 后续可以映射到对象存储 Prefix。

限额必须进入配置，而不是散落硬编码。至少考虑：

```text
workspace_directory_max_files
workspace_directory_max_total_bytes
workspace_directory_manifest_page_size
workspace_directory_scan_timeout_seconds
```

沿用仓库现有配置命名和读取方式。

### 任务七：工作台 AI 助手上下文

不要把目录引入逻辑限制在 `studio_mode`。

当普通工作台 AI 助手收到合法目录附件时：

1. 校验并登记当前 Session 引用；
2. 如果当前模式具备工作区读取能力，提供确定的工作区路径；
3. 提示模型先使用 `workspace_list`，再按需读取文件；
4. 在没有运行容器时使用现有宿主磁盘回退读取；
5. 后续轮次从消息附件或 Session 授权恢复目录上下文；
6. 安全模式或无文件权限模式不得静默提升权限，应明确提示当前模式不能读取目录；
7. 不允许模型依靠目录名称猜测其他用户路径。

上下文示例：

```text
[目录 project/raw-data 已只读引入当前 Session：/workspace/input/raw-data/。
包含约 120 个文件，总容量约 8.4 GB。请使用 workspace_list 分页检查目录，
再按需读取具体文件；不要尝试修改 input/ 或访问目录之外的路径。]
```

### 任务八：Overdrive 继承与权限推导

Overdrive Run 创建或启动时，持久化父 Session 当前激活的 Workspace References 摘要。

Worker 上下文必须包含：

- `resource_ref`；
- `sandbox_path`；
- 权限；
- 是否递归；
- Manifest 摘要；
- 当前 Run 的权威根目录。

规划和调度要求：

- 需要读取用户输入的任务获得 `workspace_access=true`；
- 仅总结已有文字的任务不自动扩大工作区权限；
- 子 Agent 继续通过父 Session ID 访问同一工作区；
- 各任务只写自己的 `tasks/{task_id}/` 或声明输出目录；
- 独立 QC 能访问输入目录 Manifest、冻结计划、上游结果和 Artifact Index；
- 下游任务启动前验证声明输入可读；
- 不通过复制目录到每个子 Agent 工作目录实现共享。

### 任务九：AgentTeams 与对象存储兼容边界

本阶段不要求把用户目录全部上传 MinIO，也不允许为了“统一”而复制大型生信目录。

需要保留扩展点，使：

```text
directory://uuid
```

未来可以解析为：

```text
s3://bucket/users/{user_id}/prefix/
```

目录 Manifest 和 Artifact Registry 不应依赖本地绝对路径。AgentTeams 跨 Worker 交接时传递受控引用或 Manifest；只有执行节点确实需要文件时才按需物化。

### 任务十：数据库与生命周期

优先评估是否可以利用现有聊天消息附件 JSON 和 Session `sandbox_meta` 保存引用状态。

只有在以下需求无法可靠满足时才新增表：

- Session 级授权查询；
- 引用撤销；
- 独立生命周期；
- 大规模目录 Manifest；
- 审计和并发更新。

若新增表，至少包含：

```text
id
session_id
user_id
resource_ref
resource_type
permission
recursive
sandbox_path
status
manifest_summary
created_at
updated_at
expires_at
```

必须提供数据库迁移，并保持旧会话兼容。

## 测试要求

必须先运行最相关测试，再逐步扩大范围。至少覆盖：

### 前端

1. 点击“进入目录”不会添加附件。
2. 点击“引用目录”会添加 `directory://` 附件。
3. 相同目录不会重复添加。
4. 删除目录附件不会调用删除用户目录 API。
5. 手动输入 `@目录` 不会伪造受控引用。
6. 请求 Payload 正确包含目录附件字段。
7. 历史消息能恢复目录附件展示。

### 后端

1. 当前用户合法目录可以解析。
2. 其他用户目录被拒绝。
3. 绝对路径、`..` 和符号链接逃逸被拒绝。
4. `directory://` 重复引入保持幂等。
5. 文件、上传和目录引用可以混合处理。
6. 单个无效引用不阻断其余合法引用。
7. 目录挂载后 `workspace_list` 可见。
8. 原始目录不可写。
9. Session 清理不删除原始目录。
10. Manifest 文件数、容量、分页和超限行为正确。
11. 普通工作台 AI 可以获得目录上下文。
12. 无读取权限模式不会自动提升权限。
13. 历史轮次目录引用可以恢复。
14. Overdrive 子 Agent 使用父 Session 工作区。
15. 独立 QC 能读取 Manifest 和上游产物。

### 回归

1. 现有 `@文件` 行为不变。
2. 聊天上传文件行为不变。
3. 图片多模态附件不变。
4. Studio 沙盒创建和用户只读挂载不变。
5. Overdrive 无附件任务不受影响。
6. AgentTeams Artifact Fetch 不受影响。

## 验收标准

只有以下条件全部满足，任务才算完成：

- 用户能在工作台输入框中明确选择并引用整个目录；
- 目录附件使用受控 `directory://` 引用；
- 普通工作台 AI 助手可以列举和读取该目录；
- OmicStudio 代码可以通过 `/workspace/input/{name}/` 读取目录；
- Overdrive 中需要数据的 Agent 可以共享该目录；
- 独立 QC 可以核对输入目录 Manifest；
- 原始用户目录在所有模式下保持只读；
- 其他用户和其他 Session 无法复用该引用；
- 不复制完整大型目录；
- 大目录不会完整注入 Prompt；
- 所有相关新增测试和现有回归测试通过；
- `git diff --check` 通过；
- 文档与最终实现保持一致。

## 实施方式

1. 先形成简短计划并识别共享抽象，不要立即在多个入口分别打补丁。
2. 先实现资源引用解析和服务端安全校验，再接前端。
3. 再实现 Session 引入、宿主回退和 Manifest。
4. 接入普通工作台 AI 和历史上下文恢复。
5. 接入 Overdrive 继承与权限推导。
6. 最后补充 AgentTeams/S3 扩展接口，不在本阶段搬迁全部数据。
7. 每完成一层就运行对应测试，失败最多迭代修复三轮。
8. 不修复与本任务无关的问题；如发现无关失败，在最终说明中单独列出。

## 最终交付说明

完成后请输出：

1. 修改的核心文件与职责；
2. 最终目录引用数据流；
3. 工作台 AI、Studio、Overdrive 的行为差异；
4. 权限和路径安全措施；
5. Manifest 与限额策略；
6. 运行过的测试和结果；
7. 尚未实施但已经预留的 S3/云迁移扩展点；
8. 任何需要管理员配置的新环境变量或配置项。

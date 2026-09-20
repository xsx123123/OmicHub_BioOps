# CygnusX 用户文件与分析项目目录协议

> **状态**：生效中  
> **版本**：v1.3（2026-08-19 L4 协作室融合修订）
> **适用范围**：所有会产生用户输入、分析中间文件、结果、报告或可下载产物的新模块。  
> **目标**：让用户只看到可理解、可管理的项目目录；UUID 仅用于系统内部任务、审计和数据库关联。

## 1. 核心原则

1. **项目名称是分析任务的必填配置。**
   - 前端必须提供“项目名称”输入框并在提交前校验非空。
   - 后端请求 Schema 必须校验项目名称非空、去除首尾空白，并设置合理长度限制。
   - 不允许以“未命名项目”、任务 UUID 或上传文件 UUID 作为新分析的用户可见目录名称。
2. **所有新分析运行目录必须由统一路径工厂创建。**
   - 使用 `cygnusx.infrastructure.storage.get_path_factory()`。
   - 使用 `StoragePathFactory.create_project_run_dir(user_id, project_name, analysis_name)`。
   - 禁止在 Service、Task、Runner 或 API 中直接拼接 `storage_path / "results"`、`/tasks/<uuid>`、`/raw` 等用户可见路径。
3. **UUID 不得出现在用户可见的新目录名称中。**
   - UUID 可继续作为数据库主键、队列任务 ID、审计 ID、缓存键和内部沙箱运行 ID。
   - 一个项目可有多次运行，使用“分析类型 + 时间戳 + 序号”区分，不使用 UUID。
4. **用户可见目录必须登记到目录表。**
   - 创建项目运行目录后，调用 `ensure_directory_chain()` 创建对应 `Directory` 记录。
   - 否则物理目录存在但“我的文件”目录树不会显示该目录。
5. **历史目录只读兼容，不强制迁移。**
   - 历史 `raw`、`tasks/<uuid>`、`results` 等数据应保持可读取和可下载。
   - 新模块及新任务不得再默认写入这些目录。

## 2. 用户工作区目录规范

用户工作区根目录：

```text
<storage_root>/users/<user_id>/
├── inbox/                         # 默认上传入口
├── projects/                      # 所有用户可见分析项目
│   └── <project_slug>/             # 由项目名称生成的安全、可读目录名
│       └── runs/
│           └── <analysis>-<UTC 时间戳>[-序号]/
│               ├── input/          # 本次运行固定输入快照
│               ├── output/         # 最终结果、报告、可下载产物
│               ├── work/           # 中间文件和流程工作目录
│               └── logs/           # 运行日志
├── raw/                            # 历史兼容目录；新写入禁止使用
├── tasks/                          # 历史 UUID 任务目录；新写入禁止使用
├── results/                        # 历史结果目录；新写入禁止使用
├── workspace/                      # 内部终端/沙箱目录；不作为分析结果入口
└── temp/                           # 内部临时目录；不作为分析结果入口
```

### 2.1 项目目录示例

项目名称为 `TnpD 建树项目`、分析类型为 `phylogenetic-tree` 时：

```text
users/<user_id>/projects/TnpD_建树项目/runs/phylogenetic-tree-20260803-163000/
```

目录名由 `cygnusx.infrastructure.storage.path_factory` 中的模块级函数 `project_slug()` 规范化：压缩连续空白、非法字符替换为 `_`、保留中文/字母/数字/`._-`、截断 80 字符，空名回退为 `untitled-project`。该规范仅用于路径安全，页面、任务历史和报告仍应保存并展示原始项目名称。

运行目录名中的时间戳为 UTC 秒级（`%Y%m%d-%H%M%S`）；同秒并发提交由工厂以原子创建 + 序号（`-2`…`-9999`）自动避让，模块无需自行处理冲突。

## 3. 必须使用的后端接入方式

### 3.1 创建运行目录

```python
from pathlib import Path
from uuid import UUID

from cygnusx.application.services.file_service import ensure_directory_chain
from cygnusx.infrastructure.storage import get_path_factory

path_factory = get_path_factory()
run_dir = path_factory.create_project_run_dir(
    user_id=user_id,
    project_name=request.project_name,
    analysis_name="my-analysis",
)

relative_run_dir = run_dir.relative_to(path_factory.user_root(user_id)).as_posix()
await ensure_directory_chain(db, UUID(user_id), relative_run_dir)
```

> **注意**：`create_project_run_dir()` 会原子创建运行根目录，并同步创建 `input`、`output`、`work`、`logs` 四个标准子目录。调用方仍必须调用 `ensure_directory_chain()` 登记用户可见目录；工厂不直接依赖数据库会话。

### 3.2 输入与结果的固定位置

| 文件类别 | 规定位置 | 说明 |
| --- | --- | --- |
| 用户上传的原始文件 | `inbox/` | 未归属项目的默认入口。 |
| 本次分析输入快照 | `<run>/input/` | 提交后复制、链接或受控引用；应能复现本次运行。 |
| 最终结果/报告/可下载文件 | `<run>/output/` | 用户主要访问位置。禁止自建 `results/`、`result/` 等同义子目录替代。 |
| 中间文件 | `<run>/work/` | 不应作为默认下载结果。 |
| 日志 | `<run>/logs/` | 用于排错与审计。 |

### 3.3 异步 Worker/容器要求

- 在投递任务前将 `run_dir` 或 `work_dir` 写入任务参数；Worker 必须使用该参数，不能依据任务 ID 重建结果目录。
- 容器内路径可以是挂载后的 `/workspace/...`，但宿主机挂载源必须是该项目运行目录。
- 可视化、报告和下载接口必须根据任务保存的实际 `work_dir` 或任务结果中的 `output_files` 读取文件，不能假定结果总位于 `results/<tool>/<task_id>`。
- 需要临时上传暂存时可使用 UUID，但在“提交分析”阶段必须迁入 `<run>/input/` 后再运行。

## 4. API、Schema 与前端要求

### 4.1 请求字段

- 新分析请求统一使用 `project_name`；若历史接口已使用 `name` 或 `task_name`，该字段必须被明确解释为项目名称并保持必填。
- Schema 至少要求：非空、去首尾空白、最大长度限制。
- 前端不得给项目名称提供会绕过用户填写的默认值，例如固定的 `"BLAST 项目"`。
- Service 层同样不得设置固定默认项目名作为兜底（如 `"Enrichment Project"`）；必填校验应止于 API/Schema 层，Service 收到空值应直接报错。

### 4.2 前端交互

- 项目名称应在文件上传/提交按钮附近明确展示，并说明其会用于结果目录和任务历史。
- 项目名称为空时，提交按钮应禁用或提交时给出明确错误。
- 文件树只展示可操作目录：`inbox`、`projects` 及用户创建目录。
- `raw`、`tasks`、`results`、`workspace`、`temp`、`raw_data` 等历史或内部目录不得作为常规用户导航入口展示。现有实现见 `frontend/src/components/DirectoryTree.vue` 的顶级目录过滤名单，新增历史根目录时需同步更新该名单。

## 5. 现有模块映射与接入状态

| 模块 | 项目名称字段 | 新运行目录策略 | 接入状态 |
| --- | --- | --- | --- |
| 通用 Snakemake/分析流程 | `TaskSubmitRequest.name` | `create_project_run_dir(..., flow_id)`，工作目录为 `<run>/work`。 | ✅ 已接入 |
| DEG | `project_name` | `create_project_run_dir(..., "deg")`；结果统一写入 `<run>/output/`。 | ✅ 已接入 |
| 富集分析 | `project_name` | `create_project_run_dir(..., "enrichment")`；基因列表写入 `<run>/input/`。 | ✅ 已接入 |
| BLAST | `project_name` | 输入在 `<run>/input/`，结果在 `<run>/output/`；旧 UUID 目录仅读取回退。 | ✅ 已接入 |
| 系统发育树 | `project_name` | 上传文件从临时暂存迁入 `<run>/input/`；计算在 `<run>/work/`，最终树文件交付到 `<run>/output/`。 | ✅ 已接入 |
| 数据下载 | `target_directory`（可选） | 默认写入 `inbox/downloads/`；文件目录记录由实际物理路径派生。 | ✅ 已接入 |
| Studio 报告交付 | Studio 会话标题 | 标题作为项目名；工作区产物复制到 `<run>/output/` 并登记目录表。 | ✅ 已接入 |
| FASTQ QC | `name` | 必须作为项目名称填写；实现运行目录时遵循本协议。 | ⏳ 尚未提供用户提交 Service/API，不产生用户目录。 |

Studio/MAS 的会话容器目录属于内部沙箱运行空间，可使用内部运行 ID；如需把产物交付到“我的文件”，必须在交付阶段按本协议登记到项目目录。Studio 报告交付已完成该迁移；MAS 当前尚无面向“我的文件”的交付入口，后续新增交付能力时必须按本协议实现。

## 9. L4 协作室融合架构（v1.3）

L4/AgentTeams Case 不再是游离的房间对象，而是一个绑定用户项目和一次分析运行的
“协作运行”。Bridge 继续负责 Case 状态机、租约、审计和 Worker 编排；CygnusX
平台负责项目归属、用户文件目录、运行目录和交付文件登记。Matrix 只是协作消息
传输层，不拥有用户文件路径。

```text
用户/协作室首条需求
        │ project_id 或 project_name
        ▼
CygnusX AgentTeams API
  ├─ 校验/创建用户 Project
  ├─ create_project_run_dir(user_id, project_name, "agentteams-case")
  ├─ ensure_directory_chain(user_id, projects/<slug>/runs/<run>/...)
  └─ 将 project/run protocol ref 写入 Case context_refs
        │
        ▼
AgentTeams Bridge Case
  ├─ project_ref = {kind: project, id: project_id}
  ├─ context_refs[].location = projects/<slug>/runs/<run>
  └─ Worker 仅消费 protocol path，不生成用户可见 UUID 路径
        │
        ├─ input/  输入快照
        ├─ work/   专家和流程中间文件
        ├─ logs/   Worker/流程日志
        └─ output/ agent-delivery 报告、manifest、最终产物
```

### 9.1 Case Run Binding

新 Case 创建请求支持以下两种项目入口，二选一：

```json
{
  "project_id": "<existing-project-uuid>",
  "intent": "完成单细胞 3v3 分析"
}
```

```json
{
  "project_name": "小鼠单细胞 3v3",
  "intent": "完成单细胞 3v3 分析"
}
```

`project_name` 入口先创建用户 Project，再创建 Case Run。平台必须调用：

```python
run_dir = get_path_factory().create_project_run_dir(
    user_id=user_id,
    project_name=project.name,
    analysis_name="agentteams-case",
)
await ensure_directory_chain(
    db,
    UUID(user_id),
    run_dir.relative_to(get_path_factory().user_root(user_id)).as_posix(),
)
```

Case 的 run 绑定使用 `context_refs` 中的 project 引用表达，`location` 是相对用户
根目录的 protocol path，`meta.run_path` 是同一值的显式索引：

```json
{
  "kind": "project",
  "id": "<project-uuid>",
  "location": "projects/mouse-sc/sn/runs/agentteams-case-20260819-120000",
  "meta": {
    "project_name": "小鼠单细胞 3v3",
    "run_path": "projects/mouse-sc/sn/runs/agentteams-case-20260819-120000"
  }
}
```

历史 Case 没有该引用时保持只读兼容；不得为历史 Case 强制创建新目录或伪造默认
项目名。

### 9.2 四层目录职责

| 目录 | L4 写入内容 | 允许读写方 |
| --- | --- | --- |
| `input/` | Case 创建时的样本表、比较组、上下文快照 | 平台快照器、受控 Worker |
| `work/` | 专家中间文件、临时表、转换结果 | 受控 Worker；用户只读预览 |
| `logs/` | Worker、流程、交付日志 | 平台和管理员；用户只读 |
| `output/` | 最终产物、`delivery-summary.md`、`agentteams-delivery-manifest.json` | 用户可见、可预览、可下载 |

Worker 不得写入 `raw/`、`tasks/<uuid>/`、`results/` 或 Case UUID 目录。Bridge 的
manifest 路径是内部审计地址，不是用户文件地址。

### 9.3 MAS Delivery Projection

`agent-delivery` 关闭 Case 后，Bridge 返回 manifest；平台按 Case 的 run binding
把交付结果投影到 `<run>/output/`：

1. 已存在且位于绑定 run 内的 artifact protocol path 原地登记，不复制出第二份；
2. 可解析的外部/历史 artifact 先复制到 `output/`，再登记目录表；
3. 始终写入 `agentteams-delivery-manifest.json` 和 `delivery-summary.md`；
4. 调用 `ensure_directory_chain()`，确保“我的文件”目录树立即可见；
5. 预览和下载只接受 Case 绑定 run 下的相对路径，拒绝 `..`、绝对路径和跨 run 路径。

交付报告是幂等投影：同一个 Case 重复读取 manifest 不产生 UUID 新目录，也不覆盖
用户已经存在的同名最终产物；manifest 文件允许按内容哈希更新。

## 10. Context Reference Protocol

### 10.1 新引用格式

新生成的文件引用必须使用相对用户工作区根目录的路径：

- `projects/<project-slug>/runs/<run>/input/<name>`
- `projects/<project-slug>/runs/<run>/work/<name>`
- `projects/<project-slug>/runs/<run>/output/<name>`
- `projects/<project-slug>/runs/<run>/logs/<name>`
- `inbox/<name>`

`file://<uuid>` 不得再由 API、Worker 或前端生成。`file://` 仅保留为历史输入的
兼容解析入口，不属于新协议。

### 10.2 解析和错误分类

预览器以用户根目录为解析根，先检查协议路径安全性，再检查物理文件和目录登记：

| 输入 | 行为 |
| --- | --- |
| `projects/...` / `inbox/...` 且文件存在 | 正常预览 |
| 路径不存在 | 返回“路径不存在” |
| 路径指向目录 | 返回“路径是目录，不是普通文件” |
| `file://...` | 返回“ 不支持的引用协议，应为工作区相对路径” |
| 历史 UUID 且数据库可映射 | 平台先转换为 protocol path，再继续预览 |
| 历史 UUID 无法映射 | 标记不可读，Case preflight 阻断并回问用户 |

所有引用可读性检查统一使用 `check_context_ref(s)`；创建 Case、启动 planning
和 Worker preflight 不得各自实现另一套路径判定。

## 11. 兼容、迁移与回滚

- 旧 Case：保持 `project_ref = null` 的只读访问；manifest 和历史 artifact 仍可读取。
- 旧文件 UUID：平台通过 `FileRecord.storage_path` 做一次性 UUID → protocol path 映射；
  映射失败不猜测目录、不生成 `file://`，而是显式阻断。
- 旧目录：`raw/`、`tasks/`、`results/` 只读兼容，新 L4 写入一律进入 project run。
- 回滚：关闭 L4 run projection 开关时，Bridge Case/审计仍可运行；已创建的项目 run
  和 output 文件保留，不回写旧 UUID 目录。重新开启时按 Case run binding 幂等补齐
  manifest 和 Directory 记录。
- 数据库：本次融合不新增 Case 表列，项目/run 绑定存入 Bridge `context_refs`；因此
  不需要破坏性迁移。若后续需要查询加速，可新增索引列，但必须提供 forward/backward
  migration，不能删除历史 context_refs。

## 12. L4 接入验收矩阵

| 验收项 | 证据 |
| --- | --- |
| Case 绑定项目 | `project_ref` + `context_refs.location` + `projects/.../runs/...` Directory 记录 |
| 四层目录存在 | `input/output/work/logs` 由路径工厂创建 |
| MAS 交付可见 | `output/agentteams-delivery-manifest.json` 与 `output/delivery-summary.md` |
| protocol path 全链路 | API、preflight、Worker evidence refs、预览器均使用相对路径 |
| UUID 兼容 | 可映射则转换，不可映射则明确阻断 |
| 安全边界 | 禁止绝对路径、`..`、跨用户和跨 run 读取 |

手动最小闭环：创建项目 → 从协作室发送需求 → 查看 Case 的 run binding → 执行并
完成 quality gate → 读取 manifest → 刷新“我的文件” → 在 `output/` 预览并下载报告。

## 6. 新模块接入检查清单

新增模块合并前逐项确认：

- [ ] 请求 Schema 有必填、非空的项目名称字段。
- [ ] 前端有项目名称输入、校验和清晰提示。
- [ ] 不直接拼接用户可见存储路径。
- [ ] 使用 `create_project_run_dir()` 创建新运行目录。
- [ ] 已创建 `input`、`output`、`work`、`logs` 目录。
- [ ] 已调用 `ensure_directory_chain()`，项目目录能出现在文件树中。
- [ ] Worker、容器、下载和报告接口均使用实际运行目录。
- [ ] 输入文件在任务运行前已受控地归入 `<run>/input/`。
- [ ] 最终可交付结果仅写入 `<run>/output/`（不使用 `results/`、`result/` 等同义目录名）。
- [ ] 旧路径仅作为读取兼容分支，不作为新任务默认值。
- [ ] 已添加至少一项测试：项目名目录创建、项目名缺失校验或历史路径兼容。

## 7. 禁止事项

以下实现不允许出现在新增模块中：

```python
# 禁止：用户可见目录使用任务 UUID
Path(settings.storage_path) / "results" / "my-tool" / task_id

# 禁止：绕过路径工厂直接创建用户项目目录
Path(settings.storage_path) / "users" / user_id / "projects" / project_name

# 禁止：没有项目名称时回退到 UUID、Untitled 或固定默认项目名
project_name = request.project_name or task_id
```

```python
# 禁止：在运行目录内自建与 output/ 同义的结果子目录
run_dir / "results"

# 禁止：Service 层用固定默认项目名兜底（必填校验应止于 API/Schema 层）
def submit(..., project_name: str = "My Tool Project"): ...
```

如确有兼容旧任务的必要，应在代码中将旧路径限制为“读取回退”，并在注释或测试中注明兼容原因。

## 8. 修订记录

| 版本 | 日期 | 内容 |
| --- | --- | --- |
| v1.0 | — | 初始版本。 |
| v1.1 | 2026-08-03 | 对照代码实现核查后修订：明确 `project_slug()` 为模块级函数；说明工厂不强制创建子目录及调用方责任；§3.2/§6/§7 明确禁止 `results/` 等同义目录；§4.1 禁止 Service 层默认项目名；§5 增加各模块真实接入状态与 Studio/MAS 交付差距说明。 |
| v1.2 | 2026-08-03 | 工厂改为强制创建标准四层目录；迁移 DEG、富集、BLAST、系统发育树、数据下载与 Studio 报告交付；将历史 UUID/`raw_data` 路径限制为只读兼容。 |
| v1.3 | 2026-08-19 | 增加 L4/AgentTeams Case → Project Run 绑定、MAS 交付投影、protocol path context_refs、UUID 兼容解析和验收矩阵。 |

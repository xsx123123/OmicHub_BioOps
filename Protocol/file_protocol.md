# OmicHub 用户文件与分析项目目录协议

> **状态**：生效中  
> **版本**：v1.2（2026-08-03 文件架构迁移后修订）  
> **适用范围**：所有会产生用户输入、分析中间文件、结果、报告或可下载产物的新模块。  
> **目标**：让用户只看到可理解、可管理的项目目录；UUID 仅用于系统内部任务、审计和数据库关联。

## 1. 核心原则

1. **项目名称是分析任务的必填配置。**
   - 前端必须提供“项目名称”输入框并在提交前校验非空。
   - 后端请求 Schema 必须校验项目名称非空、去除首尾空白，并设置合理长度限制。
   - 不允许以“未命名项目”、任务 UUID 或上传文件 UUID 作为新分析的用户可见目录名称。
2. **所有新分析运行目录必须由统一路径工厂创建。**
   - 使用 `omichub.infrastructure.storage.get_path_factory()`。
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

目录名由 `omichub.infrastructure.storage.path_factory` 中的模块级函数 `project_slug()` 规范化：压缩连续空白、非法字符替换为 `_`、保留中文/字母/数字/`._-`、截断 80 字符，空名回退为 `untitled-project`。该规范仅用于路径安全，页面、任务历史和报告仍应保存并展示原始项目名称。

运行目录名中的时间戳为 UTC 秒级（`%Y%m%d-%H%M%S`）；同秒并发提交由工厂以原子创建 + 序号（`-2`…`-9999`）自动避让，模块无需自行处理冲突。

## 3. 必须使用的后端接入方式

### 3.1 创建运行目录

```python
from pathlib import Path
from uuid import UUID

from omichub.application.services.file_service import ensure_directory_chain
from omichub.infrastructure.storage import get_path_factory

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

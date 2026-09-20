# Agent 容器权限与镜像配置检查优化清单

## 0. 给 Kimi Code 的 paste-ready 提示词

```text
你是一名资深 DevOps / 容器环境工程师。请对 analysis-plot Agent 的运行容器做“先证据化诊断、再最小改动修复”。

## 已知故障现象

1. Agent 声明了火山图任务所需 R 包，但当前镜像没有装齐：`ggpubr` 缺失，导致 `theme_pubclean()` 不可用。
2. 容器镜像为 `cygnusx-analysis:plot-v0.0.2dev`，运行时显示 R 4.4.3，已有 `ggplot2 3.5.1`、`ggrepel 0.9.6`、`patchwork 1.3.0`、`scales 1.4.0`，缺 `ggpubr`。
3. 在容器里执行 `micromamba install -y -n base r-ggpubr` 失败：`/opt/conda/conda-meta/history` 只读，报 `Read-only file system`。
4. 运行时 `/workspace` 与 `/tmp` 可写；`/opt/conda`、`/home` 实际不可写。虽然目录 listing 看起来权限宽松，但底层文件系统是只读挂载。
5. 尝试在 `/workspace/envs/rplot` 新建独立 R 环境时，通道解析和缓存有问题：日志中出现不可达的 `mirrors.nju.edu.cn`，代理返回 `CONNECT tunnel failed, response 403`；USTC 通道实测可达。
6. 独立环境下载了约 475MB 后，又失败在 `/home/mambauser/.conda/environments.txt`：目录不存在且 `/home` 只读，无法补建 `.conda`。
7. 字体检查显示 Noto Sans/Serif CJK 可用，中文字体不是当前阻断点。

## 核心判断

这不是单纯“少装一个包”的问题，而是三层配置一起出错：
- Agent 依赖声明没有被镜像构建链路消费；
- 容器运行时将 `/opt/conda` 和 `/home` 挂载为只读，却仍按可写 base 环境 / 可写 HOME 来设计；
- conda/mamba 镜像源、代理、缓存目录和错误退出码处理不可靠。

## 工作要求

1. 先做只查不改诊断，禁止一上来就 `chmod -R 777`、禁止把 `/opt/conda` 改成运行时可写、禁止关闭 TLS 校验、禁止把不可信通道加进默认配置。
2. 所有结论必须带证据：命令、关键输出、文件路径、配置来源。没有证据的判断不要写进报告。
3. 明确区分：
   - 镜像构建期应该解决的问题；
   - 容器运行时权限设计应该解决的问题；
   - 临时运行时 bootstrap 只能兜底的边界。
4. 修复目标是：Agent 声明的 R 包在镜像构建后已经存在；若允许运行时补装，则必须有明确可写前缀、可靠镜像源、可复用缓存、严格失败检查和清晰错误提示。
5. 不要只看 shell 退出码；`micromamba ... | tail` 这类命令必须检查 `PIPESTATUS[0]`，避免把失败吞掉。
6. 不要假设 HOME 可写。运行时如需 HOME，请用 `/workspace` 或专门挂载的可写目录。
7. 不要混用多个镜像源逻辑。以实际容器网络可达、代理允许、可审计为准；优先使用内网镜像或已验证可达的固定通道。
8. 修改配置前先确认依赖声明源：Agent manifest、skill 文档、启动器配置、镜像构建脚本分别在哪里声明 R 包，是否存在多处不一致。

## 请交付

### A. 只查不改诊断报告

1. 依赖声明链路：从 Agent 声明到镜像构建脚本到运行时实际包列表，逐项标注文件路径。
2. 文件系统权限矩阵：路径、挂载/权限、是否可写、对 conda/mamba/R 的影响。
3. 镜像源与代理链路：实际读取的 `.condarc`、环境变量、代理、可达性测试结果；解释为什么配置里写 USTC，日志却走到 NJU。
4. 风险清单：按“阻断任务 / 阻断构建 / 隐藏故障 / 性能浪费”分级，每条给证据。

### B. 最小修复方案

1. 推荐方案：镜像构建期安装全部声明依赖，并增加 fresh-container smoke test。
2. 如必须支持运行时补装：给出可写 env/cache/HOME 前缀、固定通道、版本锁定、失败即停的 bootstrap 方案。
3. 明确不改哪些内容，以及理由。

### C. 验收清单

每一条都给出：操作命令、期望输出、失败时的处理路径。至少覆盖：
- fresh container 内 R 包完整性；
- R 版本一致性；
- 只读 `/opt/conda` 下不尝试写 base；
- `/home` 只读时 bootstrap 仍可工作；
- 镜像源/代理可达且稳定；
- 火山图任务端到端跑通，输出图片与日志完整；
- 日志能明确看到版本、环境前缀和错误根因。

### D. 代码/配置 diff

列出所有改动文件、改动原因、回滚方式。不要输出与目标无关的重构。
```

## 1. 本次对话提炼出的根因证据

| 证据 | 直接影响 | 应归属的修复层 |
|---|---|---|
| `analysis-plot` 镜像 `cygnusx-analysis:plot-v0.0.2dev` 已有 R 4.4.3、`ggplot2`、`ggrepel`、`patchwork`、`scales`，但缺 `ggpubr` | Agent 已声明依赖，运行时却不可用；`theme_pubclean()` 来自 `ggpubr` | Agent 依赖声明 → 镜像构建链路没有闭环 |
| `micromamba install -n base r-ggpubr` 报 `/opt/conda/conda-meta/history` 只读 | 容器被设计成 `/opt/conda` 只读，却沿用可写 base 环境的安装方式 | 镜像/容器挂载策略；不要运行时写 base |
| `/workspace`、`/tmp` 可写；`/opt/conda`、`/home` 实际不可写 | 所有依赖 HOME、base env、用户 cache 的默认行为都会失败 | 运行时路径设计：显式设置 HOME、env prefix、package cache |
| `.condarc` 配置 USTC，但失败日志落到 `mirrors.nju.edu.cn`，代理 403 | 通道来源不止 `.condarc`，还可能来自环境变量、代理重定向、镜像构建默认值或拼接逻辑 | 镜像源治理：收敛来源、网络可达性验证、固定通道 |
| 独立环境下载 475MB 后失败于 `/home/mambauser/.conda/environments.txt` | 包缓存/下载不是最终阻断点，HOME 只读才是；错误发生在环境注册阶段 | 初始化时应创建 `$HOME/.conda`，或将 HOME 重定向到可写路径 |
| `PIPE_EXIT=1`，但外层 shell 曾显示执行成功 | 失败可能被编排层误判为成功，后续继续跑空环境 | 执行包装必须 `set -euo pipefail` 并检查 `PIPESTATUS[0]` |
| 新建环境日志出现 `r45` 包名 | 新建 env 很可能解析到 R 4.5，而原镜像是 R 4.4.3；混用会造成行为差异 | 必须锁定 R 版本或显式对齐镜像声明版本 |

## 2. 检查清单

### 2.1 Agent 依赖声明与镜像构建闭环

- [ ] 找到 `analysis-plot` Agent 的依赖声明位置：Agent manifest、skill 配置、启动器配置、prompt 模板、requirements/environment 文件分别在哪里。
- [ ] 建立“声明依赖表”：包名、用途、来源文件、所需版本、所在 R 版本、导入语句、验收方式。
- [ ] 建立“镜像实际依赖表”：在 fresh container 中运行 `Rscript -e '...'` 输出每个包的 `packageVersion()`。
- [ ] 对比两张表，列出缺失、版本不一致、重复声明、仅在 prompt 中出现而没有进入构建链的依赖。
- [ ] 检查是否存在“prompt 临时要求包 → 运行时现场安装”的隐性依赖；这些应进入声明源，而不是靠运行时补救。
- [ ] 检查镜像构建脚本是否在构建后执行 `Rscript` 依赖完整性校验；没有则补上，构建失败就阻断发布。

### 2.2 容器文件系统权限

- [ ] 输出完整权限矩阵：路径、挂载属性、owner、模式、`touch` 写入测试结果、影响组件。
- [ ] 至少覆盖：`/opt/conda`、`/home/mambauser`、`/workspace`、`/tmp`、`/var/cache`、`/root`、`/etc`。
- [ ] 确认 `/opt/conda` 只读是刻意设计还是误挂载；如果是刻意设计，所有安装必须发生在镜像构建期或显式可写 prefix。
- [ ] 确认 `/home/mambauser` 只读是否影响：`$HOME/.conda`、`$HOME/.cache`、`$HOME/.mamba`、`$HOME/.local`、`$HOME/.config`。
- [ ] 不要在运行时修改 `/opt/conda` 权限；不要把 `chmod -R 777` 当修复。
- [ ] 如果必须支持运行时创建环境，显式设置并创建：
  - `HOME=/workspace` 或其他可写 HOME；
  - `MAMBA_ROOT_PREFIX=/workspace/.mamba`；
  - `CONDA_PKGS_DIRS=/workspace/.mamba/pkgs`；
  - `XDG_CACHE_HOME=/workspace/.cache`；
  - env prefix `/workspace/envs/<name>`。
- [ ] 确保目录在容器启动或 bootstrap 脚本中创建，并验证可写。

### 2.3 R / mamba 环境与版本一致性

- [ ] 明确镜像声明的 R 主版本，例如 R 4.4.x。
- [ ] 所有运行时补装必须锁定同一 R 版本，不能临时解析到 R 4.5。
- [ ] 优先方案：不要为每个任务新建一套完整 R；把声明包打进镜像。
- [ ] 若确需独立环境：使用显式 `r-base=4.4.*`（或镜像声明版本）并固定关键包版本。
- [ ] 验证 `Rscript --version`、`R.version.string`、`packageVersion()` 三组信息一致。
- [ ] 检查 `PATH`、`R_LIBS`、`R_LIBS_SITE`、`LD_LIBRARY_PATH`，确保 Agent 调用的是预期 Rscript，不是 base 环境与独立环境混杂。

### 2.4 镜像源、代理与缓存

- [ ] 列出实际生效的 conda/mamba 配置来源：`/home/mambauser/.condarc`、`/workspace/.condarc`、`/opt/conda/.condarc`、`/etc/conda/.condarc`、`$HOME/.mambarc`、环境变量、构建脚本内联参数。
- [ ] 用 `micromamba config sources` / `micromamba info` 验证运行时真实读取的配置，而不是只看某个文件。
- [ ] 在容器网络内实测 `repodata.json`：USTC、NJU、TUNA、默认 conda、内网镜像；记录 HTTP 状态、代理行为和响应大小。
- [ ] 解释“`.condarc` 写 USTC，但日志访问 NJU”的来源：代理白名单、channel alias、构建期残留、默认配置、脚本硬编码逐一排查。
- [ ] 收敛通道策略：只允许一个明确可达的来源；不要同时保留 USTC/NJU/TUNA/defaults 多个不确定来源。
- [ ] 检查代理 `studio-egress-proxy:3128` 对镜像域名的 CONNECT 规则；403 应被识别为网络策略问题，而不是包不存在。
- [ ] 确保 repodata/package cache 目录存在且可写；缓存路径必须在创建环境前配置好。
- [ ] 对失败重试设置合理上限；失败后给出“镜像源不可达/代理 403/目录只读/包缺失”的分类错误。

### 2.5 运行时 bootstrap 与错误处理

- [ ] 所有 bootstrap 脚本使用 `set -euo pipefail`。
- [ ] 凡有管道命令，必须捕获 `PIPESTATUS[0]`，不能让 `tail` 的退出码掩盖失败。
- [ ] 环境创建采用“可复用”逻辑：已存在且校验通过则复用；不完整则清理后重建；禁止半残留环境继续运行。
- [ ] 创建环境前打印：R 版本目标、通道、prefix、cache dir、HOME、代理状态。
- [ ] 创建后打印：Rscript 路径、R 版本、每个包版本、CJK 字体检测结果。
- [ ] 任一步失败时，给 Agent 返回可操作错误，而不是“环境问题”这种模糊文案。
- [ ] 保存完整日志到 `/workspace/output/logs` 或项目约定日志目录，便于回溯。

### 2.6 安全与稳定性红线

- [ ] 不关闭 TLS 证书校验。
- [ ] 不把未知第三方 channel 加进默认配置。
- [ ] 不将 token、代理密码写入会被持久化的日志。
- [ ] 不在运行时修改只读系统目录。
- [ ] 不为省事把整个 `/workspace` 或 `/` 权限放开。
- [ ] 新增依赖必须有声明来源和版本约束。

## 3. 推荐修复顺序

### 阶段 0：只查不改，产出证据化诊断报告

目标：确认依赖声明源、镜像构建链、权限矩阵、镜像源解析链。

验收：
- [ ] 报告列出所有相关文件路径。
- [ ] 每项结论有命令输出或配置文件摘录。
- [ ] 明确哪些问题是镜像构建期问题，哪些是运行时权限问题。

### 阶段 1：止血方案，保证当前任务可跑

目标：不重建镜像时，让 `analysis-plot` 能在声明依赖缺失的情况下以受控方式补齐。

建议做法：
- [ ] 新增 bootstrap 脚本，设置可写 `HOME`、`MAMBA_ROOT_PREFIX`、`CONDA_PKGS_DIRS`、env prefix。
- [ ] 使用固定可达通道；容器网络中先探测 `repodata.json`，不可达则直接报错。
- [ ] 锁定 R 版本，与镜像 R 4.4.3 对齐。
- [ ] 创建或复用 `/workspace/envs/rplot`。
- [ ] 安装后校验 `ggplot2`、`ggrepel`、`ggpubr`、`patchwork`、`scales`。
- [ ] 用测试数据实际生成火山图，确认 `theme_pubclean()` 可用、中文不乱码、PDF/SVG/PNG 输出正常。

限制：这是临时兜底，不应替代镜像修复。

### 阶段 2：修复镜像构建链路

目标：把 Agent 声明的依赖在构建期安装好，fresh container 不需要现场补装。

建议做法：
- [ ] 在镜像构建文件中增加声明依赖安装步骤。
- [ ] 固定 R 版本和包版本，避免 `conda-forge` 解析漂移。
- [ ] 构建期使用可达镜像源；构建环境与运行环境的代理策略要一致。
- [ ] 在镜像内创建 `$HOME/.conda`、`$HOME/.cache` 等运行时需要的目录；若运行时 HOME 仍只读，则显式改用 `/workspace`。
- [ ] 构建结束执行 smoke test：`Rscript` 加载全部声明包并打印版本。

验收：fresh container 启动后，无需联网即可直接加载全部声明 R 包。

### 阶段 3：运行时权限与镜像源治理

目标：即使允许运行时补装，也有稳定、可审计、可复用的路径。

建议做法：
- [ ] 明确 `/opt/conda` 只读是设计约束，禁止写 base。
- [ ] 统一运行时 env/cache/HOME 前缀。
- [ ] 收敛 `.condarc`，移除不可达或未经允许的镜像。
- [ ] 代理白名单放行选定镜像域；不放行则报错，不做长时间无效重试。
- [ ] 对 repodata 缓存设置容量与清理策略，避免每个任务重复下载 475MB。

### 阶段 4：CI / 发布前 smoke test

目标：防止同类问题再次进入镜像。

必测项：
- [ ] fresh container 能跑 `Rscript --version`。
- [ ] 声明包全部存在且版本正确。
- [ ] `/opt/conda` 只读时任务仍不崩溃；若需要写，只写允许路径。
- [ ] CJK 字体存在。
- [ ] 用最小测试数据生成火山图。
- [ ] 模拟镜像源 403 / 网络超时 / cache 只读 / HOME 只读，错误提示分类正确。
- [ ] bootstrap 脚本失败时退出码非零，编排层不会误判成功。

## 4. 验收对照表

| 操作 | 期望现象 | 不通过时的处理路径 |
|---|---|---|
| fresh container 中执行 `Rscript -e 'for (p in c("ggplot2","ggrepel","ggpubr","patchwork","scales")) cat(p, as.character(tryCatch(packageVersion(p), error=function(e) "MISSING")), "\n")'` | 全部为实际版本号，没有 `MISSING` | 回到阶段 2，检查依赖声明是否进入镜像构建 |
| fresh container 中执行火山图最小任务 | 图片生成成功，使用 `theme_pubclean()` 不报错 | 先查 `ggpubr`，再查 Rscript 路径和字体 |
| 检查 `/opt/conda` 写入测试 | 若只读，任务不尝试写 base；若构建期可写，运行期仍只读 | 修正 bootstrap 的 prefix，不运行时改 `/opt/conda` |
| 检查 `$HOME/.conda` 创建 | HOME 可写时目录存在；HOME 只读时自动切换到 `/workspace` | 修正 HOME 重定向和初始化逻辑 |
| `micromamba info` | envs dirs、package cache 指向可写路径 | 修正 `MAMBA_ROOT_PREFIX` / `CONDA_PKGS_DIRS` |
| 镜像源 reachability 测试 | 选定通道 HTTP 200；被代理拦截的通道返回明确 403 分类 | 修正代理白名单或通道配置 |
| 模拟无网络/镜像源 403 | 任务快速失败，错误提示为“镜像源不可达/代理拦截” | 修正错误分类与重试策略 |
| 检查 R 版本 | 镜像 R、bootstrap 新建 env R、包构建 R 一致 | 显式锁定 `r-base` 版本 |
| 检查失败退出码 | 管道失败时外层退出码非零 | 修正 `set -o pipefail` 与 `PIPESTATUS[0]` |
| 检查日志 | 日志含环境前缀、镜像源、包版本、错误根因 | 补齐日志埋点 |

## 5. 建议的最小配置基线

以下是配置方向示例，具体值以项目实际路径和代理策略为准：

```bash
# 运行时可写路径（不要写 /opt/conda）
export HOME=/workspace
export MAMBA_ROOT_PREFIX=/workspace/.mamba
export CONDA_PKGS_DIRS=/workspace/.mamba/pkgs
export XDG_CACHE_HOME=/workspace/.cache
mkdir -p "$HOME/.conda" "$MAMBA_ROOT_PREFIX" "$CONDA_PKGS_DIRS"

# 环境创建时必须检查管道退出码
set -o pipefail
micromamba create -y -p /workspace/envs/rplot --override-channels \
  -c <已验证可达的固定通道> \
  'r-base=4.4.*' r-ggplot2 r-ggrepel r-ggpubr r-patchwork r-scales
status=${PIPESTATUS[0]}
if [ "$status" -ne 0 ]; then
  echo "ENV_CREATE_FAILED status=$status" >&2
  exit "$status"
fi
```

## 6. 回滚策略

- [ ] 所有镜像改动保留旧 tag，例如 `plot-v0.0.2dev` 与 `plot-v0.0.3dev` 并存。
- [ ] bootstrap 脚本通过开关启用；失败时可切回旧镜像或不启用 bootstrap。
- [ ] `.condarc` / 代理配置修改前先备份，回滚时恢复。
- [ ] 新增依赖校验失败时，阻断发布而不是允许带缺包镜像上线。
- [ ] 每次修复都记录：问题、根因、证据、改动文件、验证命令、回滚命令。

## 7. Kimi Code 汇报模板

```text
## 诊断结论

1. 依赖声明源：
   - <文件路径>：声明了哪些包
   - <镜像构建文件路径>：实际安装了哪些包
   - fresh container 实测：哪些包缺失/版本不一致

2. 权限结论：
   - <路径>：只读/可写证据
   - 对 mamba/R/HOME/cache 的实际影响

3. 镜像源结论：
   - 实际读取配置：<来源>
   - 网络实测：<通道 + HTTP 状态>
   - NJU/USTC 不一致的根因：<证据>

## 已修复

- <文件>：<改动>；<验证命令与结果>

## 验收结果

- [ ] fresh container R 包完整性
- [ ] R 版本一致
- [ ] 火山图端到端通过
- [ ] 只读路径下无违规写入
- [ ] 镜像源可达且稳定
- [ ] 失败退出码正确

## 未解决 / 需要人工决策

- <问题>：<原因>：<建议>
```

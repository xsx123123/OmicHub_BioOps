# analysis-plot 容器权限与镜像配置诊断报告（2026-09-16）

对应清单：`docs/info/26.9.16/agent容器权限与镜像配置检查优化清单.md`

## 1. 依赖声明链路

| 环节 | 文件路径 | 内容 |
|---|---|---|
| 依赖要求源（prompt） | `data/ai/prompts/visualization.md:170` | 强制「R 出图一律以 `ggpubr::theme_pubclean()` 为基础主题」 |
| skill 声明 | `skills/bio_skills/data-visualization/statistical-annotation/SKILL.md` | `primary_tool: ggpubr`，要求 ggpubr 0.6+ |
| 镜像能力声明表 | `data/ai/runtime_images.yaml:36-62`（analysis-plot profile） | 声明 r-ggplot2/ggrepel/patchwork/plotly，**原缺 r-ggpubr**（已修复） |
| studio 镜像映射 | `data/ai/studio.yaml:12-14` | `analysis-plot → cygnusx-analysis:plot-v0.0.2dev` |
| 镜像构建脚本 | `deploy/runtime-images/plot.Dockerfile:43-58` | micromamba install 列表**原漏 r-ggpubr**，且原无构建后校验（已修复） |
| 构建入口 | `deploy/runtime-images/build.sh` / `Makefile:357 runtime-images-build` | core→plot→scrna 串联 |
| 校验样板（已存在的正确实践） | `deploy/docker/Dockerfile.deg:92-101` | 构建后 library 级强制校验 |

结论：ggpubr 是「prompt 强制 + skill 声明」依赖，但从未进入 plot.Dockerfile 安装列表——声明→构建链路断裂。runtime_images.yaml 声明表与 Dockerfile 之间无一致性校验机制。

## 2. 文件系统权限矩阵

运行时（Studio 会话容器，`docker inspect studio-e43ed970`）：

| 路径 | 挂载/来源 | 可写性 | 证据 | 影响 |
|---|---|---|---|---|
| `/opt/conda` | 镜像层，`read_only_rootfs: true` | ❌ 只读 | `touch` → `Read-only file system` | base 环境补装必败（`conda-meta/history` 不可写） |
| `/home/mambauser` | 镜像层，同上 | ❌ 只读 | 同上 | `$HOME/.conda`、`environments.txt` 无法创建；`HOME=/home/mambauser` |
| `/workspace` | bind mount `/data/omichub/studio/<id>:/workspace:rw` | ✅ | inspect HostConfig.Binds | 唯一可靠可写前缀 |
| `/tmp` | tmpfs（`tmpfs_size: 512m`） | ✅（会话内） | studio.yaml:62 | 临时文件可用，不持久 |
| `/data/platform` | bind mount `:ro` | ❌ | inspect Binds | 平台数据只读 |

关键环境变量（docker exec 实测）：`HOME=/home/mambauser`、`MAMBA_ROOT_PREFIX=/opt/conda`——两者都指向只读路径，任何运行时 install/create 都会在写元数据时失败。

注意：`studio.yaml:61 read_only_rootfs: true` 是**刻意设计**（studio 会话沙盒安全边界），不是误挂载。普通 `docker run`（无 read_only_rootfs）下 /opt/conda 以 10001 属主可写——两种启动方式行为不同，诊断时须区分。

## 3. 镜像源与代理链路

- 实际读取配置：`micromamba config sources` → 仅 `~/.condarc`（`/home/mambauser/.condarc`，515 字节，构建期烘焙，内容全部 USTC）。
- `micromamba info` channels：全部解析为 `mirrors.ustc.edu.cn`，无 NJU。
- 代理：`HTTPS_PROXY=http://studio-egress-proxy:3128`（studio.yaml network 配置）。
- 可达性实测（容器内 urllib）：
  - USTC `cloud/conda-forge/noarch/repodata.json` → **HTTP 200，约 187MB**
  - NJU `cloud/conda-forge/noarch/repodata.json` → **`Tunnel connection failed: 403 Forbidden`**（代理白名单拒绝，非网络不通）
- 代理白名单来源：`deploy/studio/egress_proxy.py` 读 `data/ai/studio.yaml` `studio.sandbox.network.allow`（含 mirrors.ustc.edu.cn，不含 nju）。
- 仓库与镜像内 grep `nju.edu.cn`：仅本文档命中，**无任何配置来源指向 NJU**。

结论：`.condarc` 写 USTC 但日志出现 NJU 的根因不在配置文件——是 Agent 在会话里用了带 `-c https://mirrors.nju.edu.cn/...` 的临时命令（或模型编造的通道），被代理白名单 403。配置本身是收敛的（单源 USTC），无需修改 `.condarc`；治理点是约束 Agent 不得自带镜像源 URL。

## 4. 风险清单

| 级别 | 风险 | 证据 |
|---|---|---|
| 阻断任务 | ggpubr 缺失，`theme_pubclean()` 不可用，可视化任务必败 | `docker run ... packageVersion("ggpubr")` → MISSING |
| 阻断构建 | plot.Dockerfile 原无构建后 library 校验，缺包镜像可带病发布 | 对照 Dockerfile.deg:92-101 有校验 |
| 隐藏故障 | `read_only_rootfs` 下 `micromamba install -n base` 在写 `conda-meta/history` 才失败，之前的 solver/下载时间全浪费（475MB） | 清单证据 #5、#6；`MAMBA_ROOT_PREFIX=/opt/conda` 只读 |
| 隐藏故障 | HOME 只读导致 `environments.txt` 注册阶段失败，错误形态误导为「环境问题」 | 清单证据 #6 |
| 隐藏故障 | 管道 `micromamba ... \| tail` 用 tail 退出码，失败被吞（PIPE_EXIT=1 但外层报成功） | 清单证据表；修复须 `set -o pipefail` + `PIPESTATUS[0]` |
| 性能浪费 | repodata 187MB/次重复下载，无持久缓存（tmpfs 512m 容不下） | USTC 实测 186779690 字节；tmpfs_size: 512m |
| 版本漂移 | 新建独立 env 不 pin r-base 会解析到 R 4.5（日志 r45），与镜像 R 4.4.3 混用 | 清单证据 #7；镜像 core.Dockerfile:62 `r-base=4.4` |

## 5. 已做修复（最小改动）

| 文件 | 改动 | 原因 | 回滚 |
|---|---|---|---|
| `deploy/runtime-images/plot.Dockerfile` | ① install 列表加 `r-ggpubr=0.6.0`；② 末尾新增 library 级 smoke test（7 包，缺包 stop 构建失败） | ggpubr 是 prompt 强制依赖；校验防止缺包镜像再发布（对齐 Dockerfile.deg 样板） | git checkout 该文件；旧镜像 `plot-v0.0.2dev` 保留未动 |

构建方式：`docker build -t cygnusx-analysis:plot-v0.0.3dev --build-arg CYGNUSX_IMAGE_TAG=v0.0.2dev -f deploy/runtime-images/plot.Dockerfile .`（基础 core 仍为 v0.0.2dev；不推 core-v0.0.3dev，回滚点单一）。
| `data/ai/runtime_images.yaml` | analysis-plot software 表加 `r-ggpubr: "0.6.0"` | 声明表与 Dockerfile 一致 | git checkout |

明确不改：
- `.condarc` / egress 代理白名单：单源 USTC 已收敛且实测可达，NJU 403 是 Agent 临时命令所致，加白 NJU 反而发散来源。
- `studio.yaml read_only_rootfs: true`：刻意的会话安全边界。
- 不在运行时补装、不写 base 环境、不放开权限。

## 6. 运行时补装兜底边界（若确需，未默认启用）

- 可写前缀：`HOME=/workspace`、`MAMBA_ROOT_PREFIX=/workspace/.mamba`、`CONDA_PKGS_DIRS=/workspace/.mamba/pkgs`
- 通道：仅 USTC（已实测 200），禁 Agent 自带镜像 URL
- 必须 pin `r-base=4.4.*` 与镜像对齐
- `set -o pipefail` + 检查 `PIPESTATUS[0]`，失败即停
- repodata 187MB，tmpfs 512m 装不下，缓存须落 /workspace

## 7. 遗留 / 需人工决策

1. 声明表（runtime_images.yaml software）与 Dockerfile install 列表无一致性自动校验——建议 CI 加一条 grep 对比。
2. repodata 缓存无持久化，Studio 会话每次现装都重拉 187MB——长期方案是镜像期装齐（本次已做 ggpubr），运行时补装应作为例外。
3. plot-v0.0.3dev 构建完成后，`studio.yaml` / `runtime_images.yaml` 的 image tag 是否切换由用户决定（切换须 `docker compose up` 重建 studio 相关服务，见 compose 启动姿势）。

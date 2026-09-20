# 外部数据供给清单（provisioning）— scrna-tcell-projectils

> 读者是**平台管理员**。本技能运行所需的全部外部数据与预装包如下，须在技能挂载前预置；运行时模型只做核查与缺失上报，不自行下载。

## 一、ProjecTILs 参考 atlas（1 个 rds，约 1~2GB）

| 文件名（沙盒路径） | 获取方式（管理员在有网环境执行） | 用途 |
|---|---|---|
| `ref/ProjecTILs/projectils_ref.rds` | R: `ref <- ProjecTILs::load.reference.map(); saveRDS(ref, "projectils_ref.rds")` | TIL 参考 atlas，运行时经 `--ref` 传入 |

```r
# 管理员下载示例（需可访问 GitHub/huggingface 的网络环境，R + ProjecTILs 已装）
library(ProjecTILs)
ref <- load.reference.map()
saveRDS(ref, "projectils_ref.rds")   # 落盘到共享卷 ref/ProjecTILs/
```

- 下载环境依赖 ProjecTILs ≥ 1.0（GitHub 独占包，`remotes::install_github("carmonalab/ProjecTILs")`）；
- 运行时脚本以 `--ref ref/ProjecTILs/projectils_ref.rds` 消费该文件，文件名可按平台约定调整，但须与技能调用参数一致。

## 二、镜像预装 R 包（沙盒白名单不可现场安装）

| 包 | 安装方式（构建镜像时执行） |
|---|---|
| ProjecTILs ≥ 1.0 | `remotes::install_github("carmonalab/ProjecTILs")` |
| scCustomize ≥ 1.1 | `remotes::install_github("samuel-marsh/scCustomize")` |

其余 R 包（Seurat/optparse/jsonlite/ggplot2 等）走 conda 通道可现场安装，见 `environment.md`。

## 三、共享卷容量建议

`ref/ProjecTILs/` 预留 ≥ 4GB（参考 rds 约 1~2GB + 版本更新余量）。
